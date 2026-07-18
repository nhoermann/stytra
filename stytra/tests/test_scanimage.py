from unittest.mock import MagicMock

import pytest

from stytra.hardware import scanimage as scanimage_module
from stytra.hardware.scanimage import ScanImageMatlabConnection


def test_connect_raises_if_matlab_engine_not_installed(monkeypatch):
    monkeypatch.setattr(scanimage_module, "matlab", None)
    conn = ScanImageMatlabConnection()
    with pytest.raises(RuntimeError, match="matlab.engine is not installed"):
        conn.connect()


def test_connect_uses_first_found_session_when_name_not_given(monkeypatch):
    fake_matlab = MagicMock()
    fake_matlab.engine.find_matlab.return_value = ["ScanImage_1234"]
    monkeypatch.setattr(scanimage_module, "matlab", fake_matlab)

    conn = ScanImageMatlabConnection()
    conn.connect()

    assert conn.engine_name == "ScanImage_1234"
    fake_matlab.engine.connect_matlab.assert_called_once_with("ScanImage_1234")
    assert conn.engine is fake_matlab.engine.connect_matlab.return_value


def test_connect_uses_given_engine_name(monkeypatch):
    fake_matlab = MagicMock()
    monkeypatch.setattr(scanimage_module, "matlab", fake_matlab)

    conn = ScanImageMatlabConnection(engine_name="MyScope")
    conn.connect()

    fake_matlab.engine.find_matlab.assert_not_called()
    fake_matlab.engine.connect_matlab.assert_called_once_with("MyScope")


def test_connect_raises_if_no_shared_session_found(monkeypatch):
    fake_matlab = MagicMock()
    fake_matlab.engine.find_matlab.return_value = []
    monkeypatch.setattr(scanimage_module, "matlab", fake_matlab)

    conn = ScanImageMatlabConnection()
    with pytest.raises(RuntimeError, match="No shared MATLAB session found"):
        conn.connect()


def test_start_acquisition_raises_if_not_connected():
    conn = ScanImageMatlabConnection()
    with pytest.raises(RuntimeError, match="Not connected"):
        conn.start_acquisition()


def test_start_acquisition_evaluates_grab_command(monkeypatch):
    fake_matlab = MagicMock()
    fake_matlab.engine.find_matlab.return_value = ["ScanImage_1234"]
    monkeypatch.setattr(scanimage_module, "matlab", fake_matlab)

    conn = ScanImageMatlabConnection(grab_command="hSI.startLoop()")
    conn.connect()
    conn.start_acquisition()

    conn.engine.eval.assert_called_once_with("hSI.startLoop();", nargout=0)


def test_close_detaches_engine(monkeypatch):
    fake_matlab = MagicMock()
    fake_matlab.engine.find_matlab.return_value = ["ScanImage_1234"]
    monkeypatch.setattr(scanimage_module, "matlab", fake_matlab)

    conn = ScanImageMatlabConnection()
    conn.connect()
    conn.close()

    assert conn.engine is None
