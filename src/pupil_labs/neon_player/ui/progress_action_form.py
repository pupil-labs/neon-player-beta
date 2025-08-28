import typing as T

from PySide6.QtWidgets import QProgressBar
from qt_property_widgets.widgets import ActionForm

from pupil_labs.neon_player.job_manager import BackgroundJob


class ProgressActionForm(ActionForm):
    @staticmethod
    def from_property_impl(prop: property) -> "ProgressActionForm":
        hints = T.get_type_hints(prop.fget)
        return ProgressActionForm.from_type(hints["return"])

    @staticmethod
    def from_type(cls: type) -> "ProgressActionForm":
        return ProgressActionForm(cls(lambda: None, None))

    def _setup_form(self) -> None:
        super()._setup_form()
        self.progress_bar = QProgressBar()
        self.form_layout.addRow("", self.progress_bar)
        self.progress_bar.hide()

    def _on_action_button_pressed(self) -> None:
        v = self.value()
        if isinstance(v, BackgroundJob):
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.action_button.setVisible(False)

            v.progress_changed.connect(self.on_job_progress)
            v.finished.connect(self.on_job_done)
            v.canceled.connect(self.on_job_done)

    def on_job_progress(self, progress: float) -> None:
        self.progress_bar.setValue(progress * 100)

    def on_job_done(self) -> None:
        self.progress_bar.hide()
        self.action_button.setVisible(True)
