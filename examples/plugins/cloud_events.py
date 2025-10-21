# /// script
# requires-python = ">=3.10"
# dependencies = [
# "pandas",
# "pupil-labs-neon-recording",
# "numpy",
# "aiohttp",
# ]
# ///
import asyncio
import dataclasses
import datetime
from dataclasses import field

import aiohttp
import numpy as np

from pupil_labs.neon_player import Plugin, action
from pupil_labs.neon_player.plugins.events import IMMUTABLE_EVENTS


@dataclasses.dataclass(frozen=True, order=True)
class Event:
    """Data class to represent a single, immutable event."""

    timestamp_ns: np.int64
    name: str
    type: str = "recording"
    _offset_s: float | None = field(default=None, compare=False)
    _updated_at: datetime.datetime | str | None = field(default=None, compare=False)


async def from_cloud(workspace_id: str, recording_id: str, token: str) -> list[Event]:
    """Create an Events instance from Pupil Cloud."""
    url = f"https://api.cloud.pupil-labs.com/v2/workspaces/{workspace_id}/recordings/{recording_id}/events"
    headers = {"api-key": token}

    async with (
        aiohttp.ClientSession() as session,
        session.get(url, headers=headers) as response,
    ):
        if response.status != 200:
            raise ConnectionError(
                f"Failed to fetch events from Pupil Cloud: {response.status} {response.reason}"
            )
        data = await response.json()

    events_data = data.get("result", [])

    if not events_data:
        return []

    return [
        Event(
            timestamp_ns=np.int64(event["epoch_ns"]),
            name=event["name"],
            type=event.get("origin", "recording"),
            _offset_s=event.get("offset_s"),
            _updated_at=event.get("updated_at", None),
        )
        for event in events_data
    ]


class CloudEventsPlugin(Plugin):
    label = "Cloud Events"

    @action
    def pull_events_from_cloud(self):
        workspace_id = self.app.recording.info.get("workspace_id")
        recording_id = self.app.recording.info.get("recording_id")

        token = self.app.get_secret("PL_CLOUD_TOKEN")
        if not token:
            return  # User was already prompted by get_secret

        events_plugin = self.app.plugins_by_class["EventsPlugin"]

        async def _sync():
            try:
                cloud_events = await from_cloud(workspace_id, recording_id, token)
                for event in cloud_events:
                    if event.name in IMMUTABLE_EVENTS:
                        continue  # Skip immutable events
                    print(
                        f"Fetched event from cloud: {event.name} at {event.timestamp_ns} ns"
                    )
                    for event_type in events_plugin._event_types:
                        if event.name == event_type.name:
                            etype = event_type
                            break
                    else:
                        etype = events_plugin._create_event_type(event.name)
                    events_plugin.add_event(event.name, etype, event.timestamp_ns)
                self.app.show_notification("Success", "Events synced from Pupil Cloud.")
            except Exception as e:
                self.app.show_notification("Error", f"Failed to sync events: {e}")

        asyncio.run(_sync())
