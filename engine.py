#!/usr/bin/env python3
"""Headless engine entry point used by the FramePilot Lightroom Classic plugin.

Usage:
    engine JOB_JSON RESULT_TSV            crop the photos in a job
    engine --verify JOB_JSON RESULT_TSV   check where applied crops landed
    engine --version                      print version details
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def run(argv: list[str]) -> int:
    """Dispatch to the requested engine mode."""
    from src.engine_info import version_text

    if argv[:1] == ["--version"]:
        print(version_text())
        return 0

    if argv[:1] == ["--verify"]:
        from src.lrc_verify import main as verify_main

        print(version_text().splitlines()[0] + " (crop position check)", flush=True)
        return verify_main(argv[1:])

    from src.lrc_bridge import main

    print(version_text().splitlines()[0], flush=True)
    return main(argv)


if __name__ == "__main__":
    try:
        sys.exit(run(sys.argv[1:]))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
