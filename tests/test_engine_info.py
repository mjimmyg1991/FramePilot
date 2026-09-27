"""Tests for the engine's version report and command-line modes."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import src.engine_info as engine_info
from src import __version__


ROOT = Path(__file__).parent.parent


class TestVersionText:
    """Tests for the --version report."""

    def test_source_checkout(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engine_info, "resource_path", lambda rel="": tmp_path / rel)
        text = engine_info.version_text()
        assert text.splitlines()[0] == f"FramePilot engine {__version__}"
        assert "Build: source checkout" in text
        assert "Python: " in text

    def test_packaged_build_info(self, monkeypatch, tmp_path):
        info_path = tmp_path / "config" / "build_info.json"
        info_path.parent.mkdir()
        info_path.write_text(json.dumps({
            "commit": "0123456789abcdef", "ref": "main", "run": "42", "date": "2026-09-27",
        }), encoding="utf-8")
        monkeypatch.setattr(engine_info, "resource_path", lambda rel="": tmp_path / rel)
        assert "Build: 0123456 (main, run 42, 2026-09-27)" in engine_info.version_text()

    def test_unreadable_build_info_is_ignored(self, monkeypatch, tmp_path):
        info_path = tmp_path / "config" / "build_info.json"
        info_path.parent.mkdir()
        info_path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(engine_info, "resource_path", lambda rel="": tmp_path / rel)
        assert engine_info.build_info() == {}


class TestEngineCommandLine:
    """Runs engine.py as the plugin does."""

    def test_version_flag_is_fast_and_skips_detection(self):
        completed = subprocess.run(
            [sys.executable, "-X", "importtime", str(ROOT / "engine.py"), "--version"],
            capture_output=True, text=True, timeout=120,
        )
        assert completed.returncode == 0
        assert completed.stdout.startswith(f"FramePilot engine {__version__}")
        assert "ultralytics" not in completed.stderr
        assert "torch" not in completed.stderr.split()

    def test_wrong_arguments_exit_2(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "engine.py")], capture_output=True, text=True, timeout=120,
        )
        assert completed.returncode == 2
        assert "Usage" in completed.stderr
