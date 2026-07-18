import json
import shutil
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import qimage2ndarray
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import QApplication, QMessageBox

import stytra.gui.container_windows as container_windows_mod
from stytra.experiments.tracking_experiments import TrackingExperiment
from stytra.gui.camera_setup_dialog import CameraSetupDialog
from stytra.gui.status_display import StatusMessageDisplay
from stytra.stimulation import Protocol, Pause
from stytra.stimulation.stimuli.visual import RadialSineStimulus, VideoStimulus


class TestProtocolPolish(Protocol):
    name = "test_protocol_polish"

    def get_stim_sequence(self):
        return [Pause(duration=5)]


def _make_experiment(app, test_dir):
    video_file = str(
        Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
    )
    return TrackingExperiment(
        app=app,
        dir_save=test_dir,
        protocol=TestProtocolPolish(),
        camera=dict(video_file=video_file),
        tracking=dict(method="tail"),
        log_format="hdf5",
    )


class TestChangeFolderGui(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.app = QApplication.instance() or QApplication([])
        self.exp = _make_experiment(self.app, self.test_dir)
        self.exp.start_experiment()

    def tearDown(self):
        self.exp.wrap_up()
        shutil.rmtree(self.test_dir)

    def test_cancel_then_accept(self):
        # A single real experiment/window exercises both the cancel and the
        # accept path, to avoid piling up extra real Qt window
        # constructions across the test suite (this dev machine has a
        # known, pre-existing macOS-only interpreter-teardown fragility
        # under many sequential real-window tests - see MODERNIZATION_
        # PROPOSAL.md/session notes on test_examples.py/test_init_gui.py).
        window = self.exp.window_main
        original_base_dir = self.exp.base_dir
        with patch.object(
            container_windows_mod.QFileDialog, "getExistingDirectory", return_value=""
        ):
            window.change_folder_gui()
        self.assertEqual(self.exp.base_dir, original_base_dir)

        new_dir = tempfile.mkdtemp()
        try:
            with patch.object(
                container_windows_mod.QFileDialog,
                "getExistingDirectory",
                return_value=new_dir,
            ):
                window.change_folder_gui()
            self.assertEqual(self.exp.base_dir, new_dir)
        finally:
            shutil.rmtree(new_dir)


class TestCloseEventConfirmation(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.app = QApplication.instance() or QApplication([])
        self.exp = _make_experiment(self.app, self.test_dir)
        self.exp.start_experiment()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_confirmation_guard(self):
        # One real experiment/window covers all three cases (see the
        # comment on TestChangeFolderGui.test_cancel_then_accept for why
        # this is consolidated into a single test rather than split up).
        window = self.exp.window_main
        original_wrap_up = self.exp.wrap_up
        self.exp.wrap_up = MagicMock()
        try:
            # Not running yet: closes straight through, no prompt.
            self.assertFalse(self.exp.protocol_runner.running)
            with patch.object(
                container_windows_mod.QMessageBox, "question"
            ) as mock_question:
                window.closeEvent(MagicMock())
            mock_question.assert_not_called()
            self.exp.wrap_up.assert_called_once()
            self.exp.wrap_up.reset_mock()

            self.exp.start_protocol()
            self.assertTrue(self.exp.protocol_runner.running)

            # Running, user declines: stays open.
            mock_event = MagicMock()
            with patch.object(
                container_windows_mod.QMessageBox,
                "question",
                return_value=QMessageBox.No,
            ):
                window.closeEvent(mock_event)
            self.exp.wrap_up.assert_not_called()
            mock_event.ignore.assert_called_once()

            # Running, user accepts: wraps up.
            with patch.object(
                container_windows_mod.QMessageBox,
                "question",
                return_value=QMessageBox.Yes,
            ):
                window.closeEvent(MagicMock())
            self.exp.wrap_up.assert_called_once()
        finally:
            self.exp.wrap_up = original_wrap_up
            self.exp.wrap_up()


class TestStatusMessageDisplayLogger(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_warning_routed_to_logger(self):
        logger = MagicMock()
        display = StatusMessageDisplay(logger=logger)
        queue = Queue()
        queue.put("W:something went wrong")
        display.addMessageQueue(queue)
        display.refresh()
        logger.warning.assert_called_once_with("something went wrong")
        logger.error.assert_not_called()

    def test_error_routed_to_logger(self):
        logger = MagicMock()
        display = StatusMessageDisplay(logger=logger)
        queue = Queue()
        queue.put("E:camera disconnected")
        display.addMessageQueue(queue)
        display.refresh()
        logger.error.assert_called_once_with("camera disconnected")

    def test_info_not_routed_to_logger(self):
        logger = MagicMock()
        display = StatusMessageDisplay(logger=logger)
        queue = Queue()
        queue.put("I:just fyi")
        display.addMessageQueue(queue)
        display.refresh()
        logger.warning.assert_not_called()
        logger.error.assert_not_called()

    def test_no_logger_does_not_crash(self):
        display = StatusMessageDisplay()
        queue = Queue()
        queue.put("W:no logger attached")
        display.addMessageQueue(queue)
        display.refresh()  # should not raise


class TestCameraSetupDialogConfig(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_save_and_load_round_trip(self):
        detected = {"opencv": [0, 1]}
        dialog = CameraSetupDialog(detected=detected)
        dialog._rows[0]["checkbox"].setChecked(True)
        dialog._rows[0]["role_edit"].setText("tail_cam")
        dialog._rows[0]["tracking_combo"].setCurrentText("tail")

        config_path = str(Path(self.test_dir) / "cfg.json")
        dialog.save_config(config_path)

        with open(config_path) as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 2)

        fresh_dialog = CameraSetupDialog(detected=detected)
        fresh_dialog.load_config(config_path)

        self.assertTrue(fresh_dialog._rows[0]["checkbox"].isChecked())
        self.assertEqual(fresh_dialog._rows[0]["role_edit"].text(), "tail_cam")
        self.assertEqual(fresh_dialog._rows[0]["tracking_combo"].currentText(), "tail")
        # Untouched row keeps its defaults:
        self.assertFalse(fresh_dialog._rows[1]["checkbox"].isChecked())

    def test_load_skips_devices_not_currently_detected(self):
        dialog = CameraSetupDialog(detected={"opencv": [0]})
        dialog._rows[0]["checkbox"].setChecked(True)
        dialog._rows[0]["role_edit"].setText("cam0")
        config_path = str(Path(self.test_dir) / "cfg.json")
        dialog.save_config(config_path)

        # Next session, a different camera is plugged in instead:
        other_dialog = CameraSetupDialog(detected={"basler": ["SN1"]})
        other_dialog.load_config(config_path)  # should not raise

        self.assertFalse(other_dialog._rows[0]["checkbox"].isChecked())


class TestVideoStimulusCaching(unittest.TestCase):
    def _make_painter(self, w=32, h=24):
        image = QImage(w, h, QImage.Format_RGB32)
        painter = QPainter(image)
        return painter, image

    def test_qimage_is_cached_across_paint_calls(self):
        stim = VideoStimulus(video_path="unused.mp4", duration=1)
        stim._current_frame = np.random.randint(0, 255, (24, 32, 3), dtype=np.uint8)

        painter, _ = self._make_painter()
        stim.paint(painter, 32, 24)
        first_qimg = stim._current_qimg
        self.assertIsNotNone(first_qimg)

        stim.paint(painter, 32, 24)
        self.assertIs(stim._current_qimg, first_qimg)
        painter.end()

    def test_paint_output_matches_uncached_conversion(self):
        stim = VideoStimulus(video_path="unused.mp4", duration=1)
        frame = np.random.randint(0, 255, (24, 32, 3), dtype=np.uint8)
        stim._current_frame = frame

        painter, _ = self._make_painter()
        stim.paint(painter, 32, 24)
        painter.end()

        expected = qimage2ndarray.array2qimage(frame)
        self.assertEqual(stim._current_qimg, expected)

    def test_cache_invalidated_on_new_frame(self):
        stim = VideoStimulus(video_path="unused.mp4", duration=1)
        stim._current_frame = np.zeros((24, 32, 3), dtype=np.uint8)

        painter, _ = self._make_painter()
        stim.paint(painter, 32, 24)
        first_qimg = stim._current_qimg

        # Mirrors what update() does when a new video frame arrives:
        stim._current_frame = np.full((24, 32, 3), 255, dtype=np.uint8)
        stim._current_qimg = None
        stim.paint(painter, 32, 24)
        painter.end()

        self.assertIsNot(stim._current_qimg, first_qimg)
        self.assertEqual(
            stim._current_qimg, qimage2ndarray.array2qimage(stim._current_frame)
        )


class TestRadialSineStimulusCaching(unittest.TestCase):
    def _reference_image(self, w, h, mm_px, period, phase):
        x, y = ((np.arange(d) - d / 2) * mm_px for d in (w, h))
        return np.round(
            np.sin(
                np.sqrt((x[None, :] ** 2 + y[:, None] ** 2) * (2 * np.pi / period))
                + phase
            )
            * 127
            + 127
        ).astype(np.uint8)

    def _make_painter(self, w, h):
        image = QImage(w, h, QImage.Format_RGB32)
        painter = QPainter(image)
        return painter, image

    def test_output_matches_uncached_reference_across_phases(self):
        w, h, mm_px, period = 40, 30, 0.15, 8
        stim = RadialSineStimulus(period=period, velocity=5, duration=1)
        stim._experiment = SimpleNamespace(calibrator=SimpleNamespace(mm_px=mm_px))

        painter, _ = self._make_painter(w, h)
        for phase in (0.0, 1.3, 4.7):
            stim.phase = phase
            stim.paint(painter, w, h)
            np.testing.assert_array_equal(
                stim.image, self._reference_image(w, h, mm_px, period, phase)
            )
        painter.end()

    def test_distance_field_is_cached_across_frames(self):
        w, h, mm_px = 40, 30, 0.15
        stim = RadialSineStimulus(period=8, velocity=5, duration=1)
        stim._experiment = SimpleNamespace(calibrator=SimpleNamespace(mm_px=mm_px))

        painter, _ = self._make_painter(w, h)
        stim.phase = 0.0
        stim.paint(painter, w, h)
        first_field = stim._dist_field

        stim.phase = 2.0
        stim.paint(painter, w, h)
        painter.end()

        self.assertIs(stim._dist_field, first_field)

    def test_distance_field_recomputed_when_mm_px_changes(self):
        w, h = 40, 30
        stim = RadialSineStimulus(period=8, velocity=5, duration=1)
        stim._experiment = SimpleNamespace(calibrator=SimpleNamespace(mm_px=0.15))

        painter, _ = self._make_painter(w, h)
        stim.paint(painter, w, h)
        first_field = stim._dist_field

        stim._experiment.calibrator.mm_px = 0.3
        stim.paint(painter, w, h)
        painter.end()

        self.assertIsNot(stim._dist_field, first_field)
        np.testing.assert_array_equal(
            stim.image, self._reference_image(w, h, 0.3, 8, stim.phase)
        )


class TestCalibrationPainting(unittest.TestCase):
    """Regression coverage for a real crash: CrossCalibrator.paint_calibration_
    pattern passed float pixel coordinates to QPainter.drawLine, which only
    accepts int/QPoint/QLine overloads - PyQt5 raises TypeError, which (since
    it happens inside paintEvent, before p.end()) can leave the QPainter
    active and freeze the display. Covers both the underlying fix and the
    paintEvent-level safety net that keeps any such bug from propagating."""

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_cross_calibrator_paints_without_raising(self):
        from stytra.calibration import CrossCalibrator

        calibrator = CrossCalibrator(mm_px=0.137)
        calibrator.set_pixel_scale(640, 480)

        image = QImage(640, 480, QImage.Format_RGB32)
        painter = QPainter(image)
        try:
            calibrator.paint_calibration_pattern(painter, 480, 640)  # must not raise
        finally:
            painter.end()

    def test_paint_event_survives_calibrator_exception(self):
        from stytra.stimulation.stimulus_display import StimDisplayWidget
        from PyQt5.QtWidgets import QWidget

        StimDisplay = type("StimDisplay", (StimDisplayWidget, QWidget), {})
        calibrator = MagicMock()
        calibrator.enabled = True
        calibrator.paint_calibration_pattern.side_effect = TypeError("boom")

        protocol_runner = MagicMock()
        protocol_runner.running = False

        widget = StimDisplay(
            calibrator=calibrator,
            protocol_runner=protocol_runner,
            record_stim_framerate=None,
        )
        widget.resize(64, 48)

        widget.paintEvent(None)  # must not raise

        calibrator.paint_calibration_pattern.assert_called_once()
        self.assertFalse(calibrator.enabled)


if __name__ == "__main__":
    unittest.main()
