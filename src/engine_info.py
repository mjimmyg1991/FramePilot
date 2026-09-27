"""Version details reported by the engine's ``--version`` flag."""

import json
import platform
import sys
from importlib import metadata

from src import __version__, resource_path


BUILD_INFO_PATH = "config/build_info.json"
REPORTED_PACKAGES = ("ultralytics", "torch", "opencv-python", "numpy")


def build_info() -> dict:
    """Read the build details the Windows build writes next to the config.

    Returns:
        Dict with ``commit``, ``ref``, ``run`` and ``date`` keys, or an empty
        dict for a source checkout
    """
    path = resource_path(BUILD_INFO_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def version_text() -> str:
    """Multi-line version report: engine, build, Python and key packages."""
    info = build_info()
    if info:
        build = f"{str(info.get('commit', '?'))[:7]} ({info.get('ref', '?')}, run {info.get('run', '?')}, {info.get('date', '?')})"
    else:
        build = "source checkout"
    frozen = getattr(sys, "frozen", False)
    packages = ", ".join(f"{name} {_package_version(name)}" for name in REPORTED_PACKAGES)
    return "\n".join([
        f"FramePilot engine {__version__}",
        f"Build: {build}",
        f"Python: {platform.python_version()} ({'packaged' if frozen else sys.executable})",
        f"Packages: {packages}",
    ])
