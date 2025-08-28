import typing as T
from pathlib import Path

import av
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColorConstants, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileDialog, QMessageBox

import pupil_labs.video as plv
from pupil_labs import neon_player
from pupil_labs.neon_player import ProgressUpdate, action
from pupil_labs.neon_player.job_manager import BackgroundJob
from pupil_labs.neon_player.utilities import ndarray_from_qimage


class VideoExporter(neon_player.Plugin):
    label = "Video Exporter"

    def __init__(self) -> None:
        super().__init__()
        self.render_layer = 0
        self.gray = QColorConstants.Gray

    @action
    def export(self, destination: Path = Path()) -> BackgroundJob | T.Generator:
        app = neon_player.instance()
        if not app.headless:
            return self.job_manager.run_background_action(
                "Video Export", "VideoExporter.export", destination
            )

        return self.bg_export(destination)

    def bg_export(self, destination: Path) -> T.Generator:
        recording = self.app.recording

        gray_preamble = np.arange(recording.start_time, recording.scene.time[0], 1e9 // 30)
        gray_prologue = np.arange(
            recording.scene.time[-1] + 1e9 // 30, recording.stop_time, 1e9 // 30
        )
        combined_timestamps = np.concatenate((
            gray_preamble,
            recording.scene.time,
            gray_prologue,
        ))
        start_time, stop_time = neon_player.instance().recording_settings.export_window
        combined_timestamps = combined_timestamps[
            (combined_timestamps >= start_time) & (combined_timestamps <= stop_time)
        ]

        frame_size = QSize(recording.scene.width or 1600, recording.scene.height or 1200)

        with plv.Writer(destination / "world.mp4") as writer:
            for frame_idx, ts in enumerate(combined_timestamps):
                rel_ts = (ts - combined_timestamps[0]) / 1e9

                frame = QImage(frame_size, QImage.Format.Format_BGR888)
                painter = QPainter(frame)
                self.app.render_to(painter, ts)
                painter.end()

                frame_pixels = ndarray_from_qimage(frame)
                av_frame = av.VideoFrame.from_ndarray(frame_pixels, format="bgr24")

                plv_frame = plv.VideoFrame(av_frame, rel_ts, frame_idx, "np")
                writer.write_frame(plv_frame)

                progress = (frame_idx + 1) / len(combined_timestamps)
                yield ProgressUpdate(progress)


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

    @action
    def copy_frame_to_clipboard(self) -> None:
        frame_size = QSize(
            self.recording.scene.width or 1, self.recording.scene.height or 1
        )
        frame = QImage(frame_size, QImage.Format.Format_RGB32)
        painter = QPainter(frame)

        self.app.render_to(painter)
        painter.end()

        clipboard = neon_player.instance().clipboard()
        clipboard.setPixmap(QPixmap.fromImage(frame))
