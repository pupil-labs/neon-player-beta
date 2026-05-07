import cv2
import typing as T
from pathlib import Path

from PySide6.QtGui import QColorConstants, QPainter, QIcon
from qt_property_widgets.utilities import property_params, action, action_params

from pupil_labs import neon_player
from pupil_labs.neon_player import Plugin, asset_path
from pupil_labs.neon_player.plugins.shared.video_export import BackgroundVideoExportMixin
from pupil_labs.neon_player.job_manager import ProgressUpdate
from pupil_labs.neon_player.utilities import qimage_from_frame


class SceneRendererPlugin(Plugin, BackgroundVideoExportMixin):
    label = "Scene Renderer"

    DEFAULT_BRIGHTNESS = 0.0
    DEFAULT_CONTRAST = 1.0

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 0
        self.gray = QColorConstants.Gray

        self._show_frame_index = False
        self._brightness = self.DEFAULT_BRIGHTNESS
        self._contrast = self.DEFAULT_CONTRAST

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            painter.drawText(100, 100, "No scene data available")
            return

        if self.is_time_gray(time_in_recording):
            painter.fillRect(
                0,
                0,
                self.recording.scene.width,
                self.recording.scene.height,
                self.gray,
            )
            return

        scene_frame = self.recording.scene.sample(
            [time_in_recording], method="backward"
        )[0]
        frame_img = cv2.convertScaleAbs(
            scene_frame.bgr, alpha=self._contrast, beta=self._brightness
        )

        painter.drawImage(0, 0, qimage_from_frame(frame_img))

        if self.show_frame_index:
            font = painter.font()
            font.setPointSize(font.pointSize() * 2)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(0, scene_frame.height, str(scene_frame.idx))

    @property
    def show_frame_index(self) -> bool:
        return self._show_frame_index

    @show_frame_index.setter
    def show_frame_index(self, value: bool) -> None:
        self._show_frame_index = value
        self.changed.emit()

    @property
    @property_params(min=0, max=100, scope="recording")
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int) -> None:
        self._brightness = value

    @property
    @property_params(min=0.0, max=3.0, scope="recording")
    def contrast(self) -> float:
        return self._contrast

    @contrast.setter
    def contrast(self, value: float) -> None:
        self._contrast = value

    @action
    @action_params(compact=True, icon=QIcon(str(asset_path("reset_settings.svg"))))
    def reset_settings(self) -> None:
        self.show_frame_index = False
        self.brightness = self.DEFAULT_BRIGHTNESS
        self.contrast = self.DEFAULT_CONTRAST

    @action
    @action_params(compact=True, icon=QIcon(str(asset_path("export.svg"))))
    def export_raw_scene_video(self, destination: Path = Path()) -> None:
        app = neon_player.instance()

        if not app.headless:
            return self.job_manager.run_background_action(
                "Scene Video Export", "SceneRendererPlugin.bg_export", destination
            )

        return self.bg_export(destination)

    def render_for_export(self, painter: QPainter, time_in_recording: int) -> None:
        self.render(painter, time_in_recording)

    def bg_export(self, destination: Path = Path()) -> T.Generator[ProgressUpdate, None, None]:
        yield from self.bg_export_video(
            recording=self.app.recording,
            export_window=self.export_window,
            render_fn=self.render_for_export,
            destination=destination,
            output_video_filename="scene.mp4",
            output_timestamps_filename="scene_timestamps.csv"
        )
