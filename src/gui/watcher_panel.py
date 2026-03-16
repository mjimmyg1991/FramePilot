"""Watch folder panel for auto-processing new images."""

import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..watcher import FolderWatcher, WatcherResult

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


class WatcherPanel(ctk.CTkFrame):
    """Panel for folder watch / hot folder mode."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=BRAND_COLORS["bg_card"], border_width=1,
                         border_color=BRAND_COLORS["border"], **kwargs)

        self._watcher: FolderWatcher | None = None
        self._log_entries: list[str] = []

        self._setup_ui()

    def _setup_ui(self):
        """Build the watcher panel UI."""
        # Header
        ctk.CTkLabel(
            self, text="Watch Folder",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(12, 4))

        ctk.CTkLabel(
            self, text="Auto-process new images and write XMP sidecars",
            font=ctk.CTkFont(size=11),
            text_color=BRAND_COLORS["text_dim"]
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # Folder selection
        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", padx=12, pady=4)

        self._folder_var = ctk.StringVar(value="")
        self._folder_entry = ctk.CTkEntry(
            folder_row, textvariable=self._folder_var,
            placeholder_text="Select a folder to watch...",
            state="readonly"
        )
        self._folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            folder_row, text="Browse", width=80,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self._browse_folder
        ).pack(side="right")

        # Settings row
        settings_row = ctk.CTkFrame(self, fg_color="transparent")
        settings_row.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(settings_row, text="Aspect:", font=ctk.CTkFont(size=11)).pack(side="left")
        self._aspect_var = ctk.StringVar(value="4:5")
        ctk.CTkOptionMenu(
            settings_row, variable=self._aspect_var,
            values=["4:5", "9:16", "2:3", "1:1", "5:7"],
            width=80
        ).pack(side="left", padx=(4, 12))

        ctk.CTkLabel(settings_row, text="Padding:", font=ctk.CTkFont(size=11)).pack(side="left")
        self._padding_var = ctk.StringVar(value="15")
        ctk.CTkEntry(settings_row, textvariable=self._padding_var, width=40).pack(side="left", padx=(4, 4))
        ctk.CTkLabel(settings_row, text="%", font=ctk.CTkFont(size=11)).pack(side="left")

        # Start/Stop button
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=8)

        self._toggle_btn = ctk.CTkButton(
            btn_row, text="Start Watching", width=140, height=36,
            fg_color=BRAND_COLORS["success"], hover_color="#1BA34E",
            text_color="white", font=ctk.CTkFont(weight="bold"),
            command=self._toggle_watcher
        )
        self._toggle_btn.pack(side="left")

        self._status_label = ctk.CTkLabel(
            btn_row, text="Stopped",
            text_color=BRAND_COLORS["text_dim"],
            font=ctk.CTkFont(size=11)
        )
        self._status_label.pack(side="left", padx=12)

        self._count_label = ctk.CTkLabel(
            btn_row, text="",
            text_color=BRAND_COLORS["text_secondary"],
            font=ctk.CTkFont(size=11)
        )
        self._count_label.pack(side="right")

        # Activity log
        ctk.CTkLabel(
            self, text="Activity",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=BRAND_COLORS["text_dim"]
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self._log_text = ctk.CTkTextbox(
            self, height=120,
            fg_color=BRAND_COLORS["bg_primary"],
            text_color=BRAND_COLORS["text_secondary"],
            font=ctk.CTkFont(size=11, family="Consolas" if __import__("sys").platform == "win32" else "monospace"),
            state="disabled"
        )
        self._log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select folder to watch")
        if folder:
            self._folder_var.set(folder)

    def _toggle_watcher(self):
        if self._watcher and self._watcher.is_running:
            self._stop_watcher()
        else:
            self._start_watcher()

    def _start_watcher(self):
        folder = self._folder_var.get()
        if not folder:
            return

        # Parse aspect ratio
        try:
            parts = self._aspect_var.get().split(":")
            aspect = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            aspect = (4, 5)

        # Parse padding
        try:
            padding = int(self._padding_var.get()) / 100
        except ValueError:
            padding = 0.15

        self._watcher = FolderWatcher(
            watch_dir=folder,
            aspect_ratio=aspect,
            padding=padding,
            on_file_processed=self._on_file_processed,
        )

        try:
            self._watcher.start()
        except Exception as e:
            self._append_log(f"Error: {e}")
            return

        self._toggle_btn.configure(
            text="Stop Watching",
            fg_color=BRAND_COLORS["error"],
            hover_color="#D43232",
        )
        self._status_label.configure(text="Watching...", text_color=BRAND_COLORS["success"])
        self._append_log(f"Watching: {folder}")

    def _stop_watcher(self):
        if self._watcher:
            self._watcher.stop()
            count = self._watcher.processed_count
            self._append_log(f"Stopped. {count} files processed.")

        self._toggle_btn.configure(
            text="Start Watching",
            fg_color=BRAND_COLORS["success"],
            hover_color="#1BA34E",
        )
        self._status_label.configure(text="Stopped", text_color=BRAND_COLORS["text_dim"])

    def _on_file_processed(self, result: WatcherResult):
        """Called from watcher thread — schedule UI update."""
        self.after(0, self._update_from_result, result)

    def _update_from_result(self, result: WatcherResult):
        """Update UI with a processing result (runs on main thread)."""
        if result.status == "success":
            msg = f"OK: {result.file_path.name} -> {result.xmp_path.name}"
        elif result.status == "no_subject":
            msg = f"Skip: {result.file_path.name} (no subject)"
        else:
            msg = f"ERR: {result.file_path.name} ({result.error_message})"

        self._append_log(msg)

        if self._watcher:
            self._count_label.configure(text=f"{self._watcher.processed_count} processed")

    def _append_log(self, message: str):
        """Append a message to the activity log."""
        self._log_text.configure(state="normal")
        self._log_text.insert("end", message + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def destroy(self):
        """Clean up watcher on destroy."""
        if self._watcher and self._watcher.is_running:
            self._watcher.stop()
        super().destroy()
