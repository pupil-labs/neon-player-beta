from datetime import datetime

from pupil_labs.neon_recording import NeonRecording
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qt_property_widgets.expander import Expander, ExpanderList
from qt_property_widgets.widgets import PropertyForm

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, secrets


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


class SecretsManagementWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.secrets_list = QListWidget()
        self.secrets_list.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.secrets_list)

        buttons_layout = QHBoxLayout()
        self.add_button = QPushButton("Add...")
        self.add_button.clicked.connect(self.on_add_secret)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.on_remove_secret)
        self.remove_button.setEnabled(False)
        buttons_layout.addWidget(self.add_button)
        buttons_layout.addWidget(self.remove_button)
        layout.addLayout(buttons_layout)

        self.refresh_secrets_list()

    def refresh_secrets_list(self):
        self.secrets_list.clear()
        keys = secrets.list_secret_keys()
        self.secrets_list.addItems(keys)

    def on_selection_changed(self):
        self.remove_button.setEnabled(len(self.secrets_list.selectedItems()) > 0)

    def on_add_secret(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Secret")
        layout = QVBoxLayout()
        dialog.setLayout(layout)

        layout.addWidget(QLabel("Name:"))
        name_input = QLineEdit()
        layout.addWidget(name_input)

        layout.addWidget(QLabel("Secret:"))
        secret_input = QLineEdit()
        secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(secret_input)

        buttons_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(dialog.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        buttons_layout.addWidget(ok_button)
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)

        if dialog.exec():
            name = name_input.text()
            secret = secret_input.text()
            if name and secret:
                secrets.set_secret(name, secret)
                self.refresh_secrets_list()

    def on_remove_secret(self):
        selected_items = self.secrets_list.selectedItems()
        if not selected_items:
            return

        key_to_remove = selected_items[0].text()
        reply = QMessageBox.question(
            self,
            "Remove Secret",
            f"Are you sure you want to remove the secret '{key_to_remove}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            secrets.delete_secret(key_to_remove)
            self.refresh_secrets_list()


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
        cls = instance.__class__
        class_name = cls.__name__

        settings_form = PropertyForm(instance)
        expander = self.add_expander(cls.get_label(), settings_form)
        self.plugin_class_expanders[class_name] = expander

    def remove_plugin_settings(self, class_name: str) -> None:
        expander = self.plugin_class_expanders[class_name]
        self.remove_expander(expander)
        del self.plugin_class_expanders[class_name]
