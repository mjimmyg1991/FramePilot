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
from .worker import ProcessingResult, ProcessingWorker, write_xmp_for_results, export_cropped_images
from .catalog_browser import CatalogBrowserDialog
from ..crop_calculator import CropRegion, calculate_vertical_crop
from ..presets import (
    SHOOT_TYPES, DESTINATIONS, SubjectStrategy,
    get_shoot_type_names, get_destination_names, get_strategy_names,
    get_shoot_type_by_name, get_destination_by_name, get_recommended_settings,
)

# Configure CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# FramePilot Brand Colors
BRAND_COLORS = {
    "orange": "#FF6B35",
    "orange_dim": "#E55A2B",
    "orange_glow": "rgba(255, 107, 53, 0.15)",
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

# Supported image extensions
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf"
}


class ExportDialog(ctk.CTkToplevel):
    """Dialog for export settings."""

    def __init__(self, parent, file_count: int, default_quality: int = 92, max_dimension: int | None = None):
        super().__init__(parent)
        self.result = None
        self._max_dimension = max_dimension

        self.title("FramePilot - Export")
        self.geometry("520x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=BRAND_COLORS["bg_secondary"])

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 520) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 280) // 2
        self.geometry(f"+{x}+{y}")

        # Content
        self.grid_columnconfigure(0, weight=1)

        # Header
        ctk.CTkLabel(
            self, text=f"Export {file_count} cropped image(s)",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=BRAND_COLORS["text_primary"]
        ).grid(row=0, column=0, padx=24, pady=(24, 16), sticky="w")

        # Output folder frame
        folder_frame = ctk.CTkFrame(self, fg_color="transparent")
        folder_frame.grid(row=1, column=0, padx=24, pady=8, sticky="ew")
        folder_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(folder_frame, text="Output Folder:").grid(row=0, column=0, padx=(0, 12))
        self._folder_var = ctk.StringVar()
        ctk.CTkEntry(folder_frame, textvariable=self._folder_var, width=280).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(folder_frame, text="Browse", width=80, command=self._browse_folder).grid(row=0, column=2)

        # Quality frame
        quality_frame = ctk.CTkFrame(self, fg_color="transparent")
        quality_frame.grid(row=2, column=0, padx=24, pady=8, sticky="w")

        ctk.CTkLabel(quality_frame, text="JPEG Quality:").pack(side="left", padx=(0, 12))
        self._quality_var = ctk.StringVar(value=str(default_quality))
        ctk.CTkEntry(quality_frame, textvariable=self._quality_var, width=60).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(quality_frame, text="(1-100)", text_color="gray").pack(side="left")

        # Max dimension info
        if max_dimension:
            dim_frame = ctk.CTkFrame(self, fg_color="transparent")
            dim_frame.grid(row=3, column=0, padx=24, pady=4, sticky="w")
            ctk.CTkLabel(
                dim_frame, text=f"ℹ Max dimension: {max_dimension}px (based on destination)",
                text_color="gray", font=ctk.CTkFont(size=12)
            ).pack(side="left")

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=4, column=0, padx=24, pady=(24, 24), sticky="e")

        ctk.CTkButton(btn_frame, text="Cancel", width=100,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      border_width=1, border_color=BRAND_COLORS["border"],
                      command=self.destroy).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Export", width=100,
                      fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
                      text_color=BRAND_COLORS["bg_primary"],
                      command=self._on_export).pack(side="left")

    def _browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self._folder_var.set(folder)

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

        self.result = (folder, quality, self._max_dimension)
        self.destroy()


