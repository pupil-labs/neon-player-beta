from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
)

from pupil_labs import neon_player


class PluginInstallationDialog(QDialog):
    def __init__(
        self, dependencies_to_install: list[str], plugin_req: str, parent=None
    ):
        super().__init__(parent)
        self.dependencies_to_install = dependencies_to_install

        self.setWindowTitle("Plugin Dependency Installation")
        self.setMinimumWidth(400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.label = QLabel(
            f"<b>{plugin_req}</b> requires {len(dependencies_to_install)} new package(s) and dependencies"  # noqa: E501
        )
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.dependency_bullets = QLabel(
            "<html><ul>" +
            "\n".join([f"<li>{dep}</li>"
            for dep in dependencies_to_install]) + "</ul></html>"
        )
        layout.addWidget(self.dependency_bullets)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        layout.addStretch()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Install")
        self.button_box.accepted.connect(self.start_installation)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def start_installation(self):
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.button_box.setEnabled(False)
        self.job = neon_player.instance().job_manager.run_background_action(
            "Install dependencies", "install_packages", *self.dependencies_to_install
        )
        self.job.finished.connect(self.close)
