from unittest.mock import MagicMock

from stytra.hardware.video.cameras import basler as basler_module
from stytra.hardware.video.cameras import ids as ids_module
from stytra.hardware.video.cameras import opencv as opencv_module
from stytra.hardware.video.cameras.basler import BaslerCamera
from stytra.hardware.video.cameras.ids import IdsCamera
from stytra.hardware.video.cameras.opencv import OpenCVCamera
from stytra.hardware.video.cameras import camera_class_dict, detect_cameras


def test_opencv_list_devices_probes_indices(monkeypatch):
    opened_indices = {0, 1}
    released = []

    def fake_video_capture(index):
        cap = MagicMock()
        cap.isOpened.return_value = index in opened_indices
        cap.release.side_effect = lambda: released.append(index)
        return cap

    monkeypatch.setattr(opencv_module.cv2, "VideoCapture", fake_video_capture)

    assert OpenCVCamera.list_devices(max_index=4) == [0, 1]
    assert released == [0, 1, 2, 3]


def test_basler_list_devices_returns_serials(monkeypatch):
    fake_pylon = MagicMock()
    dev1, dev2 = MagicMock(), MagicMock()
    dev1.GetSerialNumber.return_value = "SN1"
    dev2.GetSerialNumber.return_value = "SN2"
    fake_pylon.TlFactory.GetInstance.return_value.EnumerateDevices.return_value = [
        dev1,
        dev2,
    ]
    monkeypatch.setattr(basler_module, "pylon", fake_pylon, raising=False)

    assert BaslerCamera.list_devices() == ["SN1", "SN2"]


def test_ids_list_devices_returns_serials(monkeypatch):
    fake_ids_peak = MagicMock()
    dev1, dev2 = MagicMock(), MagicMock()
    dev1.SerialNumber.return_value = "IDS1"
    dev2.SerialNumber.return_value = "IDS2"
    fake_ids_peak.DeviceManager.Instance.return_value.Devices.return_value = [
        dev1,
        dev2,
    ]
    monkeypatch.setattr(ids_module, "ids_peak", fake_ids_peak)

    assert IdsCamera.list_devices() == ["IDS1", "IDS2"]
    fake_ids_peak.Library.Initialize.assert_called_once()


def test_ids_list_devices_empty_when_sdk_absent(monkeypatch):
    monkeypatch.setattr(ids_module, "ids_peak", None)
    assert IdsCamera.list_devices() == []


def test_detect_cameras_aggregates_all_backends(monkeypatch):
    monkeypatch.setattr(
        camera_class_dict["opencv"], "list_devices", staticmethod(lambda: [0])
    )
    monkeypatch.setattr(
        camera_class_dict["basler"], "list_devices", staticmethod(lambda: ["SN1"])
    )
    monkeypatch.setattr(
        camera_class_dict["ids"], "list_devices", staticmethod(lambda: ["IDS1"])
    )

    result = detect_cameras()
    assert result["opencv"] == [0]
    assert result["basler"] == ["SN1"]
    assert result["ids"] == ["IDS1"]


def test_detect_cameras_survives_backend_error(monkeypatch):
    def raise_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(
        camera_class_dict["opencv"], "list_devices", staticmethod(raise_error)
    )
    monkeypatch.setattr(
        camera_class_dict["basler"], "list_devices", staticmethod(lambda: ["SN1"])
    )

    result = detect_cameras()
    assert result["opencv"] == []
    assert result["basler"] == ["SN1"]
