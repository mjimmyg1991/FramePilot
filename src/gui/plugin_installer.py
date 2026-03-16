"""Lightroom plugin installer dialog."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import customtkinter as ctk

from .. import resource_path

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


def _get_plugin_source() -> Path | None:
    """Find the bundled plugin source directory."""
    plugin_dir = resource_path("lrplugin") / "FramePilot.lrplugin"
    if plugin_dir.exists():
        return plugin_dir
    return None


def _get_lightroom_modules_dir() -> Path | None:
    """Get the Lightroom Modules directory for plugin installation."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            modules = Path(appdata) / "Adobe" / "Lightroom" / "Modules"
            return modules
    elif sys.platform == "darwin":
        modules = Path.home() / "Library" / "Application Support" / "Adobe" / "Lightroom" / "Modules"
        return modules
    return None


def is_plugin_installed() -> bool:
    """Check if the FramePilot plugin is installed."""
    modules_dir = _get_lightroom_modules_dir()
    if modules_dir:
        return (modules_dir / "FramePilot.lrplugin").exists()
    return False


def install_lightroom_plugin() -> tuple[bool, str]:
    """Install the Lightroom plugin.

    Returns:
        Tuple of (success, message)
    """
    source = _get_plugin_source()
    if not source:
        return False, "Plugin source not found. Reinstall FramePilot."

    modules_dir = _get_lightroom_modules_dir()
    if not modules_dir:
        return False, "Could not find Lightroom modules directory."

    try:
        modules_dir.mkdir(parents=True, exist_ok=True)
        dest = modules_dir / "FramePilot.lrplugin"

        if dest.exists():
            shutil.rmtree(dest)

        shutil.copytree(source, dest)
        return True, f"Plugin installed to:\n{dest}"

    except PermissionError:
        return False, "Permission denied. Try running as administrator."
    except Exception as e:
        return False, f"Installation failed: {e}"


class PluginInstallerDialog(ctk.CTkToplevel):
    """Dialog for installing/managing the Lightroom plugin."""

    def __init__(self, parent):
        super().__init__(parent)

        self.title("FramePilot - Lightroom Plugin")
        self.geometry("450x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=BRAND_COLORS["bg_secondary"])

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 450) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 280) // 2
        self.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            self, text="Lightroom Plugin",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=BRAND_COLORS["text_primary"]
        ).pack(pady=(24, 4))

        ctk.CTkLabel(
            self,
            text="Auto-applies crops when FramePilot writes XMP files.\nNo more manual 'Read Metadata from Files'!",
            text_color=BRAND_COLORS["text_dim"],
            font=ctk.CTkFont(size=11),
            justify="center",
        ).pack(pady=(0, 16))

        # Status
        installed = is_plugin_installed()
        status_text = "Installed" if installed else "Not installed"
        status_color = BRAND_COLORS["success"] if installed else BRAND_COLORS["text_dim"]

        self._status_label = ctk.CTkLabel(
            self, text=f"Status: {status_text}",
            text_color=status_color,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._status_label.pack(pady=8)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=8)

        ctk.CTkButton(
            btn_frame,
            text="Reinstall Plugin" if installed else "Install Plugin",
            width=180, height=40,
            fg_color=BRAND_COLORS["orange"], hover_color=BRAND_COLORS["orange_dim"],
            text_color=BRAND_COLORS["bg_primary"],
            font=ctk.CTkFont(weight="bold"),
            command=self._install,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="Open Plugin Folder", width=160, height=40,
            fg_color=BRAND_COLORS["bg_tertiary"], hover_color=BRAND_COLORS["border"],
            command=self._open_folder,
        ).pack(side="left")

        ctk.CTkButton(
            self, text="Close", width=100,
            fg_color="transparent", hover_color=BRAND_COLORS["bg_tertiary"],
            command=self.destroy,
        ).pack(pady=(8, 16))

    def _install(self):
        from tkinter import messagebox
        success, message = install_lightroom_plugin()
        if success:
            self._status_label.configure(text="Status: Installed", text_color=BRAND_COLORS["success"])
            messagebox.showinfo("Plugin Installed", message + "\n\nRestart Lightroom to activate.", parent=self)
        else:
            messagebox.showerror("Installation Failed", message, parent=self)

    def _open_folder(self):
        modules_dir = _get_lightroom_modules_dir()
        if modules_dir and modules_dir.exists():
            if sys.platform == "win32":
                os.startfile(str(modules_dir))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(modules_dir)])
            else:
                subprocess.run(["xdg-open", str(modules_dir)])
        else:
            source = _get_plugin_source()
            if source:
                parent = source.parent
                if sys.platform == "win32":
                    os.startfile(str(parent))
                elif sys.platform == "darwin":
                    subprocess.run(["open", str(parent)])
                else:
                    subprocess.run(["xdg-open", str(parent)])
