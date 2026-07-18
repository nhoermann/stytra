import traceback

import numpy as np
from multiprocessing import Queue, Event
from pathlib import Path

from stytra.experiments import VisualExperiment
from stytra.gui.container_windows import (
    CameraExperimentWindow,
    TrackingExperimentWindow,
)
from stytra.hardware.video import (
    CameraControlParameters,
    VideoControlParameters,
    VideoFileSource,
    CameraSource,
)

# imports for tracking
from stytra.collectors import (
    QueueDataAccumulator,
    EstimatorLog,
    FramerateQueueAccumulator,
)
from stytra.tracking.tracking_process import TrackingProcess, DispatchProcess
from stytra.tracking.pipelines import Pipeline
from stytra.collectors.namedtuplequeue import NamedTupleQueue
from stytra.experiments.fish_pipelines import pipeline_dict

from stytra.stimulation.estimators import estimator_dict

from stytra.hardware.video.write import (
    H5VideoWriter,
    StreamingVideoWriter,
    ZarrVideoWriter,
)

import sys
from typing import *


def _normalize_cameras_config(cameras, camera, recording, extra_singular=None):
    """Normalize the legacy singular ``camera=``/``recording=`` (optionally
    plus one more singular key, e.g. ``tracking=``) into the plural
    ``cameras=[...]`` list form, so every existing single-camera caller
    keeps working unchanged. Returns a list of resolved entry dicts, each
    guaranteed to have a "role" key.
    """
    if cameras is None:
        entry = dict(camera=camera, recording=recording)
        if extra_singular:
            entry.update(extra_singular)
        cameras = [entry]

    resolved = []
    for i, entry in enumerate(cameras):
        entry = dict(entry)
        entry.setdefault("role", "camera_{}".format(i))
        resolved.append(entry)
    return resolved


