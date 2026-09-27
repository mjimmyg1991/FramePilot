"""Generate and score candidate crops around the chosen subject (GAIC-style).

Instead of computing a single window, windows of the target aspect ratio are
generated at several scales and offsets around the subject. Windows that cut
a subject's head, or cut the ball while it is within the lead player's reach,
are rejected. The rest are scored on composition terms: partly visible
non-subjects, hands or feet touching an edge, a low head in a vertical frame,
lead room towards the ball, the ball in frame, balance, and staying close to
the size the padding asks for. The best few distinct windows are returned so
the GUI can offer alternates.
"""

import math
from dataclasses import dataclass, fields

from .crop_calculator import MIN_CROP_SCALE, CropRegion, calculate_crop_for_subject
from .detector import Detection
from .subject_modes import BALL_REACH_HEIGHTS, SubjectChoice, SubjectMode
from .subject_scoring import DEFAULT_IMAGE_SIZE, distance_to_box


HEAD_FRACTION = 0.2
HEAD_WIDTH_FRACTION = 0.6
EXTREMITY_BAND = 0.12
EDGE_TOLERANCE = 0.01
LOW_HEAD_LIMIT = 0.45
SCALE_STEPS = (0.8, 0.9, 1.0, 1.15, 1.3, 1.5)
HORIZONTAL_ANCHORS = (0.3, 0.4, 0.5, 0.6, 0.7)
HEAD_ANCHORS = (0.08, 0.18, 0.3)
TOP_K = 3
BALL_VISIBLE = (0.05, 0.95)
DUPLICATE_IOU = 0.9


@dataclass
class CropScoreWeights:
    """Weight per crop term; hand-set until labelled crops allow training."""

    intruder: float = -2.0
    extremity: float = -0.6
    low_head: float = -2.0
    lead_room: float = 1.0
    ball_in_frame: float = 1.0
    balance: float = -1.0
    scale_change: float = -1.5

    @classmethod
    def names(cls) -> list[str]:
        """Term names in order."""
        return [f.name for f in fields(cls)]


@dataclass
class ScoredCrop:
    """A candidate crop with its score and the term values behind it."""

    crop: CropRegion
    score: float
    terms: dict[str, float]
    choice: SubjectChoice | None = None  # What was framed; the lead alone when a duel or group can't fit


def head_box(person: Detection) -> tuple[float, float, float, float]:
    """Approximate head region: the central top part of a person box."""
    x1, y1, x2, y2 = person.bbox
    inset = (x2 - x1) * (1 - HEAD_WIDTH_FRACTION) / 2
    return (x1 + inset, y1, x2 - inset, y1 + (y2 - y1) * HEAD_FRACTION)


def visible_fraction(bbox: tuple[float, float, float, float], crop: CropRegion) -> float:
    """Share of a box's area inside the crop."""
    ix = max(0.0, min(bbox[2], crop.right) - max(bbox[0], crop.left))
    iy = max(0.0, min(bbox[3], crop.bottom) - max(bbox[1], crop.top))
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    return ix * iy / area if area > 0 else 0.0


def contains(crop: CropRegion, bbox: tuple[float, float, float, float]) -> bool:
    """True when the box lies inside the crop (within a small tolerance)."""
    return (crop.left <= bbox[0] + EDGE_TOLERANCE and crop.right >= bbox[2] - EDGE_TOLERANCE
            and crop.top <= bbox[1] + EDGE_TOLERANCE and crop.bottom >= bbox[3] - EDGE_TOLERANCE)


def balls_in_reach(choice: SubjectChoice, balls: list[Detection], aspect: float) -> list[Detection]:
    """Balls within reach of the lead person."""
    lead = choice.primary
    return [b for b in balls
            if distance_to_box(b.center, lead.bbox, aspect) <= BALL_REACH_HEIGHTS * lead.height]


def all_heads_in(crop: CropRegion, choice: SubjectChoice) -> bool:
    """True when every framed person's head is fully in the crop."""
    return all(contains(crop, head_box(m)) for m in choice.members)


