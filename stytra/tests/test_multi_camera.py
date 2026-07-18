import json
import shutil
import tempfile
import unittest
from pathlib import Path
from time import sleep

import pandas as pd
from PyQt5.QtWidgets import QApplication

from stytra.experiments.tracking_experiments import TrackingExperiment
from stytra.stimulation import Protocol, Pause

PROTOCOL_DURATION = 5
N_REFRESH_EVTS = 10


class TestProtocolMultiCam(Protocol):
    name = "test_protocol_multicam"

    def get_stim_sequence(self):
        return [Pause(duration=PROTOCOL_DURATION)]


class TestMultiCamera(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @property
    def metadata_path(self):
        return next(Path(self.test_dir).glob("*/*/*.json"))

    def test_two_cameras_two_pipelines(self):
        """Two VideoFileSource-backed cameras, each with a different
        tracking method, running concurrently."""
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )

        exp = TrackingExperiment(
            app=self.app,
            dir_save=self.test_dir,
            protocol=TestProtocolMultiCam(),
            cameras=[
                dict(
                    role="tail_cam",
                    camera=dict(video_file=video_file),
                    tracking=dict(method="tail"),
                ),
                dict(
                    role="eyes_cam",
                    camera=dict(video_file=video_file),
                    tracking=dict(method="eyes"),
                ),
            ],
            log_format="hdf5",
        )

        self.assertEqual(set(exp.cameras.keys()), {"tail_cam", "eyes_cam"})
        self.assertEqual(set(exp.pipelines.keys()), {"tail_cam", "eyes_cam"})

        exp.start_experiment()
        exp.start_protocol()
        for _ in range(N_REFRESH_EVTS):
            exp.protocol_runner.timestep()
            sleep(PROTOCOL_DURATION / N_REFRESH_EVTS)
        exp.acc_tracking.update_list()
        for acc in exp.acc_trackings.values():
            acc.update_list()
        exp.end_protocol(save=True)
        exp.wrap_up()

        # Both cameras produced independent, non-empty tracking logs:
        with open(self.metadata_path, "r") as f:
            data = json.load(f)

        behavior_log_tail = pd.read_hdf(
            self.metadata_path.parent / data["tracking"]["behavior_log_tail_cam"],
            "/data",
        )
        behavior_log_eyes = pd.read_hdf(
            self.metadata_path.parent / data["tracking"]["behavior_log_eyes_cam"],
            "/data",
        )
        self.assertGreater(len(behavior_log_tail), 0)
        self.assertGreater(len(behavior_log_eyes), 0)
        self.assertIn("theta_00", behavior_log_tail.columns)
        self.assertIn("th_e0", behavior_log_eyes.columns)

        # Clean teardown - no cameras/dispatchers left alive:
        for cam in exp.cameras.values():
            self.assertFalse(cam.is_alive())
        for dispatcher in exp.frame_dispatchers.values():
            self.assertFalse(dispatcher.is_alive())
