from PySide6.QtGui import QColorConstants, QPainter

from pupil_labs.neon_player import Plugin
from pupil_labs.neon_player.utilities import qimage_from_frame


class SceneRendererPlugin(Plugin):
    label = "Scene Renderer"

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 0
        self.gray = QColorConstants.Gray

    def render(self, painter: QPainter, time_in_recording: int) -> None:
        if self.recording is None:
            painter.drawText(100, 100, "No scene data available")
            return

        scene_frame = self.recording.scene.sample([time_in_recording])[0]
        if abs(time_in_recording - scene_frame.time) / 1e9 > 1 / 30:
            painter.fillRect(
                0,
                0,
                self.recording.scene.width,
                self.recording.scene.height,
                self.gray,
            )
            return

        image = qimage_from_frame(scene_frame.bgr)
        painter.drawImage(0, 0, image)
