"""Catalog integration modules for various photo management applications."""

from .lightroom import LightroomCatalog, is_catalog_locked
from .lightroom_prefs import find_active_catalog
from .darktable import DarktableCatalog
from .capture_one import CaptureOneCatalog

__all__ = [
    "LightroomCatalog", "is_catalog_locked", "find_active_catalog",
    "DarktableCatalog", "CaptureOneCatalog",
]
