"""Scrollable thumbnail grid widget for batch crop preview."""

import threading
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
from PIL import Image, ImageTk

from ..crop_calculator import CropRegion


# Brand colors (matching main_window.py)
BRAND_COLORS = {
    "orange": "#FF6B35",
    "orange_dim": "#E55A2B",
    "bg_primary": "#0A0A0B",
    "bg_secondary": "#111113",
    "bg_tertiary": "#1A1A1D",
    "bg_card": "#151517",
    "border": "#2A2A2E",
    "text_primary": "#FFFFFF",
    "text_secondary": "#A0A0A5",
    "text_dim": "#6B6B70",
    "success": "#22C55E",
    "error": "#EF4444",
}


@dataclass
class ThumbnailItem:
    """Data for a single thumbnail."""

    path: Path
    crop: CropRegion | None
    status: str  # "pending", "processing", "success", "no_subject", "error"
    thumbnail: ImageTk.PhotoImage | None = None
    excluded: bool = False


class ThumbnailGrid(ctk.CTkScrollableFrame):
    """Scrollable grid displaying cropped thumbnail previews."""

    THUMB_SIZE = 100  # Thumbnail dimension (smaller = faster)
    THUMB_PADDING = 4
    COLUMNS = 5  # More columns
    MAX_CONCURRENT_LOADS = 2  # Fewer concurrent loads = less lag

    def __init__(
        self,
        parent,
        on_select: Callable[[int], None] | None = None,
        **kwargs
    ):
        super().__init__(parent, fg_color=BRAND_COLORS["bg_card"], **kwargs)

        self._on_select = on_select
        self._items: list[ThumbnailItem] = []
        self._selected_index: int = -1
        self._thumbnail_frames: list[ctk.CTkFrame] = []
        self._thumbnail_labels: list[ctk.CTkLabel] = []
        self._status_dots: list[ctk.CTkLabel] = []
        self._excluded_overlays: list[ctk.CTkLabel | None] = []

        # Throttled thumbnail loading
        self._load_queue: queue.Queue = queue.Queue()
        self._active_loaders = 0
        self._loader_lock = threading.Lock()
        self._pending_rebuild = False

        # Configure grid columns
        for col in range(self.COLUMNS):
            self.grid_columnconfigure(col, weight=1, uniform="thumb")

    def set_items(self, items: list[dict[str, Any]]) -> None:
        """Set items to display.

        Args:
            items: List of queue item dicts with 'path', 'status', 'result', 'crop_override' keys
        """
        self._items = []
        for item in items:
            result = item.get("result")
            crop = item.get("crop_override")
            if crop is None and result is not None:
                crop = result.crop

            self._items.append(ThumbnailItem(
                path=item["path"],
                crop=crop,
                status=item["status"],
                excluded=item.get("excluded", False)
            ))

        self._rebuild_grid()
        # Only load thumbnails for items that have crops (processed)
        self._load_processed_thumbnails()

    def update_item(self, index: int, item: dict[str, Any]) -> None:
        """Update a single item (e.g., after processing)."""
        if 0 <= index < len(self._items):
            result = item.get("result")
            crop = item.get("crop_override")
            if crop is None and result is not None:
                crop = result.crop

            old_crop = self._items[index].crop
            self._items[index] = ThumbnailItem(
                path=item["path"],
                crop=crop,
                status=item["status"],
                excluded=item.get("excluded", False)
            )
            self._update_status_dot(index)
            self._update_excluded_overlay(index)

            # Only load thumbnail if crop changed (newly processed)
            if crop is not None and old_crop is None:
                self._load_single_thumbnail(index)

    def set_selected(self, index: int) -> None:
        """Set the selected item."""
        old_index = self._selected_index
        self._selected_index = index

        # Update visual selection
        if 0 <= old_index < len(self._thumbnail_frames):
            self._thumbnail_frames[old_index].configure(
                border_width=0,
                border_color=BRAND_COLORS["bg_tertiary"]
            )
        if 0 <= index < len(self._thumbnail_frames):
            self._thumbnail_frames[index].configure(
                border_width=3,
                border_color=BRAND_COLORS["orange"]
            )

    def clear(self) -> None:
        """Clear all items."""
        self._items.clear()
        self._selected_index = -1
        for frame in self._thumbnail_frames:
            frame.destroy()
        self._thumbnail_frames.clear()
        self._thumbnail_labels.clear()
        self._status_dots.clear()
        self._excluded_overlays.clear()

    def _rebuild_grid(self) -> None:
        """Rebuild the grid layout."""
        # Clear existing frames
        for frame in self._thumbnail_frames:
            frame.destroy()
        self._thumbnail_frames.clear()
        self._thumbnail_labels.clear()
        self._status_dots.clear()
        self._excluded_overlays.clear()

        if not self._items:
            # Show empty hint
            hint = ctk.CTkLabel(
                self,
                text="Process images to see crop previews",
                text_color=BRAND_COLORS["text_dim"],
                font=ctk.CTkFont(size=12)
            )
            hint.grid(row=0, column=0, columnspan=self.COLUMNS, pady=30)
            return

        # Create thumbnail frames
        for i, item in enumerate(self._items):
            row = i // self.COLUMNS
            col = i % self.COLUMNS

            frame = ctk.CTkFrame(
                self,
                width=self.THUMB_SIZE,
                height=self.THUMB_SIZE + 20,
                fg_color=BRAND_COLORS["bg_tertiary"],
                corner_radius=6,
                border_width=0
            )
            frame.grid(row=row, column=col, padx=self.THUMB_PADDING, pady=self.THUMB_PADDING, sticky="nsew")
            frame.grid_propagate(False)
            frame.bind("<Button-1>", lambda e, idx=i: self._on_click(idx))

            # Thumbnail image label - show placeholder for pending items
            placeholder_text = "" if item.crop else str(i + 1)
            label = ctk.CTkLabel(
                frame,
                text=placeholder_text,
                width=self.THUMB_SIZE - 8,
                height=self.THUMB_SIZE - 8,
                fg_color="transparent",
                text_color=BRAND_COLORS["text_dim"],
                font=ctk.CTkFont(size=16)
            )
            label.place(x=4, y=4)
            label.bind("<Button-1>", lambda e, idx=i: self._on_click(idx))

            # Filename label (truncated)
            name = item.path.stem
            if len(name) > 14:
                name = name[:12] + "..."
            name_label = ctk.CTkLabel(
                frame,
                text=name,
                font=ctk.CTkFont(size=9),
                text_color=BRAND_COLORS["text_dim"],
                height=16
            )
            name_label.place(x=4, y=self.THUMB_SIZE - 2)
            name_label.bind("<Button-1>", lambda e, idx=i: self._on_click(idx))

            # Status dot indicator
            status_color = self._get_status_color(item.status)
            status_dot = ctk.CTkLabel(
                frame,
                text="",
                width=12,
                height=12,
                fg_color=status_color,
                corner_radius=6
            )
            status_dot.place(x=self.THUMB_SIZE - 16, y=6)

            # Excluded overlay (X mark)
            excluded_overlay = None
            if item.excluded:
                excluded_overlay = ctk.CTkLabel(
                    frame,
                    text="✗",
                    font=ctk.CTkFont(size=32, weight="bold"),
                    text_color=BRAND_COLORS["error"],
                    fg_color="transparent"
                )
                excluded_overlay.place(relx=0.5, rely=0.4, anchor="center")
                excluded_overlay.bind("<Button-1>", lambda e, idx=i: self._on_click(idx))

            self._thumbnail_frames.append(frame)
            self._thumbnail_labels.append(label)
            self._status_dots.append(status_dot)
            self._excluded_overlays.append(excluded_overlay)

        # Highlight selected
        if 0 <= self._selected_index < len(self._thumbnail_frames):
            self._thumbnail_frames[self._selected_index].configure(
                border_width=3,
                border_color=BRAND_COLORS["orange"]
            )

    def _get_status_color(self, status: str) -> str:
        """Get color for status indicator."""
        return {
            "pending": BRAND_COLORS["text_dim"],
            "processing": BRAND_COLORS["orange"],
            "success": BRAND_COLORS["success"],
            "no_subject": BRAND_COLORS["text_secondary"],
            "error": BRAND_COLORS["error"]
        }.get(status, BRAND_COLORS["text_dim"])

    def _update_status_dot(self, index: int) -> None:
        """Update status dot color for an item."""
        if 0 <= index < len(self._status_dots) and index < len(self._items):
            color = self._get_status_color(self._items[index].status)
            self._status_dots[index].configure(fg_color=color)

    def _update_excluded_overlay(self, index: int) -> None:
        """Update excluded overlay for an item."""
        if 0 <= index < len(self._excluded_overlays) and index < len(self._items):
            item = self._items[index]
            overlay = self._excluded_overlays[index]

            if item.excluded and overlay is None:
                # Create overlay
                frame = self._thumbnail_frames[index]
                overlay = ctk.CTkLabel(
                    frame,
                    text="✗",
                    font=ctk.CTkFont(size=32, weight="bold"),
                    text_color=BRAND_COLORS["error"],
                    fg_color="transparent"
                )
                overlay.place(relx=0.5, rely=0.4, anchor="center")
                overlay.bind("<Button-1>", lambda e, idx=index: self._on_click(idx))
                self._excluded_overlays[index] = overlay
            elif not item.excluded and overlay is not None:
                # Remove overlay
                overlay.destroy()
                self._excluded_overlays[index] = None

    def _on_click(self, index: int) -> None:
        """Handle thumbnail click."""
        self.set_selected(index)
        if self._on_select:
            self._on_select(index)

    def _load_processed_thumbnails(self) -> None:
        """Only load thumbnails for items that have been processed (have crops)."""
        # Clear queue
        while not self._load_queue.empty():
            try:
                self._load_queue.get_nowait()
            except queue.Empty:
                break

        # Only queue items that have crops (processed successfully)
        for i, item in enumerate(self._items):
            if item.crop is not None and item.thumbnail is None:
                self._load_queue.put(i)

        # Start loader workers if we have items to load
        if not self._load_queue.empty():
            self._start_loaders()

    def _load_thumbnails_async(self) -> None:
        """Queue all thumbnails for background loading."""
        # Clear queue and re-add all items
        while not self._load_queue.empty():
            try:
                self._load_queue.get_nowait()
            except queue.Empty:
                break

        for i in range(len(self._items)):
            self._load_queue.put(i)

        # Start loader workers (up to MAX_CONCURRENT_LOADS)
        self._start_loaders()

    def _start_loaders(self) -> None:
        """Start thumbnail loader threads if needed."""
        with self._loader_lock:
            while self._active_loaders < self.MAX_CONCURRENT_LOADS:
                self._active_loaders += 1
                threading.Thread(target=self._loader_worker, daemon=True).start()

    def _loader_worker(self) -> None:
        """Worker thread that processes thumbnail load queue."""
        while True:
            try:
                index = self._load_queue.get(timeout=0.5)
            except queue.Empty:
                with self._loader_lock:
                    self._active_loaders -= 1
                return

            if index >= len(self._items):
                continue

            try:
                item = self._items[index]
                img = Image.open(item.path)

                # Apply crop if available (show cropped preview)
                if item.crop:
                    w, h = img.size
                    left = int(item.crop.left * w)
                    top = int(item.crop.top * h)
                    right = int(item.crop.right * w)
                    bottom = int(item.crop.bottom * h)
                    img = img.crop((left, top, right, bottom))

                # Resize to fit thumbnail (maintain aspect ratio)
                thumb_inner = self.THUMB_SIZE - 12
                img.thumbnail((thumb_inner, thumb_inner), Image.Resampling.LANCZOS)

                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)

                # Update UI on main thread
                self.after(0, lambda idx=index, p=photo: self._set_thumbnail(idx, p))

            except Exception:
                self.after(0, lambda idx=index: self._set_thumbnail_error(idx))

    def _load_single_thumbnail(self, index: int) -> None:
        """Queue a single thumbnail for loading."""
        if index >= len(self._items):
            return
        self._load_queue.put(index)
        self._start_loaders()

    def _set_thumbnail(self, index: int, photo: ImageTk.PhotoImage) -> None:
        """Set thumbnail image (must be called from main thread)."""
        if 0 <= index < len(self._thumbnail_labels) and index < len(self._items):
            # Keep reference to prevent garbage collection
            self._items[index].thumbnail = photo
            self._thumbnail_labels[index].configure(image=photo)

    def _set_thumbnail_error(self, index: int) -> None:
        """Show error state for thumbnail."""
        if 0 <= index < len(self._thumbnail_labels):
            self._thumbnail_labels[index].configure(
                text="!",
                text_color=BRAND_COLORS["error"],
                font=ctk.CTkFont(size=24, weight="bold")
            )
