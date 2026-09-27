"""Crop calculation module for vertical crops centered on subjects."""

from dataclasses import dataclass
from typing import Literal

from .detector import Detection
from .subject_modes import MODE_EXTRA_PADDING, SubjectChoice, SubjectMode, choose_subject
from .subject_scoring import SubjectWeights, score_subjects


MIN_CROP_SCALE = 0.5
HEADROOM_SHARE = 1 / 3


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


def combine_detections(detections: list[Detection]) -> Detection | None:
    """Combine multiple detections into a single bounding box.

    Useful for group shots or contested possession in sports where
    you want to include all detected subjects in the crop.

    Args:
        detections: List of Detection objects

    Returns:
        A synthetic Detection covering all input detections, or None if empty
    """
    if not detections:
        return None

    if len(detections) == 1:
        return detections[0]

    # Find bounding box that encompasses all detections
    min_x = min(d.bbox[0] for d in detections)
    min_y = min(d.bbox[1] for d in detections)
    max_x = max(d.bbox[2] for d in detections)
    max_y = max(d.bbox[3] for d in detections)

    # Average confidence and sharpness
    avg_confidence = sum(d.confidence for d in detections) / len(detections)
    avg_sharpness = sum(d.sharpness for d in detections) / len(detections)

    return Detection(
        bbox=(min_x, min_y, max_x, max_y),
        confidence=avg_confidence,
        label="group",
        sharpness=avg_sharpness,
        mask=None,
        original_bbox=(min_x, min_y, max_x, max_y)
    )


def should_use_landscape(
    detections: list[Detection],
    threshold: float = 1.5
) -> bool:
    """Determine if the image should use landscape orientation based on subject layout.

    Checks if subjects are arranged more horizontally than vertically,
    which is common in team photos, group shots, or huddles.

    Args:
        detections: List of Detection objects
        threshold: Ratio of width/height above which landscape is recommended

    Returns:
        True if landscape orientation is recommended
    """
    if not detections:
        return False

    if len(detections) == 1:
        # Single detection - check if it's wider than tall
        det = detections[0]
        return det.width / det.height > threshold if det.height > 0 else False

    # Multiple detections - check combined bounding box
    combined = combine_detections(detections)
    if combined is None:
        return False

    # Check if the combined area is significantly wider than tall
    return combined.width / combined.height > threshold if combined.height > 0 else False


def select_primary_subject(
    detections: list[Detection],
    strategy: Literal["largest", "centered", "highest_confidence", "group"] = "highest_confidence",
    balls: list[Detection] | None = None,
    image_size: tuple[int, int] | None = None,
    weights: SubjectWeights | None = None
) -> Detection | None:
    """Select the primary subject from a list of detections.

    All strategies factor in sharpness to avoid selecting out-of-focus subjects.

    Args:
        detections: List of Detection objects
        strategy: Selection strategy
            - "largest": Select the detection with largest bounding box area (sharpness-weighted)
            - "centered": Select the detection closest to image center (sharpness-weighted)
            - "highest_confidence": Smart Select; sports-aware score combining size,
              focus, ball proximity, frame-edge cut-off and confidence
            - "group": Combine all detections into one box
        balls: Sports ball detections, used by Smart Select
        image_size: (width, height) in pixels, used by Smart Select
        weights: Smart Select feature weights (defaults to the configured weights)

    Returns:
        Selected Detection or None if no detections
    """
    if not detections:
        return None

    if len(detections) == 1:
        return detections[0]

    # Calculate sharpness normalization factor
    # We normalize sharpness so the sharpest detection has score 1.0
    max_sharpness = max(d.sharpness for d in detections) if detections else 0.0

    def sharpness_factor(det: Detection) -> float:
        """Returns 0.0-1.0 based on relative sharpness. Below 30% of max is penalized heavily."""
        # If no sharpness data available (all zeros), return 1.0 to not affect selection
        if max_sharpness == 0:
            return 1.0
        relative = det.sharpness / max_sharpness
        if relative < 0.3:
            # Heavily penalize very blurry detections
            return relative * 0.5
        return relative

    if strategy == "largest":
        # Combine area with sharpness: area * sqrt(sharpness_factor)
        # sqrt dampens sharpness effect so size still matters, but blur is penalized
        return max(detections, key=lambda d: d.area * (sharpness_factor(d) ** 0.5))
    elif strategy == "centered":
        # Find detection closest to center, but penalize blurry detections
        def score_centered(det: Detection) -> float:
            cx, cy = det.center
            distance = ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
            # Lower distance = better, higher sharpness = better
            # Return negative distance multiplied by sharpness factor
            return -distance * (2.0 - sharpness_factor(det))
        return max(detections, key=score_centered)
    elif strategy == "highest_confidence":
        scores = score_subjects(detections, balls, image_size, weights)
        return detections[max(range(len(detections)), key=scores.__getitem__)]
    elif strategy == "group":
        # Combine all detections into a single bounding box
        return combine_detections(detections)
    else:
        raise ValueError(f"Unknown selection strategy: {strategy}")


