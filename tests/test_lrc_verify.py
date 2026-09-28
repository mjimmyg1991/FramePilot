"""Tests for the crop position self-check run after the plugin applies crops.

Lightroom is simulated by rendering a stored image under a "true" orientation:
crop the stored pixels by the develop crop, then rotate/flip for display.
"""

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.crop_calculator import CropRegion
from src.lrc_bridge import display_to_original, original_to_display
from src.lrc_verify import (
    MATCH_THRESHOLD,
    ORIENTATIONS,
    VerifyItem,
    expected_region,
    load_verify_job,
    run_verify,
    verify_item,
)
from tests.lr_simulation import orient, render, textured_image


ROOT = Path(__file__).parent.parent
CHECK_PHOTO = ROOT / "lightroom" / "FramePilot.lrplugin" / "check-photo.jpg"
FULL = CropRegion(left=0.0, right=1.0, top=0.0, bottom=1.0)


def simulate(
    tmp_path: Path,
    stored: np.ndarray,
    true_orientation: str,
    believed_orientation: str,
    previous_crop: CropRegion,
    rendition_crop: CropRegion,
) -> VerifyItem:
    """Run the plugin's steps: render, crop in rendition space, map with the believed orientation."""
    before = render(stored, previous_crop, true_orientation, 1024)
    before_path = tmp_path / "before.jpg"
    cv2.imwrite(str(before_path), before)

    visible = original_to_display(previous_crop, believed_orientation)
    display_crop = CropRegion(
        left=visible.left + rendition_crop.left * visible.width,
        right=visible.left + rendition_crop.right * visible.width,
        top=visible.top + rendition_crop.top * visible.height,
        bottom=visible.top + rendition_crop.bottom * visible.height,
    )
    applied = display_to_original(display_crop, believed_orientation)

    after_path = tmp_path / "after.jpg"
    cv2.imwrite(str(after_path), render(stored, applied, true_orientation, 512))
    return VerifyItem(
        id="1",
        before_path=before_path,
        after_path=after_path,
        orientation=believed_orientation,
        previous_crop=previous_crop,
        applied_crop=applied,
    )


def portrait_crop_in(before_w: int, before_h: int, left: float) -> CropRegion:
    """A full-height 4:5 crop of a landscape rendition, or a full-width 4:5 band of a portrait one.

    ``left`` places the crop from the left (landscape) or top (portrait) edge.
    """
    if before_w > before_h:
        width = (before_h * 0.8) / before_w
        return CropRegion(left=left, right=left + width, top=0.0, bottom=1.0)
    height = (before_w / 0.8) / before_h
    top = min(left, 1.0 - height)
    return CropRegion(left=0.0, right=1.0, top=top, bottom=top + height)


class TestExpectedRegion:
    """Tests for locating the applied crop inside the pre-crop rendition."""

    def test_identity(self):
        applied = CropRegion(left=0.2, right=0.6, top=0.0, bottom=1.0)
        region = expected_region(FULL, applied, "AB")
        assert (region.left, region.top, region.right, region.bottom) == pytest.approx((0.2, 0.0, 0.6, 1.0))

    def test_relative_to_previous_crop(self):
        previous = CropRegion(left=0.5, right=1.0, top=0.0, bottom=0.5)
        applied = CropRegion(left=0.5, right=0.75, top=0.0, bottom=0.5)
        region = expected_region(previous, applied, "AB")
        assert (region.left, region.right) == pytest.approx((0.0, 0.5))

    def test_rotated(self):
        applied = CropRegion(left=0.0, right=1.0, top=0.0, bottom=0.25)
        region = expected_region(FULL, applied, "BC")
        assert (region.left, region.top, region.right, region.bottom) == pytest.approx((0.75, 0.0, 1.0, 1.0))


class TestLightroomOrientationCodes:
    """Pin each code to what Lightroom Classic 15.5 actually shows.

    Rotate Right (Cmd+]) reported "BC", Rotate Left (Cmd+[) and a camera-vertical
    EXIF 8 raw reported "DA", Flip Horizontal "BA", two Rotate Rights "CD".
    Everything else in these tests builds on orient(), so this is the anchor.
    """

    @pytest.mark.parametrize("orientation, expected", [
        ("AB", lambda img: img),
        ("BC", lambda img: cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)),
        ("CD", lambda img: cv2.rotate(img, cv2.ROTATE_180)),
        ("DA", lambda img: cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)),
        ("BA", lambda img: cv2.flip(img, 1)),
        ("DC", lambda img: cv2.flip(img, 0)),
        ("AD", lambda img: cv2.transpose(img)),
        ("CB", lambda img: cv2.rotate(cv2.transpose(img), cv2.ROTATE_180)),
    ])
    def test_orient_matches_lightroom(self, orientation, expected):
        stored = np.arange(3 * 5 * 3, dtype=np.uint8).reshape(3, 5, 3)
        np.testing.assert_array_equal(orient(stored, orientation), expected(stored))

    def test_outside_previous_crop_is_none(self):
        previous = CropRegion(left=0.5, right=1.0, top=0.0, bottom=1.0)
        applied = CropRegion(left=0.1, right=0.4, top=0.0, bottom=1.0)
        assert expected_region(previous, applied, "AB") is None


