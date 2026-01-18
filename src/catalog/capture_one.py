"""Capture One catalog reader.

Capture One uses SQLite databases for catalogs (.cocatalogdb) and sessions (.cosessiondb).
It can also read XMP sidecars for compatibility.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaptureOneImage:
    """Represents an image in Capture One."""

    id: int
    filename: str
    folder_path: str
    rating: int = 0
    color_tag: int = 0

    @property
    def full_path(self) -> Path:
        """Get the full file path."""
        return Path(self.folder_path) / self.filename


@dataclass
class CaptureOneCollection:
    """Represents a collection/album in Capture One."""

    id: int
    name: str
    image_count: int = 0


class CaptureOneCatalog:
    """Read-only interface to a Capture One catalog."""

    def __init__(self, catalog_path: str | Path):
        """Open a Capture One catalog.

        Args:
            catalog_path: Path to .cocatalogdb file
        """
        self.catalog_path = Path(catalog_path)
        if not self.catalog_path.exists():
            raise FileNotFoundError(f"Catalog not found: {catalog_path}")

        # Capture One stores the actual database inside a package/folder
        if self.catalog_path.is_dir():
            # It's a .cocatalog package, find the database inside
            self.db_path = self.catalog_path / "database" / "catalog.cocatalogdb"
            if not self.db_path.exists():
                self.db_path = self.catalog_path / "Catalog.cocatalogdb"
        else:
            self.db_path = self.catalog_path

        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found in catalog: {catalog_path}")

        self._conn: sqlite3.Connection | None = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        """Open the database connection."""
        uri = f"file:{self.db_path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Catalog not open.")
        return self._conn

    def get_all_images(self) -> list[CaptureOneImage]:
        """Get all images in the catalog.

        Note: Capture One's schema varies by version. This is a best-effort implementation.
        """
        # Try different schema patterns
        queries = [
            # Newer Capture One versions
            """
                SELECT
                    i.Z_PK as id,
                    i.ZNAME as filename,
                    f.ZPATH as folder_path
                FROM ZIMAGE i
                LEFT JOIN ZFOLDER f ON i.ZFOLDER = f.Z_PK
                ORDER BY i.ZNAME
            """,
            # Alternative schema
            """
                SELECT
                    id,
                    name as filename,
                    path as folder_path
                FROM images
                ORDER BY name
            """,
        ]

        images = []
        for query in queries:
            try:
                cursor = self.conn.execute(query)
                for row in cursor:
                    images.append(CaptureOneImage(
                        id=row["id"],
                        filename=row["filename"] or "",
                        folder_path=row["folder_path"] or "",
                    ))
                if images:
                    return images
            except sqlite3.OperationalError:
                continue

        return images

    def get_collections(self) -> list[CaptureOneCollection]:
        """Get all collections/albums in the catalog."""
        queries = [
            """
                SELECT
                    Z_PK as id,
                    ZNAME as name
                FROM ZALBUM
                WHERE ZNAME IS NOT NULL
                ORDER BY ZNAME
            """,
            """
                SELECT
                    id,
                    name
                FROM albums
                WHERE name IS NOT NULL
                ORDER BY name
            """,
        ]

        collections = []
        for query in queries:
            try:
                cursor = self.conn.execute(query)
                for row in cursor:
                    collections.append(CaptureOneCollection(
                        id=row["id"],
                        name=row["name"],
                    ))
                if collections:
                    return collections
            except sqlite3.OperationalError:
                continue

        return collections


def find_capture_one_catalogs() -> list[Path]:
    """Find Capture One catalogs in common locations."""
    import os

    catalogs = []
    search_paths = []

    if os.name == "nt":
        # Windows
        user_home = Path.home()
        search_paths.extend([
            user_home / "Pictures" / "Capture One",
            user_home / "Documents" / "Capture One",
            user_home / "Capture One",
        ])
    else:
        # macOS
        user_home = Path.home()
        search_paths.extend([
            user_home / "Pictures" / "Capture One",
            user_home / "Pictures",
        ])

    # Look for .cocatalog packages and .cocatalogdb files
    for search_path in search_paths:
        if search_path.exists():
            for item in search_path.rglob("*.cocatalog"):
                catalogs.append(item)
            for item in search_path.rglob("*.cocatalogdb"):
                catalogs.append(item)

    return sorted(set(catalogs))


# Note: Capture One can import XMP sidecars.
# After processing with this tool:
# 1. In Capture One: File → Import → select images
# 2. Or: Right-click images → "Synchronize Metadata" to reload XMP