def cuts_head(crop: CropRegion, choice: SubjectChoice) -> bool:
    """True when the lead's head isn't fully in, or another member's head is sliced by an edge.

    A duel partner or group member left fully outside the crop doesn't count.
    """
    if not contains(crop, head_box(choice.primary)):
        return True
    for member in choice.members:
        head = head_box(member)
        if not contains(crop, head) and visible_fraction(head, crop) > 0.0:
            return True
    return False


def cuts_ball(crop: CropRegion, reachable: list[Detection]) -> bool:
    """True when a reachable ball is partly in and partly out of the crop.

    Uses visible area rather than the edge tolerance, which is as wide as a
    small ball.
    """
    return any(BALL_VISIBLE[0] < visible_fraction(b.bbox, crop) < BALL_VISIBLE[1] for b in reachable)


def _extremity_touches(crop: CropRegion, person: Detection) -> int:
    """Crop edges running through the outer band of a person's box (hands, feet)."""
    x1, y1, x2, y2 = person.bbox
    band_x = (x2 - x1) * EXTREMITY_BAND
    band_y = (y2 - y1) * EXTREMITY_BAND
    touches = 0
    if x1 - EDGE_TOLERANCE < crop.left < x1 + band_x and crop.left > EDGE_TOLERANCE:
        touches += 1
    if x2 - band_x < crop.right < x2 + EDGE_TOLERANCE and crop.right < 1.0 - EDGE_TOLERANCE:
        touches += 1
    if y2 - band_y < crop.bottom < y2 + EDGE_TOLERANCE and crop.bottom < 1.0 - EDGE_TOLERANCE:
        touches += 1
    return touches


def crop_terms(
    crop: CropRegion,
    choice: SubjectChoice,
    people: list[Detection],
    reachable: list[Detection],
    base_height: float,
    target_aspect: tuple[int, int],
) -> dict[str, float]:
    """Composition term values for one window (see CropScoreWeights)."""
    lead = choice.primary
    member_ids = {id(m) for m in choice.members}

    intruder = 0.0
    for person in people:
        if id(person) in member_ids:
            continue
        visible = visible_fraction(person.bbox, crop)
        partial = 2 * min(visible, 1.0 - visible)
        intruder += partial * min(1.0, person.height / max(lead.height, 1e-6))

    extremity = float(sum(_extremity_touches(crop, m) for m in choice.members))

    low_head = 0.0
    if target_aspect[0] < target_aspect[1]:
        head_position = (lead.bbox[1] - crop.top) / crop.height
        low_head = max(0.0, head_position - LOW_HEAD_LIMIT) / (1 - LOW_HEAD_LIMIT)

    subject_x = (choice.bbox[0] + choice.bbox[2]) / 2
    crop_x = (crop.left + crop.right) / 2
    lead_room = 0.0
    ball_in_frame = 0.0
    weight_x = subject_x
    if reachable:
        ball = min(reachable, key=lambda b: abs(b.center[0] - subject_x))
        ahead = crop.right - subject_x if ball.center[0] >= subject_x else subject_x - crop.left
        behind = crop.width - ahead
        lead_room = (ahead - behind) / crop.width
        ball_in_frame = 1.0 if visible_fraction(ball.bbox, crop) >= BALL_VISIBLE[1] else 0.0
        weight_x = (subject_x + ball.center[0]) / 2
    balance = min(1.0, abs(weight_x - crop_x) / (crop.width / 2))

    return {
        "intruder": intruder,
        "extremity": extremity,
        "low_head": low_head,
        "lead_room": lead_room,
        "ball_in_frame": ball_in_frame,
        "balance": balance,
        "scale_change": abs(math.log(crop.height / base_height)),
    }


def _window(center_x: float, top: float, height: float, width_per_height: float) -> CropRegion:
    width = min(1.0, height * width_per_height)
    left = max(0.0, min(center_x - width / 2, 1.0 - width))
    top = max(0.0, min(top, 1.0 - height))
    return CropRegion(left=left, right=left + width, top=top, bottom=top + height)


