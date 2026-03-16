"""Main application window for FramePilot GUI - CustomTkinter."""

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageTk

from .preview_widget import PreviewWidget
from .thumbnail_grid import ThumbnailGrid
from .worker import ProcessingResult, ProcessingWorker, write_xmp_for_results, export_cropped_images
from .catalog_browser import CatalogBrowserDialog
from .collection_dialog import CollectionDialog
from .watcher_panel import WatcherPanel
from ..crop_calculator import CropRegion, calculate_vertical_crop, should_use_landscape
from ..catalog.lightroom import LightroomCatalog, is_catalog_locked
from ..xmp_handler import write_signal_file
from .. import resource_path
from ..constants import SUPPORTED_EXTENSIONS, BRAND_COLORS
from ..presets import (
    SHOOT_TYPES, DESTINATIONS, SubjectStrategy,
    get_shoot_type_names, get_destination_names, get_strategy_names,
    get_shoot_type_by_name, get_destination_by_name, get_recommended_settings,
)

# Configure CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")



class ExportDialog(ctk.CTkToplevel):
    """Dialog for export settings with watermark support."""

    WATERMARK_POSITIONS = ["Bottom Right", "Bottom Left", "Top Right", "Top Left", "Center"]

    def __init__(self, parent, file_count: int, default_quality: int = 92, max_dimension: int | None = None):
        super().__init__(parent)
        self.result = None
        self._max_dimension = max_dimension

        self.title("FramePilot - Export")
        self.geometry("520x420")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=BRAND_COLORS["bg_secondary"])

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 520) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 420) // 2
        self.geometry(f"+{x}+{y}")

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text=f"Export {file_count} cropped image(s)",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=BRAND_COLORS["text_primary"]
        ).grid(row=0, column=0, padx=24, pady=(24, 16), sticky="w")

        # Output folder
        folder_frame = ctk.CTkFrame(self, fg_color="transparent")
        folder_frame.grid(row=1, column=0, padx=24, pady=8, sticky="ew")
        folder_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(folder_frame, text="Output Folder:").grid(row=0, column=0, padx=(0, 12))
        self._folder_var = ctk.StringVar()
        ctk.CTkEntry(folder_frame, textvariable=self._folder_var, width=280).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(folder_frame, text="Browse", width=80, command=self._browse_folder).grid(row=0, column=2)

        # Quality
        quality_frame = ctk.CTkFrame(self, fg_color="transparent")
        quality_frame.grid(row=2, column=0, padx=24, pady=8, sticky="w")

        ctk.CTkLabel(quality_frame, text="JPEG Quality:").pack(side="left", padx=(0, 12))
        self._quality_var = ctk.StringVar(value=str(default_quality))
        ctk.CTkEntry(quality_frame, textvariable=self._quality_var, width=60).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(quality_frame, text="(1-100)", text_color="gray").pack(side="left")

        if max_dimension:
            dim_frame = ctk.CTkFrame(self, fg_color="transparent")
            dim_frame.grid(row=3, column=0, padx=24, pady=4, sticky="w")
            ctk.CTkLabel(
                dim_frame, text=f"Max dimension: {max_dimension}px",
                text_color="gray", font=ctk.CTkFont(size=12)
            ).pack(side="left")

        # Watermark section
        wm_header = ctk.CTkFrame(self, fg_color="transparent")
        wm_header.grid(row=4, column=0, padx=24, pady=(16, 8), sticky="w")

        self._watermark_enabled = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(wm_header, text="Add Watermark",
                        variable=self._watermark_enabled,
                        command=self._toggle_watermark,
                        fg_color=BRAND_COLORS["orange"],
                        hover_color=BRAND_COLORS["orange_dim"]).pack(side="left")

        self._wm_frame = ctk.CTkFrame(self, fg_color=BRAND_COLORS["bg_card"])
        self._wm_frame.grid(row=5, column=0, padx=24, pady=4, sticky="ew")

        # Watermark file
        wm_file_row = ctk.CTkFrame(self._wm_frame, fg_color="transparent")
        wm_file_row.pack(fill="x", padx=12, pady=(12, 8))

        ctk.CTkLabel(wm_file_row, text="Image:", width=60).pack(side="left")
        self._wm_path_var = ctk.StringVar()
        ctk.CTkEntry(wm_file_row, textvariable=self._wm_path_var, width=240).pack(side="left", padx=(0, 8))
        ctk.CTkButton(wm_file_row, text="Browse", width=70, command=self._browse_watermark,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"]).pack(side="left")

        # Position and opacity
        wm_opts_row = ctk.CTkFrame(self._wm_frame, fg_color="transparent")
        wm_opts_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(wm_opts_row, text="Position:", width=60).pack(side="left")
        self._wm_position = ctk.StringVar(value="Bottom Right")
        ctk.CTkOptionMenu(wm_opts_row, variable=self._wm_position,
                          values=self.WATERMARK_POSITIONS, width=120).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(wm_opts_row, text="Opacity:").pack(side="left", padx=(0, 8))
        self._wm_opacity = ctk.CTkSlider(wm_opts_row, from_=10, to=100, number_of_steps=18,
                                          width=100, progress_color=BRAND_COLORS["orange"],
                                          button_color=BRAND_COLORS["orange"])
        self._wm_opacity.set(50)
        self._wm_opacity.pack(side="left", padx=(0, 4))
        self._wm_opacity_label = ctk.CTkLabel(wm_opts_row, text="50%", width=35)
        self._wm_opacity_label.pack(side="left")
        self._wm_opacity.configure(command=lambda v: self._wm_opacity_label.configure(text=f"{int(v)}%"))

        # Size
        wm_size_row = ctk.CTkFrame(self._wm_frame, fg_color="transparent")
        wm_size_row.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(wm_size_row, text="Size:", width=60).pack(side="left")
        self._wm_size = ctk.CTkSlider(wm_size_row, from_=5, to=30, number_of_steps=25,
                                       width=100, progress_color=BRAND_COLORS["orange"],
                                       button_color=BRAND_COLORS["orange"])
        self._wm_size.set(15)
        self._wm_size.pack(side="left", padx=(0, 4))
        self._wm_size_label = ctk.CTkLabel(wm_size_row, text="15%", width=35)
        self._wm_size_label.pack(side="left")
        self._wm_size.configure(command=lambda v: self._wm_size_label.configure(text=f"{int(v)}%"))
        ctk.CTkLabel(wm_size_row, text="of image width", text_color="gray",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(8, 0))

        # Initially hide watermark options
        self._wm_frame.grid_remove()

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=6, column=0, padx=24, pady=(24, 24), sticky="e")

        ctk.CTkButton(btn_frame, text="Cancel", width=100,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      command=self.destroy).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Export", width=100,
                      fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
                      text_color=BRAND_COLORS["bg_primary"],
                      command=self._on_export).pack(side="left")

    def _browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self._folder_var.set(folder)

    def _browse_watermark(self):
        filetypes = [("Image files", "*.png *.jpg *.jpeg *.gif"), ("All files", "*.*")]
        file = filedialog.askopenfilename(filetypes=filetypes)
        if file:
            self._wm_path_var.set(file)

    def _toggle_watermark(self):
        if self._watermark_enabled.get():
            self._wm_frame.grid()
        else:
            self._wm_frame.grid_remove()

    def _on_export(self):
        folder = self._folder_var.get().strip()
        if not folder:
            messagebox.showerror("Error", "Please select an output folder.")
            return
        try:
            quality = int(self._quality_var.get())
            if not 1 <= quality <= 100:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Quality must be between 1 and 100.")
            return

        # Watermark settings
        watermark = None
        if self._watermark_enabled.get():
            wm_path = self._wm_path_var.get().strip()
            if wm_path:
                watermark = {
                    "path": wm_path,
                    "position": self._wm_position.get(),
                    "opacity": int(self._wm_opacity.get()) / 100,
                    "size": int(self._wm_size.get()) / 100,
                }

        self.result = (folder, quality, self._max_dimension, watermark)
        self.destroy()


