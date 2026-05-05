import typing as T
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColorConstants, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileDialog
from qt_property_widgets.utilities import action_params

from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_player.job_manager import BackgroundJob
from pupil_labs.neon_player.plugins.shared import BackgroundVideoExportMixin


class VideoExporter(neon_player.Plugin, BackgroundVideoExportMixin):
    label = "Video Exporter"

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 0
        self.gray = QColorConstants.Gray
        self.is_exporting = False

    @action
    @action_params(compact=True, icon=QIcon(str(neon_player.asset_path("export.svg"))))
    def export(self, destination: Path = Path()) -> BackgroundJob | T.Generator:
        app = neon_player.instance()

        if not app.headless:
            return self.job_manager.run_background_action(
                "Video Export", "VideoExporter.export", destination
            )

        return self.bg_export(destination)

    def render_for_export(self, painter: QPainter, time_in_recording: int) -> None:
        self.app.render_to(painter, time_in_recording)

    def bg_export(self, destination: Path = Path()) -> T.Generator:
        yield from self.bg_export_video(
            recording=self.app.recording,
            export_window=self.export_window,
            render_fn=self.render_for_export,
            destination=destination,
            output_video_filename="world.mp4",
            output_timestamps_filename="world_timestamps.csv"
        )

    @action
    @action_params(compact=True, icon=QIcon(str(neon_player.asset_path("export.svg"))))
    def export_current_frame(self) -> None:
        file_path_str, type_selection = QFileDialog.getSaveFileName(
            None, "Export frame", "", "PNG Images (*.png)"
        )
        if not file_path_str:
            return

        if not file_path_str.endswith(".png"):
            file_path_str += ".png"

        frame_size = QSize(
            self.recording.scene.width or 1, self.recording.scene.height or 1
        )
        frame = QImage(frame_size, QImage.Format.Format_RGB32)
        painter = QPainter(frame)

        self.app.render_to(painter)
        painter.end()
        frame.save(str(file_path_str))

    @action
    @action_params(
        compact=True,
        icon=QIcon(str(neon_player.asset_path("duplicate.svg"))),
    )
    def copy_frame_to_clipboard(self) -> None:
        frame_size = QSize(
            self.recording.scene.width or 1, self.recording.scene.height or 1
        )
        frame = QImage(frame_size, QImage.Format.Format_RGB32)
        painter = QPainter(frame)

        self.app.render_to(painter)
        painter.end()

        clipboard = neon_player.instance().clipboard()
        clipboard.setPixmap(QPixmap.fromImage(frame))
