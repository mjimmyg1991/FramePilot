"""Tests for the focus measures compared in eval/compare_sharpness.py."""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

from compare_sharpness import laplacian_variance, region_gray, tenengrad  # noqa: E402


@pytest.fixture
def checkerboard() -> np.ndarray:
    tile = np.kron([[0, 255] * 8, [255, 0] * 8] * 8, np.ones((8, 8))).astype(np.uint8)
    return tile


class TestFocusMeasures:
    """Both measures should rank a sharp pattern above a blurred copy."""

    @pytest.mark.parametrize("measure", [laplacian_variance, tenengrad])
    def test_sharp_beats_blurred(self, measure, checkerboard):
        blurred = cv2.GaussianBlur(checkerboard, (9, 9), 3)
        assert measure(checkerboard) > measure(blurred) * 2

    @pytest.mark.parametrize("measure", [laplacian_variance, tenengrad])
    def test_flat_is_zero(self, measure):
        assert measure(np.full((32, 32), 128, dtype=np.uint8)) == pytest.approx(0.0)


class TestRegionGray:
    """Tests for sampling a person's head or core."""

    def test_region_size(self):
        image = np.zeros((400, 600, 3), dtype=np.uint8)
        gray = region_gray(image, (0.1, 0.1, 0.5, 0.9), (0.2, 0.0, 0.8, 0.2))
        assert gray.shape == (64, 144)

    def test_too_small_region(self):
        image = np.zeros((40, 60, 3), dtype=np.uint8)
        assert region_gray(image, (0.1, 0.1, 0.2, 0.2), (0.2, 0.0, 0.8, 0.2)) is None
