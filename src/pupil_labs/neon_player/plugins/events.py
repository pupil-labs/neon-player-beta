from pupil_labs import neon_player
from pupil_labs.neon_recording import NeonRecording


class EventsPlugin(neon_player.Plugin):
    label = "Events"

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.recording = recording
        app = neon_player.instance()

        app.main_window.timeline_dock.add_timeline_scatter(
            "Events",
            [(event.ts, 0) for event in self.recording.events],
        )
        events_by_name: dict[str, list[int]] = {}

        for event in self.recording.events:
            event_name = str(event.event)
            if event_name not in events_by_name:
                events_by_name[event_name] = []

            events_by_name[event_name].append(int(event.ts))

        for event_name, timestamps in events_by_name.items():
            app.main_window.timeline_dock.add_timeline_scatter(
                f"Events/{event_name}",
                [(ts, 0) for ts in timestamps],
            )
