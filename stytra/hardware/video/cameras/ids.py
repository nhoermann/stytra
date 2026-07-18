from stytra.hardware.video.cameras.interface import Camera, CameraError

try:
    from ids_peak import ids_peak
    from ids_peak import ids_peak_ipl_extension
except ImportError:
    ids_peak = None
    ids_peak_ipl_extension = None

_PARAM_NODE_NAMES = dict(
    exposure="ExposureTime", framerate="AcquisitionFrameRate", gain="Gain"
)


class IdsCamera(Camera):
    """Control of an IDS camera via the `ids_peak
    <https://pypi.org/project/ids-peak/>`_ genericAPI.

    Untested against real hardware (no IDS camera available in this
    environment) - the numpy conversion in :meth:`read` (``get_numpy_2D()``
    on the ``ids_peak_ipl`` image, per IDS's own example scripts) is the
    piece most likely to need adjustment for a given pixel format/SDK
    version; verify on first real-camera run.

    Parameters
    ----------
    camera_id : int or str
        index into the enumerated device list, or a device serial number.
        If None, the first detected device is used.
    """

    def __init__(self, camera_id=None, **kwargs):
        super().__init__(**kwargs)
        self.camera_id = camera_id
        self.device = None
        self.nodemap = None
        self.data_stream = None

    @staticmethod
    def list_devices():
        if ids_peak is None:
            return []
        ids_peak.Library.Initialize()
        device_manager = ids_peak.DeviceManager.Instance()
        device_manager.Update()
        return [dev.SerialNumber() for dev in device_manager.Devices()]

    def open_camera(self):
        messages = []
        if ids_peak is None:
            raise CameraError("ids_peak is not installed")

        ids_peak.Library.Initialize()
        device_manager = ids_peak.DeviceManager.Instance()
        device_manager.Update()
        devices = device_manager.Devices()
        if len(devices) == 0:
            raise CameraError("No IDS camera found")

        if self.camera_id is None:
            index = 0
        elif isinstance(self.camera_id, int):
            index = self.camera_id
        else:
            index = next(
                i
                for i, dev in enumerate(devices)
                if dev.SerialNumber() == self.camera_id
            )

        self.device = devices[index].OpenDevice(ids_peak.DeviceAccessType_Control)
        messages.append("I:Opened IDS camera {}".format(devices[index].DisplayName()))

        self.nodemap = self.device.RemoteDevice().NodeMaps()[0]

        payload_size = self.nodemap.FindNode("PayloadSize").Value()
        self.data_stream = self.device.DataStreams()[0].OpenDataStream()
        n_buffers = self.data_stream.NumBuffersAnnouncedMinRequired()
        for _ in range(n_buffers):
            buffer = self.data_stream.AllocAndAnnounceBuffer(payload_size)
            self.data_stream.QueueBuffer(buffer)

        self.data_stream.StartAcquisition()
        self.nodemap.FindNode("AcquisitionStart").Execute()
        self.nodemap.FindNode("AcquisitionStart").WaitUntilDone()

        return messages

    def set(self, param, val):
        node_name = _PARAM_NODE_NAMES.get(param)
        if node_name is None:
            return ["W:{} not implemented for IDS cameras".format(param)]
        try:
            value = val * 1000 if param == "exposure" else val
            self.nodemap.FindNode(node_name).SetValue(value)
            return []
        except Exception as e:
            return ["E:Invalid {} value {}: {}".format(param, val, e)]

    def read(self):
        try:
            buffer = self.data_stream.WaitForFinishedBuffer(1000)
            image = ids_peak_ipl_extension.BufferToImage(buffer)
            arr = image.get_numpy_2D().copy()
            self.data_stream.QueueBuffer(buffer)
            return arr
        except Exception:
            return None

    def release(self):
        try:
            self.nodemap.FindNode("AcquisitionStop").Execute()
            self.nodemap.FindNode("AcquisitionStop").WaitUntilDone()
            self.data_stream.StopAcquisition(ids_peak.AcquisitionStopMode_Default)
        except Exception:
            pass
        ids_peak.Library.Close()
