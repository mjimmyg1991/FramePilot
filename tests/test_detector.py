"""Tests for the RF-DETR detector wrapper, using a fake model so no weights are needed."""

import numpy as np
import pytest
import supervision as sv

from src.detector import DETR_MODELS, SubjectDetector, default_detr_model


class FakeModel:
    """Stands in for an RF-DETR model: returns canned detections."""

    def __init__(self, detections: sv.Detections):
        self.detections = detections
        self.threshold = None

    def predict(self, image, threshold):
        self.threshold = threshold
        return self.detections


def detector_with(detections: sv.Detections, **kwargs) -> tuple[SubjectDetector, FakeModel]:
    detector = SubjectDetector(**kwargs)
    model = FakeModel(detections)
    detector._detr_model = model
    return detector, model


def scene(boxes, confidences, names, mask=None) -> sv.Detections:
    return sv.Detections(
        xyxy=np.array(boxes, dtype=float),
        confidence=np.array(confidences, dtype=float),
        class_id=np.zeros(len(boxes), dtype=int),
        mask=mask,
        data={"class_name": np.array(names)},
    )


class TestModelCatalogue:
    def test_only_apache_sizes_are_listed(self):
        classes = {class_name for class_name, _ in DETR_MODELS.values()}
        for pml_size in ("Atto", "Femto", "Pico", "XLarge", "2XLarge"):
            assert not any(pml_size in name for name in classes)

    def test_default_models_exist(self):
        assert default_detr_model(False) in DETR_MODELS
        assert default_detr_model(True).startswith("seg-") and default_detr_model(True) in DETR_MODELS

    def test_unknown_model_is_rejected(self):
        with pytest.raises(ValueError):
            SubjectDetector(detr_model="xlarge")


class TestPersonThreshold:
    def test_box_models_default_to_tuned_threshold_and_seg_keeps_half(self):
        assert SubjectDetector().confidence_threshold == 0.75
        assert SubjectDetector(detr_model="seg-medium").confidence_threshold == 0.5
        assert SubjectDetector(confidence_threshold=0.3).confidence_threshold == 0.3

    def test_default_threshold_drops_weak_people_but_keeps_balls(self):
        boxes = [[10, 10, 30, 90], [50, 10, 70, 90], [80, 60, 85, 65]]
        detector, model = detector_with(scene(boxes, [0.9, 0.6, 0.3], ["person", "person", "sports ball"]))
        people, balls = detector._detect_detr(np.zeros((100, 100, 3), dtype=np.uint8), 100, 100)
        assert len(people) == 1 and len(balls) == 1
        assert model.threshold == 0.25

    def test_falls_back_to_the_best_person_above_half_when_nobody_reaches_threshold(self):
        boxes = [[10, 10, 30, 90], [50, 10, 70, 90], [80, 10, 95, 90]]
        detector, _ = detector_with(scene(boxes, [0.6, 0.72, 0.4], ["person", "person", "person"]))
        people, _ = detector._detect_detr(np.zeros((100, 100, 3), dtype=np.uint8), 100, 100)
        assert [p.confidence for p in people] == [pytest.approx(0.72)]

    def test_no_fallback_below_half(self):
        detector, _ = detector_with(scene([[10, 10, 30, 90]], [0.45], ["person"]))
        people, _ = detector._detect_detr(np.zeros((100, 100, 3), dtype=np.uint8), 100, 100)
        assert people == []


class TestDetectDetr:
    def test_people_and_balls_split_by_class_name_and_confidence(self):
        found = scene(
            [(100, 100, 300, 500), (50, 50, 80, 90), (400, 400, 420, 420), (500, 100, 700, 500), (10, 10, 40, 40)],
            [0.9, 0.3, 0.4, 0.6, 0.1],
            ["person", "person", "sports ball", "bus", "sports ball"],
        )
        detector, model = detector_with(found)

        people, balls = detector._detect_detr(np.zeros((1000, 1000, 3), np.uint8), 1000, 1000)

        assert model.threshold == pytest.approx(0.25)
        assert [p.bbox for p in people] == [pytest.approx((0.1, 0.1, 0.3, 0.5))]
        assert people[0].label == "person"
        assert [b.label for b in balls] == ["sports_ball"]
        assert balls[0].bbox == pytest.approx((0.4, 0.4, 0.42, 0.42))

    def test_tight_bbox_comes_from_the_mask(self):
        mask = np.zeros((1, 100, 200), dtype=bool)
        mask[0, 20:60, 40:100] = True
        found = scene([(0, 0, 200, 100)], [0.9], ["person"], mask=mask)
        detector, _ = detector_with(found, detr_model="seg-medium", use_tight_bbox=True)

        people, _ = detector._detect_detr(np.zeros((100, 200, 3), np.uint8), 200, 100)

        assert people[0].original_bbox == pytest.approx((0.0, 0.0, 1.0, 1.0))
        x1, y1, x2, y2 = people[0].bbox
        assert 0.15 < x1 < 0.25 and 0.45 < x2 < 0.55
        assert 0.15 < y1 < 0.25 and 0.55 < y2 < 0.65
        assert people[0].mask is not None

    def test_mask_ignored_unless_tight_bbox_requested(self):
        mask = np.ones((1, 100, 200), dtype=bool)
        found = scene([(20, 10, 100, 90)], [0.9], ["person"], mask=mask)
        detector, _ = detector_with(found, detr_model="seg-medium")

        people, _ = detector._detect_detr(np.zeros((100, 200, 3), np.uint8), 200, 100)

        assert people[0].bbox == people[0].original_bbox
        assert people[0].mask is None