class CameraVisualExperiment(VisualExperiment):
    """
    General class for Experiment that need to handle one or more cameras.
    It implements a view of frames from the (first) camera in the control
    GUI, and the respective parameters. For debugging it can be used with a
    video read from file with the VideoFileSource class.
    """

    def __init__(
        self,
        *args,
        camera: dict = None,
        cameras: list = None,
        camera_queue_mb: int = 100,
        recording: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        Parameters
        ----------
        camera
            dictionary containing the parameters for the camera setup (i.e. for offline processing it would contain
            an entry 'video_file' with the path to the video). Mutually exclusive with `cameras`.
        cameras
            list of dictionaries, one per camera, each with a "camera" sub-dict (same shape as the singular `camera`
            param above), an optional "role" string identifying it (defaults to "camera_<i>"), and an optional
            "recording" sub-dict. Use this instead of `camera`/`recording` to run several cameras at once.
        camera_queue_mb
            the maximum size of frames that are kept at once, if the limit is exceeded, frames will be dropped.
        recording
            dictionary containing the parameters for the recording (i.e. to save to an mp4 file, add the 'extension'
            entry with the 'mp4' value). If None, no recording is performed. Mutually exclusive with `cameras`.
        """
        super().__init__(*args, **kwargs)

        if not hasattr(self, "_camera_configs"):
            self._camera_configs = _normalize_cameras_config(cameras, camera, recording)

        self.cameras = {}
        self.camera_states = {}
        self.acc_camera_framerates = {}

        for entry in self._camera_configs:
            role = entry["role"]
            cam_cfg = entry["camera"]

            if cam_cfg.get("video_file", None) is None:
                self.cameras[role] = CameraSource(
                    cam_cfg["type"],
                    rotation=cam_cfg.get("rotation", 0),
                    downsampling=cam_cfg.get("downsampling", 1),
                    roi=cam_cfg.get("roi", (-1, -1, -1, -1)),
                    max_mbytes_queue=camera_queue_mb,
                    camera_params=cam_cfg.get("camera_params", dict()),
                )
                self.camera_states[role] = CameraControlParameters(tree=self.dc)
            else:
                self.cameras[role] = VideoFileSource(
                    cam_cfg["video_file"],
                    rotation=cam_cfg.get("rotation", 0),
                    max_mbytes_queue=camera_queue_mb,
                )
                self.camera_states[role] = VideoControlParameters(tree=self.dc)

            self.acc_camera_framerates[role] = FramerateQueueAccumulator(
                self,
                queue=self.cameras[role].framerate_queue,
                goal_framerate=cam_cfg.get("min_framerate", None),
                name="camera_{}".format(role),
            )

        # New parameters are sent with GUI timer:
        self.gui_timer.timeout.connect(self.send_gui_parameters)
        for acc in self.acc_camera_framerates.values():
            self.gui_timer.timeout.connect(acc.update_list)

        self.recording_events = {}
        self.reset_events = {}
        self.finish_events = {}
        self.frame_dispatchers = {}
        self.frame_recorders = {}

        for entry in self._camera_configs:
            rec_cfg = entry.get("recording", None)
            if rec_cfg is not None:
                self._setup_recording(
                    entry["role"],
                    kbit_framerate=rec_cfg.get("kbit_rate", 1000),
                    extension=rec_cfg["extension"],
                )

        # A camera with neither "recording" (handled above) nor "tracking"
        # (handled by TrackingExperiment.__init__, which populates
        # pipeline_clss on self *before* calling super().__init__() - see
        # there) still needs a plain frame dispatcher for its live preview
        # in the GUI (CameraViewWidget always reads
        # experiment.frame_dispatchers[role]). Roles already spoken for by
        # either path are skipped here.
        tracked_roles = getattr(self, "pipeline_clss", {})
        for entry in self._camera_configs:
            role = entry["role"]
            if role not in self.frame_dispatchers and role not in tracked_roles:
                self.frame_dispatchers[role] = self._setup_frame_dispatcher(role)
                self.frame_dispatchers[role].start()

    # -- Backward-compatible scalar accessors: everything not yet made
    # multi-camera-aware (GUI docking, save paths, etc.) keeps working
    # unchanged by transparently getting "the first (or only) camera".
    @property
    def camera(self):
        if not self.cameras:
            raise AttributeError("camera")
        return next(iter(self.cameras.values()))

    @property
    def camera_state(self):
        if not self.camera_states:
            raise AttributeError("camera_state")
        return next(iter(self.camera_states.values()))

    @property
    def acc_camera_framerate(self):
        if not self.acc_camera_framerates:
            raise AttributeError("acc_camera_framerate")
        return next(iter(self.acc_camera_framerates.values()))

    @property
    def frame_dispatcher(self):
        if not self.frame_dispatchers:
            raise AttributeError("frame_dispatcher")
        return next(iter(self.frame_dispatchers.values()))

    def reset(self) -> None:
        super().reset()
        for acc in self.acc_camera_framerates.values():
            acc.reset()

    def initialize_plots(self) -> None:
        super().initialize_plots()

    def send_gui_parameters(self) -> None:
        for role, cam in self.cameras.items():
            state = self.camera_states[role]
            cam.control_queue.put(state.params.changed_values())
            state.params.acknowledge_changes()

    def start_experiment(self) -> None:
        """ """
        self.go_live()
        super().start_experiment()

    def start_protocol(self) -> None:
        """
        Starts the recording(s) if recording parameters are set for any camera.
        """
        multi = len(self._camera_configs) > 1
        for entry in self._camera_configs:
            if entry.get("recording") is not None:
                role = entry["role"]
                # Slight work around, the problem is in when set_id() is updated.
                # See issue #71.
                p = Path()
                suffix = (role + "_") if multi else ""
                fb = p.joinpath(
                    self.folder_name,
                    self.current_timestamp.strftime("%H%M%S") + "_" + suffix,
                )
                self.dc.add_static_data(
                    fb,
                    "recording/filename"
                    if not multi
                    else "recording/{}/filename".format(role),
                )
                self._start_recording(role, fb)

        super().start_protocol()

    def end_protocol(self, save: bool = True) -> None:
        """
        Stops the recording(s) if recording parameters are set for any camera.
        """
        for entry in self._camera_configs:
            if entry.get("recording") is not None:
                self._stop_recording(entry["role"])

        super().end_protocol(save=save)

    def make_window(self) -> None:
        """ """
        self.window_main = CameraExperimentWindow(experiment=self)
        self.window_main.construct_ui()
        self.window_main.show()
        self.restore_window_state()
        self.initialize_plots()

    def go_live(self) -> None:
        """ """
        sys.excepthook = self.excepthook
        for cam in self.cameras.values():
            cam.start()

    def wrap_up(self, *args, **kwargs) -> None:
        self.gui_timer.stop()
        super().wrap_up(*args, **kwargs)

        for cam in self.cameras.values():
            cam.kill_event.set()
            cam.frame_queue.clear()

        for cam in self.cameras.values():
            if cam.is_alive():
                cam.join()

        for cam in self.cameras.values():
            cam.frame_queue.unlink()

    def _setup_frame_dispatcher(
        self, role: str, recording_event: Event = None
    ) -> DispatchProcess:
        """
        Creates a dispatcher that handles the frames of a camera. It will trigger the recording (i.e. stop it) using
        the given 'recording_event' event.

        Parameters
        ----------
        role
            the camera's role/id (key into self.cameras).
        recording_event
            The event used for recording (if relevant).
        """
        cam = self.cameras[role]
        return DispatchProcess(cam.frame_queue, cam.kill_event, recording_event)

    def _setup_recording(
        self, role: str, kbit_framerate: int = 1000, extension: str = "mp4"
    ) -> None:
        """
        Does the necessary setup before performing the recording, such as creating events, setting up the dispatcher
        (via _setup_frame_dispatcher) and initialising the VideoWriter.

        Parameters
        ----------
        role
            the camera's role/id (key into self.cameras) to record.
        kbit_framerate
            the byte rate at which the video is encoded.
        extension
            the extension used at the end of the video file.
        """
        self.recording_events[role] = Event()
        self.reset_events[role] = Event()
        self.finish_events[role] = Event()

        self.frame_dispatchers[role] = self._setup_frame_dispatcher(
            role, self.recording_events[role]
        )
        self.frame_dispatchers[role].start()

        if extension == "h5":
            self.frame_recorders[role] = H5VideoWriter(
                input_queue=self.frame_dispatchers[role].frame_copy_queue,
                recording_event=self.recording_events[role],
                reset_event=self.reset_events[role],
                finish_event=self.finish_events[role],
                log_format=self.log_format,
            )
        elif extension == "zarr":
            self.frame_recorders[role] = ZarrVideoWriter(
                input_queue=self.frame_dispatchers[role].frame_copy_queue,
                recording_event=self.recording_events[role],
                reset_event=self.reset_events[role],
                finish_event=self.finish_events[role],
                log_format=self.log_format,
            )
        else:
            self.frame_recorders[role] = StreamingVideoWriter(
                input_queue=self.frame_dispatchers[role].frame_copy_queue,
                recording_event=self.recording_events[role],
                reset_event=self.reset_events[role],
                finish_event=self.finish_events[role],
                kbit_rate=kbit_framerate,
                log_format=self.log_format,
            )

        self.frame_recorders[role].start()

    def _start_recording(self, role: str, filename: str) -> None:
        """
        Pushes the filename to the queue and sets the recording event in order to start the recording.

        Parameters
        ----------
        role
            the camera's role/id being recorded.
        filename
            a unique identifier that will be added to the video file.
        """
        self.frame_recorders[role].filename_queue.put(filename)
        self.recording_events[role].set()

    def _stop_recording(self, role: str) -> None:
        """
        Stops the recording by clearing the recording event.
        """
        self.recording_events[role].clear()

    def _finish_recording(self, role: str) -> None:
        """
        Finishes the recording process and joins the frame recorder.
        """
        self.frame_recorders[role].finish_event.set()
        self.frame_recorders[role].join()

    def excepthook(self, exctype, value, tb) -> None:
        for role in list(self.frame_recorders.keys()):
            self._finish_recording(role)

        traceback.print_tb(tb)
        print("{0}: {1}".format(exctype, value))
        for cam in self.cameras.values():
            cam.kill_event.set()
            cam.join()


class TrackingExperiment(CameraVisualExperiment):
    """
    Abstract class for an experiment which contains tracking on one or more
    cameras.

    Each camera in the `cameras` list config can have its own "tracking"
    sub-dict (a different tracking method per camera, e.g. tail tracking on
    one camera and heart-rate tracking on another, running concurrently), or
    none at all (in which case that camera is only acquired/recorded, not
    tracked).

    For each tracked camera, a frame dispatcher handles two input queues:

        - frame queue from that camera;
        - parameters queue from parameter window.

    and it puts data in three queues:

        - subset of frames are dispatched to the GUI, for displaying;
        - all the frames, together with the parameters, are dispatched
          to perform tracking;
        - the result of the tracking function, is dispatched to a data
          accumulator for saving or other purposes (e.g. VR control).
    """

    def __init__(
        self,
        *args,
        tracking: dict = None,
        camera: dict = None,
        cameras: list = None,
        recording: Optional[Dict[str, Any]] = None,
        second_output_queue: Queue = None,
        **kwargs
    ) -> None:
        """
        tracking
            containing fields:  tracking_method
                                estimator: can be vigor for embedded fish, position
                                    for freely-swimming, or a custom subclass of Estimator
            Mutually exclusive with `cameras` (which carries its own per-camera "tracking" sub-dict).
        recording
            dictionary containing the parameters for the recording (i.e. to save to an mp4 file, add the 'extension'
            entry with the 'mp4' value). If None, no recording is performed. Mutually exclusive with `cameras`.
        """

        self._camera_configs = _normalize_cameras_config(
            cameras, camera, recording, extra_singular=dict(tracking=tracking)
        )

        self.second_output_queue = second_output_queue
        self.finished_sig = Event()

        self.pipeline_clss = {}
        self.processing_params_queues = {}
        self.tracking_output_queues = {}
        for entry in self._camera_configs:
            tr_cfg = entry.get("tracking")
            if tr_cfg is None:
                continue
            role = entry["role"]
            pcls = (
                pipeline_dict.get(tr_cfg["method"], None)
                if isinstance(tr_cfg["method"], str)
                else tr_cfg["method"]
            )
            if pcls is None:
                raise NameError("The selected tracking method does not exist!")
            self.pipeline_clss[role] = pcls
            self.processing_params_queues[role] = Queue()
            self.tracking_output_queues[role] = NamedTupleQueue()

        super().__init__(recording=recording, *args, **kwargs)
        self.arguments.update(locals())

        self.pipelines = {}
        self.acc_trackings = {}
        self.acc_tracking_framerates = {}

        for entry in self._camera_configs:
            role = entry["role"]
            if role not in self.pipeline_clss:
                continue

            pipeline = self.pipeline_clss[role]()
            assert isinstance(pipeline, Pipeline)
            pipeline.setup(tree=self.dc)
            self.pipelines[role] = pipeline

            # Roles with a "recording" config already got a frame dispatcher
            # (a TrackingProcess, via polymorphism from
            # CameraVisualExperiment._setup_recording) - only roles without
            # recording need one set up here, purely for live tracking.
            if role not in self.frame_dispatchers:
                self.frame_dispatchers[role] = self._setup_frame_dispatcher(role)
                self.frame_dispatchers[role].start()

            self.acc_trackings[role] = QueueDataAccumulator(
                name="tracking_{}".format(role),
                experiment=self,
                data_queue=self.tracking_output_queues[role],
                monitored_headers=pipeline.headers_to_plot,
            )
            self.acc_trackings[role].sig_acc_init.connect(self.refresh_plots)

            self.acc_tracking_framerates[role] = FramerateQueueAccumulator(
                self,
                queue=self.frame_dispatchers[role].framerate_queue,
                name="tracking_{}".format(role),
                goal_framerate=entry["camera"].get("min_framerate", None),
            )

            self.gui_timer.timeout.connect(
                self.acc_tracking_framerates[role].update_list
            )
            self.gui_timer.timeout.connect(self.acc_trackings[role].update_list)
            self.protocol_runner.sig_protocol_started.connect(
                self.acc_trackings[role].reset
            )

        # Only one estimator is supported (closed-loop stimuli reference
        # experiment.estimator as a single scalar) - the first camera whose
        # tracking config requests one wins.
        self.estimator = None
        self.estimator_log = None
        for entry in self._camera_configs:
            tr_cfg = entry.get("tracking")
            if tr_cfg is None:
                continue
            est_type = tr_cfg.get("estimator", None)
            if est_type is None:
                continue
            est = (
                estimator_dict.get(est_type, None)
                if isinstance(est_type, str)
                else est_type
            )
            if est is None:
                continue
            self.estimator_log = EstimatorLog(experiment=self)
            self.estimator = est(
                self.acc_trackings[entry["role"]],
                experiment=self,
                **tr_cfg.get("estimator_params", {})
            )
            self.estimator_log.sig_acc_init.connect(self.refresh_plots)
            break

    @property
    def pipeline(self):
        if not self.pipelines:
            raise AttributeError("pipeline")
        return next(iter(self.pipelines.values()))

    @property
    def acc_tracking(self):
        if not self.acc_trackings:
            raise AttributeError("acc_tracking")
        return next(iter(self.acc_trackings.values()))

    @property
    def acc_tracking_framerate(self):
        if not self.acc_tracking_framerates:
            raise AttributeError("acc_tracking_framerate")
        return next(iter(self.acc_tracking_framerates.values()))

    def _setup_frame_dispatcher(
        self, role: str, recording_event: Event = None
    ) -> DispatchProcess:
        """
        Initialises and returns a dispatcher for the given camera role.
        Falls back to a plain (non-tracking) DispatchProcess if that role
        has no tracking configured.

        Parameters
        ----------
        role
            the camera's role/id (key into self.cameras).
        recording_event
            event used to signal the start and end of the recording.
        """
        if role not in self.pipeline_clss:
            return super()._setup_frame_dispatcher(role, recording_event)

        cam = self.cameras[role]
        return TrackingProcess(
            in_frame_queue=cam.frame_queue,
            finished_signal=cam.kill_event,
            pipeline=self.pipeline_clss[role],
            processing_parameter_queue=self.processing_params_queues[role],
            output_queue=self.tracking_output_queues[role],
            second_output_queue=self.second_output_queue,
            recording_signal=recording_event,
            gui_framerate=20,
        )

    def reset(self) -> None:
        super().reset()
        for acc in self.acc_tracking_framerates.values():
            acc.reset()
        for acc in self.acc_trackings.values():
            acc.reset()
        if self.estimator is not None:
            self.estimator.reset()
            self.estimator_log.reset()

    def make_window(self) -> None:
        self.window_main = TrackingExperimentWindow(experiment=self)
        self.window_main.construct_ui()
        self.initialize_plots()
        self.window_main.show()
        self.restore_window_state()

    def initialize_plots(self) -> None:
        super().initialize_plots()
        self.refresh_plots()

    def refresh_plots(self) -> None:
        self.window_main.stream_plot.remove_streams()
        for acc in self.acc_trackings.values():
            self.window_main.stream_plot.add_stream(acc)
        if self.estimator is not None:
            self.window_main.stream_plot.add_stream(self.estimator_log)

            # We display the stimulus log only if we have vigor estimator, meaning 1D closed-loop experiments
            self.window_main.stream_plot.add_stream(self.protocol_runner.dynamic_log)

        if self.stim_plot:  # but also if forced:
            self.window_main.stream_plot.add_stream(self.protocol_runner.dynamic_log)

    def send_gui_parameters(self) -> None:
        """
        Called upon gui timeout, put tracking parameters in the relative queue.
        """
        super().send_gui_parameters()
        for role, pipeline in self.pipelines.items():
            self.processing_params_queues[role].put(pipeline.serialize_changed_params())

    def start_protocol(self) -> None:
        # Freeze the plots so the plotting does not interfere with
        # stimulus display
        if not self.window_main.stream_plot.frozen:
            self.window_main.stream_plot.toggle_freeze()

        # Reset data accumulator when starting the protocol.
        self.gui_timer.stop()

        super().start_protocol()

        self.gui_timer.start(1000 // 60)

    def end_protocol(self, save: bool = True) -> None:
        super().end_protocol(save)
        if self.window_main.stream_plot.frozen:
            self.window_main.stream_plot.toggle_freeze()

    def save_data(self) -> None:
        """Save tracking positions and dynamic parameters and terminate."""

        self.window_main.camera_display.save_image(
            name=self.filename_base() + "img.png"
        )
        self.dc.add_static_data(self.filename_prefix() + "img.png", "tracking/image")

        # Save log and estimators:
        multi = len(self.acc_trackings) > 1
        for role, acc in self.acc_trackings.items():
            self.save_log(
                acc, "behavior_log_{}".format(role) if multi else "behavior_log"
            )
        try:
            self.save_log(self.estimator.log, "estimator_log")
        except AttributeError:
            pass

        super().save_data()

    def set_protocol(self, protocol: np.ndarray) -> None:
        """
        Connect new protocol start to resetting of the data accumulators.
        """
        super().set_protocol(protocol)
        for acc in self.acc_trackings.values():
            self.protocol.sig_protocol_started.connect(acc.reset)

    def wrap_up(self, *args, **kwargs) -> None:
        super().wrap_up(*args, **kwargs)

        for dispatcher in self.frame_dispatchers.values():
            dispatcher.gui_queue.clear()

        for dispatcher in self.frame_dispatchers.values():
            dispatcher.join()

        for dispatcher in self.frame_dispatchers.values():
            dispatcher.gui_queue.unlink()
            if getattr(dispatcher, "frame_copy_queue", None) is not None:
                dispatcher.frame_copy_queue.unlink()
            if getattr(dispatcher, "output_frame_queue", None) is not None:
                dispatcher.output_frame_queue.unlink()

    def excepthook(self, exctype, value, tb) -> None:
        """
        If an exception happens in the main loop, close all the processes so nothing is left hanging.
        """
        traceback.print_tb(tb)
        print("{0}: {1}".format(exctype, value))
        for role in list(self.frame_recorders.keys()):
            self._finish_recording(role)
        for cam in self.cameras.values():
            cam.join()
        for dispatcher in self.frame_dispatchers.values():
            dispatcher.join()
