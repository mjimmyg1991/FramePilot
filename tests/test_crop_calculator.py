"""Tests for crop_calculator module."""

import pytest
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crop_calculator import (
    MIN_CROP_SCALE,
    CropRegion,
    calculate_vertical_crop,
    select_primary_subject,
)
from src.detector import Detection


class TestCropRegion:
    """Tests for CropRegion dataclass."""

    def test_width_height(self):
        crop = CropRegion(left=0.2, right=0.8, top=0.0, bottom=1.0)
        assert crop.width == pytest.approx(0.6)
        assert crop.height == pytest.approx(1.0)

    def test_center(self):
        crop = CropRegion(left=0.2, right=0.8, top=0.0, bottom=1.0)
        cx, cy = crop.center
        assert cx == pytest.approx(0.5)
        assert cy == pytest.approx(0.5)

    def test_aspect_ratio(self):
        # 4:5 crop from 3:2 image
        # Crop width = 0.5556, height = 1.0
        crop = CropRegion(left=0.2222, right=0.7778, top=0.0, bottom=1.0)
        # In normalized coords, need to account for source aspect
        assert crop.aspect_ratio == pytest.approx(0.5556, rel=0.01)

    def test_to_lightroom_format(self):
        crop = CropRegion(left=0.2, right=0.8, top=0.0, bottom=1.0)
        lr_format = crop.to_lightroom_format()
        assert lr_format["CropLeft"] == 0.2
        assert lr_format["CropRight"] == 0.8
        assert lr_format["CropTop"] == 0.0
        assert lr_format["CropBottom"] == 1.0


class TestSelectPrimarySubject:
    """Tests for select_primary_subject function."""

    def test_empty_list(self):
        result = select_primary_subject([])
        assert result is None

    def test_single_detection(self):
        det = Detection(bbox=(0.3, 0.2, 0.7, 0.8), confidence=0.9, label="person")
        result = select_primary_subject([det])
        assert result == det

    def test_highest_confidence(self):
        det1 = Detection(bbox=(0.1, 0.1, 0.3, 0.3), confidence=0.7, label="person")
        det2 = Detection(bbox=(0.5, 0.5, 0.9, 0.9), confidence=0.95, label="person")
        det3 = Detection(bbox=(0.2, 0.2, 0.6, 0.6), confidence=0.8, label="person")

        result = select_primary_subject([det1, det2, det3], strategy="highest_confidence")
        assert result == det2
        assert result.confidence == 0.95

    def test_largest(self):
        det1 = Detection(bbox=(0.1, 0.1, 0.2, 0.2), confidence=0.9, label="person")  # 0.01 area
        det2 = Detection(bbox=(0.3, 0.3, 0.8, 0.8), confidence=0.7, label="person")  # 0.25 area
        det3 = Detection(bbox=(0.0, 0.0, 0.4, 0.4), confidence=0.8, label="person")  # 0.16 area

        result = select_primary_subject([det1, det2, det3], strategy="largest")
        assert result == det2

    def test_centered(self):
        det1 = Detection(bbox=(0.0, 0.0, 0.2, 0.2), confidence=0.9, label="person")  # center at 0.1, 0.1
        det2 = Detection(bbox=(0.4, 0.4, 0.6, 0.6), confidence=0.7, label="person")  # center at 0.5, 0.5
        det3 = Detection(bbox=(0.7, 0.7, 0.9, 0.9), confidence=0.8, label="person")  # center at 0.8, 0.8

        result = select_primary_subject([det1, det2, det3], strategy="centered")
        assert result == det2


