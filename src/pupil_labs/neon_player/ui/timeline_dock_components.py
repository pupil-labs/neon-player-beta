import math

import pyqtgraph as pg
from pyqtgraph.GraphicsScene.mouseEvents import MouseDragEvent
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsRectItem,
    QGraphicsSceneMouseEvent,
    QLabel,
    QSizePolicy,
    QStyleOptionGraphicsItem,
    QWidget,
)


class ScrubbableViewBox(pg.ViewBox):
    scrub_start = Signal(MouseDragEvent)
    scrub_end = Signal(MouseDragEvent)
    scrubbed = Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.allow_y_panning = True

    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            if Qt.KeyboardModifier.ControlModifier == ev.modifiers():
                if self.allow_y_panning:
                    self.setMouseMode(pg.ViewBox.RectMode)

            else:
                self.scrubbed.emit(ev)

        return super().mousePressEvent(ev)

    def mouseDragEvent(self, ev: MouseDragEvent, axis=None) -> None:
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.setMouseEnabled(x=True, y=self.allow_y_panning)
            return super().mouseDragEvent(ev, axis)

        if self.state["mouseMode"] == pg.ViewBox.RectMode:
            super().mouseDragEvent(ev, axis)
            if ev.finish:
                self.setMouseMode(pg.ViewBox.PanMode)

            return

        if ev.start:
            self.scrub_start.emit(ev)
        elif ev.finish:
            self.scrub_end.emit(ev)
        else:
            self.scrubbed.emit(ev)

        ev.accept()

    def wheelEvent(self, ev, axis=None) -> None:
        mouse_enabled = {
            "x": Qt.KeyboardModifier.ControlModifier in ev.modifiers(),
            "y": Qt.KeyboardModifier.ShiftModifier in ev.modifiers(),
        }
        mouse_enabled["y"] = self.allow_y_panning and mouse_enabled["y"]

        if any(mouse_enabled.values()):
            self.setMouseEnabled(**mouse_enabled)
            return super().wheelEvent(ev, axis)

        ev.ignore()


