import pyqtgraph as pg
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QIcon
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


class TimeLineDock(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        app = neon_player.instance()

        self.timeline_plots: dict[str, pg.PlotItem] = {}
        self.timeline_labels: dict[str, pg.LabelItem] = {}
        self.playhead_lines: dict[str, pg.InfiniteLine] = {}
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
        self.graphics_layout = pg.GraphicsLayout()
        self.graphics_view.setCentralItem(self.graphics_layout)

        self.main_layout.addWidget(self.graphics_view)

        app.playback_state_changed.connect(self.on_playback_state_changed)
        app.position_changed.connect(self.on_position_changed)

        self.setMouseTracking(True)

    def on_playback_state_changed(self, is_playing: bool):
        icon_name = "pause.svg" if is_playing else "play.svg"
        self.play_button.setIcon(QIcon(str(neon_player.asset_path(icon_name))))

    def on_position_changed(self, t: int):
        app = neon_player.instance()
        if app.recording is None:
            return

        self.timestamp_label.set_time(t - app.recording.start_time)

        for line in self.playhead_lines.values():
            line.setValue(t)

    def get_chart_area(self) -> QRect:
        return self.graphics_view.geometry()

    def show_context_menu(self, position: QPoint) -> None:
        menu = neon_player.instance().main_window.get_menu(
            "Timeline", auto_create=False
        )
        if menu is None:
            return
        context_menu = self.clone_menu(menu)
        context_menu.exec(self.mapToGlobal(position))

    def clone_menu(self, menu: QMenu) -> QMenu:
        menu_copy = QMenu(menu.title(), self)
        for action in menu.actions():
            if action.menu():
                menu_copy.addMenu(self.clone_menu(action.menu()))
            else:
                menu_copy.addAction(action)

        return menu_copy

    def on_plot_clicked(self, event, plot_item: pg.PlotItem):
        app = neon_player.instance()
        if app.recording is None:
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        mouse_point = plot_item.getViewBox().mapSceneToView(event.scenePos())
        time_ns = int(mouse_point.x())

        time_ns = max(app.recording.start_time, time_ns)
        time_ns = min(app.recording.stop_time, time_ns)

        app.seek_to(time_ns)

    def get_timeline_plot(
        self, timeline_row_name: str, create_if_missing: bool = True
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
        plot_item.setMouseEnabled(x=True, y=False)
        plot_item.setMenuEnabled(False)
        plot_item.setXRange(
            app.recording.start_time, app.recording.stop_time, padding=0
        )
        plot_item.getAxis("left").setWidth(0)
        plot_item.getAxis("bottom").setHeight(0)
        plot_item.showGrid(x=True, y=False, alpha=0.3)

        plot_item.scene().sigMouseClicked.connect(
            lambda event: self.on_plot_clicked(event, plot_item)
        )

        # Add a playhead line
        playhead_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("red"))
        plot_item.addItem(playhead_line)
        self.playhead_lines[timeline_row_name] = playhead_line

        self.timeline_plots[timeline_row_name] = plot_item

        # Link x-axes of all plots
        plots = list(self.timeline_plots.values())
        if len(plots) > 1:
            for i in range(1, len(plots)):
                plots[i].setXLink(plots[0])

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

        plot_item = self.get_timeline_plot(timeline_row_name)
        if plot_item is None:
            return

        plot_index = self.plot_count.get(timeline_row_name, 0)
        color = self.plot_colors[plot_index % len(self.plot_colors)]
        self.plot_count[timeline_row_name] = plot_index + 1

        if "pen" not in kwargs:
            kwargs["pen"] = pg.mkPen(color=color, width=2, cap="flat")

        plot_item.plot(
            [p[0] for p in data], [p[1] for p in data], name=plot_name, **kwargs
        )

    def remove_timeline_plot(self, name: str):
        if name not in self.timeline_plots:
            return

        plot_item = self.timeline_plots[name]
        self.graphics_layout.removeItem(plot_item)

        if name in self.timeline_labels:
            self.graphics_layout.removeItem(self.timeline_labels[name])
            del self.timeline_labels[name]

        if name in self.playhead_lines:
            del self.playhead_lines[name]

        del self.timeline_plots[name]
        if name in self.plot_count:
            del self.plot_count[name]

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
        plot_widget = self.get_timeline_plot(timeline_row_name)
        pen = pg.mkPen("white")

        import numpy as np

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
