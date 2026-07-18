import logging
import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QLabel,
    QWidget,
    QHBoxLayout,
    QPlainTextEdit,
    QMainWindow,
    QCheckBox,
    QVBoxLayout,
    QDockWidget,
    QFileDialog,
    QMessageBox,
)

from stytra.gui.monitor_control import ProjectorAndCalibrationWidget
from stytra.gui.multiscope import MultiStreamPlot, FrameratePlot
from stytra.gui.protocol_control import ProtocolControlToolbar
from stytra.gui.camera_display import CameraViewWidget
from stytra.gui.buttons import IconButton, ToggleIconButton
from stytra.gui.status_display import StatusMessageDisplay
from stytra.gui.framerate_viewer import MultiFrameratesWidget

from stytra.stimulation.stimulus_display import StimulusDisplayOnMainWindow

from stytra.lightparam.gui import ParameterGui, pretty_name, ControlCombo, ControlButton


class QPlainTextEditLogger(logging.Handler):
    def __init__(self):
        super().__init__()
        self.widget = QPlainTextEdit()
        self.widget.setReadOnly(True)

    def emit(self, record):
        msg = "{} {}".format(
            datetime.datetime.now().strftime("[%H:%M:%S]"), self.format(record)
        )
        try:
            self.widget.appendPlainText(msg)
        except:
            pass


