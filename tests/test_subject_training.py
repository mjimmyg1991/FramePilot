"""Tests for labelling helpers and Smart Select weight training."""

import cv2
import numpy as np
import pytest

from src.detector import Detection, SceneDetections
from src.subject_scoring import SubjectWeights
from src.subject_training import (
    TrainingExample,
    accuracy,
    box_at_point,
    build_examples,
    cross_validate,
    fit_weights,
    iou,
    load_labels,
    match_label,
    predict,
    save_labels,
)


def person(bbox) -> Detection:
    return Detection(bbox=bbox, confidence=0.9, label="person", sharpness=100.0)


def synthetic_examples(count: int, feature_name: str, seed: int = 0) -> list[TrainingExample]:
    """Photos where only one feature tells the labelled person apart."""
    rng = np.random.default_rng(seed)
    column = SubjectWeights.names().index(feature_name)
    examples = []
    for i in range(count):
        features = rng.normal(0, 0.05, size=(3, len(SubjectWeights.names())))
        label = int(rng.integers(0, 3))
        features[label, column] += 1.0
        examples.append(TrainingExample(name=f"{i}.jpg", features=features, label_index=label))
    return examples


class TestLabelMatching:
    """Tests for matching labels and clicks to detections."""

    def test_iou(self):
        assert iou((0, 0, 1, 1), (0, 0, 1, 1)) == pytest.approx(1.0)
        assert iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0
        assert iou((0, 0, 2, 1), (1, 0, 3, 1)) == pytest.approx(1 / 3)

    def test_match_label_picks_best_overlap(self):
        people = [person((0.1, 0.1, 0.3, 0.9)), person((0.5, 0.1, 0.7, 0.9))]
        assert match_label(people, (0.51, 0.12, 0.7, 0.88)) == 1

    def test_match_label_requires_overlap(self):
        people = [person((0.1, 0.1, 0.3, 0.9))]
        assert match_label(people, (0.25, 0.1, 0.5, 0.9)) is None

    def test_box_at_point_prefers_smallest(self):
        people = [person((0.0, 0.0, 1.0, 1.0)), person((0.4, 0.4, 0.6, 0.6))]
        assert box_at_point(people, (0.5, 0.5)) == 1
        assert box_at_point(people, (0.1, 0.1)) == 0
        assert box_at_point([person((0.4, 0.4, 0.6, 0.6))], (0.1, 0.1)) is None

    def test_labels_round_trip(self, tmp_path):
        labels = {"a.jpg": {"bbox": [0.1, 0.2, 0.3, 0.4]}, "b.jpg": {"skip": "no clear subject"}}
        save_labels(tmp_path, labels)
        assert load_labels(tmp_path) == labels
        assert load_labels(tmp_path / "missing") == {}


class TestTraining:
    """Tests for fitting weights to labelled examples."""

    def test_fit_learns_informative_feature(self):
        examples = synthetic_examples(40, "ball_holder")
        start = SubjectWeights(**{name: 0.0 for name in SubjectWeights.names()})
        assert accuracy(examples, start) < 0.9

        fitted = fit_weights(examples, start, l2=0.01)

        assert accuracy(examples, fitted) == pytest.approx(1.0)
        assert fitted.ball_holder > 1.0

    def test_strong_prior_keeps_weights_near_initial(self):
        examples = synthetic_examples(20, "centrality")
        initial = SubjectWeights()
        fitted = fit_weights(examples, initial, l2=100.0)
        assert np.abs(fitted.as_vector() - initial.as_vector()).max() < 0.05

    def test_no_examples_returns_initial(self):
        initial = SubjectWeights(size=2.5)
        assert fit_weights([], initial) == initial

    def test_cross_validation_generalizes(self):
        examples = synthetic_examples(30, "size", seed=3)
        start = SubjectWeights(**{name: 0.0 for name in SubjectWeights.names()})
        assert cross_validate(examples, start, folds=5, l2=0.01) >= 0.9

    def test_predict(self):
        features = np.zeros((2, len(SubjectWeights.names())))
        features[1, SubjectWeights.names().index("size")] = 1.0
        example = TrainingExample(name="x.jpg", features=features, label_index=1)
        assert predict(example, SubjectWeights()) == 1


class TestBuildExamples:
    """Tests for turning a labelled folder into training examples."""

    def test_builds_matches_and_skips(self, tmp_path):
        for name in ("pair.jpg", "solo.jpg", "wrong.jpg", "skipped.jpg"):
            cv2.imwrite(str(tmp_path / name), np.zeros((40, 60, 3), dtype=np.uint8))
        scenes = {
            "pair.jpg": [person((0.1, 0.1, 0.3, 0.9)), person((0.5, 0.1, 0.7, 0.9))],
            "solo.jpg": [person((0.1, 0.1, 0.3, 0.9))],
            "wrong.jpg": [person((0.1, 0.1, 0.3, 0.9)), person((0.5, 0.1, 0.7, 0.9))],
            "skipped.jpg": [person((0.1, 0.1, 0.3, 0.9)), person((0.5, 0.1, 0.7, 0.9))],
        }

        class FakeDetector:
            def detect_scene(self, path):
                return SceneDetections(people=scenes[path.name], balls=[], image_size=(60, 40))

        labels = {
            "pair.jpg": {"bbox": [0.5, 0.1, 0.7, 0.9]},
            "solo.jpg": {"bbox": [0.1, 0.1, 0.3, 0.9]},
            "wrong.jpg": {"bbox": [0.85, 0.1, 0.95, 0.9]},
            "skipped.jpg": {"skip": "no clear subject"},
            "gone.jpg": {"bbox": [0.1, 0.1, 0.3, 0.9]},
        }

        examples, unmatched = build_examples(tmp_path, labels, FakeDetector())

        assert [ex.name for ex in examples] == ["pair.jpg"]
        assert examples[0].label_index == 1
        assert examples[0].features.shape == (2, len(SubjectWeights.names()))
        assert unmatched == ["wrong.jpg"]
