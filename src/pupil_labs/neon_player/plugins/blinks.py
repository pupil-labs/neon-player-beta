from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtGui import QIcon
from qt_property_widgets.utilities import action_params

from pupil_labs import neon_player
from pupil_labs.neon_player import action
from pupil_labs.neon_recording import NeonRecording


class BlinksPlugin(neon_player.Plugin):
    label = "Blinks"

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        if len(recording.blinks) == 0:
            return

        self.get_timeline().add_timeline_broken_bar(
            "Blinks", self.recording.blinks[["start_time", "stop_time"]]
        )

    def on_disabled(self) -> None:
        self.get_timeline().remove_timeline_plot("Blinks")

    @action
    @action_params(compact=True, icon=QIcon.fromTheme("document-save"))
    def export(self, destination: Path = Path()) -> None:
        blink_ids = 1 + np.arange(len(self.recording.blinks))
        blinks = self.recording.blinks

        start_time, stop_time = neon_player.instance().recording_settings.export_window
        start_mask = blinks.stop_time > start_time
        stop_mask = blinks.start_time < stop_time

        blinks = blinks[start_mask & stop_mask]
        blink_ids = blink_ids[start_mask & stop_mask]

        export_data = pd.DataFrame({
            "recording id": self.recording.info["recording_id"],
            "blink id": blink_ids,
            "start timestamp [ns]": blinks.start_time,
            "end timestamp [ns]": blinks.stop_time,
            "duration [ms]": (blinks.stop_time - blinks.start_time) / 1e6,
        })

        export_file = destination / "blinks.csv"
        export_data.to_csv(export_file, index=False)
