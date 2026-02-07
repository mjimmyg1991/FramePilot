"""Lightroom Subject Crop - Auto-crop photos for vertical formats."""

import sys
from pathlib import Path

__version__ = "0.1.0"


def resource_path(relative_path: str | Path = "") -> Path:
    """Resolve a path to a bundled resource, works both in dev and PyInstaller frozen exe."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent
    return base / relative_path