def generate_windows(
    choice: SubjectChoice,
    base: CropRegion,
    image_size: tuple[int, int],
    target_aspect: tuple[int, int],
    min_scale: float = MIN_CROP_SCALE,
) -> list[CropRegion]:
    """Candidate windows of the target aspect at several scales and offsets.

    The base window (the single computed crop) comes first.
    """
    width, height = image_size
    width_per_height = (target_aspect[0] / target_aspect[1]) / (width / height)
    max_height = min(1.0, 1.0 / width_per_height)
    subject_x = (choice.bbox[0] + choice.bbox[2]) / 2
    subject_top = choice.bbox[1]

    windows = [base]
    heights = sorted({
        round(min(max(base.height * step, max_height * min_scale), max_height), 6)
        for step in SCALE_STEPS
    })
    for crop_height in heights:
        crop_width = min(1.0, crop_height * width_per_height)
        for anchor_x in HORIZONTAL_ANCHORS:
            center_x = subject_x + (0.5 - anchor_x) * crop_width
            for anchor_y in HEAD_ANCHORS:
                windows.append(_window(center_x, subject_top - anchor_y * crop_height,
                                       crop_height, width_per_height))
    return windows


def _iou(a: CropRegion, b: CropRegion) -> float:
    ix = max(0.0, min(a.right, b.right) - max(a.left, b.left))
    iy = max(0.0, min(a.bottom, b.bottom) - max(a.top, b.top))
    inter = ix * iy
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


def rank_crops(
    choice: SubjectChoice,
    people: list[Detection],
    balls: list[Detection] | None = None,
    image_size: tuple[int, int] | None = None,
    target_aspect: tuple[int, int] = (4, 5),
    padding: float = 0.15,
    min_scale: float = MIN_CROP_SCALE,
    weights: CropScoreWeights | None = None,
    top_k: int = TOP_K,
) -> list[ScoredCrop]:
    """Best distinct crops for a subject, best first.

    Args:
        choice: Subject from frame_subject
        people: Every detected person (to penalize partly visible ones)
        balls: Sports ball detections, if any
        image_size: (width, height) in pixels
        target_aspect: Target aspect ratio as (width, height)
        padding: Padding around a single subject (sets the preferred size)
        min_scale: Smallest crop as a fraction of the largest crop that fits
        weights: Crop term weights
        top_k: How many distinct crops to return

    Returns:
        Up to top_k ScoredCrops. When no window keeps a duel or group's heads
        in frame, the lead is framed alone; when nothing passes, the single
        computed crop is returned with a score of -inf
    """
    image_size = image_size or DEFAULT_IMAGE_SIZE
    weights = weights or CropScoreWeights()
    aspect = image_size[0] / image_size[1]
    reachable = balls_in_reach(choice, balls or [], aspect)

    def score_windows(framed: SubjectChoice, keep_all_heads: bool) -> list[ScoredCrop]:
        base = calculate_crop_for_subject(framed, image_size[0], image_size[1], target_aspect,
                                          padding, min_scale)
        scored = []
        for window in generate_windows(framed, base, image_size, target_aspect, min_scale):
            heads_ok = all_heads_in(window, framed) if keep_all_heads else not cuts_head(window, choice)
            if not heads_ok or cuts_ball(window, reachable):
                continue
            terms = crop_terms(window, framed, people, reachable, base.height, target_aspect)
            score = sum(getattr(weights, name) * terms[name] for name in CropScoreWeights.names())
            scored.append(ScoredCrop(crop=window, score=score, terms=terms, choice=framed))
        return scored

    scored = score_windows(choice, keep_all_heads=True)
    if not scored and choice.mode is not SubjectMode.SINGLE:
        # The duel or group doesn't fit: frame the lead, leaving partners fully in or out
        lead_only = SubjectChoice(mode=SubjectMode.SINGLE, primary=choice.primary, members=[choice.primary])
        scored = score_windows(lead_only, keep_all_heads=False)

    if not scored:
        base = calculate_crop_for_subject(choice, image_size[0], image_size[1], target_aspect,
                                          padding, min_scale)
        terms = crop_terms(base, choice, people, reachable, base.height, target_aspect)
        return [ScoredCrop(crop=base, score=float("-inf"), terms=terms, choice=choice)]

    scored.sort(key=lambda c: c.score, reverse=True)
    best: list[ScoredCrop] = []
    for candidate in scored:
        if all(_iou(candidate.crop, kept.crop) < DUPLICATE_IOU for kept in best):
            best.append(candidate)
        if len(best) == top_k:
            break
    return best
