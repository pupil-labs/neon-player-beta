import typing as T

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
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


class ExpanderList(QWidget):
    def __init__(self, parent: T.Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setMinimumSize(350, 100)

        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setSpacing(0)
        self.container_layout.setContentsMargins(5, 5, 5, 5)

        scroll_area.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)

        self.spacer = QWidget()
        self.spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.container_layout.addWidget(self.spacer)

    def add_expander(self, title: str, content: QWidget) -> None:
        expander = Expander(title=title, content_widget=content)
        self.container_layout.insertWidget(self.container_layout.count() - 1, expander)

        return expander

    def remove_expander(self, expander: Expander) -> None:
        self.container_layout.removeWidget(expander)
        expander.deleteLater()
