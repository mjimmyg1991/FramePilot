"""Headless crop engine for the FramePilot Lightroom Classic plugin.

The plugin renders each selected photo to a small JPEG (with the user's edits
applied), writes a JSON job file, and runs this engine. The engine detects the
subject in each rendition and writes back crop values in Lightroom's develop
coordinate space: normalized to the stored (unrotated) pixels, independent of
the photo's orientation.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import cv2

from .crop_calculator import (
    MIN_CROP_SCALE,
    CropRegion,
    calculate_crop_for_detection,
    select_primary_subject,
)
from .detector import Detection, SubjectDetector


CORNER_POSITIONS = {
    "A": (0.0, 0.0),
    "B": (1.0, 0.0),
    "C": (1.0, 1.0),
    "D": (0.0, 1.0),
}
CLOCKWISE_CORNERS = "ABCD"
VALID_STRATEGIES = {"highest_confidence", "largest", "centered", "group"}


class Detector(Protocol):
    """Anything that can find subjects in an image file."""

    def detect(self, image_path: str | Path) -> list[Detection]: ...


@dataclass
class LrcJobItem:
    """One photo rendition to crop."""

    id: str
    path: Path
    orientation: str = "AB"
    current_crop: CropRegion = field(
        default_factory=lambda: CropRegion(left=0.0, right=1.0, top=0.0, bottom=1.0)
    )


@dataclass
class LrcJobSettings:
    """Crop settings shared by every photo in a job."""

    aspect_ratio: tuple[int, int] = (4, 5)
    padding: float = 0.15
    min_scale: float = MIN_CROP_SCALE
    strategy: str = "highest_confidence"
    precise: bool = False


@dataclass
class LrcJobResult:
    """Outcome for one photo, with the crop in develop coordinates."""

    id: str
    status: str  # "success", "no_subject", "error"
    crop: CropRegion | None = None
    message: str = ""


def _orientation_frame(
    orientation: str,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Return (origin, u_axis, v_axis) mapping displayed coords to stored coords.

    Lightroom describes orientation by the two stored-image corners that end up
    along the top edge of the displayed image, left to right (A=top-left,
    B=top-right, C=bottom-right, D=bottom-left of the stored pixels).
    """
    if (
        len(orientation) != 2
        or orientation[0] not in CORNER_POSITIONS
        or orientation[1] not in CORNER_POSITIONS
    ):
        raise ValueError(f"Unsupported orientation: {orientation!r}")

    first, second = orientation[0], orientation[1]
    idx_first = CLOCKWISE_CORNERS.index(first)
    idx_second = CLOCKWISE_CORNERS.index(second)
    if idx_second == (idx_first + 1) % 4:
        step = 1
    elif idx_second == (idx_first - 1) % 4:
        step = -1
    else:
        raise ValueError(f"Unsupported orientation: {orientation!r}")

    bottom_left = CLOCKWISE_CORNERS[(idx_second + 2 * step) % 4]
    origin = CORNER_POSITIONS[first]
    top_right = CORNER_POSITIONS[second]
    bottom_left_pos = CORNER_POSITIONS[bottom_left]
    u_axis = (top_right[0] - origin[0], top_right[1] - origin[1])
    v_axis = (bottom_left_pos[0] - origin[0], bottom_left_pos[1] - origin[1])
    return origin, u_axis, v_axis


def _bounding_region(points: list[tuple[float, float]]) -> CropRegion:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return CropRegion(left=min(xs), right=max(xs), top=min(ys), bottom=max(ys))


def display_to_original(crop: CropRegion, orientation: str) -> CropRegion:
    """Convert a crop in displayed (oriented) coordinates to develop coordinates.

    Args:
        crop: Crop normalized to the image as the user sees it
        orientation: Lightroom orientation code such as "AB", "BC", "CD", "DA"

    Returns:
        Crop normalized to the stored, unrotated pixels
    """
    origin, u_axis, v_axis = _orientation_frame(orientation)

    def to_original(u: float, v: float) -> tuple[float, float]:
        return (
            origin[0] + u * u_axis[0] + v * v_axis[0],
            origin[1] + u * u_axis[1] + v * v_axis[1],
        )

    return _bounding_region([
        to_original(crop.left, crop.top),
        to_original(crop.right, crop.bottom),
    ])