class MainWindow(ctk.CTk):
    """Main application window with CustomTkinter."""

    def __init__(self):
        super().__init__()

        self.title("FramePilot")
        self.geometry("1320x850")
        self.minsize(1100, 700)
        self.configure(fg_color=BRAND_COLORS["bg_primary"])

        # Set app icon
        self._set_app_icon()

        # State
        self._queue: list[dict[str, Any]] = []
        self._selected_index: int = -1
        self._worker = ProcessingWorker(
            on_progress=self._on_progress,
            on_file_complete=self._on_file_complete,
            on_complete=self._on_processing_complete,
        )

        # Settings
        self._aspect_w = ctk.StringVar(value="4")
        self._aspect_h = ctk.StringVar(value="5")
        self._padding = ctk.StringVar(value="15")
        self._strategy = ctk.StringVar(value="Smart Select")
        self._current_preset = "4:5"

        # Smart presets
        self._shoot_type = ctk.StringVar(value="Portraits")
        self._destination = ctk.StringVar(value="Client Gallery")
        self._auto_detecting = False

        self._preset_buttons: dict[str, ctk.CTkButton] = {}

        self._setup_ui()
        self._setup_drag_drop()

    def _set_app_icon(self):
        """Set the application window icon."""
        branding_dir = Path(__file__).parent.parent.parent / "branding"

        # On Windows, use .ico file with iconbitmap for proper taskbar/window icons
        if sys.platform == "win32":
            ico_path = branding_dir / "framepilot.ico"
            if ico_path.exists():
                try:
                    self.iconbitmap(str(ico_path))
                    return
                except Exception:
                    pass  # Fall through to PNG method

        # Fallback: use PNG with iconphoto (works on Linux/macOS)
        png_path = branding_dir / "FramePilot Icon Mark.png"
        if png_path.exists():
            try:
                icon_img = Image.open(png_path)
                icon_img = icon_img.resize((48, 48), Image.Resampling.LANCZOS)
                self._icon_photo = ImageTk.PhotoImage(icon_img)
                self.iconphoto(True, self._icon_photo)
            except Exception:
                pass  # Silently fail if icon can't be loaded

    def _setup_ui(self):
        """Set up the main UI."""
        # Configure grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left sidebar
        self._setup_sidebar()

        # Main content (preview)
        self._setup_main_content()

    def _setup_sidebar(self):
        """Set up the left sidebar with scrollable content."""
        sidebar = ctk.CTkFrame(self, width=380, corner_radius=0, fg_color=BRAND_COLORS["bg_secondary"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(1, weight=1)  # Scrollable area expands
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_propagate(False)

        # App header with logo (fixed at top)
        title_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        title_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")

        # Load and display logo
        self._logo_image = None
        logo_path = Path(__file__).parent.parent.parent / "branding" / "FramePilot Wordmark.png"
        if logo_path.exists():
            try:
                logo_img = Image.open(logo_path)
                # Scale to fit header (max height ~36px)
                aspect = logo_img.width / logo_img.height
                new_height = 36
                new_width = int(new_height * aspect)
                logo_img = logo_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                self._logo_image = ctk.CTkImage(light_image=logo_img, dark_image=logo_img, size=(new_width, new_height))
                ctk.CTkLabel(title_frame, image=self._logo_image, text="").pack(anchor="w")
            except Exception:
                # Fallback to text if logo fails
                ctk.CTkLabel(
                    title_frame, text="FramePilot",
                    font=ctk.CTkFont(family="DM Sans", size=22, weight="bold"),
                    text_color=BRAND_COLORS["orange"]
                ).pack(anchor="w")
        else:
            ctk.CTkLabel(
                title_frame, text="FramePilot",
                font=ctk.CTkFont(family="DM Sans", size=22, weight="bold"),
                text_color=BRAND_COLORS["orange"]
            ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame, text="Smart crops. Zero effort.",
            font=ctk.CTkFont(size=11), text_color=BRAND_COLORS["text_dim"]
        ).pack(anchor="w")

        # Scrollable content area
        scroll_container = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        scroll_container.grid(row=1, column=0, padx=0, pady=0, sticky="nsew")
        scroll_container.grid_columnconfigure(0, weight=1)

        # --- Smart Settings Section ---
        smart_frame = ctk.CTkFrame(scroll_container, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        smart_frame.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(smart_frame, text="Smart Settings", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6))

        # Shoot type dropdown
        shoot_row = ctk.CTkFrame(smart_frame, fg_color="transparent")
        shoot_row.pack(fill="x", padx=12, pady=2)

        ctk.CTkLabel(shoot_row, text="Shoot type:", width=90, anchor="w").pack(side="left")
        self._shoot_type_menu = ctk.CTkOptionMenu(
            shoot_row, variable=self._shoot_type,
            values=get_shoot_type_names(),
            width=170,
            command=self._on_shoot_type_change
        )
        self._shoot_type_menu.pack(side="left", padx=(4, 0))

        self._shoot_desc_label = ctk.CTkLabel(
            smart_frame, text="",
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w"
        )
        self._shoot_desc_label.pack(fill="x", padx=12, pady=(0, 4))

        # Destination dropdown
        dest_row = ctk.CTkFrame(smart_frame, fg_color="transparent")
        dest_row.pack(fill="x", padx=12, pady=2)

        ctk.CTkLabel(dest_row, text="Destination:", width=90, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            dest_row, variable=self._destination,
            values=get_destination_names(),
            width=170,
            command=self._on_destination_change
        ).pack(side="left", padx=(4, 0))

        self._dest_desc_label = ctk.CTkLabel(
            smart_frame, text="",
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w"
        )
        self._dest_desc_label.pack(fill="x", padx=12, pady=(0, 6))

        # Quality slider
        quality_row = ctk.CTkFrame(smart_frame, fg_color="transparent")
        quality_row.pack(fill="x", padx=12, pady=2)

        ctk.CTkLabel(quality_row, text="Quality:", width=60, anchor="w").pack(side="left")
        self._quality_slider = ctk.CTkSlider(
            quality_row, from_=60, to=100, number_of_steps=40,
            command=self._on_quality_change, width=140,
            progress_color=BRAND_COLORS["orange"], button_color=BRAND_COLORS["orange"],
            button_hover_color=BRAND_COLORS["orange_dim"]
        )
        self._quality_slider.set(92)
        self._quality_slider.pack(side="left", padx=4)
        self._quality_label = ctk.CTkLabel(quality_row, text="92%", width=40)
        self._quality_label.pack(side="left")

        self._quality_desc_label = ctk.CTkLabel(
            smart_frame, text="Balanced quality and file size",
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w"
        )
        self._quality_desc_label.pack(fill="x", padx=12, pady=(0, 10))

        self._update_dropdown_descriptions()

        # --- Aspect Ratio Section ---
        ar_frame = ctk.CTkFrame(scroll_container, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        ar_frame.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(ar_frame, text="Aspect Ratio", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6))

        # Preset buttons
        presets_frame = ctk.CTkFrame(ar_frame, fg_color="transparent")
        presets_frame.pack(fill="x", padx=12, pady=(0, 6))

        presets = [("4:5", 4, 5), ("9:16", 9, 16), ("2:3", 2, 3), ("1:1", 1, 1)]
        for label, w, h in presets:
            btn = ctk.CTkButton(
                presets_frame, text=label, width=65, height=28,
                fg_color=(BRAND_COLORS["orange"] if label == "4:5" else BRAND_COLORS["bg_tertiary"]),
                hover_color=(BRAND_COLORS["orange_dim"] if label == "4:5" else BRAND_COLORS["border"]),
                text_color=(BRAND_COLORS["bg_primary"] if label == "4:5" else BRAND_COLORS["text_primary"]),
                command=lambda l=label, w=w, h=h: self._set_preset(l, w, h),
            )
            btn.pack(side="left", padx=2)
            self._preset_buttons[label] = btn

        # Custom AR + Padding in one row
        custom_pad_frame = ctk.CTkFrame(ar_frame, fg_color="transparent")
        custom_pad_frame.pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkLabel(custom_pad_frame, text="Custom:").pack(side="left")
        ctk.CTkEntry(custom_pad_frame, textvariable=self._aspect_w, width=40).pack(side="left", padx=2)
        ctk.CTkLabel(custom_pad_frame, text=":").pack(side="left")
        ctk.CTkEntry(custom_pad_frame, textvariable=self._aspect_h, width=40).pack(side="left", padx=2)

        ctk.CTkLabel(custom_pad_frame, text="  Pad:").pack(side="left", padx=(8, 0))
        self._padding_slider = ctk.CTkSlider(
            custom_pad_frame, from_=0, to=30, number_of_steps=30,
            command=self._on_padding_change, width=80,
            progress_color=BRAND_COLORS["orange"], button_color=BRAND_COLORS["orange"],
            button_hover_color=BRAND_COLORS["orange_dim"]
        )
        self._padding_slider.set(15)
        self._padding_slider.pack(side="left", padx=4)
        self._padding_label = ctk.CTkLabel(custom_pad_frame, text="15%", width=35)
        self._padding_label.pack(side="left")

        # --- Subject Selection ---
        strat_frame = ctk.CTkFrame(scroll_container, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        strat_frame.pack(fill="x", padx=12, pady=8)

        strat_row = ctk.CTkFrame(strat_frame, fg_color="transparent")
        strat_row.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(strat_row, text="Subject:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkOptionMenu(
            strat_row, variable=self._strategy,
            values=get_strategy_names(),
            width=160,
            command=self._on_strategy_change
        ).pack(side="left", padx=8)

        self._strategy_desc_label = ctk.CTkLabel(
            strat_frame, text="AI picks the best subject automatically",
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w"
        )
        self._strategy_desc_label.pack(fill="x", padx=12, pady=(0, 10))

        # --- File Queue ---
        queue_frame = ctk.CTkFrame(scroll_container, fg_color=BRAND_COLORS["bg_card"], border_width=1, border_color=BRAND_COLORS["border"])
        queue_frame.pack(fill="x", padx=12, pady=8)

        # Queue header with buttons
        queue_header = ctk.CTkFrame(queue_frame, fg_color="transparent")
        queue_header.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(queue_header, text="File Queue", font=ctk.CTkFont(weight="bold")).pack(side="left")

        btn_row = ctk.CTkFrame(queue_header, fg_color="transparent")
        btn_row.pack(side="right")
        ctk.CTkButton(btn_row, text="+Files", width=55, height=24,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      command=self._add_files).pack(side="left", padx=1)
        ctk.CTkButton(btn_row, text="+Folder", width=60, height=24,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      command=self._add_folder).pack(side="left", padx=1)
        ctk.CTkButton(btn_row, text="Clear", width=50, height=24,
                      fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                      command=self._clear_queue).pack(side="left", padx=1)

        # Import from catalog button
        ctk.CTkButton(
            queue_frame, text="Import from Catalog...",
            height=28, fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self._open_catalog_browser
        ).pack(fill="x", padx=12, pady=(0, 6))

        # Queue list (fixed height, internal scroll)
        self._queue_scroll = ctk.CTkScrollableFrame(queue_frame, fg_color=BRAND_COLORS["bg_primary"], height=120)
        self._queue_scroll.pack(fill="x", padx=12, pady=(0, 10))
        self._queue_scroll.grid_columnconfigure(0, weight=1)

        self._drop_hint = ctk.CTkLabel(
            self._queue_scroll, text="Drag & drop files here",
            text_color="gray", font=ctk.CTkFont(size=11)
        )
        self._drop_hint.grid(row=0, column=0, pady=20)

        # --- Actions (fixed at bottom) ---
        action_frame = ctk.CTkFrame(sidebar, fg_color=BRAND_COLORS["bg_secondary"])
        action_frame.grid(row=2, column=0, padx=12, pady=(4, 8), sticky="ew")

        self._process_btn = ctk.CTkButton(
            action_frame, text="Process All", height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=BRAND_COLORS["orange"],
            hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"],
            command=self._start_processing
        )
        self._process_btn.pack(fill="x", padx=8, pady=(8, 4))

        btn_row2 = ctk.CTkFrame(action_frame, fg_color="transparent")
        btn_row2.pack(fill="x", padx=8, pady=4)

        self._write_xmp_btn = ctk.CTkButton(
            btn_row2, text="Write XMP", height=32,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            border_width=1, border_color=BRAND_COLORS["border"],
            command=self._write_xmp, state="disabled"
        )
        self._write_xmp_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))

        self._export_btn = ctk.CTkButton(
            btn_row2, text="Export JPEGs", height=32,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            border_width=1, border_color=BRAND_COLORS["border"],
            command=self._export_images, state="disabled"
        )
        self._export_btn.pack(side="left", expand=True, fill="x", padx=(2, 0))

        # --- Progress (fixed at bottom) ---
        progress_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        progress_frame.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")

        self._progress_bar = ctk.CTkProgressBar(progress_frame, height=8,
                                                 progress_color=BRAND_COLORS["orange"],
                                                 fg_color=BRAND_COLORS["bg_tertiary"])
        self._progress_bar.pack(fill="x", pady=(0, 4))
        self._progress_bar.set(0)

        self._status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(progress_frame, textvariable=self._status_var,
                     text_color=BRAND_COLORS["text_dim"], font=ctk.CTkFont(size=11)).pack(fill="x")

    def _setup_main_content(self):
        """Set up the main preview area."""
        main_frame = ctk.CTkFrame(self, fg_color=BRAND_COLORS["bg_primary"], corner_radius=0)
        main_frame.grid(row=0, column=1, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        # Header with controls
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(16, 8), sticky="ew")

        ctk.CTkLabel(header, text="Preview", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=BRAND_COLORS["text_primary"]).pack(side="left")

        # Per-image controls
        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.pack(side="right")

        self._flip_ar_btn = ctk.CTkButton(
            controls, text="Flip to Landscape", width=140,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            border_width=1, border_color=BRAND_COLORS["border"],
            command=self._flip_aspect_ratio, state="disabled"
        )
        self._flip_ar_btn.pack(side="left", padx=4)

        self._recenter_btn = ctk.CTkButton(
            controls, text="Re-center", width=100,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            border_width=1, border_color=BRAND_COLORS["border"],
            command=self._recenter_crop, state="disabled"
        )
        self._recenter_btn.pack(side="left", padx=4)

        # Preview widget (using tk Canvas inside CTk)
        preview_container = ctk.CTkFrame(main_frame, fg_color=BRAND_COLORS["bg_secondary"],
                                          border_width=1, border_color=BRAND_COLORS["border"])
        preview_container.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self._preview = PreviewWidget(
            preview_container,
            on_crop_changed=self._on_crop_dragged,
            on_empty_click=self._add_files,
        )
        self._preview.pack(fill="both", expand=True, padx=2, pady=2)

    def _setup_drag_drop(self):
        """Set up drag and drop functionality."""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            # TkinterDnD needs to be initialized differently with CTk
            # We register on the scrollable frame's interior
            self._queue_scroll._parent_canvas.drop_target_register(DND_FILES)
            self._queue_scroll._parent_canvas.dnd_bind("<<Drop>>", self._on_drop)
        except (ImportError, Exception):
            pass

    def _on_drop(self, event):
        """Handle file drop."""
        files_str = event.data
        if files_str.startswith("{"):
            files = []
            i = 0
            while i < len(files_str):
                if files_str[i] == "{":
                    end = files_str.index("}", i)
                    files.append(files_str[i + 1:end])
                    i = end + 2
                elif files_str[i] != " ":
                    end = files_str.find(" ", i)
                    if end == -1:
                        end = len(files_str)
                    files.append(files_str[i:end])
                    i = end + 1
                else:
                    i += 1
        else:
            files = files_str.split()

        for f in files:
            path = Path(f)
            if path.is_dir():
                self._add_folder_path(path)
            elif path.suffix.lower() in SUPPORTED_EXTENSIONS:
                self._add_file_to_queue(path)

    def _on_padding_change(self, value):
        """Handle padding slider change."""
        val = int(value)
        self._padding.set(str(val))
        self._padding_label.configure(text=f"{val}%")

    def _on_quality_change(self, value):
        """Handle quality slider change."""
        val = int(value)
        self._quality_label.configure(text=f"{val}%")

        # Update description based on quality level
        if val >= 95:
            desc = "Maximum quality, larger files"
        elif val >= 88:
            desc = "Balanced quality and file size"
        elif val >= 80:
            desc = "Good quality, smaller files"
        else:
            desc = "Compressed, smallest files"
        self._quality_desc_label.configure(text=desc)

    def _on_strategy_change(self, value: str):
        """Handle subject selection strategy change."""
        strategy_descriptions = {
            "Smart Select": "AI picks the sharpest, most confident subject",
            "Main Subject": "Focuses on the largest in-focus person",
            "Center Stage": "Prioritizes centered, in-focus subjects",
        }
        self._strategy_desc_label.configure(text=strategy_descriptions.get(value, ""))

    def _update_dropdown_descriptions(self):
        """Update description labels for current dropdown selections."""
        # Shoot type descriptions
        shoot_descriptions = {
            "Wedding & Events": "Optimizes for couples and groups at ceremonies",
            "Sports & Action": "Tracks fast-moving athletes and action shots",
            "Portraits": "Perfect for headshots and individual subjects",
            "Street & Travel": "Handles candid moments and varied scenes",
            "Auto-Detect": "AI analyzes your photos to pick the best mode",
        }
        shoot_name = self._shoot_type.get()
        self._shoot_desc_label.configure(text=shoot_descriptions.get(shoot_name, ""))

        # Destination descriptions
        dest_descriptions = {
            "Instagram / Social": "Optimized for fast uploads, good enough quality",
            "Client Gallery": "High quality files your clients will love",
            "Print / Magazine": "Maximum quality for professional printing",
            "Web / Portfolio": "Sharp images that load quickly online",
        }
        dest_name = self._destination.get()
        self._dest_desc_label.configure(text=dest_descriptions.get(dest_name, ""))

        # Update quality slider to match destination
        dest_preset = get_destination_by_name(dest_name)
        if dest_preset:
            self._quality_slider.set(dest_preset.jpeg_quality)
            self._quality_label.configure(text=f"{dest_preset.jpeg_quality}%")
            self._on_quality_change(dest_preset.jpeg_quality)

    def _on_shoot_type_change(self, value: str):
        """Handle shoot type selection change."""
        self._update_dropdown_descriptions()
        if value == "Auto-Detect":
            self._run_auto_detect()
        else:
            self._apply_shoot_type_preset(value)

    def _on_destination_change(self, value: str):
        """Handle destination selection change."""
        self._update_dropdown_descriptions()

    def _apply_shoot_type_preset(self, shoot_type_name: str):
        """Apply settings from a shoot type preset."""
        preset = get_shoot_type_by_name(shoot_type_name)
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

        # Apply suggested aspect ratio
        if preset.suggested_aspects:
            w, h = preset.suggested_aspects[0]
            self._aspect_w.set(str(w))
            self._aspect_h.set(str(h))
            preset_label = f"{w}:{h}"
            if preset_label in self._preset_buttons:
                self._set_preset(preset_label, w, h)

    def _run_auto_detect(self):
        """Run auto-detection on queued images."""
        if self._auto_detecting:
            return

        if not self._queue:
            messagebox.showinfo("No Images", "Add some images to auto-detect shoot type.")
            self._shoot_type.set("Portraits")
            return

        self._auto_detecting = True
        self._status_var.set("Analyzing images...")
        self._shoot_type_menu.configure(state="disabled")

        # Run in background thread
        def detect():
            try:
                from ..scene_classifier import auto_detect_shoot_type

                image_paths = [item["path"] for item in self._queue[:5]]  # Sample first 5

                def progress(current, total):
                    self.after(0, lambda: self._status_var.set(f"Analyzing image {current+1}/{total}..."))

                category_key, preset, confidence, scores = auto_detect_shoot_type(image_paths, progress)

                # Update UI on main thread
                self.after(0, lambda: self._auto_detect_complete(preset.name, confidence, scores))

            except ImportError as e:
                self.after(0, lambda: self._auto_detect_failed(f"CLIP not installed: {e}"))
            except Exception as e:
                self.after(0, lambda: self._auto_detect_failed(str(e)))

        threading.Thread(target=detect, daemon=True).start()

    def _auto_detect_complete(self, detected_type: str, confidence: float, scores: dict):
        """Handle auto-detection completion."""
        self._auto_detecting = False
        self._shoot_type_menu.configure(state="normal")

        self._shoot_type.set(detected_type)
        self._apply_shoot_type_preset(detected_type)
        self._update_dropdown_descriptions()

        self._status_var.set(f"Detected: {detected_type} ({confidence:.0%} confidence)")

    def _auto_detect_failed(self, error: str):
        """Handle auto-detection failure."""
        self._auto_detecting = False
        self._shoot_type_menu.configure(state="normal")
        self._shoot_type.set("Portraits")
        self._status_var.set(f"Auto-detect failed: {error}")

    def _set_preset(self, label: str, w: int, h: int):
        """Set aspect ratio from preset."""
        self._aspect_w.set(str(w))
        self._aspect_h.set(str(h))
        self._current_preset = label

        # Update button colors
        for btn_label, btn in self._preset_buttons.items():
            if btn_label == label:
                btn.configure(fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
                              text_color=BRAND_COLORS["bg_primary"])
            else:
                btn.configure(fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
                              text_color=BRAND_COLORS["text_primary"])

        # Update preview
        self._preview.set_aspect_ratio((w, h), is_landscape=False)

    def _flip_aspect_ratio(self):
        """Flip AR between portrait and landscape for current image."""
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return

        item = self._queue[self._selected_index]
        result = item.get("result")
        if not result or not result.crop:
            return

        is_landscape = item.get("is_landscape", False)
        is_landscape = not is_landscape
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
        self._preview.set_aspect_ratio(self._get_aspect_ratio(), is_landscape=is_landscape)
        self._preview.update_crop(new_crop, result.primary_detection)

        if is_landscape:
            self._flip_ar_btn.configure(text="Flip to Portrait")
        else:
            self._flip_ar_btn.configure(text="Flip to Landscape")

    def _recenter_crop(self):
        """Re-center crop on detected subject."""
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
        self._preview.update_crop(new_crop, result.primary_detection)

    def _on_crop_dragged(self, crop: CropRegion):
        """Handle user dragging the crop in preview."""
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return
        self._queue[self._selected_index]["crop_override"] = crop

    def _get_aspect_ratio(self) -> tuple[int, int]:
        """Get current aspect ratio."""
        try:
            return (int(self._aspect_w.get()), int(self._aspect_h.get()))
        except ValueError:
            return (4, 5)

    def _add_files(self):
        filetypes = [
            ("Image files", " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)),
            ("All files", "*.*"),
        ]
        files = filedialog.askopenfilenames(filetypes=filetypes)
        for f in files:
            self._add_file_to_queue(Path(f))

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self._add_folder_path(Path(folder))

    def _add_folder_path(self, folder: Path):
        for ext in SUPPORTED_EXTENSIONS:
            for f in folder.glob(f"*{ext}"):
                self._add_file_to_queue(f)
            for f in folder.glob(f"*{ext.upper()}"):
                self._add_file_to_queue(f)

    def _open_catalog_browser(self):
        """Open the catalog browser dialog."""
        def on_import(paths: list[Path]):
            for path in paths:
                self._add_file_to_queue(path)
            self._status_var.set(f"Imported {len(paths)} images from catalog")

        CatalogBrowserDialog(self, on_import=on_import)

    def _add_file_to_queue(self, path: Path):
        for item in self._queue:
            if item["path"] == path:
                return

        item = {
            "path": path,
            "status": "pending",
            "result": None,
            "crop_override": None,
            "is_landscape": False,
        }
        self._queue.append(item)
        self._update_queue_display()

    def _clear_queue(self):
        self._queue.clear()
        self._selected_index = -1
        self._update_queue_display()
        self._preview.clear()
        self._write_xmp_btn.configure(state="disabled")
        self._export_btn.configure(state="disabled")
        self._flip_ar_btn.configure(state="disabled")
        self._recenter_btn.configure(state="disabled")

    def _update_queue_display(self):
        """Update the queue display."""
        # Clear existing items
        for widget in self._queue_scroll.winfo_children():
            widget.destroy()

        if not self._queue:
            self._drop_hint = ctk.CTkLabel(
                self._queue_scroll, text="Drag & drop files here\nor use buttons above",
                text_color="gray", font=ctk.CTkFont(size=12)
            )
            self._drop_hint.grid(row=0, column=0, pady=40)
            return

        status_icons = {
            "pending": ("○", BRAND_COLORS["text_dim"]),
            "processing": ("◐", BRAND_COLORS["orange"]),
            "success": ("●", BRAND_COLORS["success"]),
            "no_subject": ("◌", BRAND_COLORS["text_secondary"]),
            "error": ("✕", BRAND_COLORS["error"]),
        }

        for i, item in enumerate(self._queue):
            icon, color = status_icons.get(item["status"], ("○", "gray"))

            row_frame = ctk.CTkFrame(self._queue_scroll, fg_color="transparent", height=32)
            row_frame.grid(row=i, column=0, sticky="ew", pady=1)
            row_frame.grid_columnconfigure(1, weight=1)

            # Make clickable
            row_frame.bind("<Button-1>", lambda e, idx=i: self._select_queue_item(idx))

            icon_label = ctk.CTkLabel(row_frame, text=icon, text_color=color, width=24)
            icon_label.grid(row=0, column=0, padx=(8, 4))
            icon_label.bind("<Button-1>", lambda e, idx=i: self._select_queue_item(idx))

            name_label = ctk.CTkLabel(
                row_frame, text=item["path"].name,
                font=ctk.CTkFont(size=12), anchor="w"
            )
            name_label.grid(row=0, column=1, sticky="w", padx=4)
            name_label.bind("<Button-1>", lambda e, idx=i: self._select_queue_item(idx))

            # Highlight selected
            if i == self._selected_index:
                row_frame.configure(fg_color=BRAND_COLORS["bg_tertiary"])

    def _select_queue_item(self, index: int):
        """Select a queue item."""
        self._selected_index = index
        self._update_queue_display()
        self._on_queue_select()

    def _on_queue_select(self):
        """Handle queue item selection."""
        if self._selected_index < 0 or self._selected_index >= len(self._queue):
            return

        item = self._queue[self._selected_index]
        result = item.get("result")
        crop = item.get("crop_override") or (result.crop if result else None)
        detection = result.primary_detection if result else None
        is_landscape = item.get("is_landscape", False)

        self._preview.set_aspect_ratio(self._get_aspect_ratio(), is_landscape=is_landscape)
        self._preview.load_image(item["path"], crop=crop, detection=detection)

        has_result = result is not None and result.status == "success"
        self._flip_ar_btn.configure(state="normal" if has_result else "disabled")
        self._recenter_btn.configure(state="normal" if has_result else "disabled")

        if is_landscape:
            self._flip_ar_btn.configure(text="Flip to Portrait")
        else:
            self._flip_ar_btn.configure(text="Flip to Landscape")

    def _start_processing(self):
        if not self._queue:
            messagebox.showinfo("No Files", "Add some files to the queue first.")
            return

        if self._worker.is_running:
            self._worker.cancel()
            self._process_btn.configure(text="Process All")
            self._status_var.set("Cancelled")
            return

        for item in self._queue:
            item["status"] = "pending"
            item["result"] = None
            item["crop_override"] = None
            item["is_landscape"] = False
        self._update_queue_display()

        aspect_ratio = self._get_aspect_ratio()
        try:
            padding = float(self._padding.get()) / 100
        except ValueError:
            padding = 0.15

        # Convert friendly strategy name to technical name
        strategy_display = self._strategy.get()
        strategy_technical = SubjectStrategy.from_display_name(strategy_display).value

        files = [item["path"] for item in self._queue]
        self._worker.start_processing(files, aspect_ratio, padding, strategy_technical)

        self._process_btn.configure(text="Cancel")
        self._write_xmp_btn.configure(state="disabled")
        self._export_btn.configure(state="disabled")

    def _on_progress(self, current: int, total: int, message: str):
        self.after(0, self._update_progress, current, total, message)

    def _update_progress(self, current: int, total: int, message: str):
        if total > 0:
            self._progress_bar.set(current / total)
        self._status_var.set(message)

    def _on_file_complete(self, result: ProcessingResult):
        self.after(0, self._update_file_result, result)

    def _update_file_result(self, result: ProcessingResult):
        for item in self._queue:
            if item["path"] == result.file_path:
                item["status"] = result.status
                item["result"] = result
                break

        self._update_queue_display()

        if self._selected_index >= 0 and self._queue[self._selected_index]["path"] == result.file_path:
            self._on_queue_select()

    def _on_processing_complete(self, results: list[ProcessingResult]):
        self.after(0, self._processing_complete, results)

    def _processing_complete(self, results: list[ProcessingResult]):
        self._process_btn.configure(text="Process All")

        success = sum(1 for r in results if r.status == "success")
        no_subject = sum(1 for r in results if r.status == "no_subject")
        errors = sum(1 for r in results if r.status == "error")

        self._status_var.set(f"Done: {success} ✓  {no_subject} no subject  {errors} errors")

        if success > 0:
            self._write_xmp_btn.configure(state="normal")
            self._export_btn.configure(state="normal")

    def _write_xmp(self):
        results = []
        for item in self._queue:
            result = item.get("result")
            if result and result.status == "success":
                if item.get("crop_override"):
                    result = ProcessingResult(
                        file_path=result.file_path,
                        status=result.status,
                        detections=result.detections,
                        primary_detection=result.primary_detection,
                        crop=item["crop_override"],
                        image_size=result.image_size,
                    )
                results.append(result)

        if not results:
            messagebox.showinfo("No Results", "Process files first.")
            return

        self._status_var.set("Writing XMP files...")
        xmp_results = write_xmp_for_results(
            results,
            on_progress=lambda c, t: self._update_progress(c, t, f"Writing XMP {c}/{t}..."),
        )

        success = sum(1 for _, ok, _ in xmp_results if ok)
        self._status_var.set(f"Wrote {success} XMP files")

        if success > 0:
            messagebox.showinfo(
                "XMP Files Written",
                f"Successfully wrote {success} XMP sidecar files.\n\n"
                "In Lightroom Classic:\n"
                "1. Select the photos\n"
                "2. Metadata → Read Metadata from Files",
            )

    def _export_images(self):
        results = []
        for item in self._queue:
            result = item.get("result")
            if result and result.status == "success":
                if item.get("crop_override"):
                    result = ProcessingResult(
                        file_path=result.file_path,
                        status=result.status,
                        detections=result.detections,
                        primary_detection=result.primary_detection,
                        crop=item["crop_override"],
                        image_size=result.image_size,
                    )
                results.append(result)

        if not results:
            messagebox.showinfo("No Results", "Process files first.")
            return

        # Get quality from slider and max_dimension from destination preset
        default_quality = int(self._quality_slider.get())
        dest_preset = get_destination_by_name(self._destination.get())
        max_dimension = dest_preset.max_dimension if dest_preset else None

        dialog = ExportDialog(self, len(results), default_quality=default_quality, max_dimension=max_dimension)
        self.wait_window(dialog)

        if not dialog.result:
            return

        output_dir, quality, max_dim = dialog.result

        self._status_var.set("Exporting cropped images...")
        export_results = export_cropped_images(
            results,
            output_dir=Path(output_dir),
            jpeg_quality=quality,
            max_dimension=max_dim,
            on_progress=lambda c, t: self._update_progress(c, t, f"Exporting {c}/{t}..."),
        )

        success = sum(1 for _, ok, _ in export_results if ok)
        self._status_var.set(f"Exported {success} images")

        if success > 0:
            if messagebox.askyesno(
                "Export Complete",
                f"Exported {success} cropped images to:\n{output_dir}\n\nOpen folder?",
            ):
                if sys.platform == "win32":
                    os.startfile(output_dir)
                elif sys.platform == "darwin":
                    subprocess.run(["open", output_dir])
                else:
                    subprocess.run(["xdg-open", output_dir])

    def _open_output_folder(self):
        if not self._queue:
            return

        folder = self._queue[0]["path"].parent
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.run(["open", folder])
        else:
            subprocess.run(["xdg-open", folder])

    def run(self):
        self.mainloop()
