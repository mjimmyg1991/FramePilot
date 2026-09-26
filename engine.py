#!/usr/bin/env python3
"""Headless engine entry point used by the FramePilot Lightroom Classic plugin."""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    try:
        from src.lrc_bridge import main

        sys.exit(main(sys.argv[1:]))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
