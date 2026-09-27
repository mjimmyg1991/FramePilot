"""Tests for sports-aware subject scoring."""

import json

import pytest

from src.crop_calculator import select_primary_subject
from src.detector import Detection
from src.subject_scoring import (
    SubjectWeights,
    load_subject_weights,
    save_subject_weights,
    score_subjects,
    subject_features,
)


IMAGE_SIZE = (6000, 4000)


def person(bbox, confidence=0.9, sharpness=100.0) -> Detection:
    return Detection(bbox=bbox, confidence=confidence, label="person", sharpness=sharpness)


def ball(center, radius=0.01) -> Detection:
    x, y = center
    return Detection(bbox=(x - radius, y - radius, x + radius, y + radius), confidence=0.6,
                     label="sports_ball")


def feature(matrix, row, name):
    return matrix[row][SubjectWeights.names().index(name)]


def pick(people, balls=None):
    return select_primary_subject(people, "highest_confidence", balls=balls,
                                  image_size=IMAGE_SIZE, weights=SubjectWeights())


class TestSubjectFeatures:
    """Tests for the per-person feature values."""

    def test_largest_has_zero_size_feature(self):
        features = subject_features([person((0.1, 0.1, 0.3, 0.9)), person((0.5, 0.5, 0.6, 0.7))])
        assert feature(features, 0, "size") == pytest.approx(0.0)
        assert feature(features, 1, "size") < 0

    def test_side_and_top_cut(self):
        features = subject_features([
            person((0.0, 0.3, 0.1, 0.9)),
            person((0.9, 0.3, 1.0, 0.9)),
            person((0.4, 0.0, 0.5, 0.6)),
            person((0.4, 0.3, 0.5, 1.0)),
        ])
        assert [feature(features, i, "side_cut") for i in range(4)] == [1, 1, 0, 0]
        assert [feature(features, i, "top_cut") for i in range(4)] == [0, 0, 1, 0]

    def test_no_balls_gives_zero_ball_features(self):
        features = subject_features([person((0.1, 0.1, 0.3, 0.9)), person((0.5, 0.1, 0.7, 0.9))])
        for row in range(2):
            assert feature(features, row, "ball_proximity") == 0
            assert feature(features, row, "ball_holder") == 0

    def test_ball_proximity_and_holder(self):
        people = [person((0.1, 0.2, 0.2, 0.9)), person((0.6, 0.2, 0.7, 0.9))]
        features = subject_features(people, [ball((0.22, 0.85))], IMAGE_SIZE)
        assert feature(features, 0, "ball_proximity") > feature(features, 1, "ball_proximity")
        assert feature(features, 0, "ball_holder") == 1
        assert feature(features, 1, "ball_holder") == 0

    def test_ball_inside_box_is_maximum_proximity(self):
        features = subject_features([person((0.1, 0.2, 0.3, 0.9))], [ball((0.2, 0.5))], IMAGE_SIZE)
        assert feature(features, 0, "ball_proximity") == pytest.approx(1.0)

    def test_distance_uses_image_aspect(self):
        # Same normalized horizontal gap is further in a wide image
        people = [person((0.4, 0.2, 0.5, 0.8))]
        wide = subject_features(people, [ball((0.6, 0.5))], (3000, 1000))
        square = subject_features(people, [ball((0.6, 0.5))], (1000, 1000))
        assert feature(wide, 0, "ball_proximity") < feature(square, 0, "ball_proximity")

    def test_empty(self):
        assert subject_features([]).shape == (0, len(SubjectWeights.names()))
        assert score_subjects([]) == []


class TestSportsSelection:
    """Smart Select should pick the player a sports photographer would."""

    def test_player_beats_small_background_figures(self):
        player = person((0.4, 0.2, 0.55, 0.95))
        crowd = [person((x, 0.05, x + 0.03, 0.15), confidence=0.95, sharpness=150) for x in (0.1, 0.2, 0.7)]
        assert pick(crowd + [player]) is player

    def test_player_with_ball_beats_bigger_teammate(self):
        with_ball = person((0.2, 0.3, 0.3, 0.9))
        bigger = person((0.6, 0.2, 0.72, 0.95))
        assert pick([bigger, with_ball], [ball((0.31, 0.85))]) is with_ball

    def test_ball_ignored_when_far_from_everyone(self):
        big = person((0.1, 0.1, 0.4, 0.95))
        small = person((0.6, 0.5, 0.65, 0.7))
        assert pick([small, big], [ball((0.95, 0.05))]) is big

    def test_fully_visible_player_beats_player_cut_by_frame_edge(self):
        cut = person((0.83, 0.37, 1.0, 0.82), sharpness=500)
        visible = person((0.28, 0.38, 0.43, 0.8), sharpness=300)
        assert pick([cut, visible]) is visible

    def test_sharp_player_beats_blurry_foreground(self):
        foreground = person((0.0, 0.1, 0.35, 1.0), sharpness=8)
        player = person((0.5, 0.3, 0.62, 0.85), sharpness=200)
        assert pick([foreground, player]) is player

    def test_single_person_always_selected(self):
        only = person((0.0, 0.0, 0.1, 0.1), confidence=0.5, sharpness=0)
        assert pick([only]) is only


class TestSubjectWeights:
    """Tests for weight vectors and weight files."""

    def test_vector_round_trip(self):
        weights = SubjectWeights(size=3.0, ball_proximity=-1.0)
        assert SubjectWeights.from_vector(weights.as_vector()) == weights

    def test_from_dict_ignores_unknown(self):
        assert SubjectWeights.from_dict({"size": 2.0, "mystery": 5}).size == 2.0

    def test_missing_file_gives_defaults(self, tmp_path):
        assert load_subject_weights(tmp_path / "none.json") == SubjectWeights()

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "w.json"
        weights = SubjectWeights(centrality=0.9)
        save_subject_weights(weights, path, metadata={"photos": 12})
        assert load_subject_weights(path) == weights
        assert json.loads(path.read_text())["metadata"]["photos"] == 12

    def test_partial_file_keeps_other_defaults(self, tmp_path):
        path = tmp_path / "w.json"
        path.write_text(json.dumps({"weights": {"size": 5.0}}))
        loaded = load_subject_weights(path)
        assert loaded.size == 5.0
        assert loaded.side_cut == SubjectWeights().side_cut
