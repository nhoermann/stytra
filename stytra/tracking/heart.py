import numpy as np
from numba import jit
from stytra.lightparam import Param
from stytra.tracking.pipelines import ImageToDataNode, NodeOutput
from collections import namedtuple


class HeartRateTrackingMethod(ImageToDataNode):
    """Heart rate tracking from an ROI, using the periodic mean-intensity
    change caused by blood flow. Since the pipeline only ever sees the raw
    image (no wall-clock timestamp), the camera's frame rate is taken as an
    explicit parameter to set - it must match the actual acquisition
    frame rate for the BPM estimate to be correct.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, name="heart_rate_tracking", **kwargs)
        self.monitored_headers = ["heart_rate_bpm"]
        self.data_log_name = "heart_rate"
        self._output_type = namedtuple("h", ["heart_rate_bpm", "roi_intensity"])
        self.diagnostic_image_options = ["roi"]
        self.intensity_buffer = None
        self.i_buffer = 0

    def reset(self):
        self.intensity_buffer = None
        self.i_buffer = 0

    def _process(
        self,
        im,
        wnd_pos: Param((0, 0), gui=False),
        wnd_dim: Param((50, 50), gui=False),
        framerate: Param(
            150.0, limits=(1.0, 1000.0), desc="camera acquisition framerate (Hz)"
        ),
        min_bpm: Param(60.0, limits=(10.0, 600.0)),
        max_bpm: Param(300.0, limits=(10.0, 600.0)),
        buffer_length: Param(200, limits=(20, 2000)),
        **extraparams
    ):
        """

        Parameters
        ----------
        im :
            image (numpy array);
        wnd_pos :
            position of the ROI on the heart (x, y);
        wnd_dim :
            dimension of the ROI on the heart (w, h);
        framerate :
            camera acquisition framerate in Hz - must match the real camera
            setting for the BPM estimate to be meaningful;
        min_bpm, max_bpm :
            plausible heart rate range, used to size the detrending window
            and reject spurious close-together peaks;
        buffer_length :
            number of past frames used for the BPM estimate.

        Returns
        -------

        """
        roi = im[
            wnd_pos[1] : wnd_pos[1] + wnd_dim[1], wnd_pos[0] : wnd_pos[0] + wnd_dim[0]
        ]

        if roi.size == 0:
            return NodeOutput(
                ["E: heart rate ROI is empty!"], self._output_type(np.nan, np.nan)
            )

        intensity = float(np.mean(roi))

        if self.intensity_buffer is None or len(self.intensity_buffer) != buffer_length:
            self.intensity_buffer = np.full(buffer_length, np.nan)
            self.i_buffer = 0

        write_slot = self.i_buffer % buffer_length
        self.intensity_buffer[write_slot] = intensity
        self.i_buffer += 1

        message = ""
        if self.i_buffer < buffer_length:
            bpm = np.nan
        else:
            oldest_slot = self.i_buffer % buffer_length
            ordered = np.roll(self.intensity_buffer, -oldest_slot)
            bpm = _estimate_bpm(ordered, framerate, min_bpm, max_bpm)
            if np.isnan(bpm):
                message = "W: no clear heart rate signal in ROI"

        if self.set_diagnostic == "roi":
            self.diagnostic_image = roi

        return NodeOutput(
            [message] if message else [], self._output_type(bpm, intensity)
        )


@jit(nopython=True, cache=True)
def _estimate_bpm(signal, framerate, min_bpm, max_bpm):
    """Estimate a heart rate in BPM from a chronologically-ordered buffer of
    ROI mean-intensity values, by detrending with a local moving average
    (high-pass, window sized to the slowest allowed heart rate) and finding
    peaks at least `max_bpm`-spaced apart.
    """
    n = signal.shape[0]

    win = int(framerate / (min_bpm / 60.0))
    if win < 3:
        win = 3

    detrended = np.empty(n)
    for i in range(n):
        lo = i - win
        if lo < 0:
            lo = 0
        hi = i + win + 1
        if hi > n:
            hi = n
        s = 0.0
        for j in range(lo, hi):
            s += signal[j]
        detrended[i] = signal[i] - s / (hi - lo)

    thresh = np.std(detrended) * 0.5
    min_dist = framerate / (max_bpm / 60.0)

    peak_positions = np.empty(n, dtype=np.int64)
    n_peaks = 0
    last_peak = -min_dist - 1.0
    for i in range(1, n - 1):
        if (
            detrended[i] > thresh
            and detrended[i] > detrended[i - 1]
            and detrended[i] >= detrended[i + 1]
            and (i - last_peak) >= min_dist
        ):
            peak_positions[n_peaks] = i
            n_peaks += 1
            last_peak = i

    if n_peaks < 2:
        return np.nan

    total_interval = 0.0
    for k in range(1, n_peaks):
        total_interval += peak_positions[k] - peak_positions[k - 1]
    mean_interval_frames = total_interval / (n_peaks - 1)

    if mean_interval_frames <= 0:
        return np.nan

    mean_interval_s = mean_interval_frames / framerate
    return 60.0 / mean_interval_s
