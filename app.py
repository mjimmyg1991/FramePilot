#!/usr/bin/env python3
"""Entry point for Lightroom Subject Crop GUI application."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.gui import MainWindow


def main():
    """Launch the GUI application."""
    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()
