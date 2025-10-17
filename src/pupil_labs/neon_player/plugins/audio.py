import av
import numpy as np
from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from pupil_labs import neon_player
from pupil_labs.neon_player.job_manager import ProgressUpdate


class AudioPlugin(neon_player.Plugin):
    label = "Audio"

    def __init__(self) -> None:
        super().__init__()
        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)

        self.app.playback_state_changed.connect(self.on_playback_state_changed)
        self.app.seeked.connect(self.on_user_seeked)
        self.app.speed_changed.connect(self.on_speed_changed)

        self.cache_file = self.get_cache_path() / "audio.wav"

    def on_disabled(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())

    def on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.sync_position()

    def sync_position(self):
        position = self.app.current_ts
        rel_time_ms = round((position - self.recording.audio.time[0]) / 1e6)
        self.player.setPosition(rel_time_ms)
        self.player.setPlaybackRate(self.app.playback_speed)

    def on_speed_changed(self, speed: float) -> None:
        self.sync_position()

    def on_user_seeked(self, position: int) -> None:
        self.sync_position()

    def on_playback_state_changed(self, is_playing: bool) -> None:
        if is_playing and self.app.playback_speed > 0:
            self.sync_position()
            self.player.play()
        else:
            self.player.stop()

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        if not self.cache_file.exists():
            if self.app.headless:
                self.generate_audio()
                self.load_audio()

            else:
                job = self.job_manager.run_background_action(
                    "Generate audio", "AudioPlugin.generate_audio"
                )
                job.finished.connect(self.load_audio)

        else:
            self.load_audio()

    def load_audio(self):
        self.player.setSource(QUrl.fromLocalFile(str(self.cache_file)))
        self.on_playback_state_changed(self.app.is_playing)

    def generate_audio(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

        container = av.open(str(self.cache_file), "w")
        stream = container.add_stream("pcm_s16le", rate=self.recording.audio.rate)
        stream.layout = self.recording.audio[0].av_frame.layout

        next_expected_frame_time = None
        frame_duration = 0

        for frame in self.recording.audio:
            rel_time = (frame.time - self.recording.audio.time[0]) / 1e9
            raw_audio = frame.to_ndarray()
            if next_expected_frame_time is not None:
                # fill in gaps
                gap = (frame.time - next_expected_frame_time) / 1e9
                if gap > frame_duration:
                    samples_to_gen = int(gap * frame.av_frame.sample_rate)
                    silence = np.zeros([raw_audio.shape[0], samples_to_gen]).astype(np.float32)

                    silence_frame = av.AudioFrame.from_ndarray(
                        silence,
                        format=frame.av_frame.format,
                        layout=frame.av_frame.layout,
                    )
                    silence_frame.sample_rate = frame.av_frame.sample_rate
                    silence_frame.time_base = frame.av_frame.time_base
                    silence_rel_time = (next_expected_frame_time - self.recording.audio.time[0]) / 1e9
                    silence_frame.pts = silence_rel_time / silence_frame.time_base
                    silence_frame.dts = silence_frame.pts
                    for packet in stream.encode(silence_frame):
                        container.mux(packet)

            frame_duration = frame.to_ndarray().shape[1] / frame.av_frame.sample_rate
            next_expected_frame_time = frame.time + frame_duration * 1e9

            frame_copy = av.AudioFrame.from_ndarray(
                raw_audio,
                format=frame.av_frame.format,
                layout=frame.av_frame.layout,
            )
            frame_copy.sample_rate = frame.av_frame.sample_rate
            frame_copy.time_base = frame.av_frame.time_base
            frame_copy.pts = rel_time / frame_copy.time_base
            frame_copy.dts = frame_copy.pts
            for packet in stream.encode(frame_copy):
                container.mux(packet)

            yield ProgressUpdate(frame.idx / len(self.recording.audio))

        # Flush encoder
        for packet in stream.encode(None):
            container.mux(packet)

        container.close()
