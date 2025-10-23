import logging
import typing as T

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pupil_labs import neon_player
from pupil_labs.neon_player.job_manager import BackgroundJob

LOG_COLORS = {
    "DEBUG": Qt.GlobalColor.green,
    "INFO": Qt.GlobalColor.white,
    "WARNING": Qt.GlobalColor.yellow,
    "ERROR": Qt.GlobalColor.red,
    "CRITICAL": Qt.GlobalColor.magenta,
}

class QTextEditLogger(logging.Handler):
    """Custom logging handler that writes to a QTextEdit.

    This handler buffers log messages until a QTextEdit is set, then flushes them.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter(neon_player.LOG_FORMAT_STRING))
        self._buffer: list[str] = []
        self._text_edit: QTextEdit | None = None

    def set_text_edit(self, text_edit: QTextEdit) -> None:
        self._text_edit = text_edit
        # Flush any buffered messages
        if self._buffer:
            self._text_edit.append("\n".join(self._buffer))
            self._buffer.clear()

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the text edit."""
        msg = self.format(record)
        color = LOG_COLORS[record.levelname]
        self._append_text(msg, color)

    def _append_text(self, text: str, color: Qt.GlobalColor | None = None) -> None:
        if self._text_edit is not None:
            # Save current text color
            current = self._text_edit.textColor()

            if color is not None:
                self._text_edit.setTextColor(color)

            self._text_edit.append(text)

            # Restore original color
            self._text_edit.setTextColor(current)

            # Auto-scroll to bottom
            self.scroll_to_bottom()
        else:
            self._buffer.append(text)

    def scroll_to_bottom(self) -> None:
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        if self._text_edit is None:
            return

        scroll_bar = self._text_edit.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        self._text_edit.horizontalScrollBar().setValue(0)


class JobProgressBar(QWidget):
    def __init__(self, job: BackgroundJob, *args: T.Any, **kwargs: T.Any) -> None:
        super().__init__(*args, **kwargs)

        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.main_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.main_layout.addWidget(self.progress_bar)

        self.cancel_button = QToolButton()
        self.cancel_button.setText("🗑")
        self.cancel_button.setAutoRaise(True)
        self.cancel_button.clicked.connect(job.cancel)
        self.main_layout.addWidget(self.cancel_button)

        self.worker = job
        self.worker.progress_changed.connect(self.on_worker_progress)

    def on_worker_progress(self, v: float):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(v * 100)


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
        self.job_table_layout.setSpacing(3)
        self.job_table.setLayout(self.job_table_layout)

        # Set size policy for job table
        job_table_size_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.job_table.setSizePolicy(job_table_size_policy)

        self.main_layout.addWidget(self.job_table)

        # Log section
        self.console_widget = QTextEdit()
        self.console_widget.setReadOnly(True)
        self.console_widget.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # Set size policy to expand vertically
        size_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.console_widget.setSizePolicy(size_policy)

        # Set monospace font for better log readability
        font = self.console_widget.font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setFamily("Monospace")
        self.console_widget.setFont(font)
        self.console_widget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        # Set up logging to console widget
        self.log_handler = QTextEditLogger()
        self.log_handler.set_text_edit(self.console_widget)
        logging.getLogger().addHandler(self.log_handler)

        # Give console more vertical space than job table
        self.main_layout.addWidget(self.console_widget, stretch=1)

        self.spacer = QWidget()
        self.spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self.main_layout.addWidget(self.spacer)

        # Buttons
        button_layout = QHBoxLayout()
        self.copy_log_button = QPushButton("Copy Log")
        self.copy_log_button.clicked.connect(self.copy_log)
        self.clear_log_button = QPushButton("Clear Log")
        self.clear_log_button.clicked.connect(self.clear_log)
        self.close_button = QPushButton("Close")
        button_layout.addWidget(self.copy_log_button)
        button_layout.addWidget(self.clear_log_button)
        self.main_layout.addLayout(button_layout)

        app = neon_player.instance()
        app.job_manager.job_started.connect(self.on_job_added)
        app.job_manager.job_finished.connect(self.remove_job)
        app.job_manager.job_canceled.connect(self.remove_job)

    def copy_log(self) -> None:
        """Copy the current log contents to the clipboard."""
        cb = neon_player.instance().clipboard()
        cb.setText(self.console_widget.toPlainText())
        logging.info("Log copied to clipboard")

    def clear_log(self) -> None:
        """Clear the log display."""
        self.console_widget.clear()
        logging.info("Log display cleared")

    def on_job_added(self, job: BackgroundJob) -> None:
        self.job_table_layout.addRow(job.name, JobProgressBar(job))

    def remove_job(self, job: BackgroundJob) -> None:
        for row_idx in range(self.job_table_layout.rowCount()):
            item = self.job_table_layout.itemAt(row_idx, QFormLayout.ItemRole.FieldRole)
            widget = item.widget()
            if isinstance(widget, JobProgressBar) and widget.worker == job:
                self.job_table_layout.removeRow(row_idx)
                break

    def show(self) -> None:
        super().show()
        self.log_handler.scroll_to_bottom()