class LightroomDialog(ctk.CTkToplevel):
    """Dialog for Lightroom integration options — XMP-first workflow."""

    def __init__(self, parent, file_count: int, has_catalog: bool = False):
        super().__init__(parent)
        self.result = None

        self.title("FramePilot - Apply to Lightroom")
        self.geometry("480x360")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=BRAND_COLORS["bg_secondary"])

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 480) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 360) // 2
        self.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            self, text="Apply Crops to Lightroom",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=BRAND_COLORS["text_primary"]
        ).pack(pady=(24, 8))

        ctk.CTkLabel(
            self, text=f"{file_count} image(s) ready",
            text_color=BRAND_COLORS["text_dim"]
        ).pack(pady=(0, 16))

        # Option 1: Apply Crops (XMP) — PRIMARY
        opt1_frame = ctk.CTkFrame(self, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["orange"])
        opt1_frame.pack(fill="x", padx=24, pady=8)

        ctk.CTkButton(
            opt1_frame, text="Apply Crops in Lightroom",
            width=200, height=40,
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"],
            font=ctk.CTkFont(weight="bold"),
            command=lambda: self._select("xmp")
        ).pack(side="left", padx=12, pady=12)

        desc_frame = ctk.CTkFrame(opt1_frame, fg_color="transparent")
        desc_frame.pack(side="left", padx=8, fill="x", expand=True)

        ctk.CTkLabel(
            desc_frame,
            text="Non-destructive \u2022 Updates your catalog via XMP",
            font=ctk.CTkFont(size=11),
            text_color=BRAND_COLORS["text_secondary"],
            justify="left"
        ).pack(anchor="w")

        ctk.CTkLabel(
            desc_frame,
            text="Recommended",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=BRAND_COLORS["orange"],
        ).pack(anchor="w")

        # Collection checkbox (only if images came from a catalog)
        if has_catalog:
            self.add_to_collection = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(
                self, text="Also add to a Lightroom collection",
                variable=self.add_to_collection,
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=36, pady=(4, 0))
        else:
            self.add_to_collection = ctk.BooleanVar(value=False)

        # Option 2: Export Copies — SECONDARY
        opt2_frame = ctk.CTkFrame(self, fg_color=BRAND_COLORS["bg_card"])
        opt2_frame.pack(fill="x", padx=24, pady=8)

        ctk.CTkButton(
            opt2_frame, text="Export Copies",
            width=200, height=40,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            font=ctk.CTkFont(weight="bold"),
            command=lambda: self._select("import")
        ).pack(side="left", padx=12, pady=12)

        ctk.CTkLabel(
            opt2_frame,
            text="Creates new cropped JPEG files\nFor sharing outside Lightroom",
            font=ctk.CTkFont(size=11),
            text_color=BRAND_COLORS["text_secondary"],
            justify="left"
        ).pack(side="left", padx=8)

        # Tip
        ctk.CTkLabel(
            self,
            text="Tip: XMP sidecars are non-destructive \u2014 your originals stay untouched,\nand you can always readjust in Lightroom\u2019s Develop module.",
            font=ctk.CTkFont(size=10),
            text_color=BRAND_COLORS["text_dim"],
            justify="left",
        ).pack(padx=24, pady=(8, 4))

        # Cancel
        ctk.CTkButton(
            self, text="Cancel", width=100,
            fg_color="transparent", hover_color=BRAND_COLORS["bg_tertiary"],
            command=self.destroy
        ).pack(pady=(8, 16))

    def _select(self, action: str):
        self.result = action
        self.destroy()


