"""Tests for the Lightroom Classic plugin crop engine."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.crop_calculator import CropRegion
from src.detector import Detection
from src.lrc_bridge import (
    LrcJobItem,
    LrcJobSettings,
    display_to_original,
    load_job,
    original_to_display,
    process_item,
    run_job,
)


ALL_ORIENTATIONS = ["AB", "BC", "CD", "DA", "BA", "AD", "DC", "CB"]


class FakeDetector:
    """Returns a fixed set of detections for any image."""

    def __init__(self, detections: list[Detection]):
        self.detections = detections
        self.calls: list[Path] = []

    def detect(self, image_path: str | Path) -> list[Detection]:
        self.calls.append(Path(image_path))
        return list(self.detections)


def make_person(bbox: tuple[float, float, float, float]) -> Detection:
    return Detection(bbox=bbox, confidence=0.9, label="person")


def write_jpeg(path: Path, width: int, height: int) -> Path:
    cv2.imwrite(str(path), np.zeros((height, width, 3), dtype=np.uint8))
    return path


def as_tuple(crop: CropRegion) -> tuple[float, float, float, float]:
    return (crop.left, crop.top, crop.right, crop.bottom)


class TestOrientationMapping:
    """Tests for converting between displayed and develop coordinates."""

    def test_identity_for_ab(self):
        crop = CropRegion(left=0.1, right=0.4, top=0.2, bottom=0.9)
        assert as_tuple(display_to_original(crop, "AB")) == pytest.approx(as_tuple(crop))

    def test_bc_maps_left_edge_to_stored_top_edge(self):
        # BC: stored top-right corner (B) is displayed top-left, so the stored
        # top edge runs up the displayed left edge
        displayed_left_strip = CropRegion(left=0.0, right=0.25, top=0.0, bottom=1.0)
        result = display_to_original(displayed_left_strip, "BC")
        assert as_tuple(result) == pytest.approx((0.0, 0.0, 1.0, 0.25))

    def test_da_maps_left_edge_to_stored_bottom_edge(self):
        displayed_left_strip = CropRegion(left=0.0, right=0.25, top=0.0, bottom=1.0)
        result = display_to_original(displayed_left_strip, "DA")
        assert as_tuple(result) == pytest.approx((0.0, 0.75, 1.0, 1.0))

    def test_cd_is_half_turn(self):
        crop = CropRegion(left=0.1, right=0.3, top=0.2, bottom=0.5)
        result = display_to_original(crop, "CD")
        assert as_tuple(result) == pytest.approx((0.7, 0.5, 0.9, 0.8))

    def test_ba_is_horizontal_mirror(self):
        crop = CropRegion(left=0.1, right=0.3, top=0.2, bottom=0.5)
        result = display_to_original(crop, "BA")
        assert as_tuple(result) == pytest.approx((0.7, 0.2, 0.9, 0.5))

    @pytest.mark.parametrize("orientation", ALL_ORIENTATIONS)
    def test_round_trip(self, orientation):
        crop = CropRegion(left=0.12, right=0.47, top=0.05, bottom=0.83)
        back = original_to_display(display_to_original(crop, orientation), orientation)
        assert as_tuple(back) == pytest.approx(as_tuple(crop))

    @pytest.mark.parametrize("orientation", ["", "A", "AC", "XY", "ABC"])
    def test_invalid_orientation(self, orientation):
        with pytest.raises(ValueError):
            display_to_original(CropRegion(0, 1, 0, 1), orientation)


class TestProcessItem:
    """Tests for computing develop-space crops from renditions."""

    def test_landscape_full_frame(self, tmp_path):
        path = write_jpeg(tmp_path / "a.jpg", 600, 400)
        detector = FakeDetector([make_person((0.45, 0.2, 0.55, 0.9))])
        item = LrcJobItem(id="1", path=path)

        result = process_item(item, detector, LrcJobSettings(aspect_ratio=(4, 5)))

        assert result.status == "success"
        crop = result.crop
        assert crop.top == pytest.approx(0.0)
        assert crop.bottom == pytest.approx(1.0)
        assert (crop.width * 600) / (crop.height * 400) == pytest.approx(0.8, abs=1e-3)
        assert crop.center[0] == pytest.approx(0.5, abs=1e-3)

    def test_no_subject(self, tmp_path):
        path = write_jpeg(tmp_path / "a.jpg", 600, 400)
        result = process_item(LrcJobItem(id="7", path=path), FakeDetector([]), LrcJobSettings())
        assert result.status == "no_subject"
        assert result.crop is None

    def test_unreadable_rendition(self, tmp_path):
        path = tmp_path / "missing.jpg"
        result = process_item(LrcJobItem(id="1", path=path), FakeDetector([]), LrcJobSettings())
        assert result.status == "error"

    def test_crop_stays_inside_existing_crop(self, tmp_path):
        # Rendition shows only the right half of the stored image
        path = write_jpeg(tmp_path / "a.jpg", 300, 400)
        detector = FakeDetector([make_person((0.4, 0.1, 0.6, 0.9))])
        existing = CropRegion(left=0.5, right=1.0, top=0.0, bottom=1.0)
        item = LrcJobItem(id="1", path=path, current_crop=existing)

        result = process_item(item, detector, LrcJobSettings(aspect_ratio=(1, 2)))

        crop = result.crop
        assert crop.left >= 0.5 - 1e-6
        assert crop.right <= 1.0 + 1e-6
        assert crop.center[0] == pytest.approx(0.75, abs=1e-3)

    def test_rotated_photo_crop_in_stored_coordinates(self, tmp_path):
        # Displayed landscape 600x400 from a stored portrait image rotated "BC"
        path = write_jpeg(tmp_path / "a.jpg", 600, 400)
        detector = FakeDetector([make_person((0.0, 0.2, 0.1, 0.9))])
        item = LrcJobItem(id="1", path=path, orientation="BC")

        result = process_item(item, detector, LrcJobSettings(aspect_ratio=(4, 5)))

        crop = result.crop
        # A full-height displayed strip at the left becomes a full-width
        # stored strip along the top
        assert crop.left == pytest.approx(0.0)
        assert crop.right == pytest.approx(1.0)
        assert crop.top == pytest.approx(0.0)
        assert crop.bottom == pytest.approx(0.8 * 400 / 600, abs=1e-3)


class TestRunJob:
    """Tests for the job file round trip used by the plugin."""

    def test_end_to_end(self, tmp_path):
        good = write_jpeg(tmp_path / "good.jpg", 600, 400)
        empty = write_jpeg(tmp_path / "empty.jpg", 600, 400)
        job = {
            "settings": {"aspect_ratio": "9:16", "strategy": "largest", "padding": 0.1},
            "photos": [
                {"id": "10", "path": str(good), "orientation": "AB",
                 "current_crop": {"left": 0, "top": 0, "right": 1, "bottom": 1}},
                {"id": "11", "path": str(empty)},
                {"id": "12", "path": str(tmp_path / "gone.jpg")},
            ],
        }
        job_path = tmp_path / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        result_path = tmp_path / "result.tsv"

        class SelectiveDetector:
            def detect(self, image_path):
                if Path(image_path).name == "good.jpg":
                    return [make_person((0.2, 0.1, 0.3, 0.9))]
                return []

        exit_code = run_job(job_path, result_path, detector=SelectiveDetector())

        assert exit_code == 0
        lines = result_path.read_text(encoding="utf-8").splitlines()
        rows = [line.split("\t") for line in lines]
        assert [r[0] for r in rows] == ["10", "11", "12"]
        assert [r[1] for r in rows] == ["success", "no_subject", "error"]
        assert all(len(r) == 7 for r in rows)
        left, top, right, bottom = (float(v) for v in rows[0][2:6])
        assert (right - left) * 600 / ((bottom - top) * 400) == pytest.approx(9 / 16, abs=1e-3)

    def test_load_job_defaults(self, tmp_path):
        job_path = tmp_path / "job.json"
        job_path.write_text(json.dumps({"photos": [{"id": 3, "path": "x.jpg"}]}), encoding="utf-8")

        settings, items = load_job(job_path)

        assert settings.aspect_ratio == (4, 5)
        assert settings.strategy == "highest_confidence"
        assert items[0].id == "3"
        assert items[0].orientation == "AB"
        assert as_tuple(items[0].current_crop) == (0.0, 0.0, 1.0, 1.0)

    @pytest.mark.parametrize("settings", [
        {"aspect_ratio": "4-5"},
        {"aspect_ratio": "0:5"},
        {"strategy": "biggest"},
    ])
    def test_load_job_rejects_bad_settings(self, tmp_path, settings):
        job_path = tmp_path / "job.json"
        job_path.write_text(json.dumps({"settings": settings, "photos": []}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_job(job_path)
