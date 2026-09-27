"""Decide whether a photo's subject is one player, a duel or a group.

Smart Select ranks people with subject_scoring, then grows a cluster around
the top-ranked person: similar-scale people who are nearly as important and
either close to the cluster or within reach of the ball with the top
person. Two people make a duel (a contest for the ball); three or more make
a group (celebration, huddle, pile-on). Duels and groups are framed as the
union of their members with looser padding.
"""

import math
from dataclasses import dataclass
from enum import Enum

from .detector import Detection
from .subject_scoring import (
    DEFAULT_IMAGE_SIZE,
    SubjectWeights,
    distance_to_box,
    score_subjects,
)


SIMILAR_SCALE = 0.6
CLUSTER_GAP_WIDTHS = 1.0
BALL_REACH_HEIGHTS = 1.0
MIN_RELATIVE_IMPORTANCE = 0.25


class SubjectMode(Enum):
    """What the photo's subject is."""

    SINGLE = "single"
    DUEL = "duel"
    GROUP = "group"


MODE_EXTRA_PADDING = {
    SubjectMode.SINGLE: 0.0,
    SubjectMode.DUEL: 0.1,
    SubjectMode.GROUP: 0.2,
}


@dataclass
class SubjectChoice:
    """The chosen subject: its mode, the lead person and everyone framed with them."""

    mode: SubjectMode
    primary: Detection
    members: list[Detection]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Union of the members' boxes (normalized)."""
        return (
            min(m.bbox[0] for m in self.members),
            min(m.bbox[1] for m in self.members),
            max(m.bbox[2] for m in self.members),
            max(m.bbox[3] for m in self.members),
        )

    def as_detection(self) -> Detection:
        """The lead person, or a synthetic detection covering a duel or group."""
        if self.mode is SubjectMode.SINGLE:
            return self.primary
        return Detection(
            bbox=self.bbox,
            confidence=self.primary.confidence,
            label=self.mode.value,
            sharpness=self.primary.sharpness,
            original_bbox=self.bbox,
        )


def _similar_scale(a: Detection, b: Detection) -> bool:
    ratio = a.height / max(b.height, 1e-6)
    return SIMILAR_SCALE <= ratio <= 1 / SIMILAR_SCALE


def _gap(a: Detection, b: Detection, aspect: float) -> float:
    """Distance between two boxes in image-height units (0 when they overlap)."""
    dx = max(0.0, max(a.bbox[0], b.bbox[0]) - min(a.bbox[2], b.bbox[2])) * aspect
    dy = max(0.0, max(a.bbox[1], b.bbox[1]) - min(a.bbox[3], b.bbox[3]))
    return math.hypot(dx, dy)


def _close(a: Detection, b: Detection, aspect: float) -> bool:
    body_width = (a.width + b.width) / 2 * aspect
    return _gap(a, b, aspect) <= CLUSTER_GAP_WIDTHS * body_width


def _within_reach(person: Detection, ball: Detection, aspect: float) -> bool:
    return distance_to_box(ball.center, person.bbox, aspect) <= BALL_REACH_HEIGHTS * person.height


def choose_subject(
    people: list[Detection],
    balls: list[Detection] | None = None,
    image_size: tuple[int, int] | None = None,
    weights: SubjectWeights | None = None,
) -> SubjectChoice | None:
    """Pick the lead person and decide between single, duel and group.

    Args:
        people: Person detections
        balls: Sports ball detections, if any
        image_size: (width, height) in pixels
        weights: Smart Select feature weights

    Returns:
        SubjectChoice, or None when there are no people
    """
    if not people:
        return None
    width, height = image_size or DEFAULT_IMAGE_SIZE
    aspect = width / height
    balls = balls or []

    scores = score_subjects(people, balls, image_size, weights)
    order = sorted(range(len(people)), key=lambda i: scores[i], reverse=True)
    lead = order[0]
    primary = people[lead]

    candidates = [
        i for i in order[1:]
        if _similar_scale(people[i], primary)
        and math.exp(scores[i] - scores[lead]) >= MIN_RELATIVE_IMPORTANCE
    ]

    cluster = [lead]
    lead_reaches = [b for b in balls if _within_reach(primary, b, aspect)]
    for i in candidates:
        if any(_within_reach(people[i], b, aspect) for b in lead_reaches):
            cluster.append(i)
            break

    grew = True
    while grew:
        grew = False
        for i in candidates:
            if i not in cluster and any(_close(people[i], people[j], aspect) for j in cluster):
                cluster.append(i)
                grew = True

    members = [people[i] for i in cluster]
    if len(members) >= 3:
        mode = SubjectMode.GROUP
    elif len(members) == 2:
        mode = SubjectMode.DUEL
    else:
        mode = SubjectMode.SINGLE
    return SubjectChoice(mode=mode, primary=primary, members=members)
