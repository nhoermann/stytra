import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from stytra import Stytra
from stytra.examples.gratings_exp import GratingsProtocol
from stytra.gui.camera_setup_dialog import CameraSetupDialog

REQUIRES_EXTERNAL_HARDWARE = False


if __name__ == "__main__":
    # NOTE: this needs to run interactively (not through an automated/
    # offscreen test) - CameraSetupDialog pops up a real window and blocks
    # until you click "Use selected cameras" or close it.
    app = QApplication.instance() or QApplication([])

    dialog = CameraSetupDialog()
    # Real detected hardware (if any) is already listed; add as many
    # simulated (video/h5 file) cameras as you like via the button, assign
    # each a role and tracking method, then click "Use selected cameras".
    # "Save config"/"Load config" let you store a setup (e.g. "1 camera,
    # tail only" vs "2 cameras, heart+tail") and reload it next time
    # without re-picking everything by hand.
    if not dialog.exec_():
        sys.exit("Camera setup cancelled.")

    cameras_config = dialog.get_cameras_config()
    if not cameras_config:
        QMessageBox.warning(None, "No cameras selected", "Select at least one camera.")
        sys.exit("No cameras selected.")

    protocol = GratingsProtocol()
    protocol.stytra_config = dict(cameras=cameras_config)

    s = Stytra(protocol=protocol, app=app)
