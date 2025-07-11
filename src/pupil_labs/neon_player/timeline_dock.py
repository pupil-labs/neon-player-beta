from PySide6.QtCharts import QChart, QChartView, QLineSeries, QScatterSeries, QValueAxis
from PySide6.QtCore import QMargins, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pupil_labs import neon_player


class TimestampLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_time(0)
        self.setStyleSheet("font-family: monospace; font-weight: bold;")

    def set_time(self, time_ns: int) -> None:
        hours = time_ns // (1e9 * 60 * 60)
        minutes = (time_ns // (1e9 * 60)) % 60
        seconds = (time_ns / 1e9) % 60
        self.setText(f"{hours:0>2,.0f}:{minutes:0>2.0f}:{seconds:0>6.3f}")


class PlayHead(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        neon_player.instance().position_changed.connect(self.on_position_changed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def on_position_changed(self, t: int) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        duration = app.recording.stop_ts - app.recording.start_ts + 2e9
        self.player_position = (t - app.recording.start_ts + 1e9) / duration
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(
            int(self.player_position * self.width() - 1),
            0,
            2,
            self.height(),
            QColor("#6d7be0"),
        )


class TimelineTable(QWidget):
    mouse_moved = Signal(QMouseEvent)
    mouse_pressed = Signal(QMouseEvent)
    resized = Signal(QResizeEvent)

    def __init__(self) -> None:
        super().__init__()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(0)
        self.setLayout(self.grid_layout)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.mouse_moved.emit(event)
        return super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.mouse_pressed.emit(event)
        return super().mousePressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.resized.emit(event)
        return super().resizeEvent(event)


class TimelineDock(QWidget):
    def __init__(self) -> None:
        super().__init__()

        app = neon_player.instance()

        self.timeline_chart_views: dict[str, QChartView] = {}

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.toolbar_layout = QHBoxLayout()
        self.play_button = QToolButton()
        self.play_button.setIcon(QIcon(str(neon_player.asset_path("play.svg"))))
        self.play_button.clicked.connect(
            lambda: app.get_action("Playback/Play\\Pause").trigger()
        )
        self.toolbar_layout.addWidget(self.play_button)

        self.timestamp_label = TimestampLabel()
        self.toolbar_layout.addWidget(self.timestamp_label)

        self.main_layout.addLayout(self.toolbar_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.timeline_table = TimelineTable()
        self.timeline_table.resized.connect(self.on_timeline_table_resized)
        self.timeline_table.mouse_moved.connect(self.on_timeline_mouse_moved)
        self.timeline_table.mouse_pressed.connect(self.on_timeline_mouse_pressed)

        scroll_area.setWidget(self.timeline_table)
        self.main_layout.addWidget(scroll_area)

        self.playhead = PlayHead(scroll_area)

        app.playback_state_changed.connect(self.on_playback_state_changed)
        app.position_changed.connect(self.on_position_changed)

    def on_playback_state_changed(self, is_playing: bool) -> None:
        self.play_button.setIcon(
            QIcon(
                str(neon_player.asset_path("pause.svg" if is_playing else "play.svg"))
            )
        )

    def on_position_changed(self, t: int) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        self.timestamp_label.set_time(t - app.recording.start_ts)

    def on_timeline_table_resized(self, event: QResizeEvent) -> None:
        rect = self.get_chart_area()
        self.playhead.setGeometry(rect)

    def get_chart_area(self) -> QRect:
        top_chart_cell_rect = self.timeline_table.grid_layout.cellRect(0, 1)
        bottom_chart_cell_rect = self.timeline_table.grid_layout.cellRect(
            self.timeline_table.grid_layout.rowCount() - 1,
            1,
        )
        top_chart_cell_rect.setTop(0)
        rect = QRect(
            top_chart_cell_rect.topLeft(),
            bottom_chart_cell_rect.bottomRight(),
        )
        return rect

    def on_timeline_mouse_moved(self, event: QMouseEvent) -> None:
        if event.buttons() != Qt.MouseButton.NoButton:
            self.on_timeline_mouse_pressed(event)

    def on_timeline_mouse_pressed(self, event: QMouseEvent) -> None:
        rect = self.get_chart_area()
        app = neon_player.instance()
        if app.recording is None:
            return

        left = (event.position() - rect.topLeft()).x()
        v = left / rect.width()
        t = (
            app.recording.start_ts
            - 1e9
            + v * (app.recording.stop_ts - app.recording.start_ts + 2e9)
        )
        if app.recording.start_ts < t < app.recording.stop_ts:
            app.seek_to(int(t))

    def add_timeline_plot(  # noqa: C901
        self,
        name: str,
        data: list[tuple[int, int]],
        series_cls: type = QLineSeries,
        item_name: str = "",
    ) -> None:
        app = neon_player.instance()
        if app.recording is None:
            return

        if name not in self.timeline_chart_views:
            chart = QChart()

            chart.legend().setVisible(False)
            chart.setTheme(QChart.ChartTheme.ChartThemeDark)
            chart.setBackgroundVisible(False)
            chart.layout().setContentsMargins(0, 0, 0, 0)
            chart.setMargins(QMargins(0, 0, 0, 0))
            chart.setBackgroundRoundness(0)

            axes = {
                Qt.AlignmentFlag.AlignBottom: QValueAxis(),
                Qt.AlignmentFlag.AlignLeft: QValueAxis(),
            }

            axes[Qt.AlignmentFlag.AlignBottom].setRange(
                app.recording.start_ts - 1e9, app.recording.stop_ts + 1e9
            )
            axes[Qt.AlignmentFlag.AlignBottom].setTickCount(2)
            axes[Qt.AlignmentFlag.AlignLeft].setTickCount(3)

            for alignment, axis in axes.items():
                axis.setGridLineVisible(False)
                axis.setLineVisible(False)
                axis.setLabelsVisible(False)
                chart.addAxis(axis, alignment)

            chart_view = QChartView(chart)

            chart_view.setInteractive(True)
            self.timeline_chart_views[name] = chart_view

            row_idx = self.timeline_table.grid_layout.rowCount()
            self.timeline_table.grid_layout.addWidget(QLabel(name), row_idx, 0)
            self.timeline_table.grid_layout.addWidget(chart_view, row_idx, 1)

        else:
            chart_view = self.timeline_chart_views[name]
            chart = chart_view.chart()

            for row_idx in range(self.timeline_table.grid_layout.rowCount()):
                item = self.timeline_table.grid_layout.itemAtPosition(row_idx, 1)
                if item is not None and item.widget() == chart_view:
                    break

        series = series_cls()
        for x, y in data:
            series.append(x, y)

        chart.addSeries(series)
        for series_axis in chart.axes():
            series.attachAxis(series_axis)

        series.setVisible(True)
        # series.hovered.connect(lambda: print("Hover:", item_name))

        chart_y_range = None
        for chart_series in chart.series():
            if not hasattr(chart_series, "points"):
                continue

            for point in chart_series.points():
                if chart_y_range is None:
                    chart_y_range = [point.y(), point.y()]
                else:
                    chart_y_range[0] = min(chart_y_range[0], point.y())
                    chart_y_range[1] = max(chart_y_range[1], point.y())

        pen = series.pen()

        if chart_y_range is not None and chart_y_range[0] == chart_y_range[1]:
            chart_y_range[0] -= 1
            chart_y_range[1] += 1

            pen = series.pen()
            pen.setWidth(15)

            self.timeline_table.grid_layout.setRowStretch(row_idx, 0)

        else:
            pen.setWidth(2)
            self.timeline_table.grid_layout.setRowStretch(row_idx, 1)

        for v_axis in chart_view.chart().axes(Qt.Orientation.Vertical):
            if chart_y_range is not None:
                v_axis.setRange(chart_y_range[0], chart_y_range[1])

        if series_cls == QLineSeries:
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            series.setPen(pen)
        elif series_cls == QScatterSeries:
            series.setMarkerShape(
                QScatterSeries.MarkerShape.MarkerShapeRotatedRectangle
            )
            series.setMarkerSize(8)

        rec = app.recording
        h_axis = chart_view.chart().axes(Qt.Orientation.Horizontal)[0]
        if isinstance(h_axis, QValueAxis):
            h_axis.setTickInterval(rec.stop_ts - rec.start_ts)
            h_axis.setTickAnchor(rec.start_ts)

    def add_timeline_line(
        self, name: str, data: list[tuple[int, int]], item_name: str = ""
    ) -> None:
        self.add_timeline_plot(name, data, QLineSeries, item_name)

    def add_timeline_scatter(
        self, name: str, data: list[tuple[int, int]], item_name: str = ""
    ) -> None:
        self.add_timeline_plot(name, data, QScatterSeries, item_name)
