"""Read Lightroom Classic preferences to find the active catalog."""

import os
import sys
from pathlib import Path
from xml.etree import ElementTree


def find_active_catalog() -> Path | None:
    """Find the most recently opened Lightroom Classic catalog.

    Reads Lightroom's preferences/agprefs files to determine which catalog
    was last opened. Falls back to None if preferences cannot be found or parsed.

    Returns:
        Path to the active .lrcat file, or None if not found
    """
    prefs_files = _find_preferences_files()

    for prefs_path in prefs_files:
        catalog_path = _parse_preferences_file(prefs_path)
        if catalog_path and catalog_path.exists():
            return catalog_path

    return None


def _find_preferences_files() -> list[Path]:
    """Locate Lightroom Classic preference files on the current platform."""
    paths = []

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            lr_prefs_dir = Path(appdata) / "Adobe" / "Lightroom"
            if lr_prefs_dir.exists():
                # Find all .agprefs files, sorted by modification time (newest first)
                agprefs = sorted(
                    lr_prefs_dir.glob("*Preferences*.agprefs"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                paths.extend(agprefs)

    elif sys.platform == "darwin":
        home = Path.home()
        # Modern Lightroom Classic preferences
        lr_prefs_dir = home / "Library" / "Preferences"
        if lr_prefs_dir.exists():
            # Look for com.adobe.LightroomClassicCC*.plist or agprefs
            for pattern in ["com.adobe.Lightroom*.plist", "com.adobe.LightroomClassic*.plist"]:
                plists = sorted(
                    lr_prefs_dir.glob(pattern),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                paths.extend(plists)

        # Also check Application Support for agprefs
        app_support = home / "Library" / "Application Support" / "Adobe" / "Lightroom"
        if app_support.exists():
            agprefs = sorted(
                app_support.glob("*Preferences*.agprefs"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            paths.extend(agprefs)

    else:
        # Linux: check common Wine/Proton paths or any config
        home = Path.home()
        try:
            username = os.getlogin()
        except OSError:
            username = os.environ.get("USER", os.environ.get("LOGNAME", "user"))
        wine_appdata = home / ".wine" / "drive_c" / "users" / username / "AppData" / "Roaming" / "Adobe" / "Lightroom"
        if wine_appdata.exists():
            paths.extend(sorted(
                wine_appdata.glob("*Preferences*.agprefs"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            ))

    return paths


def _parse_preferences_file(prefs_path: Path) -> Path | None:
    """Extract the last-opened catalog path from a Lightroom preferences file.

    Args:
        prefs_path: Path to the preferences file (.agprefs or .plist)

    Returns:
        Path to the .lrcat catalog file, or None
    """
    try:
        if prefs_path.suffix.lower() == ".plist":
            return _parse_plist(prefs_path)
        elif prefs_path.suffix.lower() == ".agprefs":
            return _parse_agprefs(prefs_path)
    except Exception:
        pass
    return None


def _parse_agprefs(prefs_path: Path) -> Path | None:
    """Parse an .agprefs XML file for the last catalog path.

    The .agprefs format is Lua-serialized data. We search for catalog path patterns.
    """
    content = prefs_path.read_text(encoding="utf-8", errors="ignore")

    # Look for recentCatalogs entries or catalog_lastOpened
    # Pattern: a line containing a path ending in .lrcat
    import re

    # Try structured patterns first
    for pattern in [
        r'catalog_lastOpened\s*=\s*["\'](.+?\.lrcat)["\']',
        r'recentCatalogs.*?["\'](.+?\.lrcat)["\']',
        r'["\'](.+?\.lrcat)["\']',
    ]:
        matches = re.findall(pattern, content, re.DOTALL)
        if matches:
            # Return the first valid path
            for match in matches:
                path = Path(match)
                if path.exists():
                    return path

    return None


def _parse_plist(prefs_path: Path) -> Path | None:
    """Parse a macOS .plist file for the last catalog path."""
    try:
        import plistlib
        with open(prefs_path, "rb") as f:
            plist_data = plistlib.load(f)

        # Look for catalog path keys
        for key in ["catalog_lastOpened", "recentCatalogs", "lastCatalog"]:
            value = plist_data.get(key)
            if isinstance(value, str):
                path = Path(value)
                if path.exists() and path.suffix.lower() == ".lrcat":
                    return path
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        path = Path(item)
                        if path.exists() and path.suffix.lower() == ".lrcat":
                            return path

    except Exception:
        pass

    # Fallback: try XML parsing
    try:
        tree = ElementTree.parse(prefs_path)
        root = tree.getroot()
        # Search all string values for .lrcat paths
        for elem in root.iter("string"):
            if elem.text and elem.text.endswith(".lrcat"):
                path = Path(elem.text)
                if path.exists():
                    return path
    except Exception:
        pass

    return None
