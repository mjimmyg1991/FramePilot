"""Dialog for creating a Lightroom collection from processed images."""

from datetime import date
from pathlib import Path

import customtkinter as ctk

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


class CollectionDialog(ctk.CTkToplevel):
    """Dialog for creating a Lightroom collection with processed images."""

    def __init__(self, parent, image_count: int, catalog_path: Path | None = None):
        super().__init__(parent)
        self.result: str | None = None

        self.title("FramePilot - Create Collection")
        self.geometry("440x220")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=BRAND_COLORS["bg_secondary"])

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 440) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 220) // 2
        self.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            self, text="Create Lightroom Collection",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=BRAND_COLORS["text_primary"]
        ).pack(pady=(20, 4))

        ctk.CTkLabel(
            self, text=f"Add {image_count} cropped image(s) to a new collection",
            text_color=BRAND_COLORS["text_dim"],
            font=ctk.CTkFont(size=11)
        ).pack(pady=(0, 12))

        # Collection name
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.pack(fill="x", padx=24, pady=4)

        ctk.CTkLabel(name_frame, text="Name:", width=50).pack(side="left")
        default_name = f"FramePilot Crops — {date.today().isoformat()}"
        self._name_var = ctk.StringVar(value=default_name)
        self._name_entry = ctk.CTkEntry(
            name_frame, textvariable=self._name_var, width=300
        )
        self._name_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # Warning if catalog locked
        self._warning_label = ctk.CTkLabel(
            self, text="",
            text_color=BRAND_COLORS["error"],
            font=ctk.CTkFont(size=11)
        )
        self._warning_label.pack(pady=(4, 0))

        if catalog_path:
            from ..catalog.lightroom import is_catalog_locked
            if is_catalog_locked(catalog_path):
                self._warning_label.configure(
                    text="Warning: Lightroom may have the catalog locked. Close Lightroom first."
                )

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=(12, 20))

        ctk.CTkButton(
            btn_frame, text="Cancel", width=100,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self.destroy
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame, text="Create Collection", width=160,
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"], font=ctk.CTkFont(weight="bold"),
            command=self._create
        ).pack(side="right")

    def _create(self):
        name = self._name_var.get().strip()
        if name:
            self.result = name
            self.destroy()
