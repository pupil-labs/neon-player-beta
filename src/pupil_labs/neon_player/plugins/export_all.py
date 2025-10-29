from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from pupil_labs import neon_player


class ExportAllPlugin(neon_player.Plugin):
    label = "Export All"

    @neon_player.action
    def export_all_enabled_plugins(self, path: Path = Path(".")):
        if self.recording is None:
            return

        self.app.export_all(path)
