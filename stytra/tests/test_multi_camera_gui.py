import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication

import stytra.gui.camera_setup_dialog as camera_setup_dialog_mod
from stytra.experiments.tracking_experiments import (
    CameraVisualExperiment,
    TrackingExperiment,
)
from stytra.gui.camera_display import HeartRateSelection, TailTrackingSelection
from stytra.gui.camera_setup_dialog import CameraSetupDialog
from stytra.stimulation import Protocol, Pause


class TestProtocolGui(Protocol):
    name = "test_protocol_gui"

    def get_stim_sequence(self):
        return [Pause(duration=1)]


class TestMultiCameraGui(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_two_camera_tiles_and_docks(self):
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )

        exp = TrackingExperiment(
            app=self.app,
            dir_save=self.test_dir,
            protocol=TestProtocolGui(),
            cameras=[
                dict(
                    role="tail_cam",
                    camera=dict(video_file=video_file),
                    tracking=dict(method="tail"),
                ),
                dict(
                    role="heart_cam",
                    camera=dict(video_file=video_file),
                    tracking=dict(method="heart_rate"),
                ),
            ],
            log_format="hdf5",
        )
        try:
            exp.start_experiment()

            window = exp.window_main

            # One dock per camera, with distinct objectNames:
            self.assertIn("dock_camera_tail_cam", window.docks)
            self.assertIn("dock_camera_heart_cam", window.docks)

            # Each tile is bound to the correct role's camera and pipeline:
            self.assertEqual(
                set(window.camera_displays.keys()), {"tail_cam", "heart_cam"}
            )
            self.assertIs(
                window.camera_displays["tail_cam"].camera, exp.cameras["tail_cam"]
            )
            self.assertIs(
                window.camera_displays["heart_cam"].camera, exp.cameras["heart_cam"]
            )
            self.assertIsInstance(
                window.camera_displays["tail_cam"], TailTrackingSelection
            )
            self.assertIsInstance(
                window.camera_displays["heart_cam"], HeartRateSelection
            )

            # backward-compat .camera_display resolves to one of the tiles:
            self.assertIn(window.camera_display, window.camera_displays.values())

            # Per-role tracking-params controls exist for both cameras:
            self.assertEqual(
                set(window.drop_displays.keys()), {"tail_cam", "heart_cam"}
            )
        finally:
            exp.wrap_up()

    def test_single_camera_gui_unchanged(self):
        """Legacy singular config still builds exactly one tile/dock."""
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )
        exp = TrackingExperiment(
            app=self.app,
            dir_save=self.test_dir,
            protocol=TestProtocolGui(),
            camera=dict(video_file=video_file),
            tracking=dict(method="tail"),
            log_format="hdf5",
        )
        try:
            exp.start_experiment()
            window = exp.window_main
            self.assertEqual(len(window.camera_displays), 1)
            camera_dock_names = [
                n for n in window.docks if n.startswith("dock_camera_")
            ]
            self.assertEqual(len(camera_dock_names), 1)
        finally:
            exp.wrap_up()

    def test_camera_without_tracking_or_recording_still_gets_preview(self):
        """A camera added purely to preview it (no tracking, no recording -
        e.g. checking a webcam works) must still get a frame dispatcher, so
        its live preview tile can be built. Regression test for a KeyError
        in CameraViewWidget.__init__ (frame_dispatchers[role] was only ever
        set up for roles with tracking or recording configured)."""
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )
        exp = TrackingExperiment(
            app=self.app,
            dir_save=self.test_dir,
            protocol=TestProtocolGui(),
            cameras=[
                dict(
                    role="tail_cam",
                    camera=dict(video_file=video_file),
                    tracking=dict(method="tail"),
                ),
                dict(role="preview_only", camera=dict(video_file=video_file)),
            ],
            log_format="hdf5",
        )
        try:
            exp.start_experiment()
            self.assertIn("preview_only", exp.frame_dispatchers)
            self.assertIn("preview_only", exp.window_main.camera_displays)
        finally:
            exp.wrap_up()

    def test_untracked_camera_experiment_still_gets_preview(self):
        """Same regression as above, but via the base (non-tracking)
        CameraVisualExperiment/CameraExperimentWindow - the exact class
        Stytra selects when no camera has a "tracking" config at all (e.g.
        just previewing a plain webcam)."""
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )
        exp = CameraVisualExperiment(
            app=self.app,
            dir_save=self.test_dir,
            protocol=TestProtocolGui(),
            cameras=[dict(role="webcam", camera=dict(video_file=video_file))],
            log_format="hdf5",
        )
        try:
            exp.start_experiment()
            self.assertIn("webcam", exp.frame_dispatchers)
            self.assertIn("webcam", exp.window_main.camera_displays)
        finally:
            exp.wrap_up()


