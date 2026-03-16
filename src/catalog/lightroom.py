"""Lightroom Classic catalog reader.

Lightroom Classic stores its catalog in a SQLite database (.lrcat file).
This module provides read-only access to browse photos, folders, and collections.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class CatalogImage:
    """Represents an image in the catalog."""

    id: int
    filename: str
    folder_path: str
    extension: str
    rating: int = 0
    pick_status: int = 0  # -1=rejected, 0=unflagged, 1=picked
    color_label: str = ""

    @property
    def full_path(self) -> Path:
        """Get the full file path."""
        return Path(self.folder_path) / f"{self.filename}.{self.extension}"

    @property
    def is_picked(self) -> bool:
        return self.pick_status == 1

    @property
    def is_rejected(self) -> bool:
        return self.pick_status == -1


@dataclass
class CatalogFolder:
    """Represents a folder in the catalog."""

    id: int
    name: str
    full_path: str
    image_count: int = 0


@dataclass
class CatalogCollection:
    """Represents a collection in the catalog."""

    id: int
    name: str
    parent_id: int | None = None
    image_count: int = 0
    is_smart: bool = False


class LightroomCatalog:
    """Interface to a Lightroom Classic catalog."""

    def __init__(self, catalog_path: str | Path):
        """Open a Lightroom catalog.

        Args:
            catalog_path: Path to the .lrcat file
        """
        self.catalog_path = Path(catalog_path)
        if not self.catalog_path.exists():
            raise FileNotFoundError(f"Catalog not found: {catalog_path}")

        if self.catalog_path.suffix.lower() != ".lrcat":
            raise ValueError(f"Not a Lightroom catalog: {catalog_path}")

        self._conn: sqlite3.Connection | None = None
        self._readonly: bool = True

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self, readonly: bool = True):
        """Open the database connection.

        Args:
            readonly: If True, open in read-only mode. Set to False for write operations.
        """
        self._readonly = readonly
        if readonly:
            uri = f"file:{self.catalog_path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
        else:
            self._conn = sqlite3.connect(str(self.catalog_path))
        self._conn.row_factory = sqlite3.Row

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Catalog not open. Call open() first or use context manager.")
        return self._conn

    def get_catalog_name(self) -> str:
        """Get the catalog filename without extension."""
        return self.catalog_path.stem

    def get_image_count(self) -> int:
        """Get total number of images in catalog."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM Adobe_images")
        return cursor.fetchone()[0]

    def get_folders(self) -> list[CatalogFolder]:
        """Get all folders in the catalog."""
        query = """
            SELECT
                f.id_local as id,
                f.pathFromRoot as name,
                r.absolutePath || f.pathFromRoot as full_path,
                COUNT(i.id_local) as image_count
            FROM AgLibraryFolder f
            JOIN AgLibraryRootFolder r ON f.rootFolder = r.id_local
            LEFT JOIN AgLibraryFile fi ON fi.folder = f.id_local
            LEFT JOIN Adobe_images i ON i.rootFile = fi.id_local
            GROUP BY f.id_local
            HAVING image_count > 0
            ORDER BY full_path
        """
        cursor = self.conn.execute(query)
        folders = []
        for row in cursor:
            folders.append(CatalogFolder(
                id=row["id"],
                name=row["name"].rstrip("/\\"),
                full_path=row["full_path"].rstrip("/\\"),
                image_count=row["image_count"],
            ))
        return folders

    def get_collections(self) -> list[CatalogCollection]:
        """Get all collections in the catalog."""
        query = """
            SELECT
                c.id_local as id,
                c.name,
                c.parent as parent_id,
                c.creationId,
                COUNT(ci.image) as image_count
            FROM AgLibraryCollection c
            LEFT JOIN AgLibraryCollectionImage ci ON ci.collection = c.id_local
            WHERE c.creationId != 'com.adobe.ag.library.smart_collection'
            GROUP BY c.id_local
            ORDER BY c.name
        """
        cursor = self.conn.execute(query)
        collections = []
        for row in cursor:
            collections.append(CatalogCollection(
                id=row["id"],
                name=row["name"],
                parent_id=row["parent_id"],
                image_count=row["image_count"],
                is_smart=False,
            ))
        return collections

    def get_smart_collections(self) -> list[CatalogCollection]:
        """Get all smart collections in the catalog."""
        query = """
            SELECT
                c.id_local as id,
                c.name,
                c.parent as parent_id
            FROM AgLibraryCollection c
            WHERE c.creationId = 'com.adobe.ag.library.smart_collection'
            ORDER BY c.name
        """
        cursor = self.conn.execute(query)
        collections = []
        for row in cursor:
            collections.append(CatalogCollection(
                id=row["id"],
                name=row["name"],
                parent_id=row["parent_id"],
                image_count=0,  # Smart collections are dynamic
                is_smart=True,
            ))
        return collections

    def get_images_in_folder(self, folder_id: int) -> list[CatalogImage]:
        """Get all images in a specific folder."""
        query = """
            SELECT
                i.id_local as id,
                fi.baseName as filename,
                r.absolutePath || fo.pathFromRoot as folder_path,
                fi.extension,
                i.rating,
                i.pick,
                i.colorLabels
            FROM Adobe_images i
            JOIN AgLibraryFile fi ON i.rootFile = fi.id_local
            JOIN AgLibraryFolder fo ON fi.folder = fo.id_local
            JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
            WHERE fo.id_local = ?
            ORDER BY fi.baseName
        """
        cursor = self.conn.execute(query, (folder_id,))
        return self._rows_to_images(cursor)

    def get_images_in_collection(self, collection_id: int) -> list[CatalogImage]:
        """Get all images in a specific collection."""
        query = """
            SELECT
                i.id_local as id,
                fi.baseName as filename,
                r.absolutePath || fo.pathFromRoot as folder_path,
                fi.extension,
                i.rating,
                i.pick,
                i.colorLabels
            FROM AgLibraryCollectionImage ci
            JOIN Adobe_images i ON ci.image = i.id_local
            JOIN AgLibraryFile fi ON i.rootFile = fi.id_local
            JOIN AgLibraryFolder fo ON fi.folder = fo.id_local
            JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
            WHERE ci.collection = ?
            ORDER BY ci.positionInCollection
        """
        cursor = self.conn.execute(query, (collection_id,))
        return self._rows_to_images(cursor)

    def get_recent_imports(self, limit: int = 100) -> list[CatalogImage]:
        """Get recently imported images."""
        query = """
            SELECT
                i.id_local as id,
                fi.baseName as filename,
                r.absolutePath || fo.pathFromRoot as folder_path,
                fi.extension,
                i.rating,
                i.pick,
                i.colorLabels
            FROM Adobe_images i
            JOIN AgLibraryFile fi ON i.rootFile = fi.id_local
            JOIN AgLibraryFolder fo ON fi.folder = fo.id_local
            JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
            ORDER BY i.id_local DESC
            LIMIT ?
        """
        cursor = self.conn.execute(query, (limit,))
        return self._rows_to_images(cursor)

    def get_picked_images(self) -> list[CatalogImage]:
        """Get all flagged/picked images."""
        query = """
            SELECT
                i.id_local as id,
                fi.baseName as filename,
                r.absolutePath || fo.pathFromRoot as folder_path,
                fi.extension,
                i.rating,
                i.pick,
                i.colorLabels
            FROM Adobe_images i
            JOIN AgLibraryFile fi ON i.rootFile = fi.id_local
            JOIN AgLibraryFolder fo ON fi.folder = fo.id_local
            JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
            WHERE i.pick = 1
            ORDER BY fi.baseName
        """
        cursor = self.conn.execute(query)
        return self._rows_to_images(cursor)

    def get_images_by_rating(self, min_rating: int = 1) -> list[CatalogImage]:
        """Get images with at least the specified rating."""
        query = """
            SELECT
                i.id_local as id,
                fi.baseName as filename,
                r.absolutePath || fo.pathFromRoot as folder_path,
                fi.extension,
                i.rating,
                i.pick,
                i.colorLabels
            FROM Adobe_images i
            JOIN AgLibraryFile fi ON i.rootFile = fi.id_local
            JOIN AgLibraryFolder fo ON fi.folder = fo.id_local
            JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
            WHERE i.rating >= ?
            ORDER BY i.rating DESC, fi.baseName
        """
        cursor = self.conn.execute(query, (min_rating,))
        return self._rows_to_images(cursor)

    def search_images(self, filename_pattern: str) -> list[CatalogImage]:
        """Search for images by filename pattern (SQL LIKE syntax)."""
        query = """
            SELECT
                i.id_local as id,
                fi.baseName as filename,
                r.absolutePath || fo.pathFromRoot as folder_path,
                fi.extension,
                i.rating,
                i.pick,
                i.colorLabels
            FROM Adobe_images i
            JOIN AgLibraryFile fi ON i.rootFile = fi.id_local
            JOIN AgLibraryFolder fo ON fi.folder = fo.id_local
            JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
            WHERE fi.baseName LIKE ?
            ORDER BY fi.baseName
        """
        cursor = self.conn.execute(query, (filename_pattern,))
        return self._rows_to_images(cursor)

    def get_image_id_by_path(self, file_path: Path) -> int | None:
        """Look up a catalog image ID by its file path.

        Args:
            file_path: Full path to the image file

        Returns:
            The image id_local, or None if not found
        """
        folder_path = str(file_path.parent).rstrip("/\\")
        basename = file_path.stem

        query = """
            SELECT i.id_local as id
            FROM Adobe_images i
            JOIN AgLibraryFile fi ON i.rootFile = fi.id_local
            JOIN AgLibraryFolder fo ON fi.folder = fo.id_local
            JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
            WHERE fi.baseName = ?
            AND (r.absolutePath || fo.pathFromRoot) LIKE ?
            LIMIT 1
        """
        cursor = self.conn.execute(query, (basename, f"%{folder_path}%"))
        row = cursor.fetchone()
        return row["id"] if row else None

    def create_collection(self, name: str) -> int:
        """Create a new collection in the catalog.

        Requires the catalog to be opened in write mode (readonly=False).
        Lightroom must NOT be running or the database will be locked.

        Args:
            name: Name for the new collection

        Returns:
            The id_local of the new collection

        Raises:
            RuntimeError: If the catalog is opened in read-only mode
        """
        if self._readonly:
            raise RuntimeError("Catalog opened in read-only mode. Use open(readonly=False) for write operations.")

        # Get the next available id
        cursor = self.conn.execute("SELECT MAX(id_local) as max_id FROM AgLibraryCollection")
        row = cursor.fetchone()
        next_id = (row["max_id"] or 0) + 1

        self.conn.execute(
            """INSERT INTO AgLibraryCollection
               (id_local, name, creationId, systemOnly)
               VALUES (?, ?, 'com.adobe.ag.library.collection', 0)""",
            (next_id, name),
        )
        self.conn.commit()
        return next_id

    def add_images_to_collection(self, collection_id: int, image_ids: list[int]) -> int:
        """Add images to an existing collection.

        Args:
            collection_id: The collection id_local
            image_ids: List of image id_local values to add

        Returns:
            Number of images successfully added
        """
        if self._readonly:
            raise RuntimeError("Catalog opened in read-only mode.")

        added = 0
        # Get current max position
        cursor = self.conn.execute(
            "SELECT MAX(positionInCollection) as max_pos FROM AgLibraryCollectionImage WHERE collection = ?",
            (collection_id,),
        )
        row = cursor.fetchone()
        position = (row["max_pos"] or 0) + 1

        for image_id in image_ids:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO AgLibraryCollectionImage
                       (collection, image, positionInCollection)
                       VALUES (?, ?, ?)""",
                    (collection_id, image_id, position),
                )
                position += 1
                added += 1
            except sqlite3.IntegrityError:
                continue

        self.conn.commit()
        return added

    def _rows_to_images(self, cursor) -> list[CatalogImage]:
        """Convert database rows to CatalogImage objects."""
        images = []
        for row in cursor:
            images.append(CatalogImage(
                id=row["id"],
                filename=row["filename"],
                folder_path=row["folder_path"].rstrip("/\\"),
                extension=row["extension"],
                rating=row["rating"] or 0,
                pick_status=row["pick"] or 0,
                color_label=row["colorLabels"] or "",
            ))
        return images


def is_catalog_locked(catalog_path: str | Path) -> bool:
    """Check if a Lightroom catalog is locked by another process.

    Args:
        catalog_path: Path to the .lrcat file

    Returns:
        True if the catalog appears to be locked
    """
    catalog_path = Path(catalog_path)
    lock_file = catalog_path.with_suffix(".lrcat.lock")
    if lock_file.exists():
        return True

    # Also check for WAL lock
    wal_file = catalog_path.with_suffix(".lrcat-wal")
    if wal_file.exists():
        try:
            conn = sqlite3.connect(str(catalog_path), timeout=1)
            conn.execute("BEGIN EXCLUSIVE")
            conn.rollback()
            conn.close()
            return False
        except sqlite3.OperationalError:
            return True

    return False


def find_lightroom_catalogs() -> list[Path]:
    """Find Lightroom catalogs in common locations."""
    import os

    catalogs = []

    # Common Lightroom catalog locations
    search_paths = []

    # Windows
    if os.name == "nt":
        user_home = Path.home()
        search_paths.extend([
            user_home / "Pictures" / "Lightroom",
            user_home / "Documents" / "Lightroom",
            user_home / "Lightroom",
        ])
        # Also check OneDrive
        onedrive = user_home / "OneDrive"
        if onedrive.exists():
            search_paths.extend([
                onedrive / "Pictures" / "Lightroom",
                onedrive / "Lightroom",
            ])
    else:
        # macOS / Linux
        user_home = Path.home()
        search_paths.extend([
            user_home / "Pictures" / "Lightroom",
            user_home / "Documents" / "Lightroom",
        ])

    # Search for .lrcat files
    for search_path in search_paths:
        if search_path.exists():
            for lrcat in search_path.rglob("*.lrcat"):
                # Skip lock files and previews
                if "-wal" not in lrcat.name and "-shm" not in lrcat.name:
                    catalogs.append(lrcat)

    return sorted(set(catalogs))
