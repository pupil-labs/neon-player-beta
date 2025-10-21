import logging
import typing as T

import numpy as np
import pyqtgraph as pg
from pyqtgraph.GraphicsScene.mouseEvents import (
    MouseClickEvent,
    MouseDragEvent,
)
from PySide6.QtCore import QPoint, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsSceneMouseEvent,
    QHBoxLayout,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pupil_labs import neon_player
from pupil_labs import neon_recording as nr
from pupil_labs.neon_player.ui.timeline_dock_components import (
    FixedLegend,
    PlayHead,
    ScrubbableViewBox,
    SmartSizePlotItem,
    TimeAxisItem,
    TimestampLabel,
    TrimDurationMarker,
    TrimEndMarker,
)
from pupil_labs.neon_player.utilities import clone_menu


class TimeLineDock(QWidget):
    key_pressed = Signal(QKeyEvent)

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

        self.speed_control = QComboBox()
        self.speed_control.addItems([
            "-2.00x", "-1.75x", "-1.50x", "-1.25x",
            "-1.00x", "-0.75x", "-0.50x", "-0.25x",
        ])
        self.speed_control.insertSeparator(self.speed_control.count())
        self.speed_control.addItems([
            " 0.25x", " 0.50x", " 0.75x", " 1.00x",
            " 1.25x", " 1.50x", " 1.75x", " 2.00x",
        ])
        self.speed_control.setStyleSheet("font-family: monospace;")
        self.speed_control.setCurrentText(" 1.00x")

        self.speed_control.currentTextChanged.connect(
            lambda t: app.set_playback_speed(float(t[:-1]))
        )

        self.toolbar_layout.addWidget(self.speed_control)

        self.timestamp_label = TimestampLabel()
        self.toolbar_layout.addWidget(self.timestamp_label, 1)

        self.main_layout.addLayout(self.toolbar_layout)

        self.graphics_view = pg.GraphicsView()
        self.graphics_view.setBackground("transparent")
        self.graphics_layout = pg.GraphicsLayout()
        self.graphics_layout.setSpacing(0)
        self.graphics_view.setCentralItem(self.graphics_layout)

        self.graphics_view.scene().sigMouseClicked.connect(self.on_chart_area_clicked)
        self.graphics_view.scene().sigMouseMoved.connect(self.on_chart_area_mouse_moved)
        self.scroll_area = QScrollArea()
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll_area.setWidget(self.graphics_view)
        self.main_layout.addWidget(self.scroll_area)

        self.setMouseTracking(True)

        # Add a permanent timeline with timestamps
        self.timestamps_plot = self.get_timeline_plot(
            "Export window", create_if_missing=True
        )
        self.timestamps_plot.showAxis("top")
        self.timestamps_plot.setMaximumHeight(50)
        self.timestamps_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

        self.playhead = PlayHead(self.timestamps_plot, parent=self.graphics_view)
        self.playhead.hide()

        app.playback_state_changed.connect(self.on_playback_state_changed)
        app.position_changed.connect(self.on_position_changed)
        app.recording_loaded.connect(self.on_recording_loaded)

        self.dragging = None

    def sizeHint(self) -> QSize:
        return QSize(100, 150)

    def keyPressEvent(self, event: QKeyEvent):
        self.key_pressed.emit(event)

    def resizeEvent(self, event):
        w = self.scroll_area.width() - self.scroll_area.verticalScrollBar().width()
        self.graphics_view.setFixedWidth(w)
        self.playhead.refresh_geometry()
        return super().resizeEvent(event)

    def on_recording_loaded(self, recording: nr.NeonRecording):
        app = neon_player.instance()

        self.playhead.show()
        for plot_item in self.timeline_plots.values():
            plot_item.setXRange(
                recording.start_time, recording.stop_time, padding=0
            )
            axis = plot_item.getAxis("top")
            axis.set_time_frame(recording.start_time, recording.stop_time)

        trim_plot = self.get_timeline_plot("Export window", create_if_missing=True)
        self.trim_markers = [
            TrimEndMarker(app.recording_settings.export_window[0], plot=trim_plot),
            TrimEndMarker(app.recording_settings.export_window[1], plot=trim_plot),
        ]
        self.duration_marker = TrimDurationMarker(*self.trim_markers)
        for tm in [*self.trim_markers, self.duration_marker]:
            trim_plot.addItem(tm)

    def on_playback_state_changed(self, is_playing: bool):
        icon_name = "pause.svg" if is_playing else "play.svg"
        self.play_button.setIcon(QIcon(str(neon_player.asset_path(icon_name))))

    def on_position_changed(self, t: int):
        app = neon_player.instance()
        if app.recording is None:
            return

        self.timestamp_label.set_time(t - app.recording.start_time)
        self.playhead.set_time(t)

    def show_context_menu(self, global_position: QPoint) -> None:
        menu = neon_player.instance().main_window.get_menu(
            "Timeline", auto_create=False
        )
        context_menu = QMenu() if menu is None else clone_menu(menu)
        context_menu.exec(global_position)

    def on_chart_area_mouse_moved(self, pos: QPointF):
        data_pos = self.timestamps_plot.getViewBox().mapSceneToView(pos)
        for tm in self.trim_markers:
            tm.set_highlighted(self.dragging == tm or tm.nearby(data_pos))

    def on_trim_area_drag_start(self, event: MouseDragEvent):
        app = neon_player.instance()
        if app.recording is None:
            return

        data_pos = self.timestamps_plot.getViewBox().mapSceneToView(event.scenePos())
        for tm in self.trim_markers:
            if tm.nearby(data_pos, 0.5):
                self.dragging = tm
                break
        else:
            self.on_trim_area_dragged(event)

    def on_trim_area_dragged(self, event: MouseDragEvent):
        app = neon_player.instance()
        if app.recording is None:
            return

        data_pos = self.timestamps_plot.getViewBox().mapSceneToView(event.scenePos())
        if self.dragging is None:
            self.on_chart_area_clicked(event)
            return

        self.dragging.time = max(
            min(data_pos.x(), app.recording.stop_time),
            app.recording.start_time
        )
        app.recording_settings.export_window = self.get_export_window()

    def on_trim_area_drag_end(self, event: MouseDragEvent):
        self.dragging = None
        data_pos = self.timestamps_plot.getViewBox().mapSceneToView(event.scenePos())
        for tm in self.trim_markers:
            tm.set_highlighted(self.dragging == tm or tm.nearby(data_pos))

    def on_chart_area_clicked(self, event: QGraphicsSceneMouseEvent | MouseClickEvent | MouseDragEvent):
        app = neon_player.instance()
        if app.recording is None:
            return

        click_types = [QGraphicsSceneMouseEvent, MouseClickEvent]
        if any(isinstance(event, cls) for cls in click_types):
            data_pos = self.timestamps_plot.getViewBox().mapSceneToView(event.scenePos())
            for tm in self.trim_markers:
                if tm.nearby(data_pos, 0.5):
                    return

        if event.button() == Qt.LeftButton:
            first_plot_item = next(iter(self.timeline_plots.values()))

            mouse_point = first_plot_item.getViewBox().mapSceneToView(event.scenePos())
            time_ns = int(mouse_point.x())

            time_ns = max(app.recording.start_time, time_ns)
            time_ns = min(app.recording.stop_time, time_ns)

            was_playing = app.is_playing
            app.set_playback_state(False)

            app.seek_to(time_ns)
            app.set_playback_state(was_playing)

            return

        if event.button() == Qt.RightButton:
            self.check_for_data_item_click(event)

    def check_for_data_item_click(self, event: MouseClickEvent):
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

        logging.info(f"Adding plot {timeline_row_name} to timeline")

        row = self.graphics_layout.nextRow()
        is_timestamps_row = timeline_row_name == "Export window"

        if is_timestamps_row:
            time_axis = TimeAxisItem(orientation="top")
        else:
            time_axis = TimeAxisItem(
                orientation="top",
                showValues=False,
                pen=pg.mkPen(color="#ffff0000")
            )

        app = neon_player.instance()
        if app.recording is not None:
            time_axis.set_time_frame(app.recording.start_time, app.recording.stop_time)

        vb = ScrubbableViewBox()
        if is_timestamps_row:
            vb.scrub_start.connect(self.on_trim_area_drag_start)
            vb.scrubbed.connect(self.on_trim_area_dragged)
            vb.scrub_end.connect(self.on_trim_area_drag_end)
        else:
            vb.scrubbed.connect(self.on_chart_area_clicked)

        legend = FixedLegend()
        legend_container = pg.GraphicsLayout()
        legend_container.setSpacing(0)
        legend_label = pg.LabelItem(f"<b>{timeline_row_name}</b>")
        legend_container.addItem(legend_label)
        legend_container.addItem(legend, row=1, col=0)

        plot_item = SmartSizePlotItem(legend=legend, axisItems={"top": time_axis}, viewBox=vb)
        legend_container.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Minimum
        )

        if is_timestamps_row:
            legend_label.anchor((.5, 0), (.5, 0), (0, 20))

        legend.layout.setSpacing(0)
        self.timeline_legends[timeline_row_name] = legend

        # determine the alphabetical order of this row
        if timeline_row_name == "Export window":
            row = 0
        else:
            sorted_names = sorted(self.timeline_legends.keys())
            sorted_names.remove("Export window")
            row = sorted_names.index(timeline_row_name) + 1

        items_to_move = []
        if row < len(self.timeline_legends) - 1:
            for move_row in range(row, len(sorted_names)):
                items_to_move.append((
                    self.graphics_layout.getItem(move_row, 0),
                    self.graphics_layout.getItem(move_row, 1)
                ))
            for (l, p) in items_to_move:
                self.graphics_layout.removeItem(l)
                self.graphics_layout.removeItem(p)

        self.graphics_layout.addItem(legend_container, row=row, col=0)
        self.graphics_layout.addItem(plot_item, row=row, col=1)

        for (l, p) in items_to_move:
            row += 1
            self.graphics_layout.addItem(l, row=row, col=0)
            self.graphics_layout.addItem(p, row=row, col=1)

        plot_item.setMouseEnabled(x=False, y=False)
        plot_item.hideButtons()
        plot_item.setMenuEnabled(False)
        plot_item.setClipToView(True)
        plot_item.hideAxis("left")
        plot_item.hideAxis("right")
        plot_item.hideAxis("bottom")
        plot_item.showGrid(x=True, y=False, alpha=0.3)

        self.timeline_plots[timeline_row_name] = plot_item

        if not is_timestamps_row and self.timestamps_plot:
            plot_item.setXRange(*self.timestamps_plot.viewRange()[0])
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

        if "pen" not in kwargs:
            kwargs["pen"] = pg.mkPen(color=color, width=2, cap="flat")

        legend = self.timeline_legends[timeline_row_name]
        data = np.asarray(data)
        if len(data) > 0:
            plot_data_item = plot_item.plot(
                data[:, 0], data[:, 1], name=plot_name, **kwargs
            )
            plot_data_item.name = plot_name
            if timeline_row_name in self.timeline_legends and plot_name != "":
                legend.addItem(plot_data_item, plot_name)

        self.fix_scroll_size()

        return plot_item

    def fix_scroll_size(self):
        h = sum([p.preferredHeight() for p in self.timeline_plots.values()])
        self.graphics_view.setFixedHeight(h)

    def remove_timeline_plot(self, plot_name: str):
        plot = self.get_timeline_plot(plot_name)
        if plot is None:
            return

        self.graphics_layout.removeItem(plot)
        del self.timeline_plots[plot_name]

        if plot_name in self.timeline_legends:
            legend = self.timeline_legends[plot_name]
            self.graphics_layout.removeItem(legend.parentItem())
            del self.timeline_legends[plot_name]

        items_to_move = []
        rows_dict = self.graphics_layout.rows
        dead_row_idx = -1
        for row_idx, row_contents in rows_dict.items():
            if row_contents == {}:
                dead_row_idx = row_idx

            elif dead_row_idx >= 0:
                items_to_move.append((
                    self.graphics_layout.getItem(row_idx, 0),
                    self.graphics_layout.getItem(row_idx, 1)
                ))

        for (l, p) in items_to_move:
            self.graphics_layout.removeItem(l)
            self.graphics_layout.removeItem(p)

        for (l, p) in items_to_move:
            self.graphics_layout.addItem(l, row=dead_row_idx, col=0)
            self.graphics_layout.addItem(p, row=dead_row_idx, col=1)
            dead_row_idx += 1

        del self.graphics_layout.rows[dead_row_idx]

        self.fix_scroll_size()

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
        return self.add_timeline_plot(timeline_row_name, data, plot_name, **kwargs)

    def add_timeline_scatter(
        self, name: str, data: list[tuple[int, int]], item_name: str = ""
    ) -> None:
        return self.add_timeline_plot(
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
        brush = pg.mkBrush("white")

        # data is a list of (start, end) tuples
        starts = [t[0] for t in start_and_stop_times]
        stops = [t[1] for t in start_and_stop_times]

        bars = pg.BarGraphItem(
            x0=starts,
            x1=stops,
            y0=-0.4,
            y1=0.4,
            pen=pen,
            brush=brush,
        )
        plot_widget.addItem(bars)

        if item_name and timeline_row_name in self.timeline_legends:
            legend = self.timeline_legends[timeline_row_name]
            legend.addItem(bars, name=item_name)

        self.fix_scroll_size()

        return plot_widget

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

        for plot_item in self.timeline_plots.values():
            plot_item.getViewBox().autoRange()

        self.timestamps_plot.getViewBox().setRange(xRange=[
            app.recording.start_time,
            app.recording.stop_time
        ])

    def init_view(self):
        h = self.height()
        self.resize(self.width(), h + 1)
        self.resize(self.width(), h)
        self.reset_view()

    def get_export_window(self) -> list[int]:
        times = [tm.time for tm in self.trim_markers]
        times.sort()
        return times

    def set_export_window(self, times: list[int]) -> None:
        self.trim_markers[0].time = times[0]
        self.trim_markers[1].time = times[1]
