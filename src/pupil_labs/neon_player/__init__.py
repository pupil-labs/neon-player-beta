import functools
import typing as T
from pathlib import Path

import pkg_resources
from qt_property_widgets.utilities import action as object_action

from pupil_labs.neon_player.job_manager import ProgressUpdate
from pupil_labs.neon_player.plugins import Plugin

if T.TYPE_CHECKING:
    from pupil_labs.neon_player.app import NeonPlayerApp

LOG_FORMAT_STRING = (
    "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)


def instance() -> "NeonPlayerApp":
    from pupil_labs.neon_player.app import NeonPlayerApp

    instance = NeonPlayerApp.instance()
    if instance is None or not isinstance(instance, NeonPlayerApp):
        raise RuntimeError()

    return instance


def action(func: T.Callable) -> T.Any:
    @functools.wraps(func)
    def wrapper(*args: T.Any, **kwargs: T.Any) -> T.Any:
        return func(*args, **kwargs)

    return object_action(wrapper)


def asset_path(resource: str) -> Path:
    return Path(pkg_resources.resource_filename(__name__, "assets")) / resource


__all__ = [
    "BGWorker",
    "Plugin",
    "ProgressUpdate",
    "action",
    "instance",
]
