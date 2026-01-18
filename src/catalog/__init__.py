"""Catalog integration modules for various photo management applications."""

from .lightroom import LightroomCatalog
from .darktable import DarktableCatalog
from .capture_one import CaptureOneCatalog

__all__ = ["LightroomCatalog", "DarktableCatalog", "CaptureOneCatalog"]