class TestCalculateVerticalCrop:
    """Tests for calculate_vertical_crop function."""

    def test_subject_centered(self):
        """Subject at center should produce centered crop."""
        # 3:2 landscape image (6000x4000)
        # Subject at center
        subject_bbox = (0.4, 0.3, 0.6, 0.7)  # centered

        crop = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.0
        )

        # Crop should be centered horizontally around 0.5
        assert crop.center[0] == pytest.approx(0.5, abs=0.01)
        # Subject is 0.4 tall, so the minimum crop size (half height) applies
        assert crop.height == pytest.approx(MIN_CROP_SCALE)

    def test_subject_left_of_center(self):
        """Subject left of center should shift crop left."""
        # Subject on left third
        subject_bbox = (0.1, 0.3, 0.3, 0.7)  # left side, center_x = 0.2

        crop = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.0
        )

        # Crop center should be at or near subject center, but clamped
        assert crop.left >= 0.0
        assert crop.right <= 1.0

    def test_subject_right_of_center(self):
        """Subject right of center should shift crop right."""
        # Subject on right third
        subject_bbox = (0.7, 0.3, 0.9, 0.7)  # right side, center_x = 0.8

        crop = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.0
        )

        # Crop should be shifted right but not exceed bounds
        assert crop.right <= 1.0
        assert crop.left >= 0.0

    def test_subject_at_extreme_left_edge(self):
        """Subject at extreme left should clamp crop to left boundary."""
        subject_bbox = (0.0, 0.3, 0.1, 0.7)  # far left

        crop = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.0
        )

        assert crop.left == pytest.approx(0.0, abs=0.001)
        assert crop.right <= 1.0

    def test_subject_at_extreme_right_edge(self):
        """Subject at extreme right should clamp crop to right boundary."""
        subject_bbox = (0.9, 0.3, 1.0, 0.7)  # far right

        crop = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.0
        )

        assert crop.right == pytest.approx(1.0, abs=0.001)
        assert crop.left >= 0.0

    def test_aspect_ratio_4_5(self):
        """Test 4:5 aspect ratio calculation."""
        subject_bbox = (0.4, 0.3, 0.6, 0.7)

        crop = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.0
        )

        pixel_aspect = (crop.width * 6000) / (crop.height * 4000)
        assert pixel_aspect == pytest.approx(4 / 5)

    def test_aspect_ratio_9_16(self):
        """Test 9:16 aspect ratio calculation."""
        subject_bbox = (0.4, 0.3, 0.6, 0.7)

        crop = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(9, 16),
            padding=0.0
        )

        pixel_aspect = (crop.width * 6000) / (crop.height * 4000)
        assert pixel_aspect == pytest.approx(9 / 16)

    def test_padding_increases_crop_size(self):
        """Padding adds space around a subject that fills most of the frame."""
        subject_bbox = (0.45, 0.2, 0.55, 0.8)

        crop_no_padding = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.0
        )

        crop_with_padding = calculate_vertical_crop(
            image_width=6000,
            image_height=4000,
            subject_bbox=subject_bbox,
            target_aspect=(4, 5),
            padding=0.15
        )

        assert crop_no_padding.height == pytest.approx(0.6)
        assert crop_with_padding.height == pytest.approx(0.6 * 1.3)
        assert crop_with_padding.width > crop_no_padding.width

    def test_crop_bounds_valid(self):
        """Test that all crop values are within valid range."""
        # Test with various subject positions
        test_cases = [
            (0.0, 0.0, 0.2, 0.5),  # top-left
            (0.8, 0.0, 1.0, 0.5),  # top-right
            (0.0, 0.5, 0.2, 1.0),  # bottom-left
            (0.8, 0.5, 1.0, 1.0),  # bottom-right
            (0.3, 0.3, 0.7, 0.7),  # center
        ]

        for bbox in test_cases:
            crop = calculate_vertical_crop(
                image_width=6000,
                image_height=4000,
                subject_bbox=bbox,
                target_aspect=(4, 5),
                padding=0.15
            )

            assert 0.0 <= crop.left <= 1.0, f"Invalid left: {crop.left}"
            assert 0.0 <= crop.right <= 1.0, f"Invalid right: {crop.right}"
            assert 0.0 <= crop.top <= 1.0, f"Invalid top: {crop.top}"
            assert 0.0 <= crop.bottom <= 1.0, f"Invalid bottom: {crop.bottom}"
            assert crop.left < crop.right, "Left should be less than right"
            assert crop.top < crop.bottom, "Top should be less than bottom"


