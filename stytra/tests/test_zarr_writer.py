import os
import shutil
import tempfile
import unittest
from multiprocessing import Queue, Event
from pathlib import Path
from time import sleep

import numpy as np
import zarr
from PyQt5.QtWidgets import QApplication

from stytra.hardware.video.write import ZarrVideoWriter
from stytra.experiments.tracking_experiments import TrackingExperiment
from stytra.stimulation import Protocol, Pause

PROTOCOL_DURATION = 5
N_REFRESH_EVTS = 10


class TestProtocolZarr(Protocol):
    name = "test_protocol_zarr"

    def get_stim_sequence(self):
        return [Pause(duration=PROTOCOL_DURATION)]


def _make_writer(test_dir):
    return ZarrVideoWriter(
        input_queue=Queue(),
        recording_event=Event(),
        reset_event=Event(),
        finish_event=Event(),
        log_format="hdf5",
    )


class TestZarrVideoWriterUnit(unittest.TestCase):
    """Direct unit tests of _configure/_ingest_frame/_complete, bypassing
    the process's run() loop entirely - matching how write.py's existing
    writers have no dedicated tests of their own."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.test_dir)

    def test_write_and_read_back(self):
        writer = _make_writer(self.test_dir)
        base = str(Path(self.test_dir) / "rec_")
        writer.filename_queue.put(base)

        frames = [np.random.randint(0, 255, (16, 20), dtype=np.uint8) for _ in range(5)]

        writer._configure(frames[0].shape)
        for frame in frames:
            writer._ingest_frame(frame)
        writer._complete(base)

        store_path = base + "video.zarr"
        group = zarr.open_group(store_path, mode="r")
        array = group["video"]

        self.assertEqual(array.shape, (5, 16, 20))
        self.assertEqual(array.dtype, np.uint8)
        self.assertEqual(array.attrs["n_frames"], 5)
        np.testing.assert_array_equal(array[:], np.stack(frames))

    def test_fallback_then_rename(self):
        """If _configure runs before a real filename arrives, the store is
        opened under the fallback name, then renamed to the real one once
        _complete is called with it - mirroring StreamingVideoWriter.

        The fallback filename has no directory prefix (same as
        StreamingVideoWriter's), so it resolves relative to the process's
        cwd - chdir into test_dir so the store lands somewhere we clean up.
        """
        os.chdir(self.test_dir)
        writer = _make_writer(self.test_dir)
        frame = np.random.randint(0, 255, (8, 8), dtype=np.uint8)

        # No filename pushed yet, so _configure falls back:
        writer._configure(frame.shape)
        fallback_path = Path(ZarrVideoWriter.CONST_FALLBACK_FILENAME + "video.zarr")
        self.assertTrue(fallback_path.exists())

        writer._ingest_frame(frame)

        # Mirror VideoWriter.run()'s own late-filename resolution: it sets
        # this private attr right before calling _complete when the real
        # name only arrives after _configure already fell back. _complete's
        # rename decision reads that internal state, not its `filename` arg.
        real_base = str(Path(self.test_dir) / "real_")
        writer._VideoWriter__filename_base = real_base
        writer._complete(real_base)

        real_path = Path(real_base + "video.zarr")
        self.assertTrue(real_path.exists())
        self.assertFalse(fallback_path.exists())

        group = zarr.open_group(str(real_path), mode="r")
        self.assertEqual(group["video"].shape, (1, 8, 8))

    def test_missing_zarr_raises(self):
        import stytra.hardware.video.write as write_mod

        original = write_mod.zarr
        write_mod.zarr = None
        try:
            with self.assertRaises(RuntimeError):
                _make_writer(self.test_dir)
        finally:
            write_mod.zarr = original


class TestZarrVideoWriterIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_recording_to_zarr_via_experiment(self):
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )

        exp = TrackingExperiment(
            app=self.app,
            dir_save=self.test_dir,
            protocol=TestProtocolZarr(),
            camera=dict(video_file=video_file),
            tracking=dict(method="tail"),
            recording=dict(extension="zarr"),
            log_format="hdf5",
        )

        exp.start_experiment()
        exp.start_protocol()
        for _ in range(N_REFRESH_EVTS):
            exp.protocol_runner.timestep()
            sleep(PROTOCOL_DURATION / N_REFRESH_EVTS)
        exp.end_protocol(save=True)

        # The recorder finalizes the store asynchronously, in its own
        # process, once end_protocol() above clears the recording event -
        # give it a moment before reading the result back from disk.
        sleep(1.0)

        stores = list(Path(self.test_dir).glob("*/*/*video.zarr"))
        self.assertEqual(len(stores), 1)

        group = zarr.open_group(str(stores[0]), mode="r")
        array = group["video"]
        self.assertGreater(array.shape[0], 0)
        self.assertEqual(array.attrs["n_frames"], array.shape[0])

        # Deliberately not calling exp.wrap_up() here: it ends with
        # self.app.closeAllWindows(), which re-enters wrap_up() via
        # ExperimentWindow.closeEvent() while frame_recorders are never
        # told to stop on that path - a pre-existing hang unrelated to
        # ZarrVideoWriter (reproduces identically with H5VideoWriter, and
        # is tracked separately). A plain manual teardown (recorder
        # finish_event + camera kill_event, then join()) *also* hangs here,
        # independent of wrap_up() - isolated to a separate pre-existing
        # issue in the recording-frame_copy_queue teardown path (confirmed
        # via direct instrumentation: TrackingProcess.run() actually returns
        # cleanly, but the OS process never reports as exited afterwards -
        # also tracked separately). Use bounded joins with a terminate()
        # fallback so this test can never hang the suite.
        for role in list(exp.frame_recorders.keys()):
            exp.frame_recorders[role].finish_event.set()
        for cam in exp.cameras.values():
            cam.kill_event.set()

        for proc in (
            list(exp.frame_recorders.values())
            + list(exp.cameras.values())
            + list(exp.frame_dispatchers.values())
        ):
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)

        for cam in exp.cameras.values():
            cam.frame_queue.unlink()
        for dispatcher in exp.frame_dispatchers.values():
            dispatcher.gui_queue.unlink()
            if getattr(dispatcher, "frame_copy_queue", None) is not None:
                dispatcher.frame_copy_queue.unlink()


if __name__ == "__main__":
    unittest.main()
