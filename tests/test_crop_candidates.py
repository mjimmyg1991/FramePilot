"""Tests for GAIC-style candidate crop generation and scoring."""

import pytest

from src.crop_calculator import CropRegion
from src.crop_candidates import (
    CropScoreWeights,
    all_heads_in,
    contains,
    crop_terms,
    cuts_ball,
    cuts_head,
    generate_windows,
    head_box,
    rank_crops,
    visible_fraction,
)
from src.detector import Detection
from src.subject_modes import SubjectChoice, SubjectMode


IMAGE_SIZE = (6000, 4000)


def person(bbox) -> Detection:
    return Detection(bbox=bbox, confidence=0.9, label="person", sharpness=100.0)


def ball(center, radius=0.01) -> Detection:
    x, y = center
    return Detection(bbox=(x - radius, y - radius, x + radius, y + radius), confidence=0.6,
                     label="sports_ball")


def single(p: Detection) -> SubjectChoice:
    return SubjectChoice(mode=SubjectMode.SINGLE, primary=p, members=[p])


def pixel_aspect(crop: CropRegion, size=IMAGE_SIZE) -> float:
    return (crop.width * size[0]) / (crop.height * size[1])


class TestGeometry:
    """Tests for head boxes, visibility and containment."""

    def test_head_box_is_central_top(self):
        assert head_box(person((0.2, 0.1, 0.4, 0.9))) == pytest.approx((0.24, 0.1, 0.36, 0.26))

    def test_visible_fraction(self):
        crop = CropRegion(left=0.0, right=0.5, top=0.0, bottom=1.0)
        assert visible_fraction((0.4, 0.2, 0.6, 0.4), crop) == pytest.approx(0.5)
        assert visible_fraction((0.6, 0.2, 0.8, 0.4), crop) == 0.0

    def test_contains_with_tolerance(self):
        crop = CropRegion(left=0.2, right=0.6, top=0.0, bottom=1.0)
        assert contains(crop, (0.195, 0.1, 0.5, 0.5))
        assert not contains(crop, (0.1, 0.1, 0.5, 0.5))


class TestHardConstraints:
    """Tests for the head and ball rejects."""

    def test_cut_through_lead_head(self):
        lead = person((0.4, 0.2, 0.5, 0.9))
        crop = CropRegion(left=0.0, right=0.43, top=0.0, bottom=1.0)
        assert cuts_head(crop, single(lead))

    def test_partner_fully_outside_is_not_a_cut(self):
        lead = person((0.2, 0.2, 0.3, 0.9))
        partner = person((0.7, 0.2, 0.8, 0.9))
        duel = SubjectChoice(mode=SubjectMode.DUEL, primary=lead, members=[lead, partner])
        crop = CropRegion(left=0.0, right=0.5, top=0.0, bottom=1.0)
        assert not cuts_head(crop, duel)
        assert not all_heads_in(crop, duel)

    def test_partner_head_sliced_is_a_cut(self):
        lead = person((0.2, 0.2, 0.3, 0.9))
        partner = person((0.45, 0.2, 0.55, 0.9))
        duel = SubjectChoice(mode=SubjectMode.DUEL, primary=lead, members=[lead, partner])
        crop = CropRegion(left=0.0, right=0.5, top=0.0, bottom=1.0)
        assert cuts_head(crop, duel)

    def test_ball_partly_in_is_cut(self):
        crop = CropRegion(left=0.0, right=0.5, top=0.0, bottom=1.0)
        assert cuts_ball(crop, [ball((0.5, 0.8))])
        assert not cuts_ball(crop, [ball((0.3, 0.8))])
        assert not cuts_ball(crop, [ball((0.8, 0.8))])


class TestWindows:
    """Tests for candidate window generation."""

    def test_windows_keep_aspect_and_bounds(self):
        lead = person((0.45, 0.3, 0.55, 0.9))
        base = CropRegion(left=0.3, right=0.7, top=0.1, bottom=0.85)
        windows = generate_windows(single(lead), base, IMAGE_SIZE, (4, 5))
        assert windows[0] is base
        assert 50 <= len(windows) <= 100
        for window in windows[1:]:
            assert 0.0 <= window.left < window.right <= 1.0 + 1e-9
            assert 0.0 <= window.top < window.bottom <= 1.0 + 1e-9
            assert pixel_aspect(window) == pytest.approx(0.8)


