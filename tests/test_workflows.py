"""Tests for the GitHub Actions workflows: tests and the Windows zip run on every push."""

from pathlib import Path

import pytest
import yaml


WORKFLOW_DIR = Path(__file__).parent.parent / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    data = yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))
    # YAML 1.1 reads the bare key `on` as True
    data["on"] = data.pop(True, data.get("on"))
    return data


class TestWorkflowTriggers:
    """Both workflows must run without workflow_dispatch, which sessions can't use."""

    @pytest.mark.parametrize("name", ["tests.yml", "build.yml"])
    def test_runs_on_every_push_and_pull_request(self, name):
        triggers = load_workflow(name)["on"]
        assert "push" in triggers and triggers["push"] is None
        assert "pull_request" in triggers

    def test_pytest_runs_on_linux(self):
        workflow = load_workflow("tests.yml")
        job = workflow["jobs"]["pytest-linux"]
        assert job["runs-on"] == "ubuntu-latest"
        assert any("pytest tests/" in step.get("run", "") for step in job["steps"])


class TestWindowsBuild:
    """The Windows build must always leave a downloadable FramePilot.zip."""

    def test_uploads_zip(self):
        steps = load_workflow("build.yml")["jobs"]["build-windows"]["steps"]
        upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact"))
        assert upload["with"]["path"] == "dist/FramePilot.zip"

    def test_zip_includes_plugin(self):
        steps = load_workflow("build.yml")["jobs"]["build-windows"]["steps"]
        runs = "\n".join(step.get("run", "") for step in steps)
        assert r"lightroom\FramePilot.lrplugin dist\FramePilot" in runs
        assert "Compress-Archive" in runs


class TestMacBuild:
    """The macOS build packages the engine and plugin for Lightroom on a Mac."""

    def job(self) -> dict:
        return load_workflow("build.yml")["jobs"]["build-macos"]

    def test_runs_on_macos(self):
        assert self.job()["runs-on"].startswith("macos")

    def test_builds_engine_only(self):
        build = next(step for step in self.job()["steps"] if step.get("name") == "Build engine with PyInstaller")
        assert build["env"]["FRAMEPILOT_ENGINE_ONLY"] == "1"

    def test_smoke_tests_detection_and_verify(self):
        runs = "\n".join(step.get("run", "") for step in self.job()["steps"])
        assert "--version" in runs and "--verify" in runs
        assert "cp -R lightroom/FramePilot.lrplugin dist/FramePilot/" in runs

    def test_uploads_zip(self):
        upload = next(step for step in self.job()["steps"] if step.get("uses", "").startswith("actions/upload-artifact"))
        assert upload["with"]["name"] == "FramePilot-macOS"
        assert upload["with"]["path"] == "dist/FramePilot-macOS.zip"


class TestPyInstallerSpec:
    """The frozen engine needs torchvision's native ops library for YOLO's NMS."""

    def test_torchvision_native_libraries_bundled_in_both_exes(self):
        spec = (Path(__file__).parent.parent / "framepilot.spec").read_text(encoding="utf-8")
        assert "torchvision_path.glob(pattern)" in spec
        assert spec.count("binaries=TORCHVISION_BINARIES") == 2

    def test_engine_only_build_bundles_models_and_config(self):
        spec = (Path(__file__).parent.parent / "framepilot.spec").read_text(encoding="utf-8")
        assert "datas=SHARED_DATAS if ENGINE_ONLY else []" in spec
