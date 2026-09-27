"""Tests for choosing single, duel or group subjects and framing them."""

import pytest

from src.crop_calculator import calculate_crop_for_subject, frame_subject
from src.detector import Detection
from src.subject_modes import MODE_EXTRA_PADDING, SubjectChoice, SubjectMode, choose_subject
from src.subject_scoring import SubjectWeights


IMAGE_SIZE = (6000, 4000)


def person(bbox, sharpness=100.0) -> Detection:
    return Detection(bbox=bbox, confidence=0.9, label="person", sharpness=sharpness)


def ball(center, radius=0.01) -> Detection:
    x, y = center
    return Detection(bbox=(x - radius, y - radius, x + radius, y + radius), confidence=0.6,
                     label="sports_ball")


def choose(people, balls=None):
    return choose_subject(people, balls, IMAGE_SIZE, SubjectWeights())


class TestChooseSubject:
    """Tests for the single / duel / group decision."""

    def test_no_people(self):
        assert choose([]) is None

    def test_lone_player_is_single(self):
        player = person((0.4, 0.2, 0.5, 0.9))
        choice = choose([player])
        assert choice.mode is SubjectMode.SINGLE
        assert choice.members == [player]

    def test_distant_players_stay_single(self):
        choice = choose([person((0.1, 0.2, 0.2, 0.9)), person((0.7, 0.2, 0.8, 0.9))])
        assert choice.mode is SubjectMode.SINGLE

    def test_two_players_side_by_side_are_a_duel(self):
        a = person((0.40, 0.2, 0.50, 0.9))
        b = person((0.52, 0.2, 0.62, 0.9))
        choice = choose([a, b])
        assert choice.mode is SubjectMode.DUEL
        assert set(map(id, choice.members)) == {id(a), id(b)}

    def test_both_within_reach_of_ball_is_a_duel(self):
        # Further apart than a body width, but the ball sits between them
        a = person((0.30, 0.3, 0.38, 0.9))
        b = person((0.52, 0.3, 0.60, 0.9))
        choice = choose([a, b], [ball((0.45, 0.85))])
        assert choice.mode is SubjectMode.DUEL

    def test_cluster_of_three_is_a_group(self):
        people = [person((0.30 + 0.09 * i, 0.2, 0.38 + 0.09 * i, 0.9)) for i in range(3)]
        choice = choose(people)
        assert choice.mode is SubjectMode.GROUP
        assert len(choice.members) == 3

    def test_small_background_people_are_not_members(self):
        lead = person((0.4, 0.2, 0.5, 0.95))
        background = person((0.52, 0.3, 0.55, 0.4))
        choice = choose([lead, background])
        assert choice.mode is SubjectMode.SINGLE

    def test_much_less_important_neighbour_is_not_a_member(self):
        lead = person((0.40, 0.2, 0.50, 0.9), sharpness=500)
        blurry = person((0.52, 0.2, 0.62, 0.9), sharpness=2)
        choice = choose([lead, blurry])
        assert choice.primary is lead
        assert choice.mode is SubjectMode.SINGLE

    def test_union_box(self):
        choice = SubjectChoice(
            mode=SubjectMode.DUEL,
            primary=person((0.4, 0.3, 0.5, 0.9)),
            members=[person((0.4, 0.3, 0.5, 0.9)), person((0.55, 0.2, 0.65, 0.8))],
        )
        assert choice.bbox == pytest.approx((0.4, 0.2, 0.65, 0.9))
        assert choice.as_detection().label == "duel"


class TestFrameSubject:
    """Tests for framing each strategy."""

    def test_smart_select_decides_mode(self):
        a = person((0.40, 0.2, 0.50, 0.9))
        b = person((0.52, 0.2, 0.62, 0.9))
        assert frame_subject([a, b], "highest_confidence", image_size=IMAGE_SIZE).mode is SubjectMode.DUEL

    def test_other_strategies_frame_one_person(self):
        a = person((0.40, 0.2, 0.50, 0.9))
        b = person((0.52, 0.2, 0.62, 0.9))
        for strategy in ("largest", "centered"):
            assert frame_subject([a, b], strategy).mode is SubjectMode.SINGLE

    def test_group_strategy_frames_everyone(self):
        people = [person((0.1, 0.2, 0.2, 0.9)), person((0.7, 0.2, 0.8, 0.9))]
        choice = frame_subject(people, "group")
        assert choice.mode is SubjectMode.GROUP
        assert len(choice.members) == 2

    def test_no_detections(self):
        assert frame_subject([]) is None


class TestCropForSubject:
    """Tests for framing duels and groups more loosely."""

    def test_duel_crop_contains_both_players(self):
        a = person((0.40, 0.4, 0.45, 0.7))
        b = person((0.47, 0.4, 0.52, 0.7))
        choice = SubjectChoice(mode=SubjectMode.DUEL, primary=a, members=[a, b])
        crop = calculate_crop_for_subject(choice, 6000, 4000, (4, 5), padding=0.15)
        assert crop.left <= 0.40 and crop.right >= 0.52
        assert crop.top <= 0.4 and crop.bottom >= 0.7

    def test_duel_padding_is_looser_than_single(self):
        a = person((0.40, 0.3, 0.52, 0.7))
        single = SubjectChoice(mode=SubjectMode.SINGLE, primary=a, members=[a])
        duel = SubjectChoice(mode=SubjectMode.DUEL, primary=a, members=[a])
        single_crop = calculate_crop_for_subject(single, 6000, 4000, (4, 5), padding=0.15)
        duel_crop = calculate_crop_for_subject(duel, 6000, 4000, (4, 5), padding=0.15)
        assert duel_crop.height == pytest.approx(0.4 * (1 + 2 * (0.15 + MODE_EXTRA_PADDING[SubjectMode.DUEL])))
        assert duel_crop.height > single_crop.height

    def test_mode_padding_order(self):
        assert (MODE_EXTRA_PADDING[SubjectMode.SINGLE] < MODE_EXTRA_PADDING[SubjectMode.DUEL]
                < MODE_EXTRA_PADDING[SubjectMode.GROUP])
