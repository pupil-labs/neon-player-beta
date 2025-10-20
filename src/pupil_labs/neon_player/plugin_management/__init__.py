import importlib.metadata
import logging
import re
import typing as T
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from ..ui.plugin_installation_dialog import PluginInstallationDialog
from .pep723 import parse_pep723_dependencies

SITE_PACKAGES_DIR = (
    Path.home() / "Pupil Labs" / "Neon Player" / "plugins" / "site-packages"
)


def get_installed_packages() -> set[str]:
    """Get a set of installed package names in the shared site-packages."""
    SITE_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return {
            dist.metadata["name"].lower()
            for dist in importlib.metadata.distributions(path=[str(SITE_PACKAGES_DIR)])
        }
    except Exception:
        logging.warning("Could not list installed packages in plugin site-packages.")
        return set()


def check_and_install_dependencies_for_plugins(plugin_path: Path) -> None:
    """Scan a plugin, find their dependencies, and install missing ones."""
    all_deps_to_install = set()
    all_dep_names = set()

    path_to_read = plugin_path
    if plugin_path.is_dir():
        path_to_read = plugin_path / "__init__.py"
    if not path_to_read.exists():
        logging.warning(f"Plugin file on {path_to_read} does not exist.")
        return

    try:
        script = path_to_read.read_text(encoding="utf-8")
        deps = parse_pep723_dependencies(script)
        if deps:
            for dep_string in deps.dependencies:
                all_deps_to_install.add(dep_string)
                match = re.match(r"^[a-zA-Z0-9-_]+", dep_string)
                if match:
                    all_dep_names.add(match.group(0).lower())
    except Exception:
        logging.exception(f"Could not parse dependencies for {plugin_path.name}")

    if not all_deps_to_install:
        return  # No dependencies to check

    installed_packages = get_installed_packages()
    missing_dep_names = all_dep_names - installed_packages

    if not missing_dep_names:
        return  # All dependencies are satisfied

    deps_to_install_filtered = sorted([
        full_dep
        for full_dep in all_deps_to_install
        if re.match(r"^[a-zA-Z0-9-_]+", full_dep).group(0).lower() in missing_dep_names
    ])

    logging.info(f"Found missing plugin dependencies: {deps_to_install_filtered}")

    if not QApplication.instance():
        logging.error("QApplication not running, cannot show installation dialog.")
        return

    dialog = PluginInstallationDialog(
        deps_to_install_filtered, plugin_req=plugin_path.name
    )
    result = dialog.exec()

    if result == QDialog.Accepted:
        logging.info("Plugin dependencies installed successfully.")
    else:
        logging.warning("Plugin dependency installation was cancelled or failed.")
