import logging
import subprocess  # noqa: S404
from pathlib import Path

from PySide6.QtCore import QObject, Signal

SITE_PACKAGES_DIR = (
    Path.home() / "Pupil Labs" / "Neon Player" / "plugins" / "site-packages"
)


def install_dependencies(dependencies: list[str]):
    """Install dependencies into the shared site-packages directory using uv."""
    if not dependencies:
        logging.info("No new dependencies to install.")
        return

    logging.info(f"Installing dependencies to {SITE_PACKAGES_DIR}: {dependencies}")
    SITE_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        "uv",
        "pip",
        "install",
        f"--target={SITE_PACKAGES_DIR}",
        *dependencies,
    ]

    try:
        result = subprocess.run(  # noqa: S603
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        logging.info(result.stdout)
        logging.info("Successfully installed dependencies.")
    except subprocess.CalledProcessError as e:
        logging.exception(f"Failed to install dependencies. Error: {e.stderr}")
        raise


class InstallationWorker(QObject):
    progress = Signal(float, str)  # progress (0-1), message
    finished = Signal(bool)  # success

    def __init__(self, dependencies_to_install: list[str]):
        super().__init__()
        self.dependencies_to_install = dependencies_to_install

    def run(self):
        num_deps = len(self.dependencies_to_install)
        self.progress.emit(0.0, f"Installing {num_deps} package(s)...")
        try:
            install_dependencies(self.dependencies_to_install)
            self.progress.emit(1.0, "Installation complete.")
            self.finished.emit(True)
        except Exception:
            logging.exception("Failed to install dependencies:")
            self.progress.emit(1.0, "Error during installation.")
            self.finished.emit(False)
