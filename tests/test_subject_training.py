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
    cross_validated_predictions,
    fit_weights,
    iou,
    load_labels,
    match_label,
    mode_report,
    predict,
    save_labels,
    summarize,
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

    def test_duel_members_all_count_as_targets(self):
        # The labelled subject has no distinguishing feature, but it and its
        # duel partner share one; fitting should learn that feature
        column = SubjectWeights.names().index("ball_holder")
        examples = []
        for i in range(30):
            features = np.zeros((3, len(SubjectWeights.names())))
            features[1, column] = 1.0
            features[2, column] = 1.0
            examples.append(TrainingExample(name=f"{i}.jpg", features=features, label_index=2,
                                            mode="duel", member_indices=[1, 2]))
        start = SubjectWeights(**{name: 0.0 for name in SubjectWeights.names()})
        fitted = fit_weights(examples, start, l2=0.01)
        assert fitted.ball_holder > 1.0
        assert accuracy(examples, fitted) == pytest.approx(1.0)

    def test_cross_validated_predictions_align_with_examples(self):
        examples = synthetic_examples(12, "size", seed=5)
        start = SubjectWeights(**{name: 0.0 for name in SubjectWeights.names()})
        predictions = cross_validated_predictions(examples, start, folds=4, l2=0.01)
        assert len(predictions) == 12
        assert sum(p == ex.label_index for p, ex in zip(predictions, examples)) >= 11

    def test_predict(self):
        features = np.zeros((2, len(SubjectWeights.names())))
        features[1, SubjectWeights.names().index("size")] = 1.0
        example = TrainingExample(name="x.jpg", features=features, label_index=1)
        assert predict(example, SubjectWeights()) == 1


class TestSummarize:
    """Tests for the per-mode evaluation report."""

    def example(self, picked_feature_row: int, label: int, mode: str, members: list[int]):
        features = np.zeros((3, len(SubjectWeights.names())))
        features[picked_feature_row, SubjectWeights.names().index("size")] = 1.0
        return TrainingExample(name="x.jpg", features=features, label_index=label,
                               mode=mode, member_indices=members)

    def test_member_counts_for_duel_but_not_strict(self):
        examples = [
            self.example(0, 0, "single", []),
            self.example(1, 0, "single", []),
            self.example(1, 0, "duel", [0, 1]),
            self.example(2, 0, "group", [0, 1]),
        ]
        rows = summarize(examples, SubjectWeights())
        assert rows["strict"] == (1, 4)
        assert rows["any_member"] == (2, 4)
        assert rows["single"] == (1, 2)
        assert rows["duel"] == (1, 1)
        assert rows["group"] == (0, 1)

    def test_is_hit(self):
        ex = TrainingExample(name="x.jpg", features=np.zeros((3, 1)), label_index=2, member_indices=[0, 2])
        assert ex.is_hit(2) and ex.is_hit(0) and not ex.is_hit(1)


class TestModeReport:
    """Tests for scoring the single/duel/group decision."""

    def test_counts_modes_and_members(self):
        duel_people = [person((0.40, 0.2, 0.50, 0.9)), person((0.52, 0.2, 0.62, 0.9)),
                       person((0.05, 0.1, 0.07, 0.2))]
        lone_people = [person((0.1, 0.2, 0.2, 0.9)), person((0.7, 0.2, 0.8, 0.9))]
        names = SubjectWeights.names()
        duel = TrainingExample(name="d.jpg", features=np.zeros((3, len(names))), label_index=0,
                               people=duel_people, mode="duel", member_indices=[0, 1],
                               image_size=(600, 400))
        lone = TrainingExample(name="s.jpg", features=np.zeros((2, len(names))), label_index=0,
                               people=lone_people, mode="single", image_size=(600, 400))

        report = mode_report([duel, lone], SubjectWeights())

        assert report["confusion"]["duel"]["duel"] == 1
        assert report["confusion"]["single"]["single"] == 1
        assert report["framing"] == (2, 2)
        assert report["member_recall"] == (2, 2)
        assert report["member_precision"] == (2, 2)


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
            "pair.jpg": {"bbox": [0.5, 0.1, 0.7, 0.9], "mode": "duel",
                         "members": [[0.5, 0.1, 0.7, 0.9], [0.1, 0.1, 0.3, 0.9], [0.8, 0.8, 0.9, 0.9]]},
            "solo.jpg": {"bbox": [0.1, 0.1, 0.3, 0.9]},
            "wrong.jpg": {"bbox": [0.85, 0.1, 0.95, 0.9]},
            "skipped.jpg": {"skip": "no clear subject"},
            "gone.jpg": {"bbox": [0.1, 0.1, 0.3, 0.9]},
        }

        examples, unmatched = build_examples(tmp_path, labels, FakeDetector())

        assert [ex.name for ex in examples] == ["pair.jpg"]
        assert examples[0].label_index == 1
        assert examples[0].mode == "duel"
        assert examples[0].member_indices == [0, 1]
        assert examples[0].features.shape == (2, len(SubjectWeights.names()))
        assert unmatched == ["wrong.jpg"]
