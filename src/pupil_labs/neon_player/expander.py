import typing as T

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QSizePolicy, QToolButton, QWidget


class Expander(QWidget):
    expanded_changed = Signal(bool)

    def __init__(
        self,
        parent: T.Optional[QWidget] = None,
        title: str = "",
        expanded: bool = False,
    ) -> None:
        # Adapted from https://stackoverflow.com/a/56275050
        super().__init__(parent=parent)

        self.content_widget: T.Optional[QWidget] = None
        self.header_line = QFrame()
        self.expander_button = QToolButton()

        self.expander_button.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; font-size: 12pt; }"
        )
        self.expander_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.expander_button.setText(str(title))
        self.expander_button.setArrowType(Qt.ArrowType.LeftArrow)

        self.header_line.setFrameShape(QFrame.Shape.HLine)
        self.header_line.setFrameShadow(QFrame.Shadow.Sunken)
        self.header_line.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )

        self.grid_layout = QGridLayout(self)
        self.grid_layout.setVerticalSpacing(0)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.addWidget(
            self.expander_button, 0, 0, 1, 1, Qt.AlignmentFlag.AlignLeft
        )
        self.grid_layout.addWidget(self.header_line, 0, 2, 1, 1)

        self.expander_button.toggled.connect(lambda _: self.on_expand_toggled())

        if expanded:
            self.expander_button.setCheckable(True)
            self.expanded = True
        else:
            self.expander_button.setCheckable(False)

    def on_expand_toggled(self) -> None:
        checked = self.expander_button.isChecked()

        if checked:
            self.expander_button.setArrowType(Qt.ArrowType.DownArrow)
            if self.content_widget is not None:
                self.content_widget.show()
        else:
            self.expander_button.setArrowType(Qt.ArrowType.RightArrow)
            if self.content_widget is not None:
                self.content_widget.hide()

        self.expanded_changed.emit(checked)

    def set_content_widget(self, content_widget: T.Optional[QWidget]) -> None:
        if content_widget is None:
            if self.content_widget is not None:
                self.grid_layout.removeWidget(self.content_widget)

                self.content_widget.deleteLater()

            self.expander_button.setCheckable(False)
            self.expander_button.setArrowType(Qt.ArrowType.LeftArrow)
            self.content_widget = None

            return

        widget: QWidget = content_widget

        widget.setContentsMargins(20, 0, 0, 20)
        self.content_widget = widget

        self.expander_button.setCheckable(True)
        self.expander_button.setArrowType(Qt.ArrowType.RightArrow)
        self.grid_layout.addWidget(self.content_widget, 1, 0, 1, 3)

        if not self.expanded:
            self.content_widget.hide()

    @property
    def expanded(self) -> bool:
        return self.expander_button.isChecked()

    @expanded.setter
    def expanded(self, value: bool) -> None:
        self.expander_button.setChecked(value)
        self.on_expand_toggled()
