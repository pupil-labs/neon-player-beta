from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QProgressBar,
    QVBoxLayout,
)

from ..plugin_management.installation import InstallationWorker


class PluginInstallationDialog(QDialog):
    def __init__(
        self, dependencies_to_install: list[str], plugin_req: str, parent=None
    ):
        super().__init__(parent)
        self.dependencies_to_install = dependencies_to_install

        self.setWindowTitle("Plugin Dependency Installation")
        self.setMinimumWidth(400)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.label = QLabel(
            f"{len(dependencies_to_install)} new package(s) are required by one or more of your plugins: \n {plugin_req}."  # noqa: E501
        )
        self.label.setWordWrap(True)
        self.layout.addWidget(self.label)

        self.list_widget = QListWidget()
        self.list_widget.addItems(dependencies_to_install)
        self.layout.addWidget(self.list_widget)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Install")
        self.button_box.accepted.connect(self.start_installation)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

        self.worker = None
        self.thread = None

    def start_installation(self):
        self.button_box.setEnabled(False)
        self.list_widget.setVisible(False)
        self.progress_bar.setVisible(True)

        self.thread = QThread()
        self.worker = InstallationWorker(self.dependencies_to_install)
        self.worker.moveToThread(self.thread)

        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def on_progress(self, value: float, message: str):
        self.progress_bar.setValue(int(value * 100))
        self.label.setText(message)

    def on_finished(self, success: bool):
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
        if success:
            self.accept()
        else:
            self.label.setText(
                "An error occurred during installation. See logs for details."
            )
            self.button_box.setStandardButtons(QDialogButtonBox.StandardButton.Cancel)
            self.button_box.setEnabled(True)
