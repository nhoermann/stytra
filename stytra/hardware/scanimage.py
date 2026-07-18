"""Triggers a ScanImage (https://vidriotechnologies.com/) acquisition via
the MATLAB Engine API, synchronized to a stytra protocol starting.
"""

try:
    import matlab.engine
except ImportError:
    matlab = None


class ScanImageMatlabConnection:
    """Triggers a ScanImage acquisition via the MATLAB Engine API, by
    attaching to an already-running, shared MATLAB session that has
    ScanImage's ``hSI`` object loaded.

    The ScanImage-side MATLAB session must call
    ``matlab.engine.shareEngine('<engine_name>')`` once (e.g. from
    ScanImage's own startup/user-function hooks, or manually in the MATLAB
    console) before stytra can connect to it - this is an external setup
    step stytra cannot perform itself.

    Parameters
    ----------
    engine_name : str
        name of the shared MATLAB session to connect to (as passed to
        ``matlab.engine.shareEngine`` on the ScanImage side). If None, the
        first shared session found is used.
    grab_command : str
        MATLAB expression evaluated to start an acquisition. Defaults to
        ScanImage's standard start-grab call; override for e.g.
        ``hSI.startLoop()`` or a custom user function.
    """

    def __init__(self, engine_name=None, grab_command="hSI.startGrab()"):
        self.engine_name = engine_name
        self.grab_command = grab_command
        self.engine = None

    def connect(self):
        """Attach to the shared MATLAB session running ScanImage."""
        if matlab is None:
            raise RuntimeError(
                "matlab.engine is not installed - install it from your "
                "MATLAB installation's extern/engines/python directory."
            )
        if self.engine_name is None:
            names = matlab.engine.find_matlab()
            if not names:
                raise RuntimeError(
                    "No shared MATLAB session found. Run "
                    "matlab.engine.shareEngine() in the MATLAB session "
                    "running ScanImage first."
                )
            self.engine_name = names[0]
        self.engine = matlab.engine.connect_matlab(self.engine_name)

    def start_acquisition(self):
        """Start a ScanImage acquisition by evaluating ``grab_command``."""
        if self.engine is None:
            raise RuntimeError("Not connected to a MATLAB/ScanImage session")
        self.engine.eval(self.grab_command + ";", nargout=0)

    def close(self):
        """Detach from the shared MATLAB session (does not stop MATLAB)."""
        self.engine = None
