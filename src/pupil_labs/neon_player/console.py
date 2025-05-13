import typing as T

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pupil_labs import neon_player
from pupil_labs.neon_player.expander import Expander
from pupil_labs.neon_player.job_manager import BGWorker


class JobProgressBar(QProgressBar):
    def __init__(self, worker: BGWorker, *args: T.Any, **kwargs: T.Any) -> None:
        super().__init__(*args, **kwargs)

        self.worker = worker
        self.worker.qt_helper.progress_changed.connect(lambda v: self.setValue(v * 100))


class ConsoleWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Neon Player Console")
        self.resize(800, 600)

        # Main layout
        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        # Job list section
        self.job_table = QWidget()
        self.job_table_layout = QFormLayout()
        self.job_table.setLayout(self.job_table_layout)

        self.job_table_expander = Expander(title="Jobs")
        self.job_table_expander.set_content_widget(self.job_table)
        self.main_layout.addWidget(self.job_table_expander)

        # Log section
        self.console_widget = QTextEdit()
        self.console_widget.setReadOnly(True)
        self.console_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.console_expander = Expander(title="Console")
        self.console_expander.set_content_widget(self.console_widget)
        self.console_expander.expanded_changed.connect(lambda _: self.update_stretches())
        self.main_layout.addWidget(self.console_expander)

        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.main_layout.addWidget(self.spacer)

        # Buttons
        button_layout = QHBoxLayout()
        self.copy_log_button = QPushButton("Copy Log")
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.copy_log_button)
        button_layout.addWidget(self.close_button)
        self.main_layout.addLayout(button_layout)

        app = neon_player.instance()
        app.job_manager.job_started.connect(self.on_job_added)
        app.job_manager.job_finished.connect(self.on_job_finished)
        app.job_manager.progress_changed.connect(self.on_total_updated)

    def on_job_added(self, worker: BGWorker) -> None:
        self.job_table_layout.addRow(worker.name, JobProgressBar(worker))

    def on_job_finished(self, worker: BGWorker) -> None:
        for row_idx in range(self.job_table_layout.rowCount()):
            item = self.job_table_layout.itemAt(row_idx, QFormLayout.ItemRole.FieldRole)
            widget = item.widget()
            if isinstance(widget, JobProgressBar) and widget.worker == worker:
                self.job_table_layout.removeRow(row_idx)
                break

    def on_total_updated(self, total_progress: float) -> None:
        pass

    def update_stretches(self) -> None:
        c_stretch = 1 if self.console_expander.expanded else 0
        self.main_layout.setStretch(1, c_stretch)
        self.main_layout.setStretch(2, 1 - c_stretch)
