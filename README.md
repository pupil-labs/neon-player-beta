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
uv sync
python -m pupil_labs.neon_player [path/to/my/recording]
```

# Plugin development
* Drop your plugin python file or folder to `$HOME/Pupil Labs/Neon Player/plugins` (you may need to create the directory)
* If you have python dependencies, they can be installed to `plugins/site-packages`. E.g.,
```bash
pip install --target "$HOME/Pupil Labs/Neon Player/plugins/site-packages" my-python-package
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