class TimeAxisItem(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            tickPen=pg.mkPen({'color': '#aaaaaa'}),
            **kwargs
        )
        self.recording_start_time_ns = 0
        self.recording_stop_time_ns = 0

        self.interval = 1
        self.setStyle(autoReduceTextSpace=False)

    def tickValues(self, minVal, maxVal, size):
        if self.recording_start_time_ns == 0 or self.recording_stop_time_ns == 0:
            return []

        minVal = max(minVal, self.recording_start_time_ns)
        maxVal = min(maxVal, self.recording_stop_time_ns)

        # Calculate the visible time range in seconds
        visible_range_ns = maxVal - minVal
        visible_range_sec = visible_range_ns / 1e9

        # Define nice intervals in seconds and their corresponding minor tick counts
        intervals = [
            (0.005, 5),
            (0.01, 2),
            (0.05, 5),
            (0.1, 10),
            (0.25, 5),
            (0.5, 5),
            (1.0, 10),
            (5.0, 5),
            (10.0, 10),
            (30.0, 6),
            (60.0, 6),
            (300.0, 5),
            (600.0, 10),
        ]

        # Find the largest interval that fits the current zoom level
        pixels_per_second = size / visible_range_sec if visible_range_sec > 0 else 0
        interval_sec, minor_ticks = intervals[-1]  # Start with largest interval

        # Find the largest interval where ticks won't be too close together
        for int_sec, minor_count in intervals:
            if pixels_per_second * int_sec >= 120:  # At least 120 pixels between major ticks
                interval_sec = int_sec
                minor_ticks = minor_count
                break

        self.interval = interval_sec

        # Calculate the first major tick at or after minVal that aligns with the interval from recording start
        interval_ns = int(interval_sec * 1e9)
        minor_interval_ns = interval_ns // minor_ticks
        offset_from_start = (minVal - self.recording_start_time_ns) % interval_ns
        first_major_tick_ns = minVal - offset_from_start

        if first_major_tick_ns < self.recording_start_time_ns:
            first_major_tick_ns += interval_ns

        # Generate major and minor ticks
        major_ticks = []
        minor_tick_list = []

        current_major_tick_ns = first_major_tick_ns
        while current_major_tick_ns <= maxVal + interval_ns:  # Add one extra interval to ensure coverage
            if minVal <= current_major_tick_ns <= maxVal:
                major_ticks.append(current_major_tick_ns)

            # Add minor ticks between this major tick and the next
            for i in range(1, minor_ticks):
                minor_tick_ns = current_major_tick_ns + i * minor_interval_ns
                if minVal <= minor_tick_ns <= maxVal and minor_tick_ns < current_major_tick_ns + interval_ns:
                    minor_tick_list.append(minor_tick_ns)

            current_major_tick_ns += interval_ns

        # Always include the start time if it's in the visible range
        if minVal <= self.recording_start_time_ns <= maxVal:
            if not major_ticks or major_ticks[0] != self.recording_start_time_ns:
                major_ticks.insert(0, self.recording_start_time_ns)

        # Return in the format expected by PyQtGraph: [(tick_scale, [ticks]), ...]
        return [
            (1.0, major_ticks),
            (0.5, minor_tick_list)
        ]

    def tickStrings(self, values, scale, spacing):
        if self.recording_start_time_ns == 0:
            return ["" for _ in values]

        strings = []
        for val in values:
            if not (self.recording_start_time_ns <= val <= self.recording_stop_time_ns):
                strings.append("")
                continue

            relative_time_ns = val - self.recording_start_time_ns
            hours = relative_time_ns // (1e9 * 60 * 60)
            minutes = (relative_time_ns // (1e9 * 60)) % 60
            seconds = (relative_time_ns // 1e9) % 60
            ms = (relative_time_ns / 1e6) % 1000
            string = f"{minutes:0>2.0f}:{seconds:0>2.0f}"

            if self.interval < 1:
                string += f".{ms:0>3.0f}"

            if hours > 0:
                string = f"{hours:0>2,.0f}:{string}"

            strings.append(string)

        return strings

    def set_time_frame(self, start: int, end: int):
        self.recording_start_time_ns = start
        self.recording_stop_time_ns = end


class FixedLegend(pg.LegendItem):
    def mouseDragEvent(self, event: MouseDragEvent) -> None:
        event.ignore()

    def addItem(self, *args, **kwargs):
        super().addItem(*args, **kwargs)
        self.setColumnCount(max(1, math.ceil(len(self.items) / 3)))

    def removeItem(self, *args, **kwargs):
        super().removeItem(*args, **kwargs)
        self.setColumnCount(max(1, math.ceil(len(self.items) / 3)))


class TimestampLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_time(0)
        font = self.font()
        font.setFixedPitch(True)
        self.setFont(font)

    def set_time(self, time_ns: int) -> None:
        hours = time_ns // (1e9 * 60 * 60)
        minutes = (time_ns // (1e9 * 60)) % 60
        seconds = (time_ns / 1e9) % 60
        self.setText(f"{hours:0>2,.0f}:{minutes:0>2.0f}:{seconds:0>6.3f}")


class SmartSizePlotItem(pg.PlotItem):
    def __init__(self, legend, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.legend_handle = legend

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )

        self.preferred_height_1d = 25
        self.preferred_height_2d = 150
        self.adjust_size()

    def addItem(self, *args, **kwargs) -> None:
        super().addItem(*args, **kwargs)
        self.adjust_size()

    def removeItem(self, *args, **kwargs) -> None:
        super().removeItem(*args, **kwargs)
        self.adjust_size()

    def adjust_size(self):
        height = self.preferred_height_2d if self.has_line else self.preferred_height_1d

        self.setFixedHeight(height)

        self.legend_handle.setFixedHeight(height)
        self.legend_handle.parentItem().setFixedHeight(height)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        pen = painter.pen()
        pen.setColor("#444")
        pen.setWidth(1)
        painter.setPen(pen)

        if self.has_line:
            painter.drawLine(-2000, 0, self.width(), 0)
            painter.drawLine(-2000, self.height() - 1, self.width(), self.height() - 1)

        super().paint(painter, option, widget)

    @property
    def has_line(self) -> bool:
        for item in self.items:
            if isinstance(item, pg.PlotDataItem) and len(item.curve.xData) > 0:
                return True

        return False

    @property
    def has_bar(self) -> bool:
        return any(isinstance(item, pg.BarGraphItem) for item in self.items)


class PlotOverlay(QWidget):
    def __init__(self, linked_plot: pg.PlotItem,*args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.linked_plot = linked_plot

        linked_plot.vb.sigResized.connect(self.refresh_geometry)

    def get_x_pixel_for_x_value(self, x_value: float) -> float:
        x_range = self.linked_plot.vb.viewRange()[0]
        return (x_value - x_range[0]) / (x_range[1] - x_range[0]) * self.width()

    def refresh_geometry(self) -> None:
        plot_rect = self.linked_plot.geometry()
        self.setGeometry(
            plot_rect.x(), 20,
            plot_rect.width(), self.parent().centralWidget.height() - 20
        )


class PlayHead(PlotOverlay):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.color = QColor(255, 0, 0, 128)
        self.t = 0

    def set_time(self, t: int) -> None:
        self.t = t
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.color)
        painter.setBrush(self.color)

        x = self.get_x_pixel_for_x_value(self.t)

        if x < 0:
            painter.drawPolygon(
                QPolygon([
                    QPoint(0, 10),
                    QPoint(10, 0),
                    QPoint(10, 20),
                ])
            )

        elif x > self.width():
            painter.drawPolygon(
                QPolygon([
                    QPoint(self.rect().right(), 10),
                    QPoint(self.rect().right() - 10, 0),
                    QPoint(self.rect().right() - 10, 20),
                ])
            )

        else:
            painter.fillRect(QRect(x-1, 0, 3, self.height()), self.color)


class TrimEndMarker(QGraphicsEllipseItem):
    def __init__(self, time, plot: pg.PlotItem, *args, **kwargs) -> None:
        super().__init__(0, -1, 0, 2, *args, **kwargs)
        self._time = time
        self._plot = plot

        class _Emitter(QObject):
            time_changed = Signal(object)

        self._emitter = _Emitter()
        self.time_changed = self._emitter.time_changed

        self.highlight_pen = pg.mkPen("#888", width=2)
        self.highlight_brush = pg.mkBrush("#00000000")
        self.normal_pen = pg.mkPen("#444", width=1)
        self.normal_brush = pg.mkBrush("#444")

        self.setPen(self.normal_pen)
        self.setBrush(self.normal_brush)

    @property
    def time(self) -> int:
        return self._time

    @time.setter
    def time(self, value: int) -> None:
        self._time = value
        self.time_changed.emit(value)
        self.update()

    def set_highlighted(self, highlighted: bool) -> None:
        if highlighted:
            self.setPen(self.highlight_pen)
            self.setBrush(self.highlight_brush)
        else:
            self.setPen(self.normal_pen)
            self.setBrush(self.normal_brush)

    def paint(self, painter: QPainter, option, widget: QWidget | None = None) -> None:
        scale_x = painter.worldTransform().m11()
        scale_y = painter.worldTransform().m22()
        scaled_width = 2 * abs(scale_y) / scale_x
        rect = self.rect()
        rect.setWidth(scaled_width)
        rect.setLeft(self._time - scaled_width / 2)
        self.setRect(rect)

        super().paint(painter, option, widget)

    def nearby(self, pos: QPoint | QPointF, buffer = 0.25):
        rect = self.rect()
        dx = rect.width() * buffer
        dy = rect.height() * buffer

        return rect.adjusted(-dx, -dy, dx, dy).contains(pos)


class TrimDurationMarker(QGraphicsRectItem):
    def __init__(self, start_marker, end_marker, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setPen(pg.mkPen("#ccc", width=0))
        self.setBrush(pg.mkBrush("#ccc"))

        self._start_marker = start_marker
        self._end_marker = end_marker

        self._start_marker.time_changed.connect(lambda _: self._update_ends())
        self._end_marker.time_changed.connect(lambda _: self._update_ends())

        self._update_ends()

    def _update_ends(self) -> None:
        self.setRect(
            self._start_marker.time, -1,
            self._end_marker.time - self._start_marker.time, 2
        )
        self.update()

