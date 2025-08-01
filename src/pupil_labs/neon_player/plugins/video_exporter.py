import typing as T
from pathlib import Path

import av
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColorConstants, QImage, QPainter
from PySide6.QtWidgets import QFileDialog, QMessageBox

import pupil_labs.video as plv
from pupil_labs import neon_player
from pupil_labs.neon_player import ProgressUpdate, action
from pupil_labs.neon_player.app import NeonPlayerApp
from pupil_labs.neon_player.utilities import ndarray_from_qimage


def bg_export(recording_path: Path, destination: Path) -> T.Generator:
    app = NeonPlayerApp([str(recording_path)])
    app.load(recording_path)

    if app.recording is None:
        return

    recording = app.recording

    gray_preamble = np.arange(recording.start_ts, recording.scene.ts[0], 1e9 // 30)
    gray_prologue = np.arange(
        recording.scene.ts[-1] + 1e9 // 30, recording.stop_ts, 1e9 // 30
    )
    combined_timestamps = np.concatenate((
        gray_preamble,
        recording.scene.ts,
        gray_prologue,
    ))
    frame_size = QSize(recording.scene.width or 1600, recording.scene.height or 1200)

    with plv.Writer(destination / "world.mp4") as writer:
        for frame_idx, ts in enumerate(combined_timestamps):
            rel_ts = (ts - combined_timestamps[0]) / 1e9

            frame = QImage(frame_size, QImage.Format.Format_BGR888)
            painter = QPainter(frame)
            app.render_to(painter, ts)
            painter.end()

            frame_pixels = ndarray_from_qimage(frame)
            av_frame = av.VideoFrame.from_ndarray(frame_pixels, format="bgr24")

            plv_frame = plv.VideoFrame(av_frame, rel_ts, frame_idx, "np")
            writer.write_frame(plv_frame)

            progress = (frame_idx + 1) / len(combined_timestamps)
            yield ProgressUpdate(progress)


class VideoExporter(neon_player.Plugin):
    label = "Video Exporter"

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 0
        self.gray = QColorConstants.Gray

    @action
    def export(self, destination: Path = Path()) -> None:
        self.app.job_manager.create_job(
            "Export Scene Video", bg_export, self.recording._rec_dir, destination
        )

    @action
    def export_current_frame(self) -> None:
        file_path_str, type_selection = QFileDialog.getSaveFileName(
            None, "Save Frame", "", "PNG Images (*.png);;JPG Images (*.jpg)"
        )
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        if not file_path.exists():
            ok_exts = [".png", ".jpg"]
            ext_ok = file_path.suffix and file_path.suffix.lower() in ok_exts
            if not ext_ok:
                ext = type_selection.split("(*.")[-1][:-1]
                file_path = file_path.with_name(f"{file_path.name}.{ext}")
                if file_path.exists():
                    reply = QMessageBox.question(
                        self.app.main_window,
                        "Overwrite File?",
                        f"'{file_path.name}' already exists. Replace file?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return

        frame_size = QSize(
            self.recording.scene.width or 1, self.recording.scene.height or 1
        )
        frame = QImage(frame_size, QImage.Format.Format_RGB32)
        painter = QPainter(frame)

        self.app.render_to(painter)
        painter.end()
        frame.save(str(file_path))
