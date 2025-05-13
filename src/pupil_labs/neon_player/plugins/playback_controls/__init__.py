from typing import Optional

import pkg_resources
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QGridLayout,
    QPushButton,
    QSlider,
    QWidget,
)

from pupil_labs import neon_player
from pupil_labs.neon_recording import NeonRecording


class PlaybackControlsPlugin(neon_player.Plugin):
    label = "Playback Controls"

    def __init__(self) -> None:
        super().__init__()

        self.recording: Optional[NeonRecording] = None
        self.resume_playback = False

        self.slider_debounce_timer = QTimer()
        self.slider_debounce_timer.setInterval(1)
        self.slider_debounce_timer.setSingleShot(True)
        self.slider_debounce_timer.timeout.connect(self.on_slider_debounce_done)

        self.widget = QWidget()

        app = neon_player.instance()
        app.playback_state_changed.connect(self.on_playback_state_changed)
        app.position_changed.connect(self.on_app_position_changed)

        self.play_button = QPushButton(
            QIcon(pkg_resources.resource_filename(__name__, "play.svg")), ""
        )
        self.play_button.clicked.connect(
            lambda: app.get_action("Playback/Play\\Pause").trigger()
        )
        self.play_button.setFlat(True)
        self.play_button.setIconSize(QSize(48, 48))

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 100)
        self.progress_slider.sliderMoved.connect(self.on_slider_changed)
        self.progress_slider.sliderPressed.connect(self.on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self.on_slider_released)

        layout = QGridLayout()
        layout.addWidget(self.play_button, 0, 1)
        layout.addWidget(self.progress_slider, 1, 0, 1, 3)
        self.widget.setLayout(layout)

        self.dock = app.main_window.add_dock(
            self.widget, "", Qt.DockWidgetArea.BottomDockWidgetArea
        )

    def on_slider_pressed(self) -> None:
        app = neon_player.instance()
        self.resume_playback = app.is_playing
        if app.is_playing:
            app.toggle_play()

    def on_slider_released(self) -> None:
        app = neon_player.instance()
        if self.resume_playback:
            app.toggle_play()

        self.resume_playback = False

    def on_disabled(self) -> None:
        app = neon_player.instance()
        if app is not None and not app.closingDown():
            self.dock.close()

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.recording = recording
        self.progress_slider.setRange(0, int(recording.duration / 1e3))

    def on_playback_state_changed(self, is_playing: bool) -> None:
        if is_playing:
            self.play_button.setIcon(
                QIcon(pkg_resources.resource_filename(__name__, "pause.svg"))
            )
        else:
            self.play_button.setIcon(
                QIcon(pkg_resources.resource_filename(__name__, "play.svg"))
            )

    def on_app_position_changed(self, time_in_recording: int) -> None:
        if self.recording is None:
            return
        elapsed_time_ns = time_in_recording - self.recording.start_ts
        self.progress_slider.setValue(int(elapsed_time_ns / 1e3))

    def on_slider_changed(self, value: int) -> None:
        self.slider_debounce_timer.start()

    def on_slider_debounce_done(self) -> None:
        if self.recording is None:
            return

        ns_rel = self.progress_slider.value() * 1e3
        app = neon_player.instance()
        app.seek_to(self.recording.start_ts + ns_rel)
