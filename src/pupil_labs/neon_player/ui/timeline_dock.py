import logging
import typing as T

import numpy as np
import pyqtgraph as pg
from pyqtgraph.GraphicsScene.mouseEvents import MouseClickEvent
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pupil_labs import neon_player
from pupil_labs import neon_recording as nr


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
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.color = QColor(255, 0, 0, 128)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.color)

    @property
    def dim(self) -> bool:
        return self.color.alpha() < 128

    @dim.setter
    def dim(self, dim: bool) -> None:
        self.color.setAlpha(48 if dim else 128)


class TimeLineDock(QWidget):
    def __init__(self) -> None:
        super().__init__()
        app = neon_player.instance()

        self.timeline_plots: dict[str, pg.PlotItem] = {}
        self.timeline_legends: dict[str, pg.LegendItem] = {}
        self.plot_colors = [
            QColor("#1f77b4"),
            QColor("#ff7f0e"),
            QColor("#2ca02c"),
            QColor("#d62728"),
            QColor("#9467bd"),
            QColor("#8c564b"),
            QColor("#e377c2"),
            QColor("#7f7f7f"),
            QColor("#bcbd22"),
            QColor("#17becf"),
        ]
        self.data_point_actions = {}

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

        self.graphics_view = pg.GraphicsView()
        self.graphics_view.setBackground("transparent")
        self.graphics_layout = pg.GraphicsLayout()
        self.graphics_layout.setSpacing(3)
        self.graphics_view.setCentralItem(self.graphics_layout)

        self.main_layout.addWidget(self.graphics_view)

        self.graphics_view.scene().sigMouseClicked.connect(self.on_chart_area_clicked)

        self.playhead = PlayHead(self)
        app.playback_state_changed.connect(self.on_playback_state_changed)
        app.position_changed.connect(self.on_position_changed)
        app.recording_loaded.connect(self.on_recording_loaded)

        self.setMouseTracking(True)

        self.chart_area_parameters = {
            "global_rect": None,
            "local_rect": None,
            "x_range": None,
        }

        # Add a permanent timeline with timestamps
        self.timestamps_plot = self.get_timeline_plot(
            "Timestamps", create_if_missing=True
        )
        self.timestamps_plot.showAxis("top")
        self.timestamps_plot.setMaximumHeight(50)
        self.timestamps_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

    def sizeHint(self) -> QSize:
        return QSize(100, 100)

    def resizeEvent(self, event):
        self.update_chart_area_params()
        return super().resizeEvent(event)

    def showEvent(self, event):
        self.update_chart_area_params()
        return super().showEvent(event)

    def on_recording_loaded(self, recording: nr.NeonRecording):
        for plot_item in self.timeline_plots.values():
            plot_item.setXRange(
                recording.start_time, recording.stop_time, padding=0
            )
            axis = plot_item.getAxis("top")
            axis.set_time_frame(recording.start_time, recording.stop_time)

        self.update_chart_area_params()

    def update_chart_area_params(self):
        if neon_player.instance().recording is None:
            return

        if self.timestamps_plot.getViewBox().viewRange()[0][0] == 0:
            return

        chart_area_global = self.get_chart_area()
        chart_area_local_top_left = self.mapFromGlobal(
            chart_area_global.topLeft()
        )
        chart_area_local_bottom_right = self.mapFromGlobal(
            chart_area_global.bottomRight()
        )
        self.chart_area_parameters["global_rect"] = chart_area_global
        self.chart_area_parameters["local_rect"] = QRect(
            chart_area_local_top_left, chart_area_local_bottom_right
        )

        self.chart_area_parameters["x_range"] = self.timestamps_plot.getViewBox().viewRange()[0]
        self.chart_area_parameters["x_size"] = self.chart_area_parameters["x_range"][1] - self.chart_area_parameters["x_range"][0]

        self.update_playhead_geometry()

    def update_playhead_geometry(self):
        if self.chart_area_parameters["x_range"] is None:
            return

        x_range = self.chart_area_parameters["x_range"]
        rel_t = neon_player.instance().current_ts - x_range[0]
        t_norm = rel_t / self.chart_area_parameters["x_size"]
        x = self.chart_area_parameters["local_rect"].x() + t_norm * self.chart_area_parameters["local_rect"].width()

        self.playhead.dim = t_norm < 0 or t_norm > 1

        self.playhead.setGeometry(
            QRect(
                QPoint(x, self.chart_area_parameters["local_rect"].y()),
                QSize(3, self.chart_area_parameters["global_rect"].height())
            )
        )

    def on_playback_state_changed(self, is_playing: bool):
        icon_name = "pause.svg" if is_playing else "play.svg"
        self.play_button.setIcon(QIcon(str(neon_player.asset_path(icon_name))))

    def on_position_changed(self, t: int):
        app = neon_player.instance()
        if app.recording is None:
            return

        self.timestamp_label.set_time(t - app.recording.start_time)

        self.update_playhead_geometry()

    def get_chart_area(self) -> QRect:
        if len(self.graphics_layout.items) == 0:
            return QRect(0, 0, 100, 100)

        plot_items = [item for item in self.graphics_layout.items if isinstance(item, pg.PlotItem)]
        min_x = min(item.sceneBoundingRect().left() for item in plot_items)
        max_x = max(item.sceneBoundingRect().right() for item in plot_items)
        min_y = min(item.sceneBoundingRect().top() for item in plot_items)
        max_y = max(item.sceneBoundingRect().bottom() for item in plot_items)
        rect = QRect(int(min_x), int(min_y), int(max_x - min_x), int(max_y - min_y))

        # convert the rect to global coordinates
        return QRect(
            self.graphics_view.mapToGlobal(rect.topLeft()),
            self.graphics_view.mapToGlobal(rect.bottomRight())
        )

    def show_context_menu(self, global_position: QPoint) -> None:
        menu = neon_player.instance().main_window.get_menu(
            "Timeline", auto_create=False
        )
        context_menu = QMenu() if menu is None else self.clone_menu(menu)
        context_menu.exec(global_position)

    def clone_menu(self, menu: QMenu) -> QMenu:
        menu_copy = QMenu(menu.title(), self)
        for action in menu.actions():
            if action.menu():
                menu_copy.addMenu(self.clone_menu(action.menu()))
            else:
                menu_copy.addAction(action)

        return menu_copy

    def on_chart_area_clicked(self, event: MouseClickEvent):
        app = neon_player.instance()
        if app.recording is None:
            return

        if event.button() == Qt.LeftButton:
            first_plot_item = next(iter(self.timeline_plots.values()))

            mouse_point = first_plot_item.getViewBox().mapSceneToView(event.scenePos())
            time_ns = int(mouse_point.x())

            time_ns = max(app.recording.start_time, time_ns)
            time_ns = min(app.recording.stop_time, time_ns)

            app.seek_to(time_ns)
            return

        if event.button() == Qt.RightButton:
            nearby_items = self.graphics_layout.scene().itemsNearEvent(event)
            clicked_plot_item = None
            clicked_data_point = None
            for item in nearby_items:
                if isinstance(item, pg.PlotItem):
                    clicked_plot_item = item
                elif isinstance(item, pg.ScatterPlotItem):
                    p = item.mapFromScene(event.scenePos())
                    points_at = item.pointsAt(p)
                    if len(points_at) == 0:
                        continue

                    spot_item = points_at[0].pos()
                    clicked_data_point = (spot_item.x(), spot_item.y())


            if clicked_plot_item is None or clicked_data_point is None:
                self.show_context_menu(event.screenPos().toPoint())
                return

            for k, v in self.timeline_plots.items():
                if v == clicked_plot_item:
                    self.on_data_point_clicked(k, clicked_data_point, event)
                    break

    def get_timeline_plot(
        self, timeline_row_name: str, create_if_missing: bool = False, **kwargs
    ) -> pg.PlotItem | None:
        if timeline_row_name in self.timeline_plots:
            return self.timeline_plots[timeline_row_name]

        if not create_if_missing:
            return None

        row = self.graphics_layout.nextRow()
        is_timestamps_row = timeline_row_name == "Timestamps"

        if is_timestamps_row:
            time_axis = TimeAxisItem(orientation="top")
        else:
            time_axis = TimeAxisItem(
                orientation="top",
                showValues=False,
                pen=pg.mkPen({'color': '#ffff0000'})
            )

        app = neon_player.instance()
        if app.recording is not None:
            time_axis.set_time_frame(app.recording.start_time, app.recording.stop_time)

        plot_item = pg.PlotItem(axisItems={"top": time_axis})

        legend = pg.LegendItem()
        label = pg.LabelItem()
        label.setText(f"<b>{timeline_row_name}</b>")

        legend.layout.addItem(label, 0, 0, 1, 2)

        legend.layout.setSpacing(0)
        if not is_timestamps_row:
            self.timeline_legends[timeline_row_name] = legend
            self.graphics_layout.addItem(legend, row=row, col=0)

        self.graphics_layout.addItem(plot_item, row=row, col=1)


        plot_item.setMouseEnabled(x=True, y=False)
        plot_item.hideButtons()
        plot_item.setMenuEnabled(False)
        plot_item.setClipToView(True)
        plot_item.hideAxis("left")
        plot_item.hideAxis("right")
        plot_item.hideAxis("bottom")
        plot_item.showGrid(x=True, y=False, alpha=0.3)

        self.timeline_plots[timeline_row_name] = plot_item

        if is_timestamps_row:
            plot_item.getViewBox().sigXRangeChanged.connect(
                self.update_chart_area_params
            )
        else:
            if self.timestamps_plot:
                plot_item.setXLink(self.timestamps_plot)

        return plot_item

    def get_timeline_series(
        self, plot_name: str, series_name: str
    ):
        plot_item = self.get_timeline_plot(plot_name)
        if plot_item is None:
            return None

        for series in plot_item.items:
            if hasattr(series, 'name') and series.name == series_name:
                return series

    def add_timeline_plot(
        self,
        timeline_row_name: str,
        data: list[tuple[int, int]],
        plot_name: str = "",
        color: QColor | None = None,
        **kwargs,
    ):
        app = neon_player.instance()
        if app.recording is None:
            return

        plot_item = self.get_timeline_plot(timeline_row_name, True)
        if plot_item is None:
            return

        if color is None:
            plot_index = len(plot_item.items)
            color = self.plot_colors[plot_index % len(self.plot_colors)]

        logging.info(f"Adding plot {timeline_row_name}.{plot_name} to timeline")

        if "pen" not in kwargs:
            kwargs["pen"] = pg.mkPen(color=color, width=2, cap="flat")

        if len(data) > 0:
            plot_data_item = plot_item.plot(
                data[:, 0], data[:, 1], name=plot_name, **kwargs
            )
            plot_data_item.name = plot_name
            if timeline_row_name in self.timeline_legends and plot_name != "":
                legend = self.timeline_legends[timeline_row_name]
                legend.addItem(plot_data_item, plot_name)


        self.update_chart_area_params()

    def remove_timeline_plot(self, plot_name: str):
        plot = self.get_timeline_plot(plot_name)
        if plot is None:
            return

        self.graphics_layout.removeItem(plot)
        del self.timeline_plots[plot_name]

        if plot_name in self.timeline_legends:
            legend = self.timeline_legends[plot_name]
            self.graphics_layout.removeItem(legend)
            del self.timeline_legends[plot_name]

    def remove_timeline_series(self, plot_name: str, series_name: str):
        if plot_name not in self.timeline_plots:
            return

        plot = self.get_timeline_plot(plot_name)
        if plot is None:
            return

        series = self.get_timeline_series(plot_name, series_name)
        if series is None:
            return

        plot.removeItem(series)
        if plot_name in self.timeline_legends:
            legend = self.timeline_legends[plot_name]
            legend.removeItem(series_name)

        if len(plot.items) == 0:
            self.remove_timeline_plot(plot_name)

    def on_data_point_clicked(self, timeline_name, data_point, event):
        if timeline_name not in self.data_point_actions:
            return

        context_menu = QMenu()

        for action_name, callback in self.data_point_actions[timeline_name]:
            action = context_menu.addAction(action_name)
            action.triggered.connect(
                lambda _, cb=callback: cb(data_point)
            )

        context_menu.exec(QPoint(event.screenPos().toQPoint()))

    def add_timeline_line(
        self, timeline_row_name: str, data: list[tuple[int, int]], plot_name: str = ""  , **kwargs
    ) -> None:
        self.add_timeline_plot(timeline_row_name, data, plot_name, **kwargs)

    def add_timeline_scatter(
        self, name: str, data: list[tuple[int, int]], item_name: str = ""
    ) -> None:
        self.add_timeline_plot(
            name,
            data,
            item_name,
            pen=None,
            symbol="o",
            symbolBrush=pg.mkColor("white"),
        )

    def add_timeline_broken_bar(
        self, timeline_row_name: str, start_and_stop_times, item_name: str = ""
    ) -> None:
        plot_widget = self.get_timeline_plot(timeline_row_name, True)
        pen = pg.mkPen("white")

        # data is a list of (start, end) tuples
        x_values = np.array(start_and_stop_times).flatten()
        x_values = np.repeat(x_values, 3)

        # y_values should be 0 when we aren't in an interval and 1 when we are
        y_values = np.zeros(len(x_values))
        y_values[1::6] = 1
        y_values[2::6] = 1
        y_values[3::6] = 1

        curve1 = plot_widget.plot(x_values, y_values, pen=pen)
        curve2 = plot_widget.plot(x_values, -y_values, pen=pen)

        brush = pg.mkBrush("white")
        fill = pg.FillBetweenItem(curve1, curve2, brush=brush)
        plot_widget.addItem(fill)

        if item_name and timeline_row_name in self.timeline_legends:
            legend = self.timeline_legends[timeline_row_name]
            legend.addItem(fill, name=item_name)


        self.update_chart_area_params()

    def register_data_point_action(
        self,
        row_name: str,
        action_name: str,
        callback: T.Callable
    ) -> None:
        if row_name not in self.data_point_actions:
            self.data_point_actions[row_name] = []

        self.data_point_actions[row_name].append((action_name, callback))

    def reset_view(self):
        app = neon_player.instance()
        if app.recording is None:
            return

        self.timestamps_plot.getViewBox().setRange(xRange=[
            app.recording.start_time,
            app.recording.stop_time
        ])