def frame_subject(
    detections: list[Detection],
    strategy: Literal["largest", "centered", "highest_confidence", "group"] = "highest_confidence",
    balls: list[Detection] | None = None,
    image_size: tuple[int, int] | None = None,
    weights: SubjectWeights | None = None
) -> SubjectChoice | None:
    """Choose what to frame: one person, a duel or a group.

    Smart Select decides the mode from the scene; the other strategies pick
    one person, except "group", which frames everyone.

    Args:
        detections: Person detections
        strategy: Selection strategy (see select_primary_subject)
        balls: Sports ball detections, used by Smart Select
        image_size: (width, height) in pixels
        weights: Smart Select feature weights

    Returns:
        SubjectChoice, or None if there are no detections
    """
    if not detections:
        return None
    if strategy == "highest_confidence":
        return choose_subject(detections, balls, image_size, weights)
    if strategy == "group" and len(detections) > 1:
        lead = select_primary_subject(detections, "largest")
        return SubjectChoice(mode=SubjectMode.GROUP, primary=lead, members=list(detections))
    primary = select_primary_subject(detections, strategy)
    return SubjectChoice(mode=SubjectMode.SINGLE, primary=primary, members=[primary])


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def calculate_vertical_crop(
    image_width: int,
    image_height: int,
    subject_bbox: tuple[float, float, float, float],
    target_aspect: tuple[int, int] = (4, 5),
    padding: float = 0.15,
    min_scale: float = MIN_CROP_SCALE
) -> CropRegion:
    """Calculate a crop of the target aspect ratio framed around the subject.

    The crop is sized to fit the subject plus padding on every side, but is
    never smaller than min_scale of the largest crop that fits the image, so
    small or distant subjects are zoomed in on without becoming low-resolution
    slivers. Spare vertical space goes mostly below the subject, which keeps
    headroom modest for people.

    Args:
        image_width: Image width in pixels
        image_height: Image height in pixels
        subject_bbox: Subject bounding box (x1, y1, x2, y2) normalized 0-1
        target_aspect: Target aspect ratio as (width, height), e.g., (4, 5) or (9, 16)
        padding: Space on each side of the subject as a fraction of its size (0.15 = 15%)
        min_scale: Smallest crop as a fraction of the largest crop that fits
            the image (1.0 = never zoom in)

    Returns:
        CropRegion with normalized coordinates
    """
    source_aspect = image_width / image_height
    target_aspect_ratio = target_aspect[0] / target_aspect[1]
    width_per_height = target_aspect_ratio / source_aspect
    max_height = min(1.0, 1.0 / width_per_height)

    subj_x1, subj_y1, subj_x2, subj_y2 = subject_bbox
    subj_width = subj_x2 - subj_x1
    subj_height = subj_y2 - subj_y1

    needed_height = max(
        subj_height * (1 + 2 * padding),
        subj_width * (1 + 2 * padding) / width_per_height,
        max_height * min_scale,
    )
    crop_height = min(needed_height, max_height)
    crop_width = min(1.0, crop_height * width_per_height)

    subj_center_x = (subj_x1 + subj_x2) / 2
    crop_left = _clamp(subj_center_x - crop_width / 2, 0.0, 1.0 - crop_width)

    # A subject taller than the crop keeps its top (heads matter more than feet)
    spare_height = max(0.0, crop_height - subj_height)
    crop_top = _clamp(subj_y1 - spare_height * HEADROOM_SHARE, 0.0, 1.0 - crop_height)

    return CropRegion(
        left=crop_left,
        right=crop_left + crop_width,
        top=crop_top,
        bottom=crop_top + crop_height
    )


def calculate_crop_for_detection(
    detection: Detection,
    image_width: int,
    image_height: int,
    target_aspect: tuple[int, int] = (4, 5),
    padding: float = 0.15,
    min_scale: float = MIN_CROP_SCALE
) -> CropRegion:
    """Convenience function to calculate crop from a Detection object.

    Args:
        detection: Detection object with subject bounding box
        image_width: Image width in pixels
        image_height: Image height in pixels
        target_aspect: Target aspect ratio as (width, height)
        padding: Padding around subject
        min_scale: Smallest crop as a fraction of the largest crop that fits

    Returns:
        CropRegion with normalized coordinates
    """
    return calculate_vertical_crop(
        image_width=image_width,
        image_height=image_height,
        subject_bbox=detection.bbox,
        target_aspect=target_aspect,
        padding=padding,
        min_scale=min_scale
    )


def calculate_crop_for_subject(
    choice: SubjectChoice,
    image_width: int,
    image_height: int,
    target_aspect: tuple[int, int] = (4, 5),
    padding: float = 0.15,
    min_scale: float = MIN_CROP_SCALE
) -> CropRegion:
    """Calculate the crop for a chosen subject, looser for duels and groups.

    Args:
        choice: Subject from frame_subject
        image_width: Image width in pixels
        image_height: Image height in pixels
        target_aspect: Target aspect ratio as (width, height)
        padding: Padding around a single subject; duels and groups add more
        min_scale: Smallest crop as a fraction of the largest crop that fits

    Returns:
        CropRegion with normalized coordinates
    """
    return calculate_vertical_crop(
        image_width=image_width,
        image_height=image_height,
        subject_bbox=choice.bbox,
        target_aspect=target_aspect,
        padding=padding + MODE_EXTRA_PADDING[choice.mode],
        min_scale=min_scale
    )
