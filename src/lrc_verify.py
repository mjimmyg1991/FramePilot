"""Crop position self-check for the FramePilot Lightroom Classic plugin.

After the plugin applies crops it renders each photo again, small. This module
compares that render with the region of the pre-crop rendition where the crop
should have landed. A low match means the display-to-develop mapping was wrong
for that photo (for example an orientation code read the wrong way round), so
the plugin restores the previous crop.

To help diagnose a mismatch, every orientation is also tried and the one that
best explains the new render is reported alongside the one that was used.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .crop_calculator import CropRegion
from .lrc_bridge import original_to_display


ORIENTATIONS = ("AB", "BC", "CD", "DA", "BA", "AD", "DC", "CB")
MATCH_THRESHOLD = 0.8
MIN_DETAIL = 3.0
COMPARE_LONG_EDGE = 128
BLUR_SIGMA = 1.0
MAX_ASPECT_DIFFERENCE = 0.12
REGION_TOLERANCE = 0.02


@dataclass
class VerifyItem:
    """One cropped photo to check."""

    id: str
    before_path: Path
    after_path: Path
    orientation: str
    previous_crop: CropRegion
    applied_crop: CropRegion


@dataclass
class VerifyResult:
    """Outcome of the position check for one photo."""

    id: str
    status: str  # "match", "mismatch", "inconclusive", "error"
    score: float | None = None
    best_orientation: str = ""
    best_score: float | None = None
    message: str = ""
    scores: dict[str, float | None] = field(default_factory=dict)


def expected_region(
    previous_crop: CropRegion,
    applied_crop: CropRegion,
    orientation: str,
) -> CropRegion | None:
    """Where the applied crop should appear in the pre-crop rendition.

    The pre-crop rendition shows the previous crop as displayed. Assuming the
    given orientation, this maps the newly applied develop crop into that
    rendition's normalized coordinates.

    Args:
        previous_crop: Crop before FramePilot ran, in develop coordinates
        applied_crop: Crop FramePilot applied, in develop coordinates
        orientation: Lightroom orientation code to assume

    Returns:
        Region normalized to the pre-crop rendition, or None when the applied
        crop would reach outside it
    """
    visible = original_to_display(previous_crop, orientation)
    shown = original_to_display(applied_crop, orientation)
    if visible.width <= 0 or visible.height <= 0:
        return None
    region = CropRegion(
        left=(shown.left - visible.left) / visible.width,
        right=(shown.right - visible.left) / visible.width,
        top=(shown.top - visible.top) / visible.height,
        bottom=(shown.bottom - visible.top) / visible.height,
    )
    low, high = -REGION_TOLERANCE, 1.0 + REGION_TOLERANCE
    if min(region.left, region.top) < low or max(region.right, region.bottom) > high:
        return None
    return region


def _prepare(gray: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    resized = cv2.resize(gray, size, interpolation=cv2.INTER_AREA).astype(np.float64)
    return cv2.GaussianBlur(resized, (0, 0), BLUR_SIGMA)


def _compare_size(width: int, height: int) -> tuple[int, int]:
    scale = COMPARE_LONG_EDGE / max(width, height)
    return max(8, round(width * scale)), max(8, round(height * scale))


def match_score(
    before: np.ndarray,
    after: np.ndarray,
    region: CropRegion,
) -> float | None:
    """Normalized cross-correlation between a region of ``before`` and ``after``.

    Args:
        before: Pre-crop rendition, grayscale
        after: Post-crop render, grayscale
        region: Normalized region of ``before`` expected to match ``after``

    Returns:
        Correlation in [-1, 1], -1.0 when the region's shape can't match the
        render, or None when either image has too little detail to judge
    """
    before_h, before_w = before.shape[:2]
    after_h, after_w = after.shape[:2]
    left = int(round(max(0.0, region.left) * before_w))
    right = int(round(min(1.0, region.right) * before_w))
    top = int(round(max(0.0, region.top) * before_h))
    bottom = int(round(min(1.0, region.bottom) * before_h))
    if right - left < 2 or bottom - top < 2:
        return -1.0

    region_aspect = (right - left) / (bottom - top)
    after_aspect = after_w / after_h
    if abs(np.log(region_aspect / after_aspect)) > MAX_ASPECT_DIFFERENCE:
        return -1.0

    size = _compare_size(after_w, after_h)
    expected = _prepare(before[top:bottom, left:right], size)
    actual = _prepare(after, size)
    expected -= expected.mean()
    actual -= actual.mean()
    if expected.std() < MIN_DETAIL or actual.std() < MIN_DETAIL:
        return None
    denominator = np.sqrt((expected ** 2).sum() * (actual ** 2).sum())
    return float((expected * actual).sum() / denominator)


def _read_gray(path: Path) -> np.ndarray | None:
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


def verify_item(item: VerifyItem) -> VerifyResult:
    """Check that the applied crop shows the region FramePilot intended.

    Args:
        item: Renditions, orientation and crops for one photo

    Returns:
        VerifyResult with the score for the photo's orientation and the
        best-scoring orientation
    """
    before = _read_gray(item.before_path)
    if before is None:
        return VerifyResult(id=item.id, status="error", message="Could not read the pre-crop rendition")
    after = _read_gray(item.after_path)
    if after is None:
        return VerifyResult(id=item.id, status="error", message="Could not read the post-crop render")

    scores: dict[str, float | None] = {}
    for orientation in ORIENTATIONS:
        region = expected_region(item.previous_crop, item.applied_crop, orientation)
        scores[orientation] = -1.0 if region is None else match_score(before, after, region)

    used = scores.get(item.orientation)
    if item.orientation not in scores:
        region = expected_region(item.previous_crop, item.applied_crop, item.orientation)
        used = -1.0 if region is None else match_score(before, after, region)
        scores[item.orientation] = used

    rated = {name: score for name, score in scores.items() if score is not None}
    best_orientation = max(rated, key=rated.get) if rated else ""
    best_score = rated.get(best_orientation)

    if used is None:
        status = "inconclusive"
        message = "Too little detail to check the crop position"
    elif used >= MATCH_THRESHOLD:
        status = "match"
        message = "Crop landed where expected"
    else:
        status = "mismatch"
        message = (
            f"Crop didn't land where expected: orientation {item.orientation} scored {used:.2f}, "
            f"best was {best_orientation} at {best_score:.2f}"
        )
    return VerifyResult(
        id=item.id,
        status=status,
        score=used,
        best_orientation=best_orientation,
        best_score=best_score,
        message=message,
        scores=scores,
    )


def _crop_from_json(raw: dict | None) -> CropRegion:
    raw = raw or {}
    return CropRegion(
        left=float(raw.get("left", 0.0)),
        right=float(raw.get("right", 1.0)),
        top=float(raw.get("top", 0.0)),
        bottom=float(raw.get("bottom", 1.0)),
    )


def load_verify_job(job_path: str | Path) -> list[VerifyItem]:
    """Read a verify job written by the Lightroom plugin.

    Args:
        job_path: Path to the JSON verify job

    Returns:
        Items to check
    """
    with open(job_path, encoding="utf-8") as f:
        data = json.load(f)
    return [
        VerifyItem(
            id=str(raw["id"]),
            before_path=Path(raw["before"]),
            after_path=Path(raw["after"]),
            orientation=raw.get("orientation") or "AB",
            previous_crop=_crop_from_json(raw.get("previous_crop")),
            applied_crop=_crop_from_json(raw.get("applied_crop")),
        )
        for raw in data.get("photos", [])
    ]


def _format_score(score: float | None) -> str:
    return "" if score is None else f"{score:.4f}"


def write_verify_results(results: list[VerifyResult], result_path: str | Path) -> None:
    """Write results as tab-separated lines the Lua plugin can parse.

    Each line: id, status, score, best orientation, best score, message.
    """
    lines = [
        "\t".join([
            " ".join(result.id.split()),
            result.status,
            _format_score(result.score),
            result.best_orientation,
            _format_score(result.best_score),
            " ".join(result.message.split()),
        ])
        for result in results
    ]
    tmp_path = Path(str(result_path) + ".tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp_path.replace(result_path)


def run_verify(job_path: str | Path, result_path: str | Path) -> int:
    """Check every photo in a verify job and write the results file.

    Scores for every orientation are printed so they end up in the run's log.

    Args:
        job_path: JSON verify job written by the plugin
        result_path: Where to write the tab-separated results

    Returns:
        Process exit code (0 when the job ran, even if some photos mismatched)
    """
    results = []
    for item in load_verify_job(job_path):
        try:
            result = verify_item(item)
        except Exception as e:
            result = VerifyResult(id=item.id, status="error", message=str(e))
        results.append(result)
        scores = " ".join(f"{name}={_format_score(score) or 'n/a'}" for name, score in result.scores.items())
        print(
            f"photo {item.id}: {result.status}; orientation used {item.orientation}, "
            f"best {result.best_orientation or 'n/a'}; scores {scores}"
        )

    write_verify_results(results, result_path)
    return 0


def main(argv: list[str]) -> int:
    """Command-line entry point: ``engine --verify JOB_JSON RESULT_TSV``."""
    if len(argv) != 2:
        print("Usage: framepilot-engine --verify JOB_JSON RESULT_TSV", file=sys.stderr)
        return 2
    return run_verify(Path(argv[0]), Path(argv[1]))
