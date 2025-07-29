
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

QtShortcutType = (
    QKeySequence | QKeyCombination | QKeySequence.StandardKey | str | int | None
)


class GUIEventNotifier:
    mouse_pressed = Signal(QMouseEvent)
    mouse_moved = Signal(QMouseEvent)
    mouse_wheel_moved = Signal(QWheelEvent)
    resized = Signal(QResizeEvent)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.mouse_moved.emit(event)
        return super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.mouse_pressed.emit(event)
        return super().mousePressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.resized.emit(event)
        return super().resizeEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.mouse_wheel_moved.emit(event)
        return super().wheelEvent(event)
