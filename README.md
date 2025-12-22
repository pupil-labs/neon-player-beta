# Pupil Labs Neon Player

[![ci](https://github.com/pupil-labs/pl-neon-player/actions/workflows/main.yml/badge.svg)](https://github.com/pupil-labs/pl-neon-player/actions/workflows/main.yml)
[![documentation](https://img.shields.io/badge/docs-mkdocs-708FCC.svg?style=flat)](https://pupil-labs.github.io/pl-neon-player/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre_commit-black?logo=pre-commit&logoColor=FAB041)](https://github.com/pre-commit/pre-commit)
[![pypi version](https://img.shields.io/pypi/v/pupil-labs-neon-player.svg)](https://pypi.org/project/pupil-labs-neon-player/)

# Run from source

```bash
uv venv .venv --python=3.11
source .venv/bin/activate # on Windows use .venv/Scripts/activate
uv sync
python -m pupil_labs.neon_player [path/to/my/recording]
```

# Paths

- Global settings are saved in `$HOME/Pupil Labs/Neon Player/settings.json`
- Per-recording settings are saved in `recording/path/.neon_player/settings.json`
- Plugin cache data is saved in `recording/path/.neon_player/cache/PluginName/`

# Plugin development

- Drop your plugin python file into `$HOME/Pupil Labs/Neon Player/plugins` (you may need to create the directory)
- If your plugin has multiple files, put them in a folder with a `__init__.py` file that either defines your `Plugin` class or imports a module which does. Do not create an instance of your plugin - just define the class which inherits from `pupil_labs.neon_player.Plugin`.
- If your plugin needs python dependencies, list them as [inline script metadata (aka PEP 723)](https://packaging.python.org/en/latest/specifications/inline-script-metadata/#inline-script-metadata). Neon Player will detect these and install them to `$HOME/Pupil Labs/Neon Player/plugins/site-packages` automatically.

To expose a plugin setting to the GUI, define a property with getter/setter functions and appropriate type hints. You can control some options of the parameter GUI widget using th `@property_params` decorator. For example, by defining a `min` and `max`  for `int` or `float` properties, the UI will present a slider.

You can also expose a function to the GUI by using the `@action` decorator. It will appear as a button, with each of its arguments as an input field

```python
from pupil_labs.neon_player import Plugin, action
from PySide6.QtWidgets import QMessageBox
from qt_property_widgets.utilities import property_params

class MyPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self._my_variable = 0.5

    @property
    @property_params(min=-1, max=100, decimals=2)
    def my_variable(self) -> float:
        return self._my_variable

    @my_variable.setter
    def my_variable(self, value: float):
        self._my_variable = value

    @action
    def show_message(self, text: str) -> None:
        QMessageBox.information(None, "Message", text)
```

Long-running actions should be ran as a background job so you don't lock-up the GUI. You can report progress back to the GUI by `yield`ing a `ProgressUpdate`

```python
import logging
import time
import typing as T

from pupil_labs.neon_player import Plugin, ProgressUpdate, action
from PySide6.QtWidgets import QMessageBox


class MyPlugin(Plugin):
    def bg_task(self, count_to: int) -> T.Generator[ProgressUpdate, None, None]:
        for i in range(count_to):
            time.sleep(0.5)
            logging.info(i)
            yield ProgressUpdate(i / count_to)

    @action
    def start_slow_job(self, count_to: int = 5) -> None:
        job = self.job_manager.run_background_action(
            "Slow Job Test", "MyPlugin.bg_task", count_to
        )

        job.finished.connect(lambda: QMessageBox.information(
            None,
            "Attention",
            "Slow job finished!"
        ))
```

# Scripting

Every function defined in a plugin can be scripted from the command line without using the GUI. Please use type hints in your function signature so that arguments can be typcast/coerced for you.

```python
from pupil_labs.neon_player import Plugin

class MyPlugin(Plugin):
    def my_function(self, arg1: int, arg2: str) -> None:
        print(f"arg1 = {arg1}, arg2 = {arg2}")
```

```bash
$EXECUTABLE path/to/my/recording --job MyPlugin.my_function 123 "Hello, World!"
```

Where `$EXECUTABLE` is either `python -m pupil_labs.neon_player` (if running from source) or the path to the compiled binary.

# Mouse control in plots

- Left click and/or drag to scrub
- Drag with the middle mouse to pan
- Shift + scroll zooms the Y axis
- Control + scroll wheel zooms the X axis
- Control + left click+drag zooms to a box you draw
