"""Tests for Lightroom integration features."""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.catalog.lightroom import LightroomCatalog, is_catalog_locked, CatalogImage
from src.catalog.lightroom_prefs import find_active_catalog, _parse_agprefs
from src.xmp_handler import write_signal_file
from src.watcher import FolderWatcher, WatcherResult, _ImageHandler, SUPPORTED_EXTENSIONS


def _create_test_catalog(db_path: Path) -> None:
    """Create a minimal Lightroom catalog SQLite database for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE AgLibraryRootFolder (
            id_local INTEGER PRIMARY KEY,
            absolutePath TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE AgLibraryFolder (
            id_local INTEGER PRIMARY KEY,
            pathFromRoot TEXT,
            rootFolder INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE AgLibraryFile (
            id_local INTEGER PRIMARY KEY,
            baseName TEXT,
            extension TEXT,
            folder INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE Adobe_images (
            id_local INTEGER PRIMARY KEY,
            rootFile INTEGER,
            rating INTEGER,
            pick INTEGER,
            colorLabels TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE AgLibraryCollection (
            id_local INTEGER PRIMARY KEY,
            name TEXT,
            parent INTEGER,
            creationId TEXT,
            systemOnly INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE AgLibraryCollectionImage (
            collection INTEGER,
            image INTEGER,
            positionInCollection REAL,
            PRIMARY KEY (collection, image)
        )
    """)

    # Insert test data
    conn.execute("INSERT INTO AgLibraryRootFolder VALUES (1, '/photos/')")
    conn.execute("INSERT INTO AgLibraryFolder VALUES (1, 'wedding/', 1)")
    conn.execute("INSERT INTO AgLibraryFile VALUES (1, 'IMG_001', 'jpg', 1)")
    conn.execute("INSERT INTO AgLibraryFile VALUES (2, 'IMG_002', 'jpg', 1)")
    conn.execute("INSERT INTO Adobe_images VALUES (1, 1, 5, 1, '')")
    conn.execute("INSERT INTO Adobe_images VALUES (2, 2, 3, 0, '')")

    conn.commit()
    conn.close()


class TestLightroomCatalogWrite:
    """Tests for Lightroom catalog write operations."""

    def test_create_collection(self, tmp_path):
        db_path = tmp_path / "test.lrcat"
        _create_test_catalog(db_path)

        catalog = LightroomCatalog(db_path)
        catalog.open(readonly=False)

        coll_id = catalog.create_collection("FramePilot Test")
        assert coll_id > 0

        # Verify collection exists
        collections = catalog.get_collections()
        names = [c.name for c in collections]
        assert "FramePilot Test" in names

        catalog.close()

    def test_add_images_to_collection(self, tmp_path):
        db_path = tmp_path / "test.lrcat"
        _create_test_catalog(db_path)

        catalog = LightroomCatalog(db_path)
        catalog.open(readonly=False)

        coll_id = catalog.create_collection("Test Collection")
        added = catalog.add_images_to_collection(coll_id, [1, 2])
        assert added == 2

        # Verify images in collection
        images = catalog.get_images_in_collection(coll_id)
        assert len(images) == 2

        catalog.close()

    def test_create_collection_readonly_raises(self, tmp_path):
        db_path = tmp_path / "test.lrcat"
        _create_test_catalog(db_path)

        catalog = LightroomCatalog(db_path)
        catalog.open(readonly=True)

        with pytest.raises(RuntimeError, match="read-only"):
            catalog.create_collection("Should Fail")

        catalog.close()

    def test_get_image_id_by_path(self, tmp_path):
        db_path = tmp_path / "test.lrcat"
        _create_test_catalog(db_path)

        catalog = LightroomCatalog(db_path)
        catalog.open()

        img_id = catalog.get_image_id_by_path(Path("/photos/wedding/IMG_001.jpg"))
        assert img_id == 1

        missing = catalog.get_image_id_by_path(Path("/photos/wedding/MISSING.jpg"))
        assert missing is None

        catalog.close()

    def test_duplicate_add_to_collection(self, tmp_path):
        db_path = tmp_path / "test.lrcat"
        _create_test_catalog(db_path)

        catalog = LightroomCatalog(db_path)
        catalog.open(readonly=False)

        coll_id = catalog.create_collection("Dupes")
        catalog.add_images_to_collection(coll_id, [1])
        # Add again — should not raise
        added = catalog.add_images_to_collection(coll_id, [1])
        assert added == 1  # INSERT OR IGNORE

        catalog.close()


class TestCatalogLockCheck:
    """Tests for catalog lock detection."""

    def test_no_lock_file(self, tmp_path):
        db_path = tmp_path / "test.lrcat"
        _create_test_catalog(db_path)
        assert not is_catalog_locked(db_path)

    def test_lock_file_present(self, tmp_path):
        db_path = tmp_path / "test.lrcat"
        _create_test_catalog(db_path)
        lock_path = tmp_path / "test.lrcat.lock"
        lock_path.touch()
        assert is_catalog_locked(db_path)