class MainWindow(ctk.CTk):
    """Main application window with two-mode layout."""

    def __init__(self):
        super().__init__()

        self.title("FramePilot")
        self.geometry("1400x900")
        self.minsize(1200, 750)
        self.configure(fg_color=BRAND_COLORS["bg_primary"])

        self._set_app_icon()

        # State
        self._queue: list[dict[str, Any]] = []
        self._selected_index: int = -1
        self._worker = ProcessingWorker(
            on_progress=self._on_progress,
            on_file_complete=self._on_file_complete,
            on_complete=self._on_processing_complete,
        )
        self._queue_update_pending = False
        self._current_mode = "setup"  # "setup" or "review"

        # Catalog tracking for collection support
        self._source_catalog_path: Path | None = None
        self._source_image_ids: dict[Path, int] = {}

        # Settings
        self._aspect_w = ctk.StringVar(value="4")
        self._aspect_h = ctk.StringVar(value="5")
        self._padding = ctk.StringVar(value="15")
        self._strategy = ctk.StringVar(value="Smart Select")
        self._destination = ctk.StringVar(value="Client Gallery")
        self._precise_mode = ctk.BooleanVar(value=False)
        self._auto_orientation = ctk.BooleanVar(value=True)

        self._preset_buttons: dict[str, ctk.CTkButton] = {}

        self._setup_ui()
        self._bind_keyboard_shortcuts()

    def _set_app_icon(self):
        branding_dir = resource_path("branding")
        if sys.platform == "win32":
            ico_path = branding_dir / "framepilot.ico"
            if ico_path.exists():
                try:
                    self.iconbitmap(str(ico_path))
                    return
                except Exception:
                    pass
        png_path = branding_dir / "FramePilot Icon Mark.png"
        if png_path.exists():
            try:
                icon_img = Image.open(png_path)
                icon_img = icon_img.resize((48, 48), Image.Resampling.LANCZOS)
                self._icon_photo = ImageTk.PhotoImage(icon_img)
                self.iconphoto(True, self._icon_photo)
            except Exception:
                pass

    def _bind_keyboard_shortcuts(self):
        """Bind global keyboard shortcuts."""
        self.bind_all("<Control-o>", lambda e: self._add_files())
        self.bind_all("<Control-O>", lambda e: self._add_files())
        self.bind_all("<Left>", lambda e: self._navigate_thumbnail(-1))
        self.bind_all("<Right>", lambda e: self._navigate_thumbnail(1))

    def _navigate_thumbnail(self, delta: int):
        """Navigate thumbnail selection by delta (-1 = previous, +1 = next)."""
        if not self._queue:
            return
        new_index = self._selected_index + delta
        if new_index < 0:
            new_index = 0
        elif new_index >= len(self._queue):
            new_index = len(self._queue) - 1
        if new_index != self._selected_index:
            self._select_queue_item(new_index)

    def _setup_ui(self):
        """Set up the main UI with top bar and content area."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top bar
        self._setup_top_bar()

        # Content container (switches between setup and review)
        self._content_frame = ctk.CTkFrame(self, fg_color=BRAND_COLORS["bg_primary"])
        self._content_frame.grid(row=1, column=0, sticky="nsew")
        self._content_frame.grid_columnconfigure(0, weight=1)
        self._content_frame.grid_rowconfigure(0, weight=1)

        # Setup mode frame
        self._setup_frame = ctk.CTkFrame(self._content_frame, fg_color=BRAND_COLORS["bg_primary"])
        self._setup_mode_ui()

        # Review mode frame
        self._review_frame = ctk.CTkFrame(self._content_frame, fg_color=BRAND_COLORS["bg_primary"])
        self._review_mode_ui()

        # Start in setup mode
        self._show_mode("setup")

    def _setup_top_bar(self):
        """Create top navigation bar."""
        top_bar = ctk.CTkFrame(self, height=56, fg_color=BRAND_COLORS["bg_secondary"])
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_propagate(False)

        # Logo
        logo_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        logo_frame.pack(side="left", padx=20, pady=10)

        self._logo_image = None
        logo_path = resource_path("branding") / "FramePilot Wordmark.png"
        if logo_path.exists():
            try:
                logo_img = Image.open(logo_path)
                aspect = logo_img.width / logo_img.height
                new_height = 32
                new_width = int(new_height * aspect)
                logo_img = logo_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                self._logo_image = ctk.CTkImage(light_image=logo_img, dark_image=logo_img, size=(new_width, new_height))
                ctk.CTkLabel(logo_frame, image=self._logo_image, text="").pack(side="left")
            except Exception:
                ctk.CTkLabel(logo_frame, text="FramePilot", font=ctk.CTkFont(size=20, weight="bold"),
                             text_color=BRAND_COLORS["orange"]).pack(side="left")
        else:
            ctk.CTkLabel(logo_frame, text="FramePilot", font=ctk.CTkFont(size=20, weight="bold"),
                         text_color=BRAND_COLORS["orange"]).pack(side="left")

        # Mode toggle
        mode_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        mode_frame.pack(side="left", padx=40)

        self._setup_btn = ctk.CTkButton(
            mode_frame, text="Setup", width=80, height=32,
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"], font=ctk.CTkFont(weight="bold"),
            command=lambda: self._show_mode("setup")
        )
        self._setup_btn.pack(side="left", padx=2)

        self._review_btn = ctk.CTkButton(
            mode_frame, text="Review", width=80, height=32,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            text_color=BRAND_COLORS["text_primary"], font=ctk.CTkFont(weight="bold"),
            command=lambda: self._show_mode("review")
        )
        self._review_btn.pack(side="left", padx=2)

        # Right side actions
        action_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        action_frame.pack(side="right", padx=20)

        self._export_top_btn = ctk.CTkButton(
            action_frame, text="Export", width=90, height=32,
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"],
            command=self._export_images, state="disabled"
        )
        self._export_top_btn.pack(side="right", padx=4)

        self._lr_btn = ctk.CTkButton(
            action_frame, text="Apply to Lightroom", width=130, height=32,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self._push_to_lightroom, state="disabled"
        )
        self._lr_btn.pack(side="right", padx=4)

        self._xmp_top_btn = ctk.CTkButton(
            action_frame, text="Write XMP", width=90, height=32,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self._write_xmp, state="disabled"
        )
        self._xmp_top_btn.pack(side="right", padx=4)

        ctk.CTkButton(
            action_frame, text="About", width=60, height=32,
            fg_color="transparent", hover_color=BRAND_COLORS["bg_tertiary"],
            text_color=BRAND_COLORS["text_dim"],
            command=self._show_about,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            action_frame, text="Plugin", width=60, height=32,
            fg_color="transparent", hover_color=BRAND_COLORS["bg_tertiary"],
            text_color=BRAND_COLORS["text_dim"],
            command=self._open_plugin_installer,
        ).pack(side="right", padx=4)

        # Progress in top bar
        self._progress_frame = ctk.CTkFrame(top_bar, fg_color="transparent", width=200)
        self._progress_frame.pack(side="right", padx=20)

        self._status_var = ctk.StringVar(value="Ready")
        self._status_label = ctk.CTkLabel(self._progress_frame, textvariable=self._status_var,
                                           text_color=BRAND_COLORS["text_dim"], font=ctk.CTkFont(size=11))
        self._status_label.pack(side="top")

        self._progress_bar = ctk.CTkProgressBar(self._progress_frame, height=6, width=180,
                                                 progress_color=BRAND_COLORS["orange"],
                                                 fg_color=BRAND_COLORS["bg_tertiary"])
        self._progress_bar.pack(side="top", pady=(2, 0))
        self._progress_bar.set(0)

    def _show_mode(self, mode: str):
        """Switch between setup and review modes."""
        self._current_mode = mode

        if mode == "setup":
            self._review_frame.grid_remove()
            self._setup_frame.grid(row=0, column=0, sticky="nsew")
            self._setup_btn.configure(fg_color=BRAND_COLORS["orange"], text_color=BRAND_COLORS["bg_primary"])
            self._review_btn.configure(fg_color=BRAND_COLORS["bg_tertiary"], text_color=BRAND_COLORS["text_primary"])
        else:
            self._setup_frame.grid_remove()
            self._review_frame.grid(row=0, column=0, sticky="nsew")
            self._review_btn.configure(fg_color=BRAND_COLORS["orange"], text_color=BRAND_COLORS["bg_primary"])
            self._setup_btn.configure(fg_color=BRAND_COLORS["bg_tertiary"], text_color=BRAND_COLORS["text_primary"])
            # Refresh thumbnail grid when entering review mode
            self._thumbnail_grid.set_items(self._queue)

    def _setup_mode_ui(self):
        """Build the Setup mode interface."""
        self._setup_frame.grid_columnconfigure(0, weight=1)
        self._setup_frame.grid_columnconfigure(1, weight=2)
        self._setup_frame.grid_rowconfigure(0, weight=1)

        # Left panel - Settings
        settings_panel = ctk.CTkFrame(self._setup_frame, fg_color=BRAND_COLORS["bg_secondary"], width=360)
        settings_panel.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)
        settings_panel.grid_propagate(False)

        scroll = ctk.CTkScrollableFrame(settings_panel, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Add Files Section ---
        files_frame = ctk.CTkFrame(scroll, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        files_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(files_frame, text="Add Images", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 8))

        btn_row = ctk.CTkFrame(files_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkButton(btn_row, text="+ Files", width=100, height=36,
                      fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
                      text_color=BRAND_COLORS["bg_primary"],
                      command=self._add_files).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="+ Folder", width=100, height=36,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      command=self._add_folder).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Catalog", width=80, height=36,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      command=self._open_catalog_browser).pack(side="left")

        self._file_count_label = ctk.CTkLabel(files_frame, text="0 images loaded",
                                               text_color=BRAND_COLORS["text_dim"], font=ctk.CTkFont(size=12))
        self._file_count_label.pack(anchor="w", padx=12, pady=(0, 12))

        # --- Shoot Type ---
        shoot_frame = ctk.CTkFrame(scroll, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        shoot_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(shoot_frame, text="Shoot Type", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 8))

        self._shoot_type = ctk.StringVar(value="Sports & Action")
        shoot_row = ctk.CTkFrame(shoot_frame, fg_color="transparent")
        shoot_row.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkOptionMenu(shoot_row, variable=self._shoot_type, values=get_shoot_type_names(),
                          width=200, command=self._on_shoot_type_change).pack(side="left")

        # --- Crop Settings ---
        crop_frame = ctk.CTkFrame(scroll, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        crop_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(crop_frame, text="Crop Settings", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 8))

        # Aspect ratio presets
        ar_row = ctk.CTkFrame(crop_frame, fg_color="transparent")
        ar_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(ar_row, text="Aspect:", width=60).pack(side="left")
        for label, w, h in [("4:5", 4, 5), ("9:16", 9, 16), ("2:3", 2, 3), ("1:1", 1, 1)]:
            btn = ctk.CTkButton(
                ar_row, text=label, width=55, height=28,
                fg_color=(BRAND_COLORS["orange"] if label == "4:5" else BRAND_COLORS["bg_tertiary"]),
                hover_color=(BRAND_COLORS["orange_dim"] if label == "4:5" else BRAND_COLORS["border"]),
                text_color=(BRAND_COLORS["bg_primary"] if label == "4:5" else BRAND_COLORS["text_primary"]),
                command=lambda l=label, w=w, h=h: self._set_preset(l, w, h),
            )
            btn.pack(side="left", padx=2)
            self._preset_buttons[label] = btn

        # Padding
        pad_row = ctk.CTkFrame(crop_frame, fg_color="transparent")
        pad_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(pad_row, text="Padding:", width=60).pack(side="left")
        self._padding_slider = ctk.CTkSlider(pad_row, from_=0, to=30, number_of_steps=30,
                                              width=150, command=self._on_padding_change,
                                              progress_color=BRAND_COLORS["orange"],
                                              button_color=BRAND_COLORS["orange"])
        self._padding_slider.set(15)
        self._padding_slider.pack(side="left", padx=8)
        self._padding_label = ctk.CTkLabel(pad_row, text="15%", width=40)
        self._padding_label.pack(side="left")

        # Strategy
        strat_row = ctk.CTkFrame(crop_frame, fg_color="transparent")
        strat_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(strat_row, text="Subject:", width=60).pack(side="left")
        ctk.CTkOptionMenu(strat_row, variable=self._strategy, values=get_strategy_names(), width=150).pack(side="left", padx=8)

        # Auto orientation
        orient_row = ctk.CTkFrame(crop_frame, fg_color="transparent")
        orient_row.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkCheckBox(orient_row, text="Auto-detect orientation (group/team photos)",
                        variable=self._auto_orientation, font=ctk.CTkFont(size=12),
                        fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"]).pack(side="left")

        # --- Quality Settings ---
        quality_frame = ctk.CTkFrame(scroll, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        quality_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(quality_frame, text="Output", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 8))

        dest_row = ctk.CTkFrame(quality_frame, fg_color="transparent")
        dest_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(dest_row, text="For:", width=60).pack(side="left")
        ctk.CTkOptionMenu(dest_row, variable=self._destination, values=get_destination_names(), width=160).pack(side="left", padx=8)

        # Quality slider
        qual_row = ctk.CTkFrame(quality_frame, fg_color="transparent")
        qual_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(qual_row, text="Quality:", width=60).pack(side="left")
        self._quality_slider = ctk.CTkSlider(qual_row, from_=60, to=100, number_of_steps=40,
                                              width=150, command=self._on_quality_change,
                                              progress_color=BRAND_COLORS["orange"],
                                              button_color=BRAND_COLORS["orange"])
        self._quality_slider.set(92)
        self._quality_slider.pack(side="left", padx=8)
        self._quality_label = ctk.CTkLabel(qual_row, text="92%", width=40)
        self._quality_label.pack(side="left")

        precise_row = ctk.CTkFrame(quality_frame, fg_color="transparent")
        precise_row.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkCheckBox(precise_row, text="Precise Mode (slower, tighter crops)",
                        variable=self._precise_mode, font=ctk.CTkFont(size=12),
                        fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"]).pack(side="left")

        # --- Process Button ---
        self._process_btn = ctk.CTkButton(
            scroll, text="Process All", height=48,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"],
            command=self._start_processing
        )
        self._process_btn.pack(fill="x", pady=(8, 0))

        # --- Quick Start Wizard ---
        ctk.CTkButton(
            scroll, text="Quick Start Wizard", height=36,
            font=ctk.CTkFont(size=13),
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            border_width=1, border_color=BRAND_COLORS["border"],
            command=self._open_wizard
        ).pack(fill="x", pady=(8, 0))

        # --- Watch Folder ---
        self._watcher_panel = WatcherPanel(scroll)
        self._watcher_panel.pack(fill="x", pady=(12, 0))

        # Right panel - Preview
        preview_panel = ctk.CTkFrame(self._setup_frame, fg_color=BRAND_COLORS["bg_secondary"])
        preview_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)

        preview_header = ctk.CTkFrame(preview_panel, fg_color="transparent")
        preview_header.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(preview_header, text="Preview", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")

        ctk.CTkButton(preview_header, text="Clear All", width=80, height=28,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      command=self._clear_queue).pack(side="right")

        self._preview = PreviewWidget(preview_panel, on_crop_changed=self._on_crop_dragged,
                                       on_empty_click=self._add_files)
        self._preview.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _review_mode_ui(self):
        """Build the Review mode interface - thumbnails left, preview right."""
        self._review_frame.grid_columnconfigure(0, weight=3)  # Thumbnails get more space
        self._review_frame.grid_columnconfigure(1, weight=2)  # Preview
        self._review_frame.grid_rowconfigure(0, weight=1)

        # Left - Thumbnail grid
        grid_panel = ctk.CTkFrame(self._review_frame, fg_color=BRAND_COLORS["bg_secondary"])
        grid_panel.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)

        grid_header = ctk.CTkFrame(grid_panel, fg_color="transparent")
        grid_header.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(grid_header, text="All Crops", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        self._review_count_label = ctk.CTkLabel(grid_header, text="0 images", text_color=BRAND_COLORS["text_dim"])
        self._review_count_label.pack(side="left", padx=12)

        self._thumbnail_grid = ThumbnailGrid(grid_panel, on_select=self._on_grid_select)
        self._thumbnail_grid.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Right - Preview and controls
        preview_panel = ctk.CTkFrame(self._review_frame, fg_color=BRAND_COLORS["bg_secondary"])
        preview_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)

        preview_header = ctk.CTkFrame(preview_panel, fg_color="transparent")
        preview_header.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(preview_header, text="Selected", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")

        # Crop controls
        ctrl_frame = ctk.CTkFrame(preview_panel, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=16, pady=(0, 8))

        # Exclude toggle (flag to skip in export)
        self._exclude_btn = ctk.CTkButton(ctrl_frame, text="✓ Include", width=90, height=32,
                                           fg_color=BRAND_COLORS["success"], hover_color="#1da34d",
                                           text_color="white",
                                           command=self._toggle_exclude, state="disabled")
        self._exclude_btn.pack(side="left", padx=(0, 8))

        self._flip_btn = ctk.CTkButton(ctrl_frame, text="Flip", width=60, height=32,
                                        fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                                        command=self._flip_aspect_ratio, state="disabled")
        self._flip_btn.pack(side="left", padx=(0, 4))

        self._recenter_btn = ctk.CTkButton(ctrl_frame, text="Re-center", width=80, height=32,
                                            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                                            command=self._recenter_crop, state="disabled")
        self._recenter_btn.pack(side="left", padx=(0, 8))

        # Crop tightness slider (0.5 = tighter/smaller, 1.5 = looser/more context)
        ctk.CTkLabel(ctrl_frame, text="Crop Size:", text_color=BRAND_COLORS["text_dim"]).pack(side="left", padx=(8, 4))
        self._crop_zoom_slider = ctk.CTkSlider(ctrl_frame, from_=0.5, to=1.5, number_of_steps=20,
                                                width=120, command=self._on_crop_zoom_change,
                                                progress_color=BRAND_COLORS["orange"],
                                                button_color=BRAND_COLORS["orange"])
        self._crop_zoom_slider.set(1.0)
        self._crop_zoom_slider.pack(side="left", padx=4)
        self._crop_zoom_label = ctk.CTkLabel(ctrl_frame, text="1.0x", width=35, text_color=BRAND_COLORS["text_dim"])
        self._crop_zoom_label.pack(side="left")
        ctk.CTkLabel(ctrl_frame, text="(← tighter | looser →)", text_color=BRAND_COLORS["text_dim"],
                     font=ctk.CTkFont(size=10)).pack(side="left", padx=(4, 0))

        self._review_preview = PreviewWidget(preview_panel, on_crop_changed=self._on_crop_dragged)
        self._review_preview.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    # ==================== Event Handlers ====================

    def _on_shoot_type_change(self, value: str):
        """Apply preset settings for shoot type."""
        preset = get_shoot_type_by_name(value)
        if not preset:
            return
        # Apply strategy
        strategy_display = SubjectStrategy.display_name(preset.default_strategy)
        self._strategy.set(strategy_display)
        # Apply padding
        padding_pct = int(preset.default_padding * 100)
        self._padding.set(str(padding_pct))
        self._padding_slider.set(padding_pct)
        self._padding_label.configure(text=f"{padding_pct}%")
        # Apply aspect ratio
        if preset.suggested_aspects:
            w, h = preset.suggested_aspects[0]
            self._set_preset(f"{w}:{h}", w, h)

    def _on_padding_change(self, value):
        val = int(value)
        self._padding.set(str(val))
        self._padding_label.configure(text=f"{val}%")

    def _on_quality_change(self, value):
        val = int(value)
        self._quality_label.configure(text=f"{val}%")

    def _set_preset(self, label: str, w: int, h: int):
        self._aspect_w.set(str(w))
        self._aspect_h.set(str(h))
        for btn_label, btn in self._preset_buttons.items():
            if btn_label == label:
                btn.configure(fg_color=BRAND_COLORS["orange"], text_color=BRAND_COLORS["bg_primary"])
            else:
                btn.configure(fg_color=BRAND_COLORS["bg_tertiary"], text_color=BRAND_COLORS["text_primary"])
        self._preview.set_aspect_ratio((w, h), is_landscape=False)

    def _get_aspect_ratio(self) -> tuple[int, int]:
        try:
            w, h = int(self._aspect_w.get()), int(self._aspect_h.get())
            if w <= 0 or h <= 0:
                return (4, 5)
            return (w, h)
        except ValueError:
            return (4, 5)

    def _on_grid_select(self, index: int):
        self._select_queue_item(index)

    def _select_queue_item(self, index: int):
        self._selected_index = index
        self._thumbnail_grid.set_selected(index)

        if index < 0 or index >= len(self._queue):
            return

        item = self._queue[index]
        result = item.get("result")
        crop = item.get("crop_override") or (result.crop if result else None)
        detection = result.primary_detection if result else None
        is_landscape = item.get("is_landscape", False)

        # Update both previews
        self._preview.set_aspect_ratio(self._get_aspect_ratio(), is_landscape=is_landscape)
        self._preview.load_image(item["path"], crop=crop, detection=detection)

        self._review_preview.set_aspect_ratio(self._get_aspect_ratio(), is_landscape=is_landscape)
        self._review_preview.load_image(item["path"], crop=crop, detection=detection)

        has_result = result is not None and result.status == "success"
        self._flip_btn.configure(state="normal" if has_result else "disabled")
        self._recenter_btn.configure(state="normal" if has_result else "disabled")
        self._exclude_btn.configure(state="normal" if has_result else "disabled")

        # Update exclude button state
        is_excluded = item.get("excluded", False)
        self._update_exclude_button(is_excluded)

        # Reset zoom slider to saved value or default
        zoom_val = item.get("crop_zoom", 1.0)
        self._crop_zoom_slider.set(zoom_val)
        self._crop_zoom_label.configure(text=f"{zoom_val:.1f}x")

    def _toggle_exclude(self):
        """Toggle whether the current image is excluded from export."""
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return

        item = self._queue[self._selected_index]
        is_excluded = not item.get("excluded", False)
        item["excluded"] = is_excluded

        self._update_exclude_button(is_excluded)
        self._thumbnail_grid.update_item(self._selected_index, item)
        self._update_export_count()

    def _update_exclude_button(self, is_excluded: bool):
        """Update exclude button appearance."""
        if is_excluded:
            self._exclude_btn.configure(
                text="✗ Excluded",
                fg_color=BRAND_COLORS["error"],
                hover_color="#dc2626"
            )
        else:
            self._exclude_btn.configure(
                text="✓ Include",
                fg_color=BRAND_COLORS["success"],
                hover_color="#1da34d"
            )

    def _update_export_count(self):
        """Update the count of images to export."""
        included = sum(1 for item in self._queue
                       if item.get("result") and item["result"].status == "success"
                       and not item.get("excluded", False))
        total = sum(1 for item in self._queue
                    if item.get("result") and item["result"].status == "success")
        self._review_count_label.configure(text=f"{included}/{total} images")

    def _on_crop_dragged(self, crop: CropRegion):
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return
        self._queue[self._selected_index]["crop_override"] = crop

    def _flip_aspect_ratio(self):
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return
        item = self._queue[self._selected_index]
        result = item.get("result")
        if not result or not result.crop:
            return

        is_landscape = not item.get("is_landscape", False)
        item["is_landscape"] = is_landscape

        aspect = self._get_aspect_ratio()
        if is_landscape:
            aspect = (aspect[1], aspect[0])

        new_crop = calculate_vertical_crop(
            result.image_size[0], result.image_size[1],
            result.primary_detection.bbox,
            target_aspect=aspect,
            padding=float(self._padding.get()) / 100,
        )
        item["crop_override"] = new_crop

        self._review_preview.set_aspect_ratio(self._get_aspect_ratio(), is_landscape=is_landscape)
        self._review_preview.update_crop(new_crop, result.primary_detection)

    def _recenter_crop(self):
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return
        item = self._queue[self._selected_index]
        result = item.get("result")
        if not result or not result.primary_detection:
            return

        is_landscape = item.get("is_landscape", False)
        aspect = self._get_aspect_ratio()
        if is_landscape:
            aspect = (aspect[1], aspect[0])

        new_crop = calculate_vertical_crop(
            result.image_size[0], result.image_size[1],
            result.primary_detection.bbox,
            target_aspect=aspect,
            padding=float(self._padding.get()) / 100,
        )
        item["crop_override"] = new_crop
        self._crop_zoom_slider.set(1.0)
        self._crop_zoom_label.configure(text="1.0x")
        self._review_preview.update_crop(new_crop, result.primary_detection)

    def _on_crop_zoom_change(self, value):
        """Adjust crop tightness - smaller value = tighter crop, larger = more context.

        Works by scaling the crop size around the subject center while maintaining aspect ratio.
        """
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return

        item = self._queue[self._selected_index]
        result = item.get("result")
        if not result or not result.primary_detection:
            return

        self._crop_zoom_label.configure(text=f"{value:.1f}x")

        # Get base crop at 1.0x zoom (original processing result)
        base_crop = result.crop
        if base_crop is None:
            return

        # Calculate crop center (anchor point)
        center_x = (base_crop.left + base_crop.right) / 2
        center_y = (base_crop.top + base_crop.bottom) / 2

        # Scale crop size: value < 1 = smaller (tighter), value > 1 = larger (more context)
        # Invert so that slider left = tight, right = loose
        scale_factor = value

        # Calculate new dimensions
        new_width = base_crop.width * scale_factor
        new_height = base_crop.height * scale_factor

        # Calculate new bounds centered on original center
        new_left = center_x - new_width / 2
        new_right = center_x + new_width / 2
        new_top = center_y - new_height / 2
        new_bottom = center_y + new_height / 2

        # Clamp to image bounds while maintaining aspect ratio
        if new_left < 0:
            shift = -new_left
            new_left = 0
            new_right += shift
        if new_right > 1.0:
            shift = new_right - 1.0
            new_right = 1.0
            new_left = max(0, new_left - shift)
        if new_top < 0:
            shift = -new_top
            new_top = 0
            new_bottom += shift
        if new_bottom > 1.0:
            shift = new_bottom - 1.0
            new_bottom = 1.0
            new_top = max(0, new_top - shift)

        # Final clamp
        new_left = max(0, new_left)
        new_right = min(1.0, new_right)
        new_top = max(0, new_top)
        new_bottom = min(1.0, new_bottom)

        new_crop = CropRegion(
            left=new_left,
            right=new_right,
            top=new_top,
            bottom=new_bottom,
        )

        item["crop_override"] = new_crop
        item["crop_zoom"] = value
        self._review_preview.update_crop(new_crop, result.primary_detection)

        # Also update thumbnail if visible
        if self._current_mode == "review":
            self._thumbnail_grid.update_item(self._selected_index, item)

    # ==================== File Management ====================

    def _add_files(self):
        filetypes = [("Image files", " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)), ("All files", "*.*")]
        files = filedialog.askopenfilenames(filetypes=filetypes)
        for f in files:
            self._add_file_to_queue(Path(f))

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            for ext in SUPPORTED_EXTENSIONS:
                for f in Path(folder).glob(f"*{ext}"):
                    self._add_file_to_queue(f)
                for f in Path(folder).glob(f"*{ext.upper()}"):
                    self._add_file_to_queue(f)

    def _open_catalog_browser(self):
        def on_import_with_ids(paths: list[Path], image_ids: dict[Path, int], catalog_path: Path | None):
            self._source_catalog_path = catalog_path
            self._source_image_ids.update(image_ids)
            for path in paths:
                self._add_file_to_queue(path)
            self._status_var.set(f"Imported {len(paths)} images from catalog")
        CatalogBrowserDialog(self, on_import_with_ids=on_import_with_ids)

    def _open_wizard(self):
        """Open the Quick Start Wizard."""
        from .wizard import LightroomWizard

        def on_complete(results):
            for result in results:
                if result.status == "success":
                    # Add to main queue for further review
                    self._add_file_to_queue(result.file_path)
            self._status_var.set(f"Wizard complete: {len(results)} images processed")

        LightroomWizard(self, on_complete=on_complete)

    def _open_plugin_installer(self):
        """Open the Lightroom plugin installer dialog."""
        from .plugin_installer import PluginInstallerDialog
        PluginInstallerDialog(self)

    def _show_about(self):
        """Show about dialog with version info."""
        from .. import __version__
        dialog = ctk.CTkToplevel(self)
        dialog.title("About FramePilot")
        dialog.geometry("340x200")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=BRAND_COLORS["bg_secondary"])

        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 340) // 2
        y = self.winfo_y() + (self.winfo_height() - 200) // 2
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            dialog, text="FramePilot",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=BRAND_COLORS["orange"]
        ).pack(pady=(24, 4))
        ctk.CTkLabel(
            dialog, text=f"Version {__version__}",
            text_color=BRAND_COLORS["text_secondary"]
        ).pack()
        ctk.CTkLabel(
            dialog, text="Smart crops. Zero effort.",
            text_color=BRAND_COLORS["text_dim"],
            font=ctk.CTkFont(size=12, slant="italic")
        ).pack(pady=(8, 0))
        ctk.CTkButton(
            dialog, text="Close", width=80,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=dialog.destroy
        ).pack(pady=(20, 0))

    def _add_file_to_queue(self, path: Path):
        for item in self._queue:
            if item["path"] == path:
                return
        self._queue.append({
            "path": path,
            "status": "pending",
            "result": None,
            "crop_override": None,
            "is_landscape": False,
        })
        self._schedule_queue_update()

    def _schedule_queue_update(self):
        if not self._queue_update_pending:
            self._queue_update_pending = True
            self.after(100, self._do_queue_update)

    def _do_queue_update(self):
        self._queue_update_pending = False
        self._file_count_label.configure(text=f"{len(self._queue)} images loaded")
        self._review_count_label.configure(text=f"{len(self._queue)} images")

    def _clear_queue(self):
        self._queue.clear()
        self._selected_index = -1
        self._thumbnail_grid.clear()
        self._preview.clear()
        self._review_preview.clear()
        self._file_count_label.configure(text="0 images loaded")
        self._review_count_label.configure(text="0 images")
        self._export_top_btn.configure(state="disabled")
        self._xmp_top_btn.configure(state="disabled")
        self._lr_btn.configure(state="disabled")
        self._flip_btn.configure(state="disabled")
        self._recenter_btn.configure(state="disabled")
        self._exclude_btn.configure(state="disabled")

    # ==================== Processing ====================

    def _start_processing(self):
        if not self._queue:
            messagebox.showinfo("No Files", "Add some files first.")
            return

        if self._worker.is_running:
            if not messagebox.askyesno("Cancel Processing", "Are you sure you want to cancel? Progress will be lost."):
                return
            self._worker.cancel()
            self._process_btn.configure(text="Process All")
            self._status_var.set("Cancelled")
            return

        for item in self._queue:
            item["status"] = "pending"
            item["result"] = None
            item["crop_override"] = None
            item["is_landscape"] = False

        aspect_ratio = self._get_aspect_ratio()
        padding = float(self._padding.get()) / 100
        strategy = SubjectStrategy.from_display_name(self._strategy.get()).value
        precise = self._precise_mode.get()

        files = [item["path"] for item in self._queue]
        self._worker.start_processing(files, aspect_ratio, padding, strategy, precise)

        self._process_btn.configure(text="Cancel")
        self._export_top_btn.configure(state="disabled")
        self._xmp_top_btn.configure(state="disabled")

    def _on_progress(self, current: int, total: int, message: str):
        self.after(0, lambda: self._update_progress(current, total, message))

    def _update_progress(self, current: int, total: int, message: str):
        if total > 0:
            self._progress_bar.set(current / total)
        self._status_var.set(message)

    def _on_file_complete(self, result: ProcessingResult):
        self.after(0, lambda: self._update_file_result(result))

    def _update_file_result(self, result: ProcessingResult):
        for item in self._queue:
            if item["path"] == result.file_path:
                item["status"] = result.status
                item["result"] = result

                # Auto-detect orientation if enabled
                if self._auto_orientation.get() and result.detections:
                    if should_use_landscape(result.detections):
                        item["is_landscape"] = True
                        # Recalculate crop with flipped aspect ratio
                        if result.primary_detection and result.status == "success":
                            aspect = self._get_aspect_ratio()
                            flipped_aspect = (aspect[1], aspect[0])  # Flip to landscape
                            new_crop = calculate_vertical_crop(
                                result.image_size[0], result.image_size[1],
                                result.primary_detection.bbox,
                                target_aspect=flipped_aspect,
                                padding=float(self._padding.get()) / 100,
                            )
                            item["crop_override"] = new_crop
                break

    def _on_processing_complete(self, results: list[ProcessingResult]):
        self.after(0, lambda: self._processing_complete(results))

    def _processing_complete(self, results: list[ProcessingResult]):
        self._process_btn.configure(text="Process All")

        success = sum(1 for r in results if r.status == "success")
        no_subject = sum(1 for r in results if r.status == "no_subject")
        errors = sum(1 for r in results if r.status == "error")

        self._status_var.set(f"Done: {success} ok, {no_subject} no subject, {errors} errors")

        # Update thumbnail grid
        self._thumbnail_grid.set_items(self._queue)

        if success > 0:
            self._export_top_btn.configure(state="normal")
            self._xmp_top_btn.configure(state="normal")
            self._lr_btn.configure(state="normal")
            # Auto-switch to review mode
            self._show_mode("review")

    # ==================== Export ====================

    def _write_xmp(self):
        results = self._get_export_results()
        if not results:
            messagebox.showinfo("No Results", "Process files first.")
            return

        self._xmp_top_btn.configure(state="disabled")
        self._status_var.set("Writing XMP files...")

        def _do_write():
            xmp_results = write_xmp_for_results(
                results,
                on_progress=lambda c, t: self.after(0, lambda: self._update_progress(c, t, f"Writing XMP {c}/{t}...")),
            )
            success = sum(1 for _, ok, _ in xmp_results if ok)
            self.after(0, lambda: self._xmp_write_done(success))

        threading.Thread(target=_do_write, daemon=True).start()

    def _xmp_write_done(self, success: int):
        self._xmp_top_btn.configure(state="normal")
        self._status_var.set(f"Wrote {success} XMP files")
        if success > 0:
            messagebox.showinfo("XMP Files Written",
                f"Wrote {success} XMP sidecar files.\n\nIn Lightroom: Metadata → Read Metadata from Files")

    def _push_to_lightroom(self):
        """Push edits to Lightroom — XMP-first workflow with collection support."""
        results = self._get_export_results()
        if not results:
            messagebox.showinfo("No Results", "Process files first.")
            return

        has_catalog = self._source_catalog_path is not None and len(self._source_image_ids) > 0
        dialog = LightroomDialog(self, len(results), has_catalog=has_catalog)
        self.wait_window(dialog)

        if not dialog.result:
            return

        action = dialog.result

        if action == "xmp":
            add_collection = has_catalog and dialog.add_to_collection.get()
            self._lr_btn.configure(state="disabled")
            self._status_var.set("Writing XMP files...")

            def _do_lr_xmp():
                xmp_results = write_xmp_for_results(
                    results,
                    on_progress=lambda c, t: self.after(0, lambda: self._update_progress(c, t, f"Writing XMP {c}/{t}...")),
                )
                success = sum(1 for _, ok, _ in xmp_results if ok)
                self.after(0, lambda: self._lr_xmp_done(success, results, add_collection))

            threading.Thread(target=_do_lr_xmp, daemon=True).start()

        elif action == "import":
            # Export cropped images and open in Lightroom for import
            folder = filedialog.askdirectory(title="Choose folder for cropped images to import")
            if not folder:
                return

            dest_preset = get_destination_by_name(self._destination.get())
            quality = dest_preset.jpeg_quality if dest_preset else 92

            self._lr_btn.configure(state="disabled")
            self._status_var.set("Exporting for import...")

            def _do_lr_export():
                export_results = export_cropped_images(
                    results, output_dir=Path(folder), jpeg_quality=quality,
                    suffix="",
                    on_progress=lambda c, t: self.after(0, lambda: self._update_progress(c, t, f"Exporting {c}/{t}...")),
                )
                success = sum(1 for _, ok, _ in export_results if ok)
                self.after(0, lambda: self._lr_export_done(success, folder))

            threading.Thread(target=_do_lr_export, daemon=True).start()

    def _lr_xmp_done(self, success: int, results: list[ProcessingResult], add_collection: bool):
        self._lr_btn.configure(state="normal")
        self._status_var.set(f"Wrote {success} XMP files")

        if success > 0:
            try:
                image_paths = [r.file_path for r in results if r.crop]
                signal_dir = results[0].file_path.parent if results else None
                if signal_dir:
                    write_signal_file(image_paths, signal_dir)
            except Exception:
                pass

            if add_collection:
                self._create_lightroom_collection(results)

            self._open_lightroom_with_instructions()

    def _lr_export_done(self, success: int, folder: str):
        self._lr_btn.configure(state="normal")
        self._status_var.set(f"Exported {success} images")
        if success > 0:
            self._open_lightroom_import(folder)

    def _create_lightroom_collection(self, results: list[ProcessingResult]):
        """Create a Lightroom collection with processed images."""
        if not self._source_catalog_path:
            return

        dialog = CollectionDialog(self, len(results), self._source_catalog_path)
        self.wait_window(dialog)

        if not dialog.result:
            return

        collection_name = dialog.result

        try:
            with LightroomCatalog(self._source_catalog_path) as catalog:
                catalog.open(readonly=False)

                collection_id = catalog.create_collection(collection_name)

                # Gather image IDs
                image_ids = []
                for result in results:
                    img_id = self._source_image_ids.get(result.file_path)
                    if img_id is not None:
                        image_ids.append(img_id)

                if image_ids:
                    added = catalog.add_images_to_collection(collection_id, image_ids)
                    messagebox.showinfo(
                        "Collection Created",
                        f"Created collection \"{collection_name}\"\nwith {added} image(s).\n\n"
                        "Restart Lightroom to see the new collection."
                    )
                else:
                    messagebox.showinfo(
                        "Collection Created",
                        f"Created collection \"{collection_name}\" (empty).\n\n"
                        "Could not match images to catalog entries."
                    )

        except Exception as e:
            messagebox.showerror(
                "Collection Error",
                f"Failed to create collection:\n{e}\n\n"
                "Make sure Lightroom is closed before writing to the catalog."
            )

    def _open_lightroom_with_instructions(self):
        """Show step-by-step instructions for applying crops in Lightroom."""
        # Try to find Lightroom executable
        lr_paths = []
        if sys.platform == "win32":
            lr_paths = [
                Path(os.environ.get("ProgramFiles", "")) / "Adobe" / "Adobe Lightroom Classic" / "Lightroom.exe",
                Path(os.environ.get("ProgramFiles(x86)", "")) / "Adobe" / "Adobe Lightroom Classic" / "Lightroom.exe",
            ]
        elif sys.platform == "darwin":
            lr_paths = [
                Path("/Applications/Adobe Lightroom Classic/Adobe Lightroom Classic.app"),
            ]

        lr_found = None
        for lr_path in lr_paths:
            if lr_path.exists():
                lr_found = lr_path
                break

        msg = "XMP sidecar files written successfully!\n\n"
        msg += "To apply crops in Lightroom Classic:\n\n"
        msg += "  Step 1:  Select the processed images in Lightroom\n"
        msg += "  Step 2:  Go to Metadata \u2192 Read Metadata from Files\n"
        msg += "  Step 3:  Your crops are now applied!\n\n"
        msg += "If the FramePilot plugin is installed, this happens automatically."

        if lr_found:
            if messagebox.askyesno("Crops Ready!", msg + "\n\nOpen Lightroom now?"):
                try:
                    if sys.platform == "win32":
                        os.startfile(str(lr_found))
                    elif sys.platform == "darwin":
                        subprocess.run(["open", str(lr_found)])
                except Exception:
                    pass
        else:
            messagebox.showinfo("Crops Ready!", msg)

    def _open_lightroom_import(self, folder: str):
        """Try to open Lightroom with import dialog for a folder."""
        msg = f"Cropped images exported to:\n{folder}\n\n"
        msg += "To import in Lightroom Classic:\n"
        msg += "1. File → Import Photos and Video\n"
        msg += "2. Navigate to the export folder\n"
        msg += "3. Select and import the cropped images"

        # Try to find Lightroom
        lr_found = None
        if sys.platform == "win32":
            for prog_dir in [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]:
                lr_path = Path(prog_dir) / "Adobe" / "Adobe Lightroom Classic" / "Lightroom.exe"
                if lr_path.exists():
                    lr_found = lr_path
                    break
        elif sys.platform == "darwin":
            lr_path = Path("/Applications/Adobe Lightroom Classic/Adobe Lightroom Classic.app")
            if lr_path.exists():
                lr_found = lr_path

        if lr_found and messagebox.askyesno("Open Lightroom?", msg + "\n\nOpen Lightroom now?"):
            try:
                if sys.platform == "win32":
                    os.startfile(str(lr_found))
                    os.startfile(folder)
                elif sys.platform == "darwin":
                    subprocess.run(["open", str(lr_found)])
                    subprocess.run(["open", folder])
            except Exception:
                pass
        else:
            if messagebox.askyesno("Export Complete", msg + "\n\nOpen export folder?"):
                if sys.platform == "win32":
                    os.startfile(folder)
                elif sys.platform == "darwin":
                    subprocess.run(["open", folder])
                else:
                    subprocess.run(["xdg-open", folder])

    def _export_images(self):
        results = self._get_export_results()
        if not results:
            messagebox.showinfo("No Results", "Process files first (or all images are excluded).")
            return

        dest_preset = get_destination_by_name(self._destination.get())
        max_dim = dest_preset.max_dimension if dest_preset else None
        quality = dest_preset.jpeg_quality if dest_preset else 92

        dialog = ExportDialog(self, len(results), default_quality=quality, max_dimension=max_dim)
        self.wait_window(dialog)

        if not dialog.result:
            return

        output_dir, quality, max_dim, watermark = dialog.result

        self._export_top_btn.configure(state="disabled")
        self._status_var.set("Exporting...")

        def _do_export():
            export_results = export_cropped_images(
                results, output_dir=Path(output_dir), jpeg_quality=quality, max_dimension=max_dim,
                watermark=watermark,
                on_progress=lambda c, t: self.after(0, lambda: self._update_progress(c, t, f"Exporting {c}/{t}...")),
            )
            success = sum(1 for _, ok, _ in export_results if ok)
            self.after(0, lambda: self._export_done(success, output_dir))

        threading.Thread(target=_do_export, daemon=True).start()

    def _export_done(self, success: int, output_dir: str):
        self._export_top_btn.configure(state="normal")
        self._status_var.set(f"Exported {success} images")
        if success > 0:
            if messagebox.askyesno("Export Complete", f"Exported {success} images to:\n{output_dir}\n\nOpen folder?"):
                if sys.platform == "win32":
                    os.startfile(output_dir)
                elif sys.platform == "darwin":
                    subprocess.run(["open", output_dir])
                else:
                    subprocess.run(["xdg-open", output_dir])

    def _get_export_results(self) -> list[ProcessingResult]:
        """Get results for export, excluding flagged items."""
        results = []
        for item in self._queue:
            # Skip excluded items
            if item.get("excluded", False):
                continue

            result = item.get("result")
            if result and result.status == "success":
                if item.get("crop_override"):
                    result = ProcessingResult(
                        file_path=result.file_path, status=result.status,
                        detections=result.detections, primary_detection=result.primary_detection,
                        crop=item["crop_override"], image_size=result.image_size,
                    )
                results.append(result)
        return results

    def run(self):
        self.mainloop()