class TestTerms:
    """Tests for the composition terms."""

    def test_partial_intruder_penalized_full_or_absent_not(self):
        lead = person((0.40, 0.2, 0.50, 0.9))
        other = person((0.60, 0.2, 0.70, 0.9))
        choice = single(lead)
        half_in = CropRegion(left=0.3, right=0.65, top=0.0, bottom=1.0)
        fully_in = CropRegion(left=0.3, right=0.75, top=0.0, bottom=1.0)
        out = CropRegion(left=0.3, right=0.58, top=0.0, bottom=1.0)
        terms = [crop_terms(c, choice, [lead, other], [], c.height, (4, 5))["intruder"]
                 for c in (half_in, fully_in, out)]
        assert terms[0] == pytest.approx(1.0)
        assert terms[1] == pytest.approx(0.0)
        assert terms[2] == pytest.approx(0.0)

    def test_extremity_touch(self):
        lead = person((0.40, 0.2, 0.50, 0.9))
        touching = CropRegion(left=0.3, right=0.495, top=0.0, bottom=1.0)
        clear = CropRegion(left=0.3, right=0.6, top=0.0, bottom=1.0)
        assert crop_terms(touching, single(lead), [lead], [], 1.0, (4, 5))["extremity"] == 1
        assert crop_terms(clear, single(lead), [lead], [], 1.0, (4, 5))["extremity"] == 0

    def test_low_head_only_in_verticals(self):
        lead = person((0.40, 0.6, 0.50, 0.9))
        crop = CropRegion(left=0.3, right=0.6, top=0.0, bottom=1.0)
        assert crop_terms(crop, single(lead), [lead], [], 1.0, (4, 5))["low_head"] > 0
        assert crop_terms(crop, single(lead), [lead], [], 1.0, (16, 9))["low_head"] == 0

    def test_lead_room_towards_ball(self):
        lead = person((0.40, 0.2, 0.50, 0.9))
        ahead = CropRegion(left=0.35, right=0.75, top=0.0, bottom=1.0)
        behind = CropRegion(left=0.15, right=0.55, top=0.0, bottom=1.0)
        reachable = [ball((0.55, 0.85))]
        room_ahead = crop_terms(ahead, single(lead), [lead], reachable, 1.0, (4, 5))["lead_room"]
        room_behind = crop_terms(behind, single(lead), [lead], reachable, 1.0, (4, 5))["lead_room"]
        assert room_ahead > 0 > room_behind


class TestRankCrops:
    """Tests for choosing the best windows."""

    def test_returns_distinct_top_three(self):
        lead = person((0.45, 0.3, 0.55, 0.9))
        ranked = rank_crops(single(lead), [lead], image_size=IMAGE_SIZE)
        assert len(ranked) == 3
        assert ranked[0].score >= ranked[1].score >= ranked[2].score
        assert ranked[0].crop != ranked[1].crop

    def test_best_avoids_half_visible_neighbour(self):
        lead = person((0.40, 0.3, 0.50, 0.9))
        neighbour = person((0.60, 0.3, 0.70, 0.9))
        best = rank_crops(single(lead), [lead, neighbour], image_size=IMAGE_SIZE)[0]
        visible = visible_fraction(neighbour.bbox, best.crop)
        assert visible == pytest.approx(0.0, abs=0.05) or visible == pytest.approx(1.0, abs=0.05)

    def test_keeps_reachable_ball_in_frame(self):
        lead = person((0.40, 0.3, 0.48, 0.9))
        near_ball = ball((0.55, 0.85))
        best = rank_crops(single(lead), [lead], [near_ball], IMAGE_SIZE)[0]
        assert contains(best.crop, near_ball.bbox)
        assert not cuts_head(best.crop, single(lead))

    def test_too_wide_duel_frames_the_lead_alone(self):
        lead = person((0.20, 0.3, 0.30, 0.9))
        partner = person((0.70, 0.3, 0.80, 0.9))
        duel = SubjectChoice(mode=SubjectMode.DUEL, primary=lead, members=[lead, partner])
        best = rank_crops(duel, [lead, partner], image_size=IMAGE_SIZE, target_aspect=(9, 16))[0]
        assert best.choice.mode is SubjectMode.SINGLE
        assert best.choice.primary is lead
        assert not cuts_head(best.crop, duel)

    def test_falls_back_to_computed_crop(self):
        # The lead's head can't fit in any 9:16 window of a very wide image
        lead = person((0.0, 0.0, 1.0, 1.0))
        ranked = rank_crops(single(lead), [lead], image_size=(12000, 2000), target_aspect=(9, 16))
        assert len(ranked) == 1
        assert ranked[0].score == float("-inf")

    def test_weights_cover_every_term(self):
        lead = person((0.45, 0.3, 0.55, 0.9))
        ranked = rank_crops(single(lead), [lead], image_size=IMAGE_SIZE)
        assert set(ranked[0].terms) == set(CropScoreWeights.names())
