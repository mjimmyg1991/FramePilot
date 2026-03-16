"""One-click Lightroom wizard — guided flow from image selection to crop application."""

from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from ..presets import (
    get_shoot_type_names, get_strategy_names, get_shoot_type_by_name,
    SubjectStrategy, get_recommended_settings,
)
from .worker import ProcessingResult, ProcessingWorker, write_xmp_for_results, export_cropped_images
from ..xmp_handler import write_signal_file

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

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf",
}


@dataclass
class WizardState:
    """Tracks wizard progress and configuration."""

    files: list[Path] = field(default_factory=list)
    aspect_ratio: tuple[int, int] = (4, 5)
    padding: float = 0.15
    strategy: str = "highest_confidence"
    results: list[ProcessingResult] = field(default_factory=list)
    output_mode: str = "xmp"  # "xmp" or "export"
    export_dir: str = ""


class LightroomWizard(ctk.CTkToplevel):
    """Multi-step wizard for guided Lightroom crop workflow."""

    def __init__(self, parent, on_complete: Callable[[list[ProcessingResult]], None] | None = None):
        super().__init__(parent)
        self._on_complete = on_complete
        self._state = WizardState()
        self._current_step = 0
        self._worker: ProcessingWorker | None = None

        self.title("FramePilot - Quick Start Wizard")
        self.geometry("700x550")
        self.minsize(600, 450)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=BRAND_COLORS["bg_secondary"])

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 700) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 550) // 2
        self.geometry(f"+{x}+{y}")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Step indicator
        self._step_frame = ctk.CTkFrame(self, fg_color="transparent", height=40)
        self._step_frame.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 0))
        self._step_labels: list[ctk.CTkLabel] = []
        for i, name in enumerate(["Select", "Configure", "Review", "Apply"]):
            lbl = ctk.CTkLabel(
                self._step_frame, text=f"  {i+1}. {name}  ",
                font=ctk.CTkFont(size=12),
                text_color=BRAND_COLORS["text_dim"],
            )
            lbl.pack(side="left", padx=4)
            self._step_labels.append(lbl)

        # Content area
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.grid(row=1, column=0, sticky="nsew", padx=24, pady=12)
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        # Navigation
        nav = ctk.CTkFrame(self, fg_color="transparent", height=50)
        nav.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 16))

        self._back_btn = ctk.CTkButton(
            nav, text="Back", width=100,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self._go_back,
        )
        self._back_btn.pack(side="left")

        self._next_btn = ctk.CTkButton(
            nav, text="Next", width=120,
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"], font=ctk.CTkFont(weight="bold"),
            command=self._go_next,
        )
        self._next_btn.pack(side="right")

        ctk.CTkButton(
            nav, text="Cancel", width=80,
            fg_color="transparent", hover_color=BRAND_COLORS["bg_tertiary"],
            command=self.destroy,
        ).pack(side="right", padx=8)

        self._show_step(0)

    def _show_step(self, step: int):
        """Display the given step."""
        self._current_step = step

        # Update step indicator
        for i, lbl in enumerate(self._step_labels):
            if i == step:
                lbl.configure(text_color=BRAND_COLORS["orange"], font=ctk.CTkFont(size=12, weight="bold"))
            elif i < step:
                lbl.configure(text_color=BRAND_COLORS["success"], font=ctk.CTkFont(size=12))
            else:
                lbl.configure(text_color=BRAND_COLORS["text_dim"], font=ctk.CTkFont(size=12))

        # Clear content
        for w in self._content.winfo_children():
            w.destroy()

        # Update nav buttons
        self._back_btn.configure(state="normal" if step > 0 else "disabled")
        self._next_btn.configure(
            text="Process" if step == 1 else "Apply" if step == 3 else "Next",
            state="normal",
        )

        # Build step UI
        if step == 0:
            self._build_step_select()
        elif step == 1:
            self._build_step_configure()
        elif step == 2:
            self._build_step_review()
        elif step == 3:
            self._build_step_apply()

    def _go_back(self):
        if self._current_step > 0:
            self._show_step(self._current_step - 1)

    def _go_next(self):
        step = self._current_step

        if step == 0:
            # Validate: files selected
            if not self._state.files:
                messagebox.showinfo("No Images", "Add some images first.", parent=self)
                return
            self._show_step(1)

        elif step == 1:
            # Read config and start processing
            self._read_config()
            self._start_processing()

        elif step == 2:
            self._show_step(3)

        elif step == 3:
            self._apply_results()

    # ==================== Step 1: Select ====================

    def _build_step_select(self):
        frame = ctk.CTkFrame(self._content, fg_color=BRAND_COLORS["bg_card"],
                             border_width=1, border_color=BRAND_COLORS["border"])
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame, text="Select Images",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(16, 4))

        ctk.CTkLabel(
            frame, text="Add files or a folder of images to crop.",
            text_color=BRAND_COLORS["text_dim"],
        ).pack(anchor="w", padx=16, pady=(0, 12))

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=4)

        ctk.CTkButton(
            btn_row, text="+ Files", width=100,
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"],
            command=self._add_files,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="+ Folder", width=100,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self._add_folder,
        ).pack(side="left")

        self._file_count_lbl = ctk.CTkLabel(
            frame,
            text=f"{len(self._state.files)} images selected",
            text_color=BRAND_COLORS["text_secondary"],
        )
        self._file_count_lbl.pack(anchor="w", padx=16, pady=(12, 0))

        # File list
        self._file_list = ctk.CTkScrollableFrame(frame, fg_color=BRAND_COLORS["bg_primary"])
        self._file_list.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self._refresh_file_list()

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.dng *.cr2 *.cr3 *.nef *.arw *.raf")],
        )
        for p in paths:
            path = Path(p)
            if path not in self._state.files:
                self._state.files.append(path)
        self._refresh_file_list()

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            for ext in SUPPORTED_EXTENSIONS:
                for f in Path(folder).glob(f"*{ext}"):
                    if f not in self._state.files:
                        self._state.files.append(f)
                for f in Path(folder).glob(f"*{ext.upper()}"):
                    if f not in self._state.files:
                        self._state.files.append(f)
        self._refresh_file_list()

    def _refresh_file_list(self):
        if hasattr(self, "_file_count_lbl"):
            self._file_count_lbl.configure(text=f"{len(self._state.files)} images selected")
        if hasattr(self, "_file_list"):
            for w in self._file_list.winfo_children():
                w.destroy()
            for path in self._state.files[:100]:  # Show max 100
                ctk.CTkLabel(
                    self._file_list, text=path.name,
                    text_color=BRAND_COLORS["text_secondary"],
                    font=ctk.CTkFont(size=11),
                ).pack(anchor="w", padx=8, pady=1)

    # ==================== Step 2: Configure ====================

    def _build_step_configure(self):
        frame = ctk.CTkFrame(self._content, fg_color=BRAND_COLORS["bg_card"],
                             border_width=1, border_color=BRAND_COLORS["border"])
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame, text="Configure Settings",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(16, 12))

        # Shoot Type
        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row1, text="Shoot Type:", width=100).pack(side="left")
        self._w_shoot = ctk.StringVar(value="Auto-Detect")
        ctk.CTkOptionMenu(row1, variable=self._w_shoot, values=get_shoot_type_names(), width=200).pack(side="left")

        # Aspect Ratio
        row2 = ctk.CTkFrame(frame, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row2, text="Aspect Ratio:", width=100).pack(side="left")
        self._w_aspect = ctk.StringVar(value="4:5")
        ctk.CTkOptionMenu(row2, variable=self._w_aspect,
                          values=["4:5", "9:16", "2:3", "1:1", "5:7", "3:4"], width=200).pack(side="left")

        # Padding
        row3 = ctk.CTkFrame(frame, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row3, text="Padding:", width=100).pack(side="left")
        self._w_padding = ctk.StringVar(value="15")
        ctk.CTkEntry(row3, textvariable=self._w_padding, width=60).pack(side="left")
        ctk.CTkLabel(row3, text="%").pack(side="left", padx=4)

        # Strategy
        row4 = ctk.CTkFrame(frame, fg_color="transparent")
        row4.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row4, text="Strategy:", width=100).pack(side="left")
        self._w_strategy = ctk.StringVar(value="Smart Select")
        ctk.CTkOptionMenu(row4, variable=self._w_strategy, values=get_strategy_names(), width=200).pack(side="left")

        ctk.CTkLabel(
            frame,
            text=f"Ready to process {len(self._state.files)} images. Click 'Process' to start.",
            text_color=BRAND_COLORS["text_dim"],
        ).pack(anchor="w", padx=16, pady=(24, 16))

    def _read_config(self):
        """Read configuration from wizard step 2."""
        # Apply shoot type preset
        shoot = get_shoot_type_by_name(self._w_shoot.get())
        if shoot:
            settings = get_recommended_settings(self._w_shoot.get())
            self._state.strategy = settings["strategy"]
            self._state.padding = settings["padding"]

        # Override with explicit selections
        try:
            parts = self._w_aspect.get().split(":")
            self._state.aspect_ratio = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass

        try:
            self._state.padding = int(self._w_padding.get()) / 100
        except ValueError:
            pass

        strategy = SubjectStrategy.from_display_name(self._w_strategy.get())
        self._state.strategy = strategy.value

    # ==================== Processing ====================

    def _start_processing(self):
        """Start processing in background thread, then show review."""
        self._next_btn.configure(state="disabled", text="Processing...")

        # Show progress
        for w in self._content.winfo_children():
            w.destroy()

        progress_frame = ctk.CTkFrame(self._content, fg_color=BRAND_COLORS["bg_card"],
                                      border_width=1, border_color=BRAND_COLORS["border"])
        progress_frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            progress_frame, text="Processing...",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(40, 8))

        self._w_progress_label = ctk.CTkLabel(
            progress_frame, text="Loading detection model...",
            text_color=BRAND_COLORS["text_dim"],
        )
        self._w_progress_label.pack(pady=4)

        self._w_progress_bar = ctk.CTkProgressBar(
            progress_frame, width=400, height=8,
            progress_color=BRAND_COLORS["orange"],
            fg_color=BRAND_COLORS["bg_tertiary"],
        )
        self._w_progress_bar.pack(pady=12)
        self._w_progress_bar.set(0)

        self._worker = ProcessingWorker(
            on_progress=lambda c, t, m: self.after(0, self._w_on_progress, c, t, m),
            on_complete=lambda r: self.after(0, self._w_on_complete, r),
        )
        self._worker.start_processing(
            files=self._state.files,
            aspect_ratio=self._state.aspect_ratio,
            padding=self._state.padding,
            strategy=self._state.strategy,
        )

    def _w_on_progress(self, current: int, total: int, message: str):
        if hasattr(self, "_w_progress_label"):
            self._w_progress_label.configure(text=message)
        if hasattr(self, "_w_progress_bar") and total > 0:
            self._w_progress_bar.set(current / total)

    def _w_on_complete(self, results: list[ProcessingResult]):
        self._state.results = results
        self._show_step(2)

    # ==================== Step 3: Review ====================

    def _build_step_review(self):
        frame = ctk.CTkFrame(self._content, fg_color=BRAND_COLORS["bg_card"],
                             border_width=1, border_color=BRAND_COLORS["border"])
        frame.pack(fill="both", expand=True)

        success = sum(1 for r in self._state.results if r.status == "success")
        no_subject = sum(1 for r in self._state.results if r.status == "no_subject")
        errors = sum(1 for r in self._state.results if r.status == "error")

        ctk.CTkLabel(
            frame, text="Review Results",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(16, 8))

        stats_text = f"{success} cropped successfully"
        if no_subject:
            stats_text += f"  |  {no_subject} no subject found"
        if errors:
            stats_text += f"  |  {errors} errors"

        ctk.CTkLabel(
            frame, text=stats_text,
            text_color=BRAND_COLORS["text_secondary"],
        ).pack(anchor="w", padx=16, pady=(0, 8))

        # Result list
        result_list = ctk.CTkScrollableFrame(frame, fg_color=BRAND_COLORS["bg_primary"])
        result_list.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        for result in self._state.results:
            color = {
                "success": BRAND_COLORS["success"],
                "no_subject": "#EAB308",
                "error": BRAND_COLORS["error"],
            }.get(result.status, BRAND_COLORS["text_dim"])

            status_icon = {"success": "OK", "no_subject": "SKIP", "error": "ERR"}.get(result.status, "?")

            row = ctk.CTkFrame(result_list, fg_color="transparent")
            row.pack(fill="x", pady=1)

            ctk.CTkLabel(
                row, text=status_icon, width=40,
                text_color=color, font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="left")

            ctk.CTkLabel(
                row, text=result.file_path.name,
                text_color=BRAND_COLORS["text_secondary"],
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=4)

    # ==================== Step 4: Apply ====================

    def _build_step_apply(self):
        frame = ctk.CTkFrame(self._content, fg_color=BRAND_COLORS["bg_card"],
                             border_width=1, border_color=BRAND_COLORS["border"])
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame, text="Apply to Lightroom",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(16, 12))

        self._w_output_mode = ctk.StringVar(value="xmp")

        # XMP option
        xmp_frame = ctk.CTkFrame(frame, fg_color=BRAND_COLORS["bg_primary"],
                                 border_width=1, border_color=BRAND_COLORS["border"])
        xmp_frame.pack(fill="x", padx=16, pady=4)

        ctk.CTkRadioButton(
            xmp_frame, text="Apply Crops in Lightroom (XMP sidecars)",
            variable=self._w_output_mode, value="xmp",
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
        ).pack(anchor="w", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            xmp_frame,
            text="Non-destructive. Updates your existing catalog. (Recommended)",
            text_color=BRAND_COLORS["text_dim"], font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=32, pady=(0, 12))

        # Export option
        export_frame = ctk.CTkFrame(frame, fg_color=BRAND_COLORS["bg_primary"],
                                    border_width=1, border_color=BRAND_COLORS["border"])
        export_frame.pack(fill="x", padx=16, pady=4)

        ctk.CTkRadioButton(
            export_frame, text="Export cropped copies (JPEG)",
            variable=self._w_output_mode, value="export",
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
        ).pack(anchor="w", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            export_frame,
            text="Creates new cropped files for sharing outside Lightroom.",
            text_color=BRAND_COLORS["text_dim"], font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=32, pady=(0, 12))

        success_count = sum(1 for r in self._state.results if r.status == "success")
        ctk.CTkLabel(
            frame,
            text=f"Click 'Apply' to process {success_count} image(s).",
            text_color=BRAND_COLORS["text_dim"],
        ).pack(anchor="w", padx=16, pady=(16, 0))

    def _apply_results(self):
        """Apply the selected output mode."""
        mode = self._w_output_mode.get()
        successful = [r for r in self._state.results if r.status == "success" and r.crop]

        if not successful:
            messagebox.showinfo("No Results", "No successful crops to apply.", parent=self)
            return

        if mode == "xmp":
            xmp_results = write_xmp_for_results(successful)
            success = sum(1 for _, ok, _ in xmp_results if ok)

            # Write signal file
            try:
                image_paths = [r.file_path for r in successful]
                if image_paths:
                    write_signal_file(image_paths, image_paths[0].parent)
            except Exception:
                pass

            messagebox.showinfo(
                "Crops Applied!",
                f"Wrote {success} XMP sidecar files.\n\n"
                "To apply in Lightroom:\n"
                "  1. Select the images\n"
                "  2. Metadata \u2192 Read Metadata from Files\n"
                "  3. Done!\n\n"
                "If the FramePilot plugin is installed, this happens automatically.",
                parent=self,
            )

        elif mode == "export":
            folder = filedialog.askdirectory(title="Choose export folder", parent=self)
            if not folder:
                return

            export_results = export_cropped_images(
                successful, output_dir=Path(folder), jpeg_quality=92,
            )
            success = sum(1 for _, ok, _ in export_results if ok)
            messagebox.showinfo("Export Complete", f"Exported {success} cropped images to:\n{folder}", parent=self)

        if self._on_complete:
            self._on_complete(self._state.results)

        self.destroy()
