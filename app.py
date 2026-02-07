#!/usr/bin/env python3
"""Entry point for FramePilot GUI application."""

import sys
import os
from pathlib import Path

# In frozen exe, redirect stderr to a log file for debugging
if getattr(sys, "frozen", False):
    log_path = Path(sys.executable).parent / "framepilot.log"
    try:
        log_file = open(log_path, "w")
        sys.stdout = log_file
        sys.stderr = log_file
    except Exception:
        pass

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from src.gui import MainWindow

    def main():
        """Launch the GUI application."""
        app = MainWindow()
        app.run()

    if __name__ == "__main__":
        main()
except Exception as e:
    import traceback
    traceback.print_exc()
    if getattr(sys, "frozen", False):
        # Also write to a guaranteed location
        with open(Path(sys.executable).parent / "crash.log", "w") as f:
            traceback.print_exc(file=f)
