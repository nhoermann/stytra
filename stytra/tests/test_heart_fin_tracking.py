import json
import shutil
import tempfile
import unittest
from pathlib import Path
from time import sleep

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtWidgets import QApplication

from stytra.experiments.fish_pipelines import (
    HeartRateTrackingPipeline,
    PectoralFinTrackingPipeline,
    pipeline_dict,
)
from stytra.experiments.tracking_experiments import TrackingExperiment
from stytra.stimulation import Protocol, Pause
from stytra.tracking.fin import _fin_angle_from_mask
from stytra.tracking.heart import _estimate_bpm

PROTOCOL_DURATION = 5
N_REFRESH_EVTS = 10


def test_estimate_bpm_recovers_known_frequency():
    framerate = 150.0
    true_bpm = 180.0
    freq_hz = true_bpm / 60.0
    n = 400
    t = np.arange(n) / framerate
    rng = np.random.RandomState(0)
    signal = (
        10 * np.sin(2 * np.pi * freq_hz * t)
        + 2.5 * np.sin(2 * np.pi * 0.05 * t)
        + rng.normal(0, 1, n)
        + 100
    )

    bpm = _estimate_bpm(signal, framerate, 60.0, 300.0)
    assert abs(bpm - true_bpm) < 8


def test_estimate_bpm_returns_nan_for_flat_signal():
    flat = np.full(400, 100.0)
    bpm = _estimate_bpm(flat, 150.0, 60.0, 300.0)
    assert np.isnan(bpm)


@pytest.mark.parametrize("true_angle_deg", [0, 30, 45, 90, 120])
def test_fin_angle_from_mask_recovers_known_angle(true_angle_deg):
    true_angle = np.deg2rad(true_angle_deg)
    h, w = 60, 60
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = h / 2, w / 2
    ct, st = np.cos(true_angle), np.sin(true_angle)
    dx = xx - cx
    dy = yy - cy
    u = dx * ct + dy * st
    v = -dx * st + dy * ct
    mask = ((u / 20) ** 2 + (v / 4) ** 2) <= 1.0

    angle, elongation, area = _fin_angle_from_mask(mask)

    # PCA axis has an inherent 180-degree ambiguity, not a bug.
    diff = (angle - true_angle + np.pi / 2) % np.pi - np.pi / 2
    assert abs(np.degrees(diff)) < 3
    assert 0 < elongation < 1
    assert area > 0


def test_fin_angle_from_mask_empty_mask_returns_nan():
    mask = np.zeros((30, 30), dtype=bool)
    angle, elongation, area = _fin_angle_from_mask(mask)
    assert np.isnan(angle)
    assert area == 0.0


def test_pipeline_dict_registration():
    assert pipeline_dict["heart_rate"] is HeartRateTrackingPipeline
    assert pipeline_dict["pectoral_fin"] is PectoralFinTrackingPipeline


def test_heart_rate_pipeline_smoke():
    pipeline = HeartRateTrackingPipeline()
    pipeline.setup()
    frame = np.full((100, 100), 100, dtype=np.uint8)
    for _ in range(5):
        out = pipeline.run(frame)
    assert "heart_rate_bpm" in out.data._fields
    assert "roi_intensity" in out.data._fields
    assert "heart_rate_bpm" in pipeline.headers_to_plot


def test_pectoral_fin_pipeline_smoke():
    pipeline = PectoralFinTrackingPipeline()
    pipeline.setup()
    frame = np.full((100, 100), 200, dtype=np.uint8)
    frame[40:60, 30:70] = 20  # a dark elongated blob to segment
    out = pipeline.run(frame)
    assert "fin_angle" in out.data._fields
    assert not np.isnan(out.data.fin_angle)
    assert "fin_angle" in pipeline.headers_to_plot


class TestProtocolHeartTail(Protocol):
    name = "test_protocol_heart_tail"

    def get_stim_sequence(self):
        return [Pause(duration=PROTOCOL_DURATION)]


class TestHeartFinMultiCamera(unittest.TestCase):
    """Confirms Phase 3a (multi-camera) and Phase 4 (new tracking methods)
    compose correctly: a heart-rate camera and a tail-tracking camera
    running concurrently, each independently."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @property
    def metadata_path(self):
        return next(Path(self.test_dir).glob("*/*/*.json"))

    def test_heart_rate_and_tail_concurrently(self):
        video_file = str(
            Path(__file__).parent.parent / "examples" / "assets" / "fish_compressed.h5"
        )

        exp = TrackingExperiment(
            app=self.app,
            dir_save=self.test_dir,
            protocol=TestProtocolHeartTail(),
            cameras=[
                dict(
                    role="heart_cam",
                    camera=dict(video_file=video_file),
                    tracking=dict(method="heart_rate"),
                ),
                dict(
                    role="tail_cam",
                    camera=dict(video_file=video_file),
                    tracking=dict(method="tail"),
                ),
            ],
            log_format="hdf5",
        )
        # Small buffer so the heart-rate estimator has a chance to produce a
        # value within the test's short duration (real content has no real
        # heart signal, so the value itself isn't checked - just that the
        # pipeline runs and produces the right shape of output).
        exp.pipelines["heart_cam"].heartrate._params.buffer_length = 20

        exp.start_experiment()
        exp.start_protocol()
        for _ in range(N_REFRESH_EVTS):
            exp.protocol_runner.timestep()
            sleep(PROTOCOL_DURATION / N_REFRESH_EVTS)
        for acc in exp.acc_trackings.values():
            acc.update_list()
        exp.end_protocol(save=True)
        exp.wrap_up()

        with open(self.metadata_path, "r") as f:
            data = json.load(f)

        heart_log = pd.read_hdf(
            self.metadata_path.parent / data["tracking"]["behavior_log_heart_cam"],
            "/data",
        )
        tail_log = pd.read_hdf(
            self.metadata_path.parent / data["tracking"]["behavior_log_tail_cam"],
            "/data",
        )
        self.assertGreater(len(heart_log), 0)
        self.assertGreater(len(tail_log), 0)
        self.assertIn("heart_rate_bpm", heart_log.columns)
        self.assertIn("roi_intensity", heart_log.columns)
        self.assertIn("theta_00", tail_log.columns)

        for cam in exp.cameras.values():
            self.assertFalse(cam.is_alive())
        for dispatcher in exp.frame_dispatchers.values():
            self.assertFalse(dispatcher.is_alive())
