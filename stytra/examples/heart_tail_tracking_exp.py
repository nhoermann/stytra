from pathlib import Path
from stytra import Stytra
from stytra.examples.gratings_exp import GratingsProtocol

REQUIRES_EXTERNAL_HARDWARE = False

ASSET_VIDEO = str(Path(__file__).parent / "assets" / "fish_compressed.h5")


class HeartTailTrackingProtocol(GratingsProtocol):
    name = "gratings_heart_tail_tracking"

    # Two cameras, one role each - each with its own "tracking" method.
    # Swap the video_file for a real camera config (e.g.
    # dict(type="opencv", camera_params=dict(cam_idx=0))) once you have
    # actual hardware; everything else (ROI widgets, tiled preview docks,
    # per-camera params) stays the same either way.
    stytra_config = dict(
        cameras=[
            dict(
                role="tail_cam",
                camera=dict(video_file=ASSET_VIDEO),
                tracking=dict(embedded=True, method="tail"),
            ),
            dict(
                role="heart_cam",
                camera=dict(video_file=ASSET_VIDEO),
                tracking=dict(method="heart_rate"),
            ),
        ],
    )


if __name__ == "__main__":
    # NOTE: fish_compressed.h5 is tail-tracking footage, not cardiac
    # footage - reused here on both cameras purely so this example runs
    # with zero hardware. The tail-tracking output will be meaningful; the
    # heart-rate camera's ROI/GUI/plotting will all work correctly, but the
    # BPM number itself is meaningless noise without a real beating heart
    # in frame. Point heart_cam's video_file (or swap it for a real camera)
    # at actual cardiac footage to get a real reading.
    s = Stytra(protocol=HeartTailTrackingProtocol())
