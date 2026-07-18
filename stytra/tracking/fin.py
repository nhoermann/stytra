import numpy as np
from numba import jit
from stytra.lightparam import Param
from stytra.tracking.pipelines import ImageToDataNode, NodeOutput
from collections import namedtuple


class PectoralFinTrackingMethod(ImageToDataNode):
    """Pectoral fin tracking from an ROI: thresholds the fin against the
    background, then fits its principal axis (a closed-form 2x2 PCA on the
    thresholded pixel coordinates) to get the fin angle, frame by frame.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, name="fin_tracking", **kwargs)
        self.monitored_headers = ["fin_angle"]
        self.data_log_name = "fin_track"
        self._output_type = namedtuple("f", ["fin_angle", "fin_elongation", "fin_area"])
        self.diagnostic_image_options = ["mask"]

    def _process(
        self,
        im,
        wnd_pos: Param((0, 0), gui=False),
        wnd_dim: Param((50, 50), gui=False),
        threshold: Param(60, limits=(0, 255)),
        color_invert: Param(True),
        **extraparams
    ):
        """

        Parameters
        ----------
        im :
            image (numpy array);
        wnd_pos :
            position of the ROI on the fin (x, y);
        wnd_dim :
            dimension of the ROI on the fin (w, h);
        threshold :
            intensity threshold used to segment the fin from the background;
        color_invert :
            if True, the fin is darker than the background (segment below
            threshold); if False, the fin is brighter (segment above).

        Returns
        -------

        """
        roi = im[
            wnd_pos[1] : wnd_pos[1] + wnd_dim[1], wnd_pos[0] : wnd_pos[0] + wnd_dim[0]
        ]

        if roi.size == 0:
            return NodeOutput(
                ["E: fin ROI is empty!"], self._output_type(np.nan, np.nan, 0.0)
            )

        mask = (roi < threshold) if color_invert else (roi > threshold)

        angle, elongation, area = _fin_angle_from_mask(mask)

        message = ""
        if np.isnan(angle):
            message = "W: no fin detected in ROI"

        if self.set_diagnostic == "mask":
            self.diagnostic_image = (mask * 255).astype(np.uint8)

        return NodeOutput(
            [message] if message else [],
            self._output_type(angle, elongation, area),
        )


@jit(nopython=True, cache=True)
def _fin_angle_from_mask(mask):
    """Fit the principal axis of a thresholded fin mask via a closed-form
    2x2 PCA on foreground pixel coordinates. Returns (angle, elongation,
    n_foreground_pixels); angle is in radians and has a 180-degree ambiguity
    (a PCA axis has no inherent direction) - not a bug, an intrinsic
    property of the method.
    """
    h, w = mask.shape
    sum_x = 0.0
    sum_y = 0.0
    n = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x]:
                sum_x += x
                sum_y += y
                n += 1

    if n < 4:
        return np.nan, np.nan, 0.0

    mean_x = sum_x / n
    mean_y = sum_y / n

    cov_xx = 0.0
    cov_yy = 0.0
    cov_xy = 0.0
    for y in range(h):
        for x in range(w):
            if mask[y, x]:
                dx = x - mean_x
                dy = y - mean_y
                cov_xx += dx * dx
                cov_yy += dy * dy
                cov_xy += dx * dy
    cov_xx /= n
    cov_yy /= n
    cov_xy /= n

    angle = 0.5 * np.arctan2(2 * cov_xy, cov_xx - cov_yy)

    trace = cov_xx + cov_yy
    det = cov_xx * cov_yy - cov_xy * cov_xy
    disc_sq = trace * trace / 4 - det
    disc = np.sqrt(disc_sq) if disc_sq > 0 else 0.0
    lambda1 = trace / 2 + disc
    lambda2 = trace / 2 - disc
    elongation = lambda2 / lambda1 if lambda1 > 1e-6 else 0.0

    return angle, elongation, float(n)
