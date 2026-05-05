import json
import shutil
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
from PySide6.QtGui import QIcon
from qt_property_widgets.utilities import action_params

from pupil_labs import neon_player


class ExportAllPlugin(neon_player.Plugin):
    label = "Export All"

    def __init__(self):
        super().__init__()
        self._export_meta_data = True
        self._export_camera_calibrations = True

    @property
    def export_meta_data(self) -> bool:
        return self._export_meta_data

    @export_meta_data.setter
    def export_meta_data(self, value: bool) -> None:
        self._export_meta_data = value

    @property
    def export_camera_calibrations(self) -> bool:
        return self._export_camera_calibrations

    @export_camera_calibrations.setter
    def export_camera_calibrations(self, value: bool) -> None:
        self._export_camera_calibrations = value

    @neon_player.action
    @action_params(compact=True, icon=QIcon(str(neon_player.asset_path("export.svg"))))
    def export_all_enabled_plugins(self, path: Path = Path(".")):
        if self.recording is None:
            return

        self.app.export_all(path)

    def export(self, destination: Path = Path()) -> None:
        if self.export_meta_data:
            shutil.copy(self.recording._rec_dir / "info.json", destination)

            try:
                app_version = version("pupil_labs.neon_player")
            except Exception:
                app_version = "?"

            frame_indicies = [self.get_scene_idx_for_time(t) for t in self.export_window]
            rel_times_formatted = [
                self.format_duration((t - self.recording.start_time) / 1e9)
                for t in self.export_window
            ]

            now = datetime.now().astimezone()
            export_info = {
                "Player Software Version": app_version,
                "Export Date": now.strftime("%d.%m.%Y"),
                "Export Time": now.strftime("%H:%M:%S"),
                "Frame Index Range": f"{frame_indicies[0]} - {frame_indicies[1]}",
                "Relative Time Range": f"{rel_times_formatted[0]} - {rel_times_formatted[1]}",
                "Absolute Time Range": f"{self.export_window[0]} - {self.export_window[1]}",
            }
            export_file = destination / "export_info.csv"
            with export_file.open("w") as out_file:
                out_file.write("key,value\n")
                for key, value in export_info.items():
                    out_file.write(f"{key},{value}\n")

        if self.export_camera_calibrations:
            calibration = {}
            for k, v in self.recording.calibration.items():
                if isinstance(v, np.ndarray):
                    v = v.tolist()
                elif isinstance(v, np.generic):
                    v = v.item()

                calibration[k] = v

            export_file = destination / "calibration.json"
            with export_file.open("w") as out_file:
                json.dump(calibration, out_file)

    def format_duration(self, duration_seconds: float) -> str:
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        seconds = int(duration_seconds % 60)
        millis = int((duration_seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
