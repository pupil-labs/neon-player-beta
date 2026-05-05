import logging

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pupil_labs import neon_recording as nr
from pupil_labs.neon_recording import NeonRecording


@dataclass
class RecordingMetadata:
    name: str
    path: Path
    recorded: datetime
    duration: timedelta
    wearer: str


def get_recording_metadata(path: Path) -> RecordingMetadata | None:
    """
    Extracts recording name, duration, and wearer name to provide
    metadata of the recording.
    """
    try:
        rec = nr.load(path)
        recorded = datetime.fromtimestamp(rec.start_time / 1e9)
        duration = timedelta(seconds=rec.duration // 1e9)

        return RecordingMetadata(
            name=path.name,
            path=path,
            duration=duration,
            wearer=rec.wearer["name"],
            recorded=recorded
        )
    except FileNotFoundError:  # path / info.json / wearer.json missing
        return None


def get_recording_list(path: Path) -> list[RecordingMetadata]:
    """
    Get a list of recordings present in a folder.
    Only a subset of fields is extracted to provide metadata.
    """
    recordings = []
    folders = sorted([p for p in path.iterdir() if p.is_dir()])
    for folder in folders:
        if desc := get_recording_metadata(folder):
            recordings.append(desc)

    return recordings


def check_if_neon_recording(path: Path) -> bool:
    """
    Check if the given path contains a Neon recording.
    """
    info_file = path / "info.json"
    wearer_file = path / "wearer.json"
    return info_file.exists() and wearer_file.exists()


class Workspace(QObject):
    recording_list_loaded = Signal(object)

    def __init__(self):
        super().__init__()

        self._recording_metadata : dict[str, RecordingMetadata] = {}
        self._recordings : list[NeonRecording] = []
        self.initialized : bool = False

    @property
    def recordings(self) -> list[NeonRecording]:
        return self._recordings

    @property
    def num_recordings(self) -> int:
        return len(self._recordings)

    @property
    def recording_metadata(self) -> list[RecordingMetadata]:
        return list(self._recording_metadata.values())

    def get_recording_path(self, recording_name: str) -> Path | None:
        """
        Get the file path of a recording by its name.
        """
        if recording_name not in self._recording_metadata:
            return None

        return self._recording_metadata[recording_name].path

    def clear(self):
        self._recording_metadata = {}
        self._recordings = []
        self.initialized = False

    def add_recording(self, path: Path):
        desc = get_recording_metadata(path)

        if desc:
            self._recordings.append(nr.load(path))
            self._recording_metadata[desc.name] = desc
            self.initialized = True
            self.recording_list_loaded.emit(self.recording_metadata)

    def load_recording_list(self, path: Path):
        logging.info(f"Scanning for recordings in: {path}")
        self.initialized = False
        recording_list = get_recording_list(path)
        self._recording_metadata = {rec.name: rec for rec in recording_list}
        self._recordings = [nr.load(rec.path) for rec in recording_list]

        logging.info(
            f"Found {self.num_recordings} recordings in the provided folder"
        )
        self.initialized = True
        self.recording_list_loaded.emit(self.recording_metadata)