def original_to_display(crop: CropRegion, orientation: str) -> CropRegion:
    """Convert a crop in develop coordinates to displayed (oriented) coordinates.

    Args:
        crop: Crop normalized to the stored, unrotated pixels
        orientation: Lightroom orientation code such as "AB", "BC", "CD", "DA"

    Returns:
        Crop normalized to the image as the user sees it
    """
    origin, u_axis, v_axis = _orientation_frame(orientation)

    def to_display(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - origin[0], y - origin[1]
        # Axes are unit vectors along x or y, so projection inverts the mapping
        return (
            dx * u_axis[0] + dy * u_axis[1],
            dx * v_axis[0] + dy * v_axis[1],
        )

    return _bounding_region([
        to_display(crop.left, crop.top),
        to_display(crop.right, crop.bottom),
    ])


def _clamp_unit(crop: CropRegion) -> CropRegion:
    def clamp(value: float) -> float:
        return round(min(1.0, max(0.0, value)), 6)

    return CropRegion(
        left=clamp(crop.left),
        right=clamp(crop.right),
        top=clamp(crop.top),
        bottom=clamp(crop.bottom),
    )


def process_item(
    item: LrcJobItem,
    detector: Detector,
    settings: LrcJobSettings,
) -> LrcJobResult:
    """Detect the subject in one rendition and compute its develop-space crop.

    The rendition shows the photo's current crop, so the new crop is placed
    inside that region rather than across the whole frame.

    Args:
        item: Job item describing the rendition and the photo's current state
        detector: Subject detector
        settings: Aspect ratio, padding, minimum crop size and subject strategy

    Returns:
        LrcJobResult with the crop in develop coordinates on success
    """
    image = cv2.imread(str(item.path))
    if image is None:
        return LrcJobResult(id=item.id, status="error", message="Could not read rendition")
    height, width = image.shape[:2]

    detections = detector.detect(item.path)
    if not detections:
        return LrcJobResult(id=item.id, status="no_subject", message="No subject detected")

    primary = select_primary_subject(detections, settings.strategy)
    rendition_crop = calculate_crop_for_detection(
        primary,
        image_width=width,
        image_height=height,
        target_aspect=settings.aspect_ratio,
        padding=settings.padding,
        min_scale=settings.min_scale,
    )

    visible = original_to_display(item.current_crop, item.orientation)
    display_crop = CropRegion(
        left=visible.left + rendition_crop.left * visible.width,
        right=visible.left + rendition_crop.right * visible.width,
        top=visible.top + rendition_crop.top * visible.height,
        bottom=visible.top + rendition_crop.bottom * visible.height,
    )
    develop_crop = display_to_original(display_crop, item.orientation)
    return LrcJobResult(id=item.id, status="success", crop=_clamp_unit(develop_crop))


def _parse_aspect_ratio(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid aspect ratio: {value!r}")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid aspect ratio: {value!r}")
    return (width, height)


def load_job(job_path: str | Path) -> tuple[LrcJobSettings, list[LrcJobItem]]:
    """Read a job file written by the Lightroom plugin.

    Args:
        job_path: Path to the JSON job file

    Returns:
        Tuple of (settings, items)
    """
    with open(job_path, encoding="utf-8") as f:
        data = json.load(f)

    raw_settings = data.get("settings", {})
    strategy = raw_settings.get("strategy", "highest_confidence")
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy!r}")
    settings = LrcJobSettings(
        aspect_ratio=_parse_aspect_ratio(raw_settings.get("aspect_ratio", "4:5")),
        padding=float(raw_settings.get("padding", 0.15)),
        min_scale=float(raw_settings.get("min_scale", MIN_CROP_SCALE)),
        strategy=strategy,
        precise=bool(raw_settings.get("precise", False)),
    )

    items = []
    for raw in data.get("photos", []):
        crop = raw.get("current_crop") or {}
        items.append(LrcJobItem(
            id=str(raw["id"]),
            path=Path(raw["path"]),
            orientation=raw.get("orientation") or "AB",
            current_crop=CropRegion(
                left=float(crop.get("left", 0.0)),
                right=float(crop.get("right", 1.0)),
                top=float(crop.get("top", 0.0)),
                bottom=float(crop.get("bottom", 1.0)),
            ),
        ))
    return settings, items


def _clean_field(value: str) -> str:
    return " ".join(value.split())


def write_results(results: list[LrcJobResult], result_path: str | Path) -> None:
    """Write results as tab-separated lines the Lua plugin can parse.

    Each line: id, status, left, top, right, bottom, message.
    """
    lines = []
    for result in results:
        crop = result.crop
        coords = (
            [f"{crop.left:.6f}", f"{crop.top:.6f}", f"{crop.right:.6f}", f"{crop.bottom:.6f}"]
            if crop is not None
            else ["", "", "", ""]
        )
        lines.append("\t".join([
            _clean_field(result.id),
            result.status,
            *coords,
            _clean_field(result.message),
        ]))

    tmp_path = Path(str(result_path) + ".tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp_path.replace(result_path)


def run_job(
    job_path: str | Path,
    result_path: str | Path,
    detector: Detector | None = None,
) -> int:
    """Process a plugin job file and write the results file.

    Args:
        job_path: JSON job written by the plugin
        result_path: Where to write the tab-separated results
        detector: Optional detector (a YOLO detector is created if omitted)

    Returns:
        Process exit code (0 when the job ran, even if some photos failed)
    """
    settings, items = load_job(job_path)

    if detector is None:
        model = "yolov8m-seg.pt" if settings.precise else "yolov8m.pt"
        detector = SubjectDetector(yolo_model=model, use_tight_bbox=settings.precise)

    results = []
    for item in items:
        try:
            results.append(process_item(item, detector, settings))
        except Exception as e:
            results.append(LrcJobResult(id=item.id, status="error", message=str(e)))

    write_results(results, result_path)
    return 0


def main(argv: list[str]) -> int:
    """Command-line entry point: ``engine JOB_JSON RESULT_TSV``."""
    if len(argv) != 2:
        print("Usage: framepilot-engine JOB_JSON RESULT_TSV", file=sys.stderr)
        return 2
    return run_job(Path(argv[0]), Path(argv[1]))
