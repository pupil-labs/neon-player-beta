import typing as T
from pathlib import Path

import av
import numpy as np
import pupil_labs.video as plv
from PySide6.QtCore import QSize
from PySide6.QtGui import QColorConstants, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileDialog, QMessageBox

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
        self.is_exporting = False

    @action
    def export(self, destination: Path = Path()) -> BackgroundJob | T.Generator:
        app = neon_player.instance()
        if not app.headless:
            return self.job_manager.run_background_action(
                "Video Export", "VideoExporter.export", destination
            )

        return self.bg_export(destination)

    def bg_export(self, destination: Path = Path()) -> T.Generator:
        self.is_exporting = True
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
        # Find any gaps in the timestamps that are greater than 1/30 of a second
        gaps = np.where(np.diff(combined_timestamps) > 1e9 // 30)[0]

        # fill the gaps with 30 hz timestamps
        for gap in reversed(gaps):
            gap_start = combined_timestamps[gap]
            gap_end = combined_timestamps[gap + 1] - 1e9 // 60
            gap_timestamps = np.arange(gap_start, gap_end, 1e9 // 30)
            combined_timestamps = np.concatenate((combined_timestamps[:gap], gap_timestamps, combined_timestamps[gap + 1:]))

        frame_size = QSize(recording.scene.width or 1600, recording.scene.height or 1200)

        audio_frame_timestamps = recording.audio.time[
            (recording.audio.time >= start_time) & (recording.audio.time <= stop_time)
        ]
        audio_iterator = iter(recording.audio.sample(audio_frame_timestamps))
        audio_frame = next(audio_iterator)
        audio_frame_idx = 0

        with plv.Writer(destination / "world.mp4") as writer:
            def write_audio_frame():
                nonlocal audio_frame, audio_frame_idx

                audio_rel_ts = (audio_frame.time - start_time) / 1e9
                plv_audio_frame = plv.AudioFrame(
                    audio_frame.av_frame,
                    audio_rel_ts,
                    audio_frame_idx,
                    ""
                )
                writer.write_frame(plv_audio_frame)
                try:
                    audio_frame = next(audio_iterator)
                    audio_frame_idx += 1
                except StopIteration:
                    audio_frame = None

            for frame_idx, ts in enumerate(combined_timestamps):
                while audio_frame and audio_frame.time < ts:
                    write_audio_frame()

                rel_ts = (ts - combined_timestamps[0]) / 1e9

                frame = QImage(frame_size, QImage.Format.Format_BGR888)
                painter = QPainter(frame)
                self.app.render_to(painter, int(ts))
                painter.end()

                frame_pixels = ndarray_from_qimage(frame)
                av_frame = av.VideoFrame.from_ndarray(frame_pixels, format="bgr24")

                plv_frame = plv.VideoFrame(av_frame, rel_ts, frame_idx, "")
                writer.write_frame(plv_frame)

                progress = (frame_idx + 1) / len(combined_timestamps)
                yield ProgressUpdate(progress)

            while audio_frame:
                write_audio_frame()

        self.is_exporting = False

    @action
    def export_current_frame(self) -> None:
        file_path_str, type_selection = QFileDialog.getSaveFileName(
            None, "Export frame", "", "PNG Images (*.png)"
        )
        if not file_path_str:
            return

        if not file_path_str.endswith(".png"):
            file_path_str += ".png"

        frame_size = QSize(
            self.recording.scene.width or 1, self.recording.scene.height or 1
        )
        frame = QImage(frame_size, QImage.Format.Format_RGB32)
        painter = QPainter(frame)

        self.app.render_to(painter)
        painter.end()
        frame.save(str(file_path_str))

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
