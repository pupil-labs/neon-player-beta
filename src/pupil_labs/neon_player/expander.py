import typing as T

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class Expander(QFrame):
    expanded_changed = Signal(bool)

    def __init__(
        self,
        parent: T.Optional[QWidget] = None,
        title: str = "",
        content_widget: T.Optional[QWidget] = None,
        expanded: bool = False,
    ) -> None:
        # Adapted from https://stackoverflow.com/a/56275050
        super().__init__(parent=parent)

        self.content_widget = content_widget
        if content_widget:
            content_widget.setContentsMargins(0, 0, 8, 0)

        self.label = QLabel(title)

        self.expander_button = QToolButton()
        self.expander_button.setCheckable(True)
        self.expander_button.setChecked(expanded)
        self.controls_layout = QHBoxLayout()
        self.controls_layout.addWidget(self.label)
        self.controls_layout.addWidget(self.expander_button)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 10, 0, 10)
        self.setLayout(layout)

        layout.addLayout(self.controls_layout)
        if self.content_widget:
            layout.addWidget(self.content_widget)

        self.expander_button.clicked.connect(lambda _: self.on_expand_toggled())
        self.expanded = expanded

    def on_expand_toggled(self) -> None:
        if not self.expanded:
            self.expander_button.setText("\uff0d")

            if self.content_widget:
                self.content_widget.show()
                self.content_widget.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
                )
        else:
            self.expander_button.setText("\uff0b")

            if self.content_widget:
                self.content_widget.hide()

        self.expanded_changed.emit(self.expanded)

    @property
    def expanded(self) -> bool:
        return self.expander_button.isChecked()

    @expanded.setter
    def expanded(self, value: bool) -> None:
        self.expander_button.setChecked(value)
        self.on_expand_toggled()
