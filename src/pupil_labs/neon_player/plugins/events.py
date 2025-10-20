import logging
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from pupil_labs.neon_recording import NeonRecording
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeyEvent
from qt_property_widgets.utilities import PersistentPropertiesMixin, property_params

from pupil_labs import neon_player
from pupil_labs.neon_player import GlobalPluginProperties, action

IMMUTABLE_EVENTS = ["recording.begin", "recording.end"]


class EventsPluginGlobalProps(GlobalPluginProperties):
    def __init__(self) -> None:
        super().__init__()
        self._global_event_types: list[str] = []

    @property
    def global_event_types(self) -> list[str]:
        return self._global_event_types

    @global_event_types.setter
    def global_event_types(self, value: list[str]) -> None:
        self._global_event_types = value


class EventType(PersistentPropertiesMixin, QObject):
    changed = Signal()
    name_changed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._name = ""
        self._shortcut = ""
        self._uid = ""

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        old_name = self._name
        self._name = value
        self.name_changed.emit(old_name, value)

    @property
    @property_params(max_length=1)
    def shortcut(self) -> str:
        return self._shortcut

    @shortcut.setter
    def shortcut(self, value: str) -> None:
        self._shortcut = value

    @property
    @property_params(widget=None)
    def uid(self) -> str:
        return self._uid

    @uid.setter
    def uid(self, value: str):
        self._uid = value


