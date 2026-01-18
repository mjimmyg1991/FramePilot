"""Crop calculation module for vertical crops centered on subjects."""

from dataclasses import dataclass
from typing import Literal

from .detector import Detection


@dataclass
class CropRegion:
    """Represents a crop region with normalized coordinates (0-1)."""

    left: float
    right: float
    top: float
    bottom: float

    @property
    def width(self) -> float:
        """Width of crop region (normalized)."""
        return self.right - self.left

    @property
    def height(self) -> float:
        """Height of crop region (normalized)."""
        return self.bottom - self.top

    @property
    def center(self) -> tuple[float, float]:
        """Center point of crop region (normalized)."""
        return (
            (self.left + self.right) / 2,
            (self.top + self.bottom) / 2
        )

    @property
    def aspect_ratio(self) -> float:
        """Aspect ratio (width / height)."""
        if self.height == 0:
            return 0
        return self.width / self.height

    def to_lightroom_format(self) -> dict[str, float]:
        """Convert to Lightroom XMP crop format."""
        return {
            "CropLeft": self.left,
            "CropRight": self.right,
            "CropTop": self.top,
            "CropBottom": self.bottom
        }


def select_primary_subject(
    detections: list[Detection],
    strategy: Literal["largest", "centered", "highest_confidence"] = "highest_confidence"
) -> Detection | None:
    """Select the primary subject from a list of detections.

    Args:
        detections: List of Detection objects
        strategy: Selection strategy
            - "largest": Select the detection with largest bounding box area
            - "centered": Select the detection closest to image center
            - "highest_confidence": Select the detection with highest confidence

    Returns:
        Selected Detection or None if no detections
    """
    if not detections:
        return None

    if len(detections) == 1:
        return detections[0]

    if strategy == "largest":
        return max(detections, key=lambda d: d.area)
    elif strategy == "centered":
        # Find detection closest to center (0.5, 0.5)
        def distance_to_center(det: Detection) -> float:
            cx, cy = det.center
            return ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
        return min(detections, key=distance_to_center)
    elif strategy == "highest_confidence":
        return max(detections, key=lambda d: d.confidence)
    else:
        raise ValueError(f"Unknown selection strategy: {strategy}")


def calculate_vertical_crop(
    image_width: int,
    image_height: int,
    subject_bbox: tuple[float, float, float, float],
    target_aspect: tuple[int, int] = (4, 5),
    padding: float = 0.15
) -> CropRegion:
    """Calculate optimal vertical crop centered on subject.

    Args:
        image_width: Image width in pixels
        image_height: Image height in pixels
        subject_bbox: Subject bounding box (x1, y1, x2, y2) normalized 0-1
        target_aspect: Target aspect ratio as (width, height), e.g., (4, 5) or (9, 16)
        padding: Padding around subject as fraction of subject width (0.15 = 15%)

    Returns:
        CropRegion with normalized coordinates
    """
    # Calculate source and target aspect ratios
    source_aspect = image_width / image_height
    target_aspect_ratio = target_aspect[0] / target_aspect[1]

    # Get subject center and dimensions
    subj_x1, subj_y1, subj_x2, subj_y2 = subject_bbox
    subj_center_x = (subj_x1 + subj_x2) / 2
    subj_center_y = (subj_y1 + subj_y2) / 2
    subj_width = subj_x2 - subj_x1
    subj_height = subj_y2 - subj_y1

    # For vertical crops (target is taller than wide), we typically want to:
    # 1. Use full height (or most of it)
    # 2. Center horizontally on the subject

    if target_aspect_ratio < source_aspect:
        # Target is more vertical than source - typical case for portrait from landscape
        # Use full height, calculate required width
        crop_height = 1.0
        crop_width = crop_height * target_aspect_ratio / source_aspect

        # Ensure crop is wide enough to include subject with padding
        min_crop_width = subj_width * (1 + 2 * padding)
        if crop_width < min_crop_width and min_crop_width <= 1.0:
            # Need to zoom in (reduce height) to accommodate subject with padding
            crop_width = min_crop_width
            crop_height = crop_width * source_aspect / target_aspect_ratio
            if crop_height > 1.0:
                # Can't fit with padding, use max height
                crop_height = 1.0
                crop_width = crop_height * target_aspect_ratio / source_aspect

        # Center horizontally on subject
        crop_left = subj_center_x - crop_width / 2

        # Clamp to image bounds
        if crop_left < 0:
            crop_left = 0
        elif crop_left + crop_width > 1.0:
            crop_left = 1.0 - crop_width

        crop_right = crop_left + crop_width

        # Center vertically (try to include subject)
        crop_top = subj_center_y - crop_height / 2
        if crop_top < 0:
            crop_top = 0
        elif crop_top + crop_height > 1.0:
            crop_top = 1.0 - crop_height

        crop_bottom = crop_top + crop_height

    else:
        # Target is more horizontal or same as source - unusual for this use case
        # Use full width, calculate required height
        crop_width = 1.0
        crop_height = crop_width * source_aspect / target_aspect_ratio

        if crop_height > 1.0:
            crop_height = 1.0
            crop_width = crop_height * target_aspect_ratio / source_aspect

        # Center on subject vertically
        crop_top = subj_center_y - crop_height / 2
        if crop_top < 0:
            crop_top = 0
        elif crop_top + crop_height > 1.0:
            crop_top = 1.0 - crop_height

        crop_bottom = crop_top + crop_height
        crop_left = 0.0
        crop_right = crop_width

    return CropRegion(
        left=crop_left,
        right=crop_right,
        top=crop_top,
        bottom=crop_bottom
    )


def calculate_crop_for_detection(
    detection: Detection,
    image_width: int,
    image_height: int,
    target_aspect: tuple[int, int] = (4, 5),
    padding: float = 0.15
) -> CropRegion:
    """Convenience function to calculate crop from a Detection object.

    Args:
        detection: Detection object with subject bounding box
        image_width: Image width in pixels
        image_height: Image height in pixels
        target_aspect: Target aspect ratio as (width, height)
        padding: Padding around subject

    Returns:
        CropRegion with normalized coordinates
    """
    return calculate_vertical_crop(
        image_width=image_width,
        image_height=image_height,
        subject_bbox=detection.bbox,
        target_aspect=target_aspect,
        padding=padding
    )