class TestSignalFile:
    """Tests for the plugin signal file mechanism."""

    def test_write_signal_file(self, tmp_path):
        paths = [
            tmp_path / "IMG_001.jpg",
            tmp_path / "IMG_002.jpg",
        ]
        signal_path = write_signal_file(paths, tmp_path)

        assert signal_path.exists()
        assert signal_path.name == ".framepilot_ready"

        content = signal_path.read_text()
        assert "IMG_001.jpg" in content
        assert "IMG_002.jpg" in content
        lines = content.strip().split("\n")
        assert len(lines) == 2

    def test_signal_file_overwrites(self, tmp_path):
        paths1 = [tmp_path / "a.jpg"]
        paths2 = [tmp_path / "b.jpg", tmp_path / "c.jpg"]

        write_signal_file(paths1, tmp_path)
        write_signal_file(paths2, tmp_path)

        content = (tmp_path / ".framepilot_ready").read_text()
        assert "a.jpg" not in content
        assert "b.jpg" in content


class TestLightroomPrefs:
    """Tests for Lightroom preferences parsing."""

    def test_find_active_catalog_returns_none_on_missing_prefs(self):
        # Should gracefully return None when prefs don't exist
        result = find_active_catalog()
        assert result is None or isinstance(result, Path)

    def test_parse_agprefs_with_catalog_path(self, tmp_path):
        # Create a mock agprefs file
        catalog_path = tmp_path / "test.lrcat"
        _create_test_catalog(catalog_path)

        prefs_path = tmp_path / "Preferences.agprefs"
        prefs_path.write_text(f'''
            catalog_lastOpened = "{catalog_path}"
            recentCatalogs = {{
                "{catalog_path}",
            }}
        ''')

        result = _parse_agprefs(prefs_path)
        assert result == catalog_path

    def test_parse_agprefs_nonexistent_path(self, tmp_path):
        prefs_path = tmp_path / "Preferences.agprefs"
        prefs_path.write_text('catalog_lastOpened = "/nonexistent/path.lrcat"')

        result = _parse_agprefs(prefs_path)
        assert result is None


class TestFolderWatcher:
    """Tests for the folder watcher module."""

    def test_supported_extensions(self):
        assert ".jpg" in SUPPORTED_EXTENSIONS
        assert ".jpeg" in SUPPORTED_EXTENSIONS
        assert ".cr2" in SUPPORTED_EXTENSIONS
        assert ".txt" not in SUPPORTED_EXTENSIONS

    def test_image_handler_filters_non_images(self):
        received = []
        handler = _ImageHandler(on_new_file=lambda p: received.append(p))

        from watchdog.events import FileCreatedEvent
        handler.on_created(FileCreatedEvent("/test/file.txt"))
        assert len(received) == 0

    def test_image_handler_accepts_images(self):
        received = []
        handler = _ImageHandler(on_new_file=lambda p: received.append(p))

        from watchdog.events import FileCreatedEvent
        handler.on_created(FileCreatedEvent("/test/photo.jpg"))
        assert len(received) == 1
        assert received[0] == Path("/test/photo.jpg")

    def test_image_handler_debounce(self):
        received = []
        handler = _ImageHandler(on_new_file=lambda p: received.append(p), debounce_seconds=10.0)

        from watchdog.events import FileCreatedEvent
        handler.on_created(FileCreatedEvent("/test/photo.jpg"))
        handler.on_created(FileCreatedEvent("/test/photo.jpg"))
        assert len(received) == 1  # Second event debounced

    def test_watcher_init(self, tmp_path):
        watcher = FolderWatcher(watch_dir=tmp_path)
        assert not watcher.is_running
        assert watcher.processed_count == 0

    def test_watcher_invalid_dir_raises(self):
        watcher = FolderWatcher(watch_dir="/nonexistent/path")
        with pytest.raises(ValueError, match="does not exist"):
            watcher.start()

    def test_watcher_start_stop(self, tmp_path):
        watcher = FolderWatcher(watch_dir=tmp_path)
        watcher.start()
        assert watcher.is_running
        watcher.stop()
        assert not watcher.is_running


class TestWatcherResult:
    """Tests for the WatcherResult dataclass."""

    def test_defaults(self):
        result = WatcherResult(file_path=Path("/test.jpg"), status="success")
        assert result.xmp_path is None
        assert result.error_message == ""

    def test_with_xmp(self):
        result = WatcherResult(
            file_path=Path("/test.jpg"),
            status="success",
            xmp_path=Path("/test.jpg.xmp"),
        )
        assert result.xmp_path == Path("/test.jpg.xmp")
