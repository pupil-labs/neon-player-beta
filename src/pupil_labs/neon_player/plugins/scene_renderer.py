import cv2
from PySide6.QtGui import QColorConstants, QPainter
from qt_property_widgets.utilities import property_params

from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.utilities import qimage_from_frame


class SceneRendererPlugin(Plugin):
    label = "Scene Renderer"

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 0
        self.gray = QColorConstants.Gray

        self._show_frame_index = False
        self._brightness = 0.0
        self._contrast = 1.0

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
    @property_params(min=0, max=100)
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int) -> None:
        self._brightness = value

    @property
    @property_params(min=0.0, max=3.0)
    def contrast(self) -> float:
        return self._contrast

    @contrast.setter
    def contrast(self, value: float) -> None:
        self._contrast = value
