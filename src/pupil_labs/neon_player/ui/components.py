from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget


class HoverRowTable(QTableWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self.setStyleSheet("""
            QTableWidget, QHeaderView {
                background: transparent;
                border: none;
            }

            QTableWidget::item {
                border-bottom: 1px solid #292d2d;
                padding: 20px;
                padding-left: 0px;
            }

            QTableWidget::item:selected {
                background: #292d2d;
            }

            QHeaderView::section {
                background-color: transparent;
                border: none;
                color: #a09fa6;
                font-size: 10pt;
                font-weight: normal;
            }

            QHeaderView::section:hover {
                background-color: #292d2d;
            }
        """)

    def update_hovered_row(self, cursor_position):
        idx = self.indexAt(cursor_position)
        if idx.isValid():
            self.setCurrentCell(idx.row(), 0)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseMoveEvent(self, event):
        self.update_hovered_row(event.pos())
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        self.update_hovered_row(event.position().toPoint())
        super().wheelEvent(event)

    def leaveEvent(self, event):
        self.clearSelection()
        self.setCurrentCell(-1, -1)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)
