
from PySide6.QtCore import (
    QKeyCombination,
    Signal,
)
from PySide6.QtGui import (
    QKeySequence,
    QMouseEvent,
    QResizeEvent,
    QWheelEvent,
)

from .progress_action_form import ProgressActionForm  # noqa: F401

QtShortcutType = (
    QKeySequence | QKeyCombination | QKeySequence.StandardKey | str | int | None
)


class GUIEventNotifier:
    mouse_pressed = Signal(QMouseEvent)
    mouse_released = Signal(QMouseEvent)
    mouse_clicked = Signal(QMouseEvent)
    mouse_moved = Signal(QMouseEvent)
    mouse_wheel_moved = Signal(QWheelEvent)
    resized = Signal(QResizeEvent)

    def __init__(self):
        super().__init__()
        self._mouse_down = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.mouse_moved.emit(event)
        return super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._mouse_down = True
        self.mouse_pressed.emit(event)
        return super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._mouse_down:
            self.mouse_clicked.emit(event)

        self._mouse_down = False
        self.mouse_released.emit(event)

        return super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.resized.emit(event)
        return super().resizeEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.mouse_wheel_moved.emit(event)
        return super().wheelEvent(event)


class HeaderAction:
    def __init__(self, callback, name):
        self.callback = callback
        self.name = name


class ListPropertyAppenderAction(HeaderAction):
    def __init__(self, property_name, name):
        super().__init__(None, name)
        self.property_name = property_name
        self.form = None