class EventsPlugin(neon_player.Plugin):
    label = "Events"
    global_properties = EventsPluginGlobalProps()

    def __init__(self) -> None:
        super().__init__()
        self._event_types: list[EventType] = []
        self.get_timeline_dock().key_pressed.connect(self._on_key_pressed)

    def _on_key_pressed(self, event: QKeyEvent) -> None:
        key_text = event.text().lower()
        if key_text == "":
            return

        for event_type in self._event_types:
            if event_type.shortcut.lower() == key_text:
                self.add_event(event_type)

    def on_recording_loaded(self, recording: NeonRecording) -> None:
        self.events = {}

        try:
            cached_events = self.load_cached_json('events.json')
        except Exception:
            logging.exception("Failed to load events json")
            cached_events = None

        if cached_events is None:
            for event in self.recording.events:
                et = self._create_event_type(str(event.event))
                if event.event in IMMUTABLE_EVENTS:
                    et.uid = str(event.event)

                self.add_event(et, event.time)

            recording_event_names = [et.name for et in self._event_types]
            for event_name in self.global_properties.global_event_types:
                if event_name not in recording_event_names:
                    self._create_event_type(event_name)
        else:
            self.events = cached_events
            for uid in self.events:
                if uid in IMMUTABLE_EVENTS:
                    et = self._create_event_type(uid)
                    et.uid = uid
                else:
                    et = self.get_event_type(uid)

                self._setup_gui_for_event_type(et)
                self._update_timeline_data(et)


        for event_uid in self.events:
            if event_uid in IMMUTABLE_EVENTS:
                continue

            event_type = self.get_event_type(event_uid)
            self._update_timeline_data(event_type)

    def get_event_type(self, uid: str) -> EventType:
        for event_type in self._event_types:
            if event_type.uid == uid:
                return event_type

        raise ValueError(f"Event type with uid {uid} not found")

    def on_disabled(self) -> None:
        if self.recording is None:
            return

        timeline = self.get_timeline_dock()
        timeline.remove_timeline_plot("Events")
        for uid in self.events:
            name = uid if uid in IMMUTABLE_EVENTS else self.get_event_type(uid).name

            timeline.remove_timeline_plot(f"Events/{name}")

    def _setup_gui_for_event_type(self, event_type: EventType) -> None:
        timeline = self.get_timeline_dock()
        existing_plot = timeline.get_timeline_plot(
            f"Events/{event_type.name}", create_if_not_exists=False
        )
        if existing_plot is not None:
            return

        timeline.add_timeline_scatter(f"Events/{event_type.name}", [])
        if event_type.name not in IMMUTABLE_EVENTS:
            action = self.register_timeline_action(
                f"Add Event/{event_type.name}",
                lambda: self.add_event(event_type)
            )
            self.app.main_window.sort_action_menu("Timeline/Add Event")
            event_type.name_changed.connect(lambda old, new: action.setText(new))

        def register_data_actions():
            if event_type.name not in IMMUTABLE_EVENTS:
                self.register_data_point_action(
                    f"Events/{event_type.name}",
                    f"Delete {event_type.name} instance",
                    lambda data_point, et=event_type: self.delete_event_instance(
                        f"Events/{event_type.name}", data_point, et
                    )
                )

            self.register_data_point_action(
                f"Events/{event_type.name}",
                f"Seek to this {event_type.name}",
                self.seek_to_event_instance
            )

        register_data_actions()
        event_type.name_changed.connect(lambda _, _2: register_data_actions())

    def add_event(self, event_type: EventType, ts: int|None = None) -> None:
        if self.recording is None:
            return

        if ts is None:
            ts = self.app.current_ts

        if event_type.uid not in self.events:
            self.events[event_type.uid] = []

        self.events[event_type.uid].append(ts)
        self.save_cached_json('events.json', self.events)
        self._update_timeline_data(event_type)

    def delete_event_instance(self, timeline_name, data_point, event_type) -> None:
        self.events[event_type.uid].remove(data_point[0])

        self.save_cached_json('events.json', self.events)
        self._update_timeline_data(event_type)

    def seek_to_event_instance(self, data_point) -> None:
        self.app.seek_to(data_point[0])

    def _update_timeline_data(self, event_type: EventType) -> None:
        timeline = self.get_timeline_dock()
        event_name = event_type.name
        plot_item = timeline.get_timeline_plot(f"Events/{event_name}", True)

        events = self.events.get(event_type.uid, [])

        if len(plot_item.items) == 0:
            timeline.add_timeline_scatter(
                f"Events/{event_name}",
                np.array([[t, 0] for t in events]),
            )
        else:
            plot_item.items[0].setData(
                np.array([[t, 0] for t in events])
            )

    @property
    @property_params()
    def event_types(self) -> list[EventType]:
        return self._event_types

    @event_types.setter
    def event_types(self, value: list[EventType]) -> None:
        new_event_types = [
            event_type for event_type in value if event_type not in self._event_types
        ]
        removed_event_types = [
            event_type for event_type in self._event_types if event_type not in value
        ]

        for new_event_type in new_event_types:
            if new_event_type.uid == "":
                new_event_type.uid = str(uuid.uuid4())

            event_type_counter = 1
            while new_event_type.name == "":
                candidate_name = f"event-{event_type_counter}"
                if candidate_name not in [s.name for s in self._event_types]:
                    new_event_type.name = candidate_name
                event_type_counter += 1

            self._setup_gui_for_event_type(new_event_type)
            new_event_type.changed.connect(self.changed.emit)
            new_event_type.name_changed.connect(
                lambda old, new, et=new_event_type: self._on_event_name_changed(
                    old, new, et
                )
            )

        for removed_event_type in removed_event_types:
            if removed_event_type.uid in self.events:
                del self.events[removed_event_type.uid]

            self.get_timeline_dock().remove_timeline_plot(
                f"Events/{removed_event_type.name}"
            )
            self.save_cached_json('events.json', self.events)
            self.app.main_window.unregister_action(
                f"Timeline/Add Event/{removed_event_type.name}"
            )

        self._event_types = value

    def _on_event_name_changed(self, old_name, new_name, event_type) -> None:
        self.get_timeline_dock().remove_timeline_plot(f"Events/{old_name}")
        self._update_timeline_data(event_type)

    def _create_event_type(self, event_name: str) -> None:
        event_type = EventType()
        event_type.uid = str(uuid.uuid4())
        event_type._name = event_name

        if event_name in IMMUTABLE_EVENTS:
            self._setup_gui_for_event_type(event_type)
        else:
            self.event_types = [*self._event_types, event_type]

        return event_type

    @action
    def export(self, destination: Path = Path(".")):
        start_time, stop_time = neon_player.instance().recording_settings.export_window
        event_names = []
        for uid in self.events:
            name = uid if uid in IMMUTABLE_EVENTS else self.get_event_type(uid).name
            event_names.append(name)

        events_df = pd.DataFrame({
            "recording id": self.recording.info["recording_id"],
            "timestamp [ns]": list(self.events.values()),
            "event": event_names,
        })

        events_df = events_df.explode("timestamp [ns]").reset_index(drop=True).dropna()
        events_df["timestamp [ns]"] = events_df["timestamp [ns]"].astype(
            self.recording.events.time.dtype
        )
        start_mask = (events_df["timestamp [ns]"] >= start_time)
        stop_mask = (events_df["timestamp [ns]"] <= stop_time)
        events_df = events_df[start_mask & stop_mask]
        events_df.to_csv(destination / "events.csv", index=False)
