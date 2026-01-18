"""darktable catalog/database reader.

darktable stores its library in a SQLite database (library.db or data.db).
It uses XMP sidecars for develop settings, same format as Lightroom.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DarktableImage:
    """Represents an image in the darktable library."""

    id: int
    filename: str
    folder_path: str
    rating: int = 0
    color_label: int = 0

    @property
    def full_path(self) -> Path:
        """Get the full file path."""
        return Path(self.folder_path) / self.filename


@dataclass
class DarktableFilmRoll:
    """Represents a film roll (folder) in darktable."""

    id: int
    folder_path: str
    image_count: int = 0

    @property
    def name(self) -> str:
        return Path(self.folder_path).name


class DarktableCatalog:
    """Read-only interface to a darktable library database."""

    def __init__(self, db_path: str | Path):
        """Open a darktable database.

        Args:
            db_path: Path to library.db or data.db
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

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
            raise RuntimeError("Database not open.")
        return self._conn

    def get_film_rolls(self) -> list[DarktableFilmRoll]:
        """Get all film rolls (folders) in the library."""
        query = """
            SELECT
                fr.id,
                fr.folder,
                COUNT(i.id) as image_count
            FROM film_rolls fr
            LEFT JOIN images i ON i.film_id = fr.id
            GROUP BY fr.id
            HAVING image_count > 0
            ORDER BY fr.folder
        """
        cursor = self.conn.execute(query)
        rolls = []
        for row in cursor:
            rolls.append(DarktableFilmRoll(
                id=row["id"],
                folder_path=row["folder"],
                image_count=row["image_count"],
            ))
        return rolls

    def get_images_in_film_roll(self, film_roll_id: int) -> list[DarktableImage]:
        """Get all images in a film roll."""
        query = """
            SELECT
                i.id,
                i.filename,
                fr.folder as folder_path,
                i.flags
            FROM images i
            JOIN film_rolls fr ON i.film_id = fr.id
            WHERE fr.id = ?
            ORDER BY i.filename
        """
        cursor = self.conn.execute(query, (film_roll_id,))
        images = []
        for row in cursor:
            images.append(DarktableImage(
                id=row["id"],
                filename=row["filename"],
                folder_path=row["folder_path"],
                rating=0,  # darktable stores ratings differently
            ))
        return images

    def get_all_images(self) -> list[DarktableImage]:
        """Get all images in the library."""
        query = """
            SELECT
                i.id,
                i.filename,
                fr.folder as folder_path,
                i.flags
            FROM images i
            JOIN film_rolls fr ON i.film_id = fr.id
            ORDER BY i.filename
        """
        cursor = self.conn.execute(query)
        images = []
        for row in cursor:
            images.append(DarktableImage(
                id=row["id"],
                filename=row["filename"],
                folder_path=row["folder_path"],
            ))
        return images


def find_darktable_database() -> Path | None:
    """Find the darktable library database in common locations."""
    import os

    search_paths = []

    if os.name == "nt":
        # Windows
        appdata = Path(os.environ.get("LOCALAPPDATA", ""))
        if appdata.exists():
            search_paths.append(appdata / "darktable")
        search_paths.append(Path.home() / ".config" / "darktable")
    else:
        # macOS / Linux
        search_paths.append(Path.home() / ".config" / "darktable")

    for search_path in search_paths:
        # darktable uses library.db or data.db depending on version
        for db_name in ["library.db", "data.db"]:
            db_path = search_path / db_name
            if db_path.exists():
                return db_path

    return None


# Note: darktable uses the same XMP sidecar format as Lightroom,
# so our existing xmp_handler.py works without modification.
# Users just need to:
# 1. Process images with this tool
# 2. In darktable: select images → right-click → "Reload XMP"
