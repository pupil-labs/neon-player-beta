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
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        app = neon_player.instance()

        self.timeline_plots: dict[str, pg.PlotItem] = {}
        self.timeline_labels: dict[str, pg.LabelItem] = {}
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
        self.plot_count: dict[str, int] = {}
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
        self.graphics_view.setCentralItem(self.graphics_layout)

        self.main_layout.addWidget(self.graphics_view)

        self.graphics_view.scene().sigMouseClicked.connect(self.on_chart_area_clicked)

        self.playhead = PlayHead(self)
        app.playback_state_changed.connect(self.on_playback_state_changed)
        app.position_changed.connect(self.on_position_changed)

        self.setMouseTracking(True)

        self.chart_area_parameters = {
            "global_rect": None,
            "local_rect": None,
            "x_range": None,
        }

    def resizeEvent(self, event):
        self.update_chart_area_params()
        return super().resizeEvent(event)

    def showEvent(self, event):
        self.update_chart_area_params()
        return super().showEvent(event)

    def update_chart_area_params(self):
        if len(self.timeline_plots) == 0:
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

        first_chart = next(iter(self.timeline_plots.values()))
        self.chart_area_parameters["x_range"] = first_chart.getViewBox().viewRange()[0]
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

    def show_context_menu(self, position: QPoint) -> None:
        menu = neon_player.instance().main_window.get_menu(
            "Timeline", auto_create=False
        )
        context_menu = QMenu() if menu is None else self.clone_menu(menu)
        context_menu.exec(self.mapToGlobal(position))

    def clone_menu(self, menu: QMenu) -> QMenu:
        menu_copy = QMenu(menu.title(), self)
        for action in menu.actions():
            if action.menu():
                menu_copy.addMenu(self.clone_menu(action.menu()))
            else:
                menu_copy.addAction(action)

        return menu_copy

    def on_chart_area_clicked(self, event: MouseClickEvent):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return

        app = neon_player.instance()
        if app.recording is None:
            return

        first_plot_item = next(iter(self.timeline_plots.values()))

        mouse_point = first_plot_item.getViewBox().mapSceneToView(event.scenePos())
        time_ns = int(mouse_point.x())

        time_ns = max(app.recording.start_time, time_ns)
        time_ns = min(app.recording.stop_time, time_ns)

        app.seek_to(time_ns)

    def get_timeline_plot(
        self, timeline_row_name: str, create_if_missing: bool = False
    ) -> pg.PlotItem | None:
        if timeline_row_name in self.timeline_plots:
            return self.timeline_plots[timeline_row_name]

        if not create_if_missing:
            return None

        app = neon_player.instance()
        if app.recording is None:
            return None

        # Add a label for the plot
        row = self.graphics_layout.nextRow()
        label = pg.LabelItem(timeline_row_name, justify="right")
        self.graphics_layout.addItem(label, row=row, col=0)
        self.timeline_labels[timeline_row_name] = label

        # Add the plot
        plot_item = self.graphics_layout.addPlot(row=row, col=1)
        plot_item.hideButtons()
        plot_item.setMouseEnabled(x=True, y=False)
        plot_item.setMenuEnabled(False)
        plot_item.setXRange(
            app.recording.start_time, app.recording.stop_time, padding=0
        )
        plot_item.getAxis("left").setWidth(0)
        plot_item.getAxis("left").hide()
        plot_item.getAxis("bottom").setHeight(0)
        plot_item.getAxis("bottom").hide()
        plot_item.showGrid(x=True, y=False, alpha=0.3)

        self.timeline_plots[timeline_row_name] = plot_item

        # Link x-axes of all plots
        plots = list(self.timeline_plots.values())
        if len(plots) > 1:
            for i in range(1, len(plots)):
                plots[i].setXLink(plots[0])
        else:
            plot_item.getViewBox().sigXRangeChanged.connect(
                self.update_chart_area_params
            )

        return plot_item

    def add_timeline_plot(
        self,
        timeline_row_name: str,
        data: list[tuple[int, int]],
        plot_name: str = "",
        **kwargs,
    ):
        app = neon_player.instance()
        if app.recording is None:
            return

        plot_item = self.get_timeline_plot(timeline_row_name, True)
        if plot_item is None:
            return

        plot_index = self.plot_count.get(timeline_row_name, 0)
        color = self.plot_colors[plot_index % len(self.plot_colors)]
        self.plot_count[timeline_row_name] = plot_index + 1

        if "pen" not in kwargs:
            kwargs["pen"] = pg.mkPen(color=color, width=2, cap="flat")

        if len(data) > 0:
            plot_data_item = plot_item.plot(
                data[:, 0], data[:, 1], name=plot_name, **kwargs
            )
            if hasattr(plot_data_item, "sigPointsClicked"):
                plot_data_item.sigPointsClicked.connect(
                    lambda _, points, event: self.on_data_point_clicked(
                        timeline_row_name,
                        plot_name,
                        points, event
                    )
                )

        self.update_chart_area_params()

    def remove_timeline_plot(self, name: str):
        if name not in self.timeline_plots:
            return

        plot_item = self.timeline_plots[name]
        self.graphics_layout.removeItem(plot_item)

        if name in self.timeline_labels:
            self.graphics_layout.removeItem(self.timeline_labels[name])
            del self.timeline_labels[name]

        del self.timeline_plots[name]
        if name in self.plot_count:
            del self.plot_count[name]

    def on_data_point_clicked(self, timeline_name, plot_name, data_points, event):
        if timeline_name not in self.data_point_actions:
            return

        context_menu = QMenu()

        for action_name, callback in self.data_point_actions[timeline_name]:
            action = context_menu.addAction(action_name)
            action.triggered.connect(
                lambda _, cb=callback: cb(timeline_name, plot_name, data_points, event)
            )

        context_menu.exec(QPoint(event.screenPos().toQPoint()))

    def add_timeline_line(
        self, timeline_row_name: str, data: list[tuple[int, int]], plot_name: str = ""
    ) -> None:
        self.add_timeline_plot(timeline_row_name, data, plot_name)

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

        brush = pg.mkBrush(255, 255, 255)  # RGBA
        fill = pg.FillBetweenItem(curve1, curve2, brush=brush)
        plot_widget.addItem(fill)

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
