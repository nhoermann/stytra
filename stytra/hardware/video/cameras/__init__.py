from stytra.hardware.video.cameras.ximea import XimeaCamera
from stytra.hardware.video.cameras.avt import AvtCamera
from stytra.hardware.video.cameras.spinnaker import SpinnakerCamera
from stytra.hardware.video.cameras.mikrotron import MikrotronCLCamera
from stytra.hardware.video.cameras.opencv import OpenCVCamera
from stytra.hardware.video.cameras.basler import BaslerCamera
from stytra.hardware.video.cameras.ids import IdsCamera


# Update this dictionary when adding a new camera!
camera_class_dict = dict(
    ximea=XimeaCamera,
    avt=AvtCamera,
    basler=BaslerCamera,
    spinnaker=SpinnakerCamera,
    mikrotron=MikrotronCLCamera,
    opencv=OpenCVCamera,
    ids=IdsCamera,
)


def detect_cameras():
    """Detect connected cameras across every registered backend.

    Returns
    -------
    dict
        maps each backend key in ``camera_class_dict`` to the list of
        device identifiers found for it (empty if the vendor SDK isn't
        installed, no devices are connected, or enumeration isn't
        supported for that backend).
    """
    detected = {}
    for key, camera_cls in camera_class_dict.items():
        try:
            detected[key] = camera_cls.list_devices()
        except Exception:
            detected[key] = []
    return detected
