import time

import numpy as np
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
        painter.drawText(50, 50, f"{time.time_ns()}")
        if self.recording is None:
            painter.drawText(100, 100, "No scene data available")
            return

        scene_idx = (
            np.searchsorted(self.recording.scene.time, time_in_recording, "right") - 1
        )
        should_gray = scene_idx < 0 or scene_idx > len(self.recording.scene) - 1
        if not should_gray:
            frame = self.recording.scene[scene_idx]
            should_gray = time_in_recording < frame.time
            should_gray = should_gray or (time_in_recording - frame.time > 1e9 / 5)

        if should_gray:
            if self.recording.scene.width and self.recording.scene.height:
                painter.fillRect(
                    0,
                    0,
                    self.recording.scene.width,
                    self.recording.scene.height,
                    self.gray,
                )
            return

        image = qimage_from_frame(self.recording.scene[scene_idx].bgr)

        painter.drawImage(0, 0, image)