class ExperimentWindow(QMainWindow):
    """Window for controlling a simple experiment including only a monitor
    the relative controls and the buttons for data_log and protocol control.
    All widgets objects are created and connected in the `__init__` and then added
    ti the GUI in the `construct_ui` method

    Parameters
    ----------
    experiment : `Experiment <stytra.experiments.Experiment>` object
        experiment for which the window is built.

    Returns
    -------

    """

    def __init__(self, experiment, **kwargs):
        """ """
        super().__init__(**kwargs)
        self.experiment = experiment

        self.setWindowTitle("Stytra | " + pretty_name(type(experiment.protocol).name))

        self.docks = dict()

        self.toolbar_control = ProtocolControlToolbar(experiment.protocol_runner, self)
        self.toolbar_control.setObjectName("toolbar")

        # Connect signals from the protocol_control:
        self.toolbar_control.sig_start_protocol.connect(experiment.start_protocol)
        self.toolbar_control.sig_stop_protocol.connect(experiment.end_protocol)

        self.btn_metadata = IconButton(
            icon_name="edit_fish", action_name="Edit metadata"
        )
        self.btn_metadata.clicked.connect(self.show_metadata_gui)
        self.toolbar_control.addWidget(self.btn_metadata)

        self.act_folder = self.toolbar_control.addAction(
            "Save in {}".format(self.experiment.base_dir)
        )
        self.act_folder.triggered.connect(self.change_folder_gui)

        if self.experiment.database is not None:
            self.chk_db = ToggleIconButton(
                action_on="Use DB",
                icon_on="dbON",
                icon_off="dbOFF",
                on=self.experiment.use_db,
            )
            self.chk_db.toggled.connect(self.toggle_db)
            self.toolbar_control.addWidget(self.chk_db)

        if experiment.trigger is not None:
            self.chk_scope = QCheckBox("Wait for trigger signal")

        self.logger = QPlainTextEditLogger()
        self.experiment.logger.addHandler(self.logger)

        self.status_display = StatusMessageDisplay(logger=self.experiment.logger)
        self.statusBar().addWidget(self.status_display)

        self.plot_framerate = MultiFrameratesWidget()
        self.plot_framerate.add_framerate(self.experiment.protocol_runner.framerate_acc)

        self.metadata_win = None

    def change_folder_gui(self):
        """Open dialog window to specify a new saving directory."""
        folder = QFileDialog.getExistingDirectory(
            caption="Results folder", directory=self.experiment.base_dir
        )
        if folder:
            self.experiment.base_dir = folder
            self.act_folder.setText("Save in {}".format(self.experiment.base_dir))

    def show_metadata_gui(self):
        """Open Param GUI to control general experiment and animal metadata."""
        # Create widget, horizontal layout
        self.metadata_win = QWidget()
        self.metadata_win.setLayout(QHBoxLayout())
        # Add metadata widgets to the main one
        self.metadata_win.layout().addWidget(ParameterGui(self.experiment.metadata))
        self.metadata_win.layout().addWidget(
            ParameterGui(self.experiment.metadata_animal)
        )
        self.metadata_win.show()

    def add_dock(self, item: QDockWidget):
        """Adding a new DockWidget updating the docks dictionary."""
        self.docks[item.objectName()] = item

    def construct_ui(self):
        """UI construction function."""
        self.addToolBar(Qt.TopToolBarArea, self.toolbar_control)

        log_dock = QDockWidget("Log", self)
        log_dock.setObjectName("dock_log")
        log_dock.setWidget(self.logger.widget)
        self.add_dock(log_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, log_dock)

        dockFramerate = QDockWidget("Frame rates", self)
        dockFramerate.setWidget(self.plot_framerate)
        dockFramerate.setObjectName("dock_framerates")
        self.addDockWidget(Qt.RightDockWidgetArea, dockFramerate)
        self.add_dock(dockFramerate)

        if self.experiment.trigger is not None:
            self.toolbar_control.addWidget(self.chk_scope)

        self.experiment.gui_timer.timeout.connect(self.plot_framerate.update)

        self.toolbar_control.setObjectName("toolbar_control")
        self.setCentralWidget(None)

    def write_log(self, msg):
        """Write something in the log window."""
        self.log_widget.textCursor().appendPlainText(msg)

    def toggle_db(self, tg):
        """Toggle database button."""
        if self.chk_db.isChecked():
            self.experiment.use_db = True
        else:
            self.experiment.use_db = False

    def closeEvent(self, event):
        """

        Parameters
        ----------
        event : QCloseEvent


        Returns
        -------

        """
        protocol_runner = self.experiment.protocol_runner
        if protocol_runner is not None and protocol_runner.running:
            reply = QMessageBox.question(
                self,
                "Protocol running",
                "A protocol is still running - close anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                if event is not None:
                    event.ignore()
                return

        self.experiment.wrap_up()


class VisualExperimentWindow(ExperimentWindow):
    """Window for controlling a visual experiment, where we add the projector
    calibration widget.

    Parameters
    ----------
    experiment : `Experiment <stytra.experiments.Experiment>` object
        experiment for which the window is built.

    Returns
    -------

    """

    def __init__(self, *args, **kwargs):
        """ """
        super().__init__(*args, **kwargs)

        if not self.experiment.offline:
            self.widget_projection = ProjectorAndCalibrationWidget(self.experiment)
            self.stimulus_display = StimulusDisplayOnMainWindow(self.experiment)

    def construct_ui(self):
        """ """
        super().construct_ui()

        if not self.experiment.offline:
            proj_dock = QDockWidget("Projector configuration", self)
            proj_dock.setWidget(self.widget_projection)
            proj_dock.setObjectName("dock_projector")
            self.add_dock(proj_dock)
            self.addDockWidget(Qt.RightDockWidgetArea, proj_dock)

            stimulus_dis = QDockWidget("Stimulus", self)
            stimulus_dis.setWidget(self.stimulus_display)
            stimulus_dis.setObjectName("stimulus_display")
            self.add_dock(stimulus_dis)
            self.addDockWidget(Qt.LeftDockWidgetArea, stimulus_dis)


class CameraExperimentWindow(VisualExperimentWindow):
    """Window for an experiment with one or more cameras - builds one
    preview tile (and, in `construct_ui`, one dock) per camera role."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        pipelines = getattr(self.experiment, "pipelines", {})
        self.camera_displays = {}
        for role in self.experiment.cameras.keys():
            pipeline = pipelines.get(role)
            if pipeline is not None and pipeline.display_overlay is not None:
                self.camera_displays[role] = pipeline.display_overlay(
                    experiment=self.experiment, role=role
                )
            else:
                self.camera_displays[role] = CameraViewWidget(
                    experiment=self.experiment, role=role
                )

        self.plot_framerate.setMaximumHeight(120)

        for cam in self.experiment.cameras.values():
            self.status_display.addMessageQueue(cam.message_queue)

    @property
    def camera_display(self):
        """The first (or only) camera tile - kept for code that hasn't been
        made multi-camera-aware yet (e.g. `save_image` on protocol end)."""
        return next(iter(self.camera_displays.values()))

    def construct_ui(self):
        super().construct_ui()

        self.experiment.gui_timer.timeout.connect(self.status_display.refresh)

        for role in self.experiment.cameras.keys():
            dock_camera = QDockWidget("Camera ({})".format(role), self)
            dock_camera.setWidget(self.camera_displays[role])
            dock_camera.setObjectName("dock_camera_{}".format(role))
            self.addDockWidget(Qt.LeftDockWidgetArea, dock_camera)
            self.add_dock(dock_camera)

        for acc in self.experiment.acc_camera_framerates.values():
            self.plot_framerate.add_framerate(acc)

        # moving the framerate dock
        self.removeDockWidget(self.docks["dock_framerates"])
        self.addDockWidget(Qt.LeftDockWidgetArea, self.docks["dock_framerates"])
        self.docks["dock_framerates"].setVisible(True)


class DynamicStimExperimentWindow(VisualExperimentWindow):
    """Window for plotting a dynamically varying stimulus.

    Parameters
    ----------

    Returns
    -------

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.monitoring_widget = QWidget()
        self.monitoring_layout = QVBoxLayout()
        self.monitoring_widget.setLayout(self.monitoring_layout)

        # Stream plot:
        self.stream_plot = MultiStreamPlot(experiment=self.experiment)
        self.monitoring_layout.addWidget(self.stream_plot)

    def construct_ui(self):
        """ """

        super().construct_ui()
        self.experiment.gui_timer.timeout.connect(self.stream_plot.update)
        # TODO put in right place
        monitoring_widget = QWidget()
        monitoring_widget.setLayout(self.monitoring_layout)
        monitoring_dock = QDockWidget("Tracking", self)
        monitoring_dock.setWidget(monitoring_widget)
        monitoring_dock.setObjectName("monitoring_dock")
        self.addDockWidget(Qt.RightDockWidgetArea, monitoring_dock)
        self.add_dock(monitoring_dock)


class TrackingExperimentWindow(CameraExperimentWindow):
    """Window for controlling an experiment where the tail of an
    embedded fish is tracked.

    Parameters
    ----------

    Returns
    -------

    """

    def __init__(self, tracking=True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # TODO refactor movement detection
        self.tracking = tracking

        self.monitoring_widget = QWidget()
        self.monitoring_layout = QVBoxLayout()
        self.monitoring_widget.setLayout(self.monitoring_layout)

        self.stream_plot = MultiStreamPlot(experiment=self.experiment)

        self.monitoring_layout.addWidget(self.stream_plot)

        # One set of tracking controls (diagnostics dropdown + params button)
        # per camera that actually has a tracking pipeline - added onto that
        # camera's own tile, rather than one global control bound to "the
        # first camera".
        self.extra_widgets = {}
        self.drop_displays = {}
        self.buttons_tracking_params = {}
        self.track_params_wnds = {}

        for role, pipeline in self.experiment.pipelines.items():
            if pipeline.extra_widget is not None:
                self.extra_widgets[role] = pipeline.extra_widget(
                    self.experiment.acc_trackings[role]
                )

            drop_display = ControlCombo(pipeline.all_params["diagnostics"], "image")
            camera_display = self.camera_displays[role]
            if hasattr(camera_display, "set_pos_from_tree"):
                drop_display.control.currentTextChanged.connect(
                    camera_display.set_pos_from_tree
                )
            self.drop_displays[role] = drop_display

            button_tracking_params = IconButton(
                icon_name="edit_tracking",
                action_name="Change tracking parameters ({})".format(role),
            )
            button_tracking_params.clicked.connect(
                lambda checked=False, r=role: self.open_tracking_params_tree(r)
            )
            self.buttons_tracking_params[role] = button_tracking_params

            camera_display.layout_control.addStretch(10)
            camera_display.layout_control.addWidget(drop_display)
            camera_display.layout_control.addWidget(button_tracking_params)

        for dispatcher in self.experiment.frame_dispatchers.values():
            self.status_display.addMessageQueue(dispatcher.message_queue)

    def construct_ui(self):
        """ """
        previous_widget = super().construct_ui()
        self.experiment.gui_timer.timeout.connect(self.stream_plot.update)

        monitoring_widget = QWidget()
        monitoring_widget.setLayout(self.monitoring_layout)
        monitoring_dock = QDockWidget("Monitoring", self)
        monitoring_dock.setObjectName("dock_monitoring")
        monitoring_dock.setWidget(monitoring_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, monitoring_dock)
        self.add_dock(monitoring_dock)

        for acc in self.experiment.acc_tracking_framerates.values():
            self.plot_framerate.add_framerate(acc)

        for role, extra_widget in self.extra_widgets.items():
            self.experiment.gui_timer.timeout.connect(extra_widget.update)

            dock_extra = QDockWidget(extra_widget.title, self)
            dock_extra.setObjectName("dock_extra_{}".format(role))
            dock_extra.setWidget(extra_widget)
            self.add_dock(dock_extra)
            self.addDockWidget(Qt.RightDockWidgetArea, dock_extra)
            dock_extra.setVisible(False)

        return previous_widget

    def open_tracking_params_tree(self, role):
        """ """
        wnd = QWidget()
        wnd.setLayout(QVBoxLayout())
        pipeline = self.experiment.pipelines[role]
        for paramsname, paramspar in pipeline.all_params.items():
            if (
                paramsname == "diagnostics"
                or paramsname == "reset"
                or len(paramspar.params.items()) == 0
            ):
                continue
            wnd.layout().addWidget(QLabel(paramsname.replace("/", "→")))
            wnd.layout().addWidget(ParameterGui(paramspar))

        wnd.layout().addWidget(ControlButton(pipeline.all_params["reset"], "reset"))

        wnd.setWindowTitle("Tracking parameters ({})".format(role))

        wnd.show()
        self.track_params_wnds[role] = wnd