class TestCropSizing:
    """Tests for how crops zoom in on subjects of different sizes."""

    def crop(self, bbox, aspect=(4, 5), padding=0.15, size=(6000, 4000), **kwargs):
        return calculate_vertical_crop(
            image_width=size[0],
            image_height=size[1],
            subject_bbox=bbox,
            target_aspect=aspect,
            padding=padding,
            **kwargs
        )

    def test_small_subject_limited_by_min_scale(self):
        crop = self.crop((0.48, 0.5, 0.52, 0.6))
        assert crop.height == pytest.approx(MIN_CROP_SCALE)

    def test_larger_padding_zooms_out(self):
        tight = self.crop((0.45, 0.3, 0.55, 0.7), padding=0.3)
        loose = self.crop((0.45, 0.3, 0.55, 0.7), padding=0.6)
        assert tight.height == pytest.approx(0.4 * 1.6)
        assert loose.height == pytest.approx(0.4 * 2.2)

    def test_min_scale_one_never_zooms(self):
        crop = self.crop((0.48, 0.5, 0.52, 0.6), min_scale=1.0)
        assert crop.top == pytest.approx(0.0)
        assert crop.bottom == pytest.approx(1.0)

    def test_tall_subject_uses_full_height(self):
        crop = self.crop((0.45, 0.05, 0.55, 0.95))
        assert crop.top == pytest.approx(0.0)
        assert crop.bottom == pytest.approx(1.0)

    def test_wide_subject_sets_size(self):
        # 0.3 wide + 15% each side needs 0.39 of the width; at 4:5 on 3:2 that
        # is 0.39 / (0.8 / 1.5) of the height
        crop = self.crop((0.35, 0.45, 0.65, 0.55))
        assert crop.width == pytest.approx(0.39)
        assert crop.height == pytest.approx(0.39 * 1.5 / 0.8)

    def test_subject_fully_inside_crop_with_padding(self):
        bbox = (0.4, 0.25, 0.5, 0.75)
        crop = self.crop(bbox, padding=0.1)
        assert crop.left <= bbox[0] - 0.1 * 0.1 + 1e-9
        assert crop.right >= bbox[2] + 0.1 * 0.1 - 1e-9
        assert crop.top <= bbox[1]
        assert crop.bottom >= bbox[3]

    def test_headroom_smaller_than_footroom(self):
        bbox = (0.45, 0.3, 0.55, 0.6)
        crop = self.crop(bbox)
        headroom = bbox[1] - crop.top
        footroom = crop.bottom - bbox[3]
        assert 0 < headroom < footroom

    def test_subject_taller_than_crop_keeps_top(self):
        # Portrait photo cropped to 16:9: the crop can't fit a full-height person
        bbox = (0.3, 0.1, 0.7, 0.95)
        crop = self.crop(bbox, aspect=(16, 9), size=(4000, 6000))
        assert crop.width == pytest.approx(1.0)
        assert crop.top == pytest.approx(0.1)

    def test_subject_near_edge_is_clamped(self):
        crop = self.crop((0.0, 0.9, 0.05, 1.0))
        assert crop.left == pytest.approx(0.0)
        assert crop.bottom == pytest.approx(1.0)

    @pytest.mark.parametrize("size", [(6000, 4000), (4000, 6000), (4000, 4000)])
    @pytest.mark.parametrize("aspect", [(4, 5), (9, 16), (1, 1), (16, 9)])
    @pytest.mark.parametrize("bbox", [
        (0.0, 0.0, 0.1, 0.2),
        (0.4, 0.3, 0.6, 0.7),
        (0.1, 0.0, 0.9, 1.0),
        (0.9, 0.8, 1.0, 1.0),
    ])
    def test_exact_aspect_and_bounds(self, size, aspect, bbox):
        crop = self.crop(bbox, aspect=aspect, size=size)
        assert 0.0 <= crop.left < crop.right <= 1.0 + 1e-9
        assert 0.0 <= crop.top < crop.bottom <= 1.0 + 1e-9
        pixel_aspect = (crop.width * size[0]) / (crop.height * size[1])
        assert pixel_aspect == pytest.approx(aspect[0] / aspect[1])


class TestDetection:
    """Tests for Detection dataclass."""

    def test_width_height(self):
        det = Detection(bbox=(0.2, 0.3, 0.8, 0.9), confidence=0.9, label="person")
        assert det.width == pytest.approx(0.6)
        assert det.height == pytest.approx(0.6)

    def test_area(self):
        det = Detection(bbox=(0.0, 0.0, 0.5, 0.5), confidence=0.9, label="person")
        assert det.area == pytest.approx(0.25)

    def test_center(self):
        det = Detection(bbox=(0.2, 0.3, 0.8, 0.7), confidence=0.9, label="person")
        cx, cy = det.center
        assert cx == pytest.approx(0.5)
        assert cy == pytest.approx(0.5)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
