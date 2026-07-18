import json
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QPushButton,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QCheckBox,
    QLineEdit,
    QFileDialog,
)

from stytra.hardware.video.cameras import detect_cameras
from stytra.experiments.fish_pipelines import pipeline_dict

# Sentinel backend for rows added via "Add simulated camera" - device_id is
# the video/h5 file path rather than a real device index/serial, and
# get_cameras_config() builds a video_file= camera config for these instead
# of a real type=/camera_params= one.
_VIDEO_FILE_BACKEND = "video_file"

# Backends disagree on the keyword their constructor uses to select which
# physical device to open (a pre-existing inconsistency, not introduced
# here) - some (spinnaker, ximea) don't support per-device selection at all
# yet and just always use the first device found, in which case this kwarg
# is harmlessly ignored (every Camera subclass accepts and drops unknown
# kwargs).
_DEVICE_ID_KWARG = dict(opencv="cam_idx", basler="cam_idx")


class CameraSetupDialog(QDialog):
    """Pre-experiment dialog: detects connected cameras across every
    registered backend (:func:`detect_cameras`), lets the user pick which
    to use and assign each a role name and optional tracking method, and
    exposes the result as a ``cameras=[...]`` list in the exact shape
    `CameraVisualExperiment`/`TrackingExperiment` expect (see
    `stytra/experiments/tracking_experiments.py`).

    Deliberately does not launch an experiment itself - a real run needs a
    real, user-supplied `Protocol`. Typical use::

        dialog = CameraSetupDialog()
        dialog.exec_()
        cameras_config = dialog.get_cameras_config()
        Stytra(protocol=MyProtocol(), cameras=cameras_config, ...)

    Alongside real detected hardware, "Add simulated camera..." lets you
    pick a video/h5 file to stand in for a camera - useful for building and
    testing a multi-camera setup with no hardware attached at all, via the
    exact same role/tracking-method controls as a real camera row.
    """

    NO_TRACKING = "(no tracking)"

    def __init__(self, detected=None):
        super().__init__()
        self.setWindowTitle("Camera setup")

        self.detected = detected if detected is not None else detect_cameras()

        self._rows = []
        self._next_row = 1
        self._no_cameras_label = None

        outer_layout = QVBoxLayout()
        self.setLayout(outer_layout)

        self._grid = QGridLayout()
        for col, title in enumerate(["Use", "Backend", "Device", "Role", "Tracking"]):
            self._grid.addWidget(QLabel(title), 0, col)

        for backend, device_ids in self.detected.items():
            for device_id in device_ids:
                self._add_row(backend, device_id)

        if self._next_row == 1:
            self._no_cameras_label = QLabel("No cameras detected.")
            self._grid.addWidget(self._no_cameras_label, 1, 0, 1, 5)
            self._next_row += 1

        outer_layout.addLayout(self._grid)

        self.btn_add_video_camera = QPushButton("Add simulated camera...")
        self.btn_add_video_camera.clicked.connect(self.add_video_camera_gui)
        outer_layout.addWidget(self.btn_add_video_camera)

        buttons_layout = QHBoxLayout()
        self.btn_save_config = QPushButton("Save config")
        self.btn_save_config.clicked.connect(self.save_config_gui)
        buttons_layout.addWidget(self.btn_save_config)

        self.btn_load_config = QPushButton("Load config")
        self.btn_load_config.clicked.connect(self.load_config_gui)
        buttons_layout.addWidget(self.btn_load_config)
        outer_layout.addLayout(buttons_layout)

        self.btn_ok = QPushButton("Use selected cameras")
        self.btn_ok.clicked.connect(self.accept)
        outer_layout.addWidget(self.btn_ok)

    def _add_row(self, backend, device_id, role=None, checked=None):
        """Add one grid row (checkbox, backend/device labels, role, tracking
        method) and its bookkeeping entry in ``self._rows``. Used both for
        cameras found by :func:`detect_cameras` at construction time and for
        rows added later via "Add simulated camera"."""
        if self._no_cameras_label is not None:
            self._grid.removeWidget(self._no_cameras_label)
            self._no_cameras_label.deleteLater()
            self._no_cameras_label = None

        row_i = self._next_row
        device_label = (
            Path(device_id).name if backend == _VIDEO_FILE_BACKEND else str(device_id)
        )

        checkbox = QCheckBox()
        checkbox.setChecked(checked if checked is not None else False)
        role_edit = QLineEdit(role or "{}_{}".format(backend, device_label))
        tracking_combo = QComboBox()
        tracking_combo.addItems([self.NO_TRACKING] + list(pipeline_dict.keys()))

        self._grid.addWidget(checkbox, row_i, 0)
        self._grid.addWidget(QLabel(str(backend)), row_i, 1)
        self._grid.addWidget(QLabel(device_label), row_i, 2)
        self._grid.addWidget(role_edit, row_i, 3)
        self._grid.addWidget(tracking_combo, row_i, 4)

        self._rows.append(
            dict(
                backend=backend,
                device_id=device_id,
                checkbox=checkbox,
                role_edit=role_edit,
                tracking_combo=tracking_combo,
            )
        )
        self._next_row += 1

    def add_video_camera_gui(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a video/h5 file to use as a simulated camera"
        )
        if path:
            self._add_row(_VIDEO_FILE_BACKEND, path, role=Path(path).stem, checked=True)

    def _row_state(self, row):
        return dict(
            backend=row["backend"],
            device_id=row["device_id"],
            checked=row["checkbox"].isChecked(),
            role=row["role_edit"].text(),
            tracking_method=row["tracking_combo"].currentText(),
        )

    def _apply_row_state(self, row, state):
        row["checkbox"].setChecked(state["checked"])
        row["role_edit"].setText(state["role"])
        row["tracking_combo"].setCurrentText(state["tracking_method"])

    def save_config(self, path):
        """Serialize the current role/tracking-method/checked selection for
        every detected row to a JSON file, for reuse in a later session."""
        with open(path, "w") as f:
            json.dump([self._row_state(row) for row in self._rows], f, indent=2)

    def load_config(self, path):
        """Apply a config saved by :meth:`save_config`. Entries for a
        (backend, device_id) that isn't in the *currently* detected rows
        are silently skipped - that device just isn't connected right now.
        Simulated (video_file) rows are the exception: they aren't tied to
        detected hardware, so they're recreated here if missing."""
        with open(path) as f:
            saved_rows = json.load(f)

        existing_keys = {(row["backend"], row["device_id"]) for row in self._rows}
        for state in saved_rows:
            key = (state["backend"], state["device_id"])
            if key not in existing_keys and state["backend"] == _VIDEO_FILE_BACKEND:
                self._add_row(state["backend"], state["device_id"])
                existing_keys.add(key)

        saved_by_key = {(s["backend"], s["device_id"]): s for s in saved_rows}
        for row in self._rows:
            state = saved_by_key.get((row["backend"], row["device_id"]))
            if state is not None:
                self._apply_row_state(row, state)

    def save_config_gui(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save camera setup", filter="JSON (*.json)"
        )
        if path:
            self.save_config(path)

    def load_config_gui(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load camera setup", filter="JSON (*.json)"
        )
        if path:
            self.load_config(path)

    def get_cameras_config(self):
        """Build the ``cameras=[...]`` config list from the checked rows."""
        cameras = []
        for row in self._rows:
            if not row["checkbox"].isChecked():
                continue

            if row["backend"] == _VIDEO_FILE_BACKEND:
                camera_cfg = dict(video_file=row["device_id"])
            else:
                id_kwarg = _DEVICE_ID_KWARG.get(row["backend"], "camera_id")
                camera_cfg = dict(
                    type=row["backend"],
                    camera_params={id_kwarg: row["device_id"]},
                )

            entry = dict(role=row["role_edit"].text(), camera=camera_cfg)

            tracking_method = row["tracking_combo"].currentText()
            if tracking_method != self.NO_TRACKING:
                entry["tracking"] = dict(method=tracking_method)

            cameras.append(entry)
        return cameras
