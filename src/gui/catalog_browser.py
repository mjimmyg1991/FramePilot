"""Catalog browser dialog for importing images from Lightroom, darktable, etc."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from ..catalog.lightroom import LightroomCatalog, find_lightroom_catalogs, CatalogImage
from ..catalog.darktable import DarktableCatalog, find_darktable_database
from ..catalog.capture_one import CaptureOneCatalog, find_capture_one_catalogs


class CatalogBrowserDialog(ctk.CTkToplevel):
    """Dialog for browsing and importing images from photo catalogs."""

    def __init__(self, parent, on_import: Callable[[list[Path]], None]):
        super().__init__(parent)

        self.on_import = on_import
        self.result: list[Path] = []

        self._catalog = None
        self._catalog_type = None
        self._current_images: list = []

        self.title("Import from Catalog")
        self.geometry("800x600")
        self.minsize(700, 500)
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 800) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 600) // 2
        self.geometry(f"+{x}+{y}")

        self._setup_ui()
        self._auto_detect_catalogs()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")

        ctk.CTkLabel(
            header, text="Import from Catalog",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        # Catalog selection
        select_frame = ctk.CTkFrame(self)
        select_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        select_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(select_frame, text="Catalog:", width=80).grid(row=0, column=0, padx=12, pady=12)

        self._catalog_var = ctk.StringVar()
        self._catalog_dropdown = ctk.CTkOptionMenu(
            select_frame, variable=self._catalog_var,
            values=["Select a catalog..."],
            width=400,
            command=self._on_catalog_select
        )
        self._catalog_dropdown.grid(row=0, column=1, padx=(0, 8), pady=12, sticky="w")

        ctk.CTkButton(
            select_frame, text="Browse...", width=100,
            command=self._browse_catalog
        ).grid(row=0, column=2, padx=(0, 12), pady=12)

        # Main content - split view
        content = ctk.CTkFrame(self)
        content.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        # Left panel - folders/collections
        left_panel = ctk.CTkFrame(content, fg_color="gray17")
        left_panel.grid(row=0, column=0, padx=(12, 6), pady=12, sticky="nsew")
        left_panel.grid_rowconfigure(1, weight=1)
        left_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left_panel, text="Folders & Collections",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(12, 8), sticky="w")

        self._source_list = ctk.CTkScrollableFrame(left_panel, fg_color="gray20")
        self._source_list.grid(row=1, column=0, padx=8, pady=(0, 12), sticky="nsew")
        self._source_list.grid_columnconfigure(0, weight=1)

        # Right panel - images
        right_panel = ctk.CTkFrame(content, fg_color="gray17")
        right_panel.grid(row=0, column=1, padx=(6, 12), pady=12, sticky="nsew")
        right_panel.grid_rowconfigure(1, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)

        # Image list header with select all
        img_header = ctk.CTkFrame(right_panel, fg_color="transparent")
        img_header.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")

        ctk.CTkLabel(img_header, text="Images", font=ctk.CTkFont(weight="bold")).pack(side="left")

        self._select_all_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            img_header, text="Select All",
            variable=self._select_all_var,
            command=self._toggle_select_all
        ).pack(side="right")

        self._image_count_label = ctk.CTkLabel(img_header, text="", text_color="gray")
        self._image_count_label.pack(side="right", padx=12)

        self._image_list = ctk.CTkScrollableFrame(right_panel, fg_color="gray20")
        self._image_list.grid(row=1, column=0, padx=8, pady=(0, 12), sticky="nsew")
        self._image_list.grid_columnconfigure(0, weight=1)

        self._image_checkboxes: list[tuple[ctk.CTkCheckBox, Path]] = []

        # Footer with actions
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=20, pady=(10, 20), sticky="ew")

        self._import_btn = ctk.CTkButton(
            footer, text="Import Selected (0)",
            command=self._do_import,
            state="disabled"
        )
        self._import_btn.pack(side="right")

        ctk.CTkButton(
            footer, text="Cancel",
            fg_color="gray30", hover_color="gray40",
            command=self.destroy
        ).pack(side="right", padx=8)

        # Filter info
        self._status_label = ctk.CTkLabel(
            footer, text="Select a catalog to browse",
            text_color="gray", font=ctk.CTkFont(size=12)
        )
        self._status_label.pack(side="left")

    def _auto_detect_catalogs(self):
        """Auto-detect available catalogs."""
        catalogs = []

        # Find Lightroom catalogs
        for cat in find_lightroom_catalogs():
            catalogs.append(("Lightroom", cat))

        # Find darktable database
        dt_db = find_darktable_database()
        if dt_db:
            catalogs.append(("darktable", dt_db))

        # Find Capture One catalogs
        for cat in find_capture_one_catalogs():
            catalogs.append(("Capture One", cat))

        if catalogs:
            values = ["Select a catalog..."]
            self._detected_catalogs = {"Select a catalog...": None}
            for app, path in catalogs:
                label = f"[{app}] {path.name}"
                values.append(label)
                self._detected_catalogs[label] = (app, path)
            self._catalog_dropdown.configure(values=values)
            self._status_label.configure(text=f"Found {len(catalogs)} catalog(s)")
        else:
            self._status_label.configure(text="No catalogs found. Use Browse to select one.")
            self._detected_catalogs = {}

    def _browse_catalog(self):
        """Browse for a catalog file."""
        filetypes = [
            ("Lightroom Catalog", "*.lrcat"),
            ("darktable Database", "*.db"),
            ("Capture One Catalog", "*.cocatalog *.cocatalogdb"),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            path = Path(path)
            # Detect type
            if path.suffix.lower() == ".lrcat":
                self._open_catalog("Lightroom", path)
            elif path.suffix.lower() == ".db":
                self._open_catalog("darktable", path)
            elif "cocatalog" in path.suffix.lower():
                self._open_catalog("Capture One", path)

    def _on_catalog_select(self, selection: str):
        """Handle catalog dropdown selection."""
        if selection in self._detected_catalogs:
            info = self._detected_catalogs[selection]
            if info:
                app, path = info
                self._open_catalog(app, path)

    def _open_catalog(self, app_type: str, path: Path):
        """Open a catalog and populate the UI."""
        # Close existing catalog
        if self._catalog:
            self._catalog.close()
            self._catalog = None

        try:
            if app_type == "Lightroom":
                self._catalog = LightroomCatalog(path)
                self._catalog.open()
                self._catalog_type = "Lightroom"
            elif app_type == "darktable":
                self._catalog = DarktableCatalog(path)
                self._catalog.open()
                self._catalog_type = "darktable"
            elif app_type == "Capture One":
                self._catalog = CaptureOneCatalog(path)
                self._catalog.open()
                self._catalog_type = "Capture One"

            self._populate_sources()
            self._status_label.configure(text=f"Opened {app_type} catalog: {path.name}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open catalog:\n{e}")

    def _populate_sources(self):
        """Populate the folders/collections list."""
        # Clear existing
        for widget in self._source_list.winfo_children():
            widget.destroy()

        if not self._catalog:
            return

        row = 0

        if self._catalog_type == "Lightroom":
            # Quick filters
            ctk.CTkLabel(
                self._source_list, text="Quick Filters",
                font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
            ).grid(row=row, column=0, padx=8, pady=(8, 4), sticky="w")
            row += 1

            for label, action in [
                ("⭐ Picked/Flagged", lambda: self._load_lightroom_picked()),
                ("🕐 Recent Imports", lambda: self._load_lightroom_recent()),
                ("★★★+ Rated 3+", lambda: self._load_lightroom_rated(3)),
            ]:
                btn = ctk.CTkButton(
                    self._source_list, text=label, anchor="w",
                    fg_color="transparent", hover_color="gray30",
                    command=action
                )
                btn.grid(row=row, column=0, padx=4, pady=2, sticky="ew")
                row += 1

            # Folders
            ctk.CTkLabel(
                self._source_list, text="Folders",
                font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
            ).grid(row=row, column=0, padx=8, pady=(12, 4), sticky="w")
            row += 1

            for folder in self._catalog.get_folders()[:50]:  # Limit for performance
                btn = ctk.CTkButton(
                    self._source_list,
                    text=f"📁 {folder.name} ({folder.image_count})",
                    anchor="w",
                    fg_color="transparent", hover_color="gray30",
                    command=lambda f=folder: self._load_lightroom_folder(f.id)
                )
                btn.grid(row=row, column=0, padx=4, pady=1, sticky="ew")
                row += 1

            # Collections
            collections = self._catalog.get_collections()
            if collections:
                ctk.CTkLabel(
                    self._source_list, text="Collections",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
                ).grid(row=row, column=0, padx=8, pady=(12, 4), sticky="w")
                row += 1

                for coll in collections[:30]:
                    btn = ctk.CTkButton(
                        self._source_list,
                        text=f"📚 {coll.name} ({coll.image_count})",
                        anchor="w",
                        fg_color="transparent", hover_color="gray30",
                        command=lambda c=coll: self._load_lightroom_collection(c.id)
                    )
                    btn.grid(row=row, column=0, padx=4, pady=1, sticky="ew")
                    row += 1

        elif self._catalog_type == "darktable":
            # Film rolls
            ctk.CTkLabel(
                self._source_list, text="Film Rolls",
                font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
            ).grid(row=row, column=0, padx=8, pady=(8, 4), sticky="w")
            row += 1

            for roll in self._catalog.get_film_rolls():
                btn = ctk.CTkButton(
                    self._source_list,
                    text=f"📁 {roll.name} ({roll.image_count})",
                    anchor="w",
                    fg_color="transparent", hover_color="gray30",
                    command=lambda r=roll: self._load_darktable_roll(r.id)
                )
                btn.grid(row=row, column=0, padx=4, pady=1, sticky="ew")
                row += 1

        elif self._catalog_type == "Capture One":
            # Collections
            ctk.CTkLabel(
                self._source_list, text="All Images",
                font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
            ).grid(row=row, column=0, padx=8, pady=(8, 4), sticky="w")
            row += 1

            btn = ctk.CTkButton(
                self._source_list,
                text="📷 Load All Images",
                anchor="w",
                fg_color="transparent", hover_color="gray30",
                command=self._load_capture_one_all
            )
            btn.grid(row=row, column=0, padx=4, pady=2, sticky="ew")

    def _load_lightroom_folder(self, folder_id: int):
        """Load images from a Lightroom folder."""
        images = self._catalog.get_images_in_folder(folder_id)
        self._display_images(images)

    def _load_lightroom_collection(self, collection_id: int):
        """Load images from a Lightroom collection."""
        images = self._catalog.get_images_in_collection(collection_id)
        self._display_images(images)

    def _load_lightroom_picked(self):
        """Load picked/flagged images."""
        images = self._catalog.get_picked_images()
        self._display_images(images)

    def _load_lightroom_recent(self):
        """Load recent imports."""
        images = self._catalog.get_recent_imports(100)
        self._display_images(images)

    def _load_lightroom_rated(self, min_rating: int):
        """Load images with minimum rating."""
        images = self._catalog.get_images_by_rating(min_rating)
        self._display_images(images)

    def _load_darktable_roll(self, roll_id: int):
        """Load images from a darktable film roll."""
        images = self._catalog.get_images_in_film_roll(roll_id)
        self._display_images(images)

    def _load_capture_one_all(self):
        """Load all images from Capture One."""
        images = self._catalog.get_all_images()
        self._display_images(images)

    def _display_images(self, images: list):
        """Display images in the image list."""
        # Clear existing
        for widget in self._image_list.winfo_children():
            widget.destroy()
        self._image_checkboxes.clear()
        self._current_images = images

        self._image_count_label.configure(text=f"{len(images)} images")
        self._select_all_var.set(False)

        # Check which files exist
        valid_count = 0
        for i, img in enumerate(images):
            path = img.full_path
            exists = path.exists()

            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(
                self._image_list,
                text=f"{img.filename}.{img.extension}" if hasattr(img, 'extension') else img.filename,
                variable=var,
                command=self._update_import_count,
                state="normal" if exists else "disabled",
                text_color="white" if exists else "gray50"
            )
            cb.grid(row=i, column=0, padx=8, pady=2, sticky="w")

            if exists:
                self._image_checkboxes.append((cb, var, path))
                valid_count += 1

        if valid_count < len(images):
            self._status_label.configure(
                text=f"{len(images) - valid_count} files not found (moved or offline)"
            )
        else:
            self._status_label.configure(text=f"Showing {len(images)} images")

        self._update_import_count()

    def _toggle_select_all(self):
        """Toggle select all checkboxes."""
        select = self._select_all_var.get()
        for cb, var, path in self._image_checkboxes:
            var.set(select)
        self._update_import_count()

    def _update_import_count(self):
        """Update the import button with selected count."""
        count = sum(1 for _, var, _ in self._image_checkboxes if var.get())
        self._import_btn.configure(
            text=f"Import Selected ({count})",
            state="normal" if count > 0 else "disabled"
        )

    def _do_import(self):
        """Import selected images."""
        selected_paths = [path for _, var, path in self._image_checkboxes if var.get()]
        if selected_paths:
            self.result = selected_paths
            self.on_import(selected_paths)
            self.destroy()

    def destroy(self):
        """Clean up and close."""
        if self._catalog:
            self._catalog.close()
        super().destroy()
