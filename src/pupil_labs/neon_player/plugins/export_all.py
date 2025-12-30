from pathlib import Path

from PySide6.QtGui import QIcon
from qt_property_widgets.utilities import action_params

from pupil_labs import neon_player


class ExportAllPlugin(neon_player.Plugin):
    label = "Export All"

    @neon_player.action
    @action_params(compact=True, icon=QIcon(str(neon_player.asset_path("export.svg"))))
    def export_all_enabled_plugins(self, path: Path = Path(".")):
        if self.recording is None:
            return

        self.app.export_all(path)
