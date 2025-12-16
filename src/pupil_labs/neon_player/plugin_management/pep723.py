import logging
import re
import tomllib
import typing as T

logger = logging.getLogger(__name__)


class Pep723Dependencies(T.NamedTuple):
    requires_python: str | None
    dependencies: list[str]


def parse_pep723_dependencies(script: str) -> Pep723Dependencies | None:
    """Parse a code for a PEP 723 dependency block and returns the dependencies."""
    # Regex to find the /// script ... /// block
    match = re.search(
        r"^# /// script\n(.*?)\n^# ///$", script, re.MULTILINE | re.DOTALL
    )
    if not match:
        return None

    # The TOML content is captured in group 1. We need to "un-comment" it.
    toml_lines = []
    for line in match.group(1).splitlines():
        if line.startswith("# "):
            toml_lines.append(line[2:])
        elif line.strip() == "#":
            toml_lines.append("")
        elif not line.strip():
            # empty or whitespace-only lines are ignored
            pass
        else:
            # malformed line
            logger.warning("Malformed line in PEP 723 block: %r", line)
            return None

    toml_content = "\n".join(toml_lines)

    try:
        data = tomllib.loads(toml_content)
    except tomllib.TOMLDecodeError:
        # Invalid TOML
        logger.exception("Failed to parse PEP 723 TOML content: %r", toml_content)
        return None

    return Pep723Dependencies(
        requires_python=data.get("requires-python"),
        dependencies=data.get("dependencies", []),
    )


if __name__ == "__main__":
    from pathlib import Path

    example_script = (
        Path.home() / "Pupil Labs" / "Neon Player" / "plugins" / "face_detect.py"
    )
    script_content = Path(example_script).read_text()
    deps = parse_pep723_dependencies(script_content)
    print(deps)
