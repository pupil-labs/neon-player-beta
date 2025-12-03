from datetime import datetime

from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.expander import Expander, ExpanderList
from qt_property_widgets.widgets import PropertyForm, PropertyWidget

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.ui import ListPropertyAppenderAction


class RecordingInfoWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)

        main_layout.addWidget(QLabel("<b>Recording ID</b>"))
        self.recording_id_label = QLabel("-")
        main_layout.addWidget(self.recording_id_label)
        main_layout.addSpacing(10)

        main_layout.addWidget(QLabel("<b>Recorded Date</b>"))
        self.recording_date_label = QLabel("-")
        main_layout.addWidget(self.recording_date_label)
        main_layout.addSpacing(10)

        main_layout.addWidget(QLabel("<b>Wearer</b>"))
        self.wearer_label = QLabel("-")
        main_layout.addWidget(self.wearer_label)

        app = neon_player.instance()
        app.recording_loaded.connect(self.on_recording_loaded)
        app.recording_unloaded.connect(self.on_recording_unloaded)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.recording_id_label.setText(recording.info["recording_id"])
        start_time = datetime.fromtimestamp(recording.info["start_time"] / 1e9)
        start_time_str = start_time.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        self.recording_date_label.setText(start_time_str)
        self.wearer_label.setText(recording.wearer["name"])

    def on_recording_unloaded(self) -> None:
        self.recording_id_label.setText("-")
        self.recording_date_label.setText("-")
        self.wearer_label.setText("-")


class SettingsPanel(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        app = neon_player.instance()
        app.recording_loaded.connect(self.on_recording_loaded)
        app.recording_unloaded.connect(self.on_recording_unloaded)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout()
        self.content_widget.setLayout(self.content_layout)
        self.setWidgetResizable(True)

        self.plugin_list_widget = ExpanderList(parent=self)
        self.setMinimumSize(400, 100)

        self.plugin_class_expanders: dict[str, Expander] = {}

        self.recording_info_widget = RecordingInfoWidget()
        self.content_layout.addWidget(Expander(
            self,
            "Recording Information",
            self.recording_info_widget,
            True
        ))

        header = QLabel("<h3>Enabled Plugins</h3>")
        header.setStyleSheet("padding-top: 30px")
        self.content_layout.addWidget(header)
        self.content_layout.addWidget(self.plugin_list_widget)

        self.setWidget(self.content_widget)
        self.plugins_form = None

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        app = neon_player.instance()
        self.plugins_form = Expander(
            self,
            "Plugin Manager",
            PropertyWidget.from_property("enabled_plugins", app.recording_settings)
        )
        self.content_layout.insertWidget(1, self.plugins_form)

    def on_recording_unloaded(self) -> None:
        if self.plugins_form is not None:
            self.content_layout.removeWidget(self.plugins_form)
            self.plugins_form.deleteLater()
            self.plugins_form = None

    def add_plugin_settings(self, instance: Plugin) -> None:
        app = neon_player.instance()

        cls = instance.__class__
        class_name = cls.__name__

        settings_form = PropertyForm(instance)
        expander = self.plugin_list_widget.add_expander(
            cls.get_label(),
            settings_form,
            not app.loading_recording
        )
        if hasattr(instance, "header_action"):
            tb = QToolButton()
            tb.setText(instance.header_action.name)
            tb.setCursor(Qt.CursorShape.PointingHandCursor)
            if isinstance(instance.header_action, ListPropertyAppenderAction):
                def do_add():
                    widget = settings_form.property_widgets.get(
                        instance.header_action.property_name, None
                    )
                    if widget and hasattr(widget, "on_add_button_clicked"):
                        widget.on_add_button_clicked()

            tb.clicked.connect(lambda _: do_add())
            tb.setObjectName("HeaderAction")
            expander.controls_layout.addWidget(tb)

        self.plugin_class_expanders[class_name] = expander
        if not app.loading_recording:
            QTimer.singleShot(
                100,
                lambda: self.plugin_list_widget.highlight(expander)
            )

    def remove_plugin_settings(self, class_name: str) -> None:
        expander = self.plugin_class_expanders[class_name]
        self.plugin_list_widget.remove_expander(expander)
        del self.plugin_class_expanders[class_name]

