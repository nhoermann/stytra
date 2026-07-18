from stytra.tracking.pipelines import Pipeline
from stytra.tracking.preprocessing import Prefilter, BackgroundSubtractor
from stytra.tracking.tail import CentroidTrackingMethod
from stytra.tracking.fish import FishTrackingMethod
from stytra.tracking.eyes import EyeTrackingMethod
from stytra.tracking.heart import HeartRateTrackingMethod
from stytra.tracking.fin import PectoralFinTrackingMethod
from stytra.gui.fishplots import TailStreamPlot, BoutPlot
from stytra.gui.camera_display import (
    TailTrackingSelection,
    CameraViewFish,
    EyeTrackingSelection,
    EyeTailTrackingSelection,
    HeartRateSelection,
    PectoralFinSelection,
)


class TailTrackingPipeline(Pipeline):
    def __init__(self):
        super().__init__()
        self.filter = Prefilter(parent=self.root)
        self.tailtrack = CentroidTrackingMethod(parent=self.filter)
        self.extra_widget = TailStreamPlot
        self.display_overlay = TailTrackingSelection


class FishTrackingPipeline(Pipeline):
    def __init__(self):
        super().__init__()
        self.bgsub = BackgroundSubtractor(parent=self.root)
        self.fishtrack = FishTrackingMethod(parent=self.bgsub)
        self.extra_widget = BoutPlot
        self.display_overlay = CameraViewFish


class EyeTrackingPipeline(Pipeline):
    def __init__(self):
        super().__init__()
        # self.filter = Prefilter(parent=self.root)
        self.eyetrack = EyeTrackingMethod(parent=self.root)
        self.display_overlay = EyeTrackingSelection


class EyeTailTrackingPipeline(Pipeline):
    def __init__(self):
        super().__init__()
        self.filter = Prefilter(parent=self.root)
        self.tailtrack = CentroidTrackingMethod(parent=self.filter)

        self.eyetrack = EyeTrackingMethod(parent=self.root)
        self.display_overlay = EyeTailTrackingSelection


class HeartRateTrackingPipeline(Pipeline):
    def __init__(self):
        super().__init__()
        self.heartrate = HeartRateTrackingMethod(parent=self.root)
        self.display_overlay = HeartRateSelection


class PectoralFinTrackingPipeline(Pipeline):
    def __init__(self):
        super().__init__()
        self.fintrack = PectoralFinTrackingMethod(parent=self.root)
        self.display_overlay = PectoralFinSelection


pipeline_dict = dict(
    tail=TailTrackingPipeline,
    fish=FishTrackingPipeline,
    eyes=EyeTrackingPipeline,
    eyes_tail=EyeTailTrackingPipeline,
    heart_rate=HeartRateTrackingPipeline,
    pectoral_fin=PectoralFinTrackingPipeline,
)
