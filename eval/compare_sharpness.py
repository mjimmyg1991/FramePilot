#!/usr/bin/env python3
"""Compare focus measures for Smart Select on a labelled folder.

Recomputes each detected person's sharpness four ways (Laplacian variance or
Tenengrad, on the head-and-torso core or the head only), rebuilds the subject
features and reports subject-pick accuracy with the current weights and with
cross-validated training:

    python eval/compare_sharpness.py /tmp/sports-eval
"""

import copy
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.detector import SHARPNESS_CORE, SHARPNESS_HEIGHT, SubjectDetector  # noqa: E402
from src.subject_scoring import SubjectWeights, subject_features  # noqa: E402
from src.subject_training import (  # noqa: E402
    build_examples,
    cross_validated_predictions,
    load_labels,
    summarize,
)


HEAD_REGION = (0.2, 0.0, 0.8, 0.2)


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the Laplacian (the current Smart Select measure)."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def tenengrad(gray: np.ndarray) -> float:
    """Mean squared Sobel gradient magnitude."""
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def region_gray(
    image: np.ndarray,
    bbox: tuple[float, float, float, float],
    fractions: tuple[float, float, float, float],
) -> np.ndarray | None:
    """Grayscale sub-region of a box, scaled down like calculate_sharpness."""
    h, w = image.shape[:2]
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x1 = max(0, int((bbox[0] + bw * fractions[0]) * w))
    y1 = max(0, int((bbox[1] + bh * fractions[1]) * h))
    x2 = min(w, int((bbox[0] + bw * fractions[2]) * w))
    y2 = min(h, int((bbox[1] + bh * fractions[3]) * h))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if gray.shape[0] > SHARPNESS_HEIGHT:
        scale = SHARPNESS_HEIGHT / gray.shape[0]
        gray = cv2.resize(gray, (max(1, int(gray.shape[1] * scale)), SHARPNESS_HEIGHT),
                          interpolation=cv2.INTER_AREA)
    return gray


VARIANTS = {
    "Laplacian, head+torso (current)": (laplacian_variance, SHARPNESS_CORE),
    "Tenengrad, head+torso": (tenengrad, SHARPNESS_CORE),
    "Tenengrad, head": (tenengrad, HEAD_REGION),
    "Laplacian, head": (laplacian_variance, HEAD_REGION),
}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    folder = Path(argv[0])
    examples, _ = build_examples(folder, load_labels(folder), SubjectDetector())
    images = {ex.name: cv2.imread(str(folder / ex.name)) for ex in examples}

    for name, (measure, fractions) in VARIANTS.items():
        variant = []
        for ex in examples:
            people = [copy.copy(p) for p in ex.people]
            for p in people:
                gray = region_gray(images[ex.name], p.bbox, fractions)
                if gray is None:
                    gray = region_gray(images[ex.name], p.bbox, (0.0, 0.0, 1.0, 1.0))
                p.sharpness = measure(gray) if gray is not None else 0.0
            changed = copy.copy(ex)
            changed.people = people
            changed.features = subject_features(people, ex.balls, ex.image_size)
            variant.append(changed)

        current = summarize(variant, SubjectWeights())
        held_out = summarize(variant, predictions=cross_validated_predictions(variant, SubjectWeights()))
        hits, total = current["any_member"]
        cv_hits, _ = held_out["any_member"]
        print(f"{name:32s} current {hits}/{total}  cross-validated {cv_hits}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
