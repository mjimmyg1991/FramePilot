"""Sports-aware scoring for choosing the main subject among detected people.

Each person gets a feature vector (relative size, focus, distance to the
ball, whether the frame edge cuts them off, ...). The subject score is a
weighted sum of those features; the weights can be fitted to labelled photos
with ``src.subject_training`` and are loaded from config/subject_weights.json
when present.
"""

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np

from src import resource_path

from .detector import Detection


WEIGHTS_PATH = "config/subject_weights.json"
EDGE_MARGIN = 0.005
MIN_LOG_RATIO = -4.0
DEFAULT_IMAGE_SIZE = (3, 2)


@dataclass
class SubjectWeights:
    """Weight per subject feature; higher scores win."""

    size: float = 1.6
    sharpness: float = 0.7
    confidence: float = 1.0
    centrality: float = 0.4
    side_cut: float = -2.5
    top_cut: float = -1.0
    ball_proximity: float = 2.0
    ball_holder: float = 0.5

    @classmethod
    def names(cls) -> list[str]:
        """Feature names in vector order."""
        return [f.name for f in fields(cls)]

    def as_vector(self) -> np.ndarray:
        """Weights as a numpy vector in feature order."""
        return np.array([getattr(self, name) for name in self.names()], dtype=float)

    @classmethod
    def from_vector(cls, vector: np.ndarray) -> "SubjectWeights":
        """Build weights from a vector in feature order."""
        return cls(**{name: float(v) for name, v in zip(cls.names(), vector)})

    @classmethod
    def from_dict(cls, data: dict) -> "SubjectWeights":
        """Build weights from a dict, ignoring unknown keys."""
        known = set(cls.names())
        return cls(**{k: float(v) for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, float]:
        """Weights as a plain dict."""
        return asdict(self)


def load_subject_weights(path: str | Path | None = None) -> SubjectWeights:
    """Load weights from a JSON file, falling back to the built-in defaults.

    Args:
        path: Weights file; defaults to the bundled config/subject_weights.json

    Returns:
        SubjectWeights
    """
    weights_path = Path(path) if path is not None else resource_path(WEIGHTS_PATH)
    if not weights_path.exists():
        return SubjectWeights()
    with open(weights_path, encoding="utf-8") as f:
        data = json.load(f)
    return SubjectWeights.from_dict(data.get("weights", data))


def save_subject_weights(weights: SubjectWeights, path: str | Path, metadata: dict | None = None) -> None:
    """Write weights (and optional training metadata) to a JSON file."""
    payload = {"weights": weights.to_dict()}
    if metadata:
        payload["metadata"] = metadata
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def _log_ratio(value: float, maximum: float) -> float:
    if maximum <= 0 or value <= 0:
        return MIN_LOG_RATIO if maximum > 0 else 0.0
    return max(MIN_LOG_RATIO, math.log(value / maximum))


def _distance_to_box(
    point: tuple[float, float],
    bbox: tuple[float, float, float, float],
    aspect: float,
) -> float:
    """Distance from a point to a box in image-height units (0 inside)."""
    dx = max(bbox[0] - point[0], 0.0, point[0] - bbox[2]) * aspect
    dy = max(bbox[1] - point[1], 0.0, point[1] - bbox[3])
    return math.hypot(dx, dy)


def subject_features(
    people: list[Detection],
    balls: list[Detection] | None = None,
    image_size: tuple[int, int] | None = None,
) -> np.ndarray:
    """Compute the feature matrix for a set of detected people.

    Args:
        people: Person detections (normalized bboxes)
        balls: Sports ball detections, if any
        image_size: (width, height) in pixels, used to measure true distances

    Returns:
        Array of shape (len(people), len(SubjectWeights.names()))
    """
    names = SubjectWeights.names()
    matrix = np.zeros((len(people), len(names)), dtype=float)
    if not people:
        return matrix

    width, height = image_size or DEFAULT_IMAGE_SIZE
    aspect = width / height
    balls = balls or []

    extents = [math.sqrt(max(p.width * aspect, 0.0) * max(p.height, 0.0)) for p in people]
    max_extent = max(extents)
    max_sharpness = max(p.sharpness for p in people)

    ball_distances = []
    for person in people:
        if balls:
            nearest = min(_distance_to_box(b.center, person.bbox, aspect) for b in balls)
            ball_distances.append(nearest / max(person.height, 1e-6))
        else:
            ball_distances.append(None)

    reachable = [d for d in ball_distances if d is not None]
    closest = min(reachable) if reachable else None

    for i, (person, extent) in enumerate(zip(people, extents)):
        x1, y1, x2, y2 = person.bbox
        distance = ball_distances[i]
        values = {
            "size": _log_ratio(extent, max_extent),
            "sharpness": _log_ratio(person.sharpness, max_sharpness),
            "confidence": person.confidence,
            "centrality": 1.0 - min(1.0, abs(person.center[0] - 0.5) * 2),
            "side_cut": 1.0 if x1 <= EDGE_MARGIN or x2 >= 1.0 - EDGE_MARGIN else 0.0,
            "top_cut": 1.0 if y1 <= EDGE_MARGIN else 0.0,
            "ball_proximity": math.exp(-distance) if distance is not None else 0.0,
            "ball_holder": 1.0 if distance is not None and distance == closest else 0.0,
        }
        matrix[i] = [values[name] for name in names]
    return matrix


def score_subjects(
    people: list[Detection],
    balls: list[Detection] | None = None,
    image_size: tuple[int, int] | None = None,
    weights: SubjectWeights | None = None,
) -> list[float]:
    """Score each person as the likely main subject (higher is better).

    Args:
        people: Person detections
        balls: Sports ball detections, if any
        image_size: (width, height) in pixels
        weights: Feature weights (defaults to load_subject_weights())

    Returns:
        One score per person, in input order
    """
    if not people:
        return []
    weights = weights or load_subject_weights()
    features = subject_features(people, balls, image_size)
    return list(features @ weights.as_vector())