class TestVerifyItem:
    """Simulated Lightroom renders, with the right and wrong orientation beliefs."""

    @pytest.mark.parametrize("orientation", ORIENTATIONS)
    def test_correct_mapping_matches(self, tmp_path, orientation):
        stored = cv2.imread(str(CHECK_PHOTO))
        stored = cv2.rotate(stored, cv2.ROTATE_90_CLOCKWISE)  # landscape stored pixels
        oriented = orient(stored, orientation)
        crop = portrait_crop_in(oriented.shape[1], oriented.shape[0], left=0.1)

        result = verify_item(simulate(tmp_path, stored, orientation, orientation, FULL, crop))

        assert result.status == "match", result.message
        assert result.score > 0.95
        assert result.best_orientation and result.best_score >= result.score

    @pytest.mark.parametrize("true, believed", [
        ("DA", "BC"),
        ("BC", "DA"),
        ("BC", "AB"),
        ("AB", "BC"),
        ("CD", "AB"),
    ])
    def test_wrong_mapping_is_caught_and_true_orientation_found(self, tmp_path, true, believed):
        stored = textured_image(900, 600)
        oriented = orient(stored, true)
        crop = portrait_crop_in(oriented.shape[1], oriented.shape[0], left=0.0)

        result = verify_item(simulate(tmp_path, stored, true, believed, FULL, crop))

        assert result.status == "mismatch"
        assert result.score < MATCH_THRESHOLD
        assert result.best_score > 0.95
        if true in ("DA", "BC") and believed in ("DA", "BC"):
            assert result.best_orientation == true
        assert f"orientation {believed}" in result.message

    def test_wrong_mapping_on_already_cropped_photo(self, tmp_path):
        stored = textured_image(1200, 800, seed=3)
        previous = CropRegion(left=0.1, right=0.9, top=0.05, bottom=0.85)

        result = verify_item(simulate(
            tmp_path, stored, "DA", "BC", previous, CropRegion(left=0.0, right=1.0, top=0.3, bottom=0.8),
        ))

        assert result.status == "mismatch"
        assert result.best_orientation == "DA"

    def test_already_cropped_photo_matches(self, tmp_path):
        stored = textured_image(1200, 800, seed=4)
        previous = CropRegion(left=0.1, right=0.9, top=0.05, bottom=0.85)

        result = verify_item(simulate(
            tmp_path, stored, "BC", "BC", previous, CropRegion(left=0.0, right=1.0, top=0.3, bottom=0.8),
        ))

        assert result.status == "match"

    def test_flat_image_is_inconclusive(self, tmp_path):
        stored = np.full((600, 900, 3), 128, dtype=np.uint8)
        crop = portrait_crop_in(900, 600, left=0.2)

        result = verify_item(simulate(tmp_path, stored, "AB", "AB", FULL, crop))

        assert result.status == "inconclusive"
        assert result.score is None

    def test_unreadable_render_is_error(self, tmp_path):
        stored = textured_image(900, 600)
        item = simulate(tmp_path, stored, "AB", "AB", FULL, portrait_crop_in(900, 600, left=0.2))
        item.after_path = tmp_path / "missing.jpg"

        result = verify_item(item)

        assert result.status == "error"


class TestRunVerify:
    """Tests for the verify job file, results file and command line."""

    def write_job(self, tmp_path: Path, item: VerifyItem) -> Path:
        job_path = tmp_path / "verify.json"
        crop = lambda c: {"left": c.left, "top": c.top, "right": c.right, "bottom": c.bottom}
        job_path.write_text(json.dumps({"photos": [{
            "id": item.id,
            "before": str(item.before_path),
            "after": str(item.after_path),
            "orientation": item.orientation,
            "previous_crop": crop(item.previous_crop),
            "applied_crop": crop(item.applied_crop),
        }]}), encoding="utf-8")
        return job_path

    def test_load_job(self, tmp_path):
        stored = textured_image(900, 600)
        item = simulate(tmp_path, stored, "AB", "AB", FULL, portrait_crop_in(900, 600, left=0.2))
        (loaded,) = load_verify_job(self.write_job(tmp_path, item))
        assert loaded.orientation == "AB"
        assert loaded.applied_crop.left == pytest.approx(item.applied_crop.left)

    def test_results_and_scores_logged(self, tmp_path, capsys):
        stored = textured_image(900, 600)
        oriented = orient(stored, "DA")
        item = simulate(tmp_path, stored, "DA", "BC", FULL, portrait_crop_in(oriented.shape[1], oriented.shape[0], 0.0))
        result_path = tmp_path / "verify.tsv"

        assert run_verify(self.write_job(tmp_path, item), result_path) == 0

        fields = result_path.read_text(encoding="utf-8").rstrip("\n").split("\t")
        assert fields[:2] == ["1", "mismatch"]
        assert fields[3] == "DA"
        assert float(fields[4]) > 0.95
        log = capsys.readouterr().out
        assert "orientation used BC, best DA" in log
        assert "DA=0.9" in log

    def test_engine_verify_mode(self, tmp_path):
        stored = textured_image(900, 600)
        item = simulate(tmp_path, stored, "AB", "AB", FULL, portrait_crop_in(900, 600, left=0.2))
        result_path = tmp_path / "verify.tsv"

        completed = subprocess.run(
            [sys.executable, "-X", "importtime", str(ROOT / "engine.py"), "--verify",
             str(self.write_job(tmp_path, item)), str(result_path)],
            capture_output=True, text=True, timeout=120,
        )

        assert completed.returncode == 0, completed.stderr
        assert "(crop position check)" in completed.stdout
        assert "ultralytics" not in completed.stderr
        assert result_path.read_text(encoding="utf-8").split("\t")[1] == "match"