class TestCameraSetupDialog(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_get_cameras_config_from_selection(self):
        detected = {"opencv": [0, 1], "basler": ["SN123"], "ids": []}
        dialog = CameraSetupDialog(detected=detected)

        # Select the two non-ids rows, leave the rest unchecked:
        selected_roles = []
        for row in dialog._rows:
            if row["backend"] == "opencv" and row["device_id"] == 0:
                row["checkbox"].setChecked(True)
                row["role_edit"].setText("tail_cam")
                row["tracking_combo"].setCurrentText("tail")
                selected_roles.append("tail_cam")
            elif row["backend"] == "basler":
                row["checkbox"].setChecked(True)
                row["role_edit"].setText("heart_cam")
                row["tracking_combo"].setCurrentText("heart_rate")
                selected_roles.append("heart_cam")

        cameras = dialog.get_cameras_config()

        self.assertEqual(len(cameras), 2)
        by_role = {c["role"]: c for c in cameras}
        self.assertEqual(set(by_role.keys()), set(selected_roles))

        self.assertEqual(by_role["tail_cam"]["camera"]["type"], "opencv")
        self.assertEqual(by_role["tail_cam"]["camera"]["camera_params"], {"cam_idx": 0})
        self.assertEqual(by_role["tail_cam"]["tracking"]["method"], "tail")

        self.assertEqual(by_role["heart_cam"]["camera"]["type"], "basler")
        self.assertEqual(
            by_role["heart_cam"]["camera"]["camera_params"], {"cam_idx": "SN123"}
        )
        self.assertEqual(by_role["heart_cam"]["tracking"]["method"], "heart_rate")

    def test_no_tracking_selection_omits_tracking_key(self):
        detected = {"opencv": [0]}
        dialog = CameraSetupDialog(detected=detected)
        dialog._rows[0]["checkbox"].setChecked(True)

        cameras = dialog.get_cameras_config()

        self.assertEqual(len(cameras), 1)
        self.assertNotIn("tracking", cameras[0])

    def test_unchecked_rows_are_excluded(self):
        detected = {"opencv": [0, 1]}
        dialog = CameraSetupDialog(detected=detected)
        # Nothing checked:
        cameras = dialog.get_cameras_config()
        self.assertEqual(cameras, [])

    def test_this_config_is_directly_consumable_by_tracking_experiment(self):
        """The dialog's output should be exactly the shape Phase 3a expects,
        with zero glue code needed - the actual point of this dialog."""
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )
        detected = {"opencv": [0]}
        dialog = CameraSetupDialog(detected=detected)
        dialog._rows[0]["checkbox"].setChecked(True)
        dialog._rows[0]["role_edit"].setText("cam0")
        dialog._rows[0]["tracking_combo"].setCurrentText("tail")
        cameras_config = dialog.get_cameras_config()
        # Swap in a video file so this is actually constructible without hardware:
        cameras_config[0]["camera"] = dict(video_file=video_file)

        test_dir = tempfile.mkdtemp()
        try:
            exp = TrackingExperiment(
                app=self.app,
                dir_save=test_dir,
                protocol=TestProtocolGui(),
                cameras=cameras_config,
                log_format="hdf5",
            )
            self.assertEqual(set(exp.cameras.keys()), {"cam0"})
            # No start_experiment() call here (no real experiment run, just
            # checking construction), so no window/live processes exist to
            # wrap_up() - just release the shared-memory segments directly.
            for cam in exp.cameras.values():
                cam.frame_queue.close()
                cam.frame_queue.unlink()
        finally:
            shutil.rmtree(test_dir)

    def test_add_video_camera_gui_adds_checked_row(self):
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )
        dialog = CameraSetupDialog(detected={})  # no hardware at all
        self.assertIsNotNone(dialog._no_cameras_label)
        with patch.object(
            camera_setup_dialog_mod.QFileDialog,
            "getOpenFileName",
            return_value=(video_file, ""),
        ):
            dialog.add_video_camera_gui()

        self.assertEqual(len(dialog._rows), 1)
        self.assertIsNone(dialog._no_cameras_label)
        cameras = dialog.get_cameras_config()
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0]["camera"], dict(video_file=video_file))
        self.assertEqual(cameras[0]["role"], Path(video_file).stem)

    def test_save_and_load_recreates_simulated_camera_row(self):
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )
        dialog = CameraSetupDialog(detected={})
        dialog._add_row("video_file", video_file, role="heart_cam", checked=True)
        dialog._rows[0]["tracking_combo"].setCurrentText("heart_rate")

        test_dir = tempfile.mkdtemp()
        try:
            config_path = str(Path(test_dir) / "cfg.json")
            dialog.save_config(config_path)

            # A brand new dialog, with no rows at all - the simulated camera
            # isn't "detected" by anything, so load_config must recreate it:
            fresh_dialog = CameraSetupDialog(detected={})
            self.assertEqual(fresh_dialog._rows, [])
            fresh_dialog.load_config(config_path)

            self.assertEqual(len(fresh_dialog._rows), 1)
            cameras = fresh_dialog.get_cameras_config()
            self.assertEqual(len(cameras), 1)
            self.assertEqual(cameras[0]["role"], "heart_cam")
            self.assertEqual(cameras[0]["camera"], dict(video_file=video_file))
            self.assertEqual(cameras[0]["tracking"], dict(method="heart_rate"))
        finally:
            shutil.rmtree(test_dir)
