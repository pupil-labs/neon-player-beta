from datetime import datetime

from pupil_labs.neon_recording import NeonRecording
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.expander import Expander, ExpanderList
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin


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

        main_layout.addWidget(QLabel("<b>Recorded</b>"))
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


class SettingsPanel(ExpanderList):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setMinimumSize(400, 100)

        self.plugin_class_expanders: dict[str, Expander] = {}

        self.recording_info_widget = RecordingInfoWidget()
        self.add_expander(
            "Recording", self.recording_info_widget, expanded=True, sort_key="000"
        )

    def add_plugin_settings(self, instance: Plugin) -> None:
        app = neon_player.instance()

        cls = instance.__class__
        class_name = cls.__name__

        settings_form = PropertyForm(instance)
        expander = self.add_expander(
            cls.get_label(),
            settings_form,
            not app.loading_recording
        )
        self.plugin_class_expanders[class_name] = expander

    def remove_plugin_settings(self, class_name: str) -> None:
        expander = self.plugin_class_expanders[class_name]
        self.remove_expander(expander)
        del self.plugin_class_expanders[class_name]

