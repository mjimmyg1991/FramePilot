"""Subject detection module using YOLO and face detection."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from ultralytics import YOLO


@dataclass
class Detection:
    """Represents a detected subject in an image."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized (0-1)
    confidence: float
    label: str  # "person" or "face"
    sharpness: float = 0.0  # Laplacian variance - higher = sharper/more in focus

    @property
    def width(self) -> float:
        """Width of bounding box (normalized)."""
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        """Height of bounding box (normalized)."""
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> float:
        """Area of bounding box (normalized)."""
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        """Center point of bounding box (normalized)."""
        return (
            (self.bbox[0] + self.bbox[2]) / 2,
            (self.bbox[1] + self.bbox[3]) / 2
        )


def calculate_sharpness(image: np.ndarray, bbox: tuple[float, float, float, float]) -> float:
    """Calculate sharpness of a region using Laplacian variance.

    Higher values indicate sharper/more in-focus regions.

    Args:
        image: Full image (BGR)
        bbox: Bounding box (x1, y1, x2, y2) normalized 0-1

    Returns:
        Sharpness score (Laplacian variance)
    """
    h, w = image.shape[:2]
    x1 = int(bbox[0] * w)
    y1 = int(bbox[1] * h)
    x2 = int(bbox[2] * w)
    y2 = int(bbox[3] * h)

    # Ensure valid crop region
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return 0.0

    # Extract region
    region = image[y1:y2, x1:x2]

    # Convert to grayscale
    if len(region.shape) == 3:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    else:
        gray = region

    # Calculate Laplacian variance (higher = sharper)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    variance = laplacian.var()

    return float(variance)


class SubjectDetector:
    """Unified interface for subject detection using YOLO and face detection."""

    PERSON_CLASS_ID = 0  # COCO class ID for person

    def __init__(
        self,
        model_type: Literal["yolo", "face"] = "yolo",
        yolo_model: str = "yolov8m.pt",
        confidence_threshold: float = 0.5
    ):
        """Initialize the detector.

        Args:
            model_type: Primary detection model to use ("yolo" or "face")
            yolo_model: YOLO model variant to use
            confidence_threshold: Minimum confidence for detections
        """
        self.model_type = model_type
        self.yolo_model_name = yolo_model
        self.confidence_threshold = confidence_threshold

        self._yolo_model: YOLO | None = None
        self._face_cascade: cv2.CascadeClassifier | None = None
        self._yolo_face_model: YOLO | None = None

    @property
    def yolo_model(self) -> YOLO:
        """Lazy-load YOLO model."""
        if self._yolo_model is None:
            self._yolo_model = YOLO(self.yolo_model_name)
        return self._yolo_model

    @property
    def face_cascade(self) -> cv2.CascadeClassifier:
        """Lazy-load OpenCV Haar cascade for face detection."""
        if self._face_cascade is None:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
        return self._face_cascade

    def detect(self, image_path: str | Path) -> list[Detection]:
        """Detect subjects in an image.

        Args:
            image_path: Path to the image file

        Returns:
            List of Detection objects sorted by confidence (highest first)
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Load image
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Failed to load image: {image_path}")

        height, width = image.shape[:2]

        # Try person detection first
        detections = self._detect_yolo(image, width, height)

        # If no person detected, try face detection as fallback
        if not detections:
            detections = self._detect_faces(image, width, height)

        # Calculate sharpness for each detection
        for det in detections:
            det.sharpness = calculate_sharpness(image, det.bbox)

        # Sort by confidence (highest first)
        detections.sort(key=lambda d: d.confidence, reverse=True)

        return detections

    def _detect_yolo(
        self,
        image: np.ndarray,
        img_width: int,
        img_height: int
    ) -> list[Detection]:
        """Run YOLO detection for persons.

        Args:
            image: OpenCV image (BGR)
            img_width: Image width in pixels
            img_height: Image height in pixels

        Returns:
            List of Detection objects for persons
        """
        results = self.yolo_model(image, verbose=False)
        detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i in range(len(boxes)):
                cls = int(boxes.cls[i])
                conf = float(boxes.conf[i])

                # Only detect persons
                if cls != self.PERSON_CLASS_ID:
                    continue

                if conf < self.confidence_threshold:
                    continue

                # Get bounding box (xyxy format)
                box = boxes.xyxy[i].cpu().numpy()
                x1, y1, x2, y2 = box

                # Normalize coordinates to 0-1 range
                bbox = (
                    float(x1 / img_width),
                    float(y1 / img_height),
                    float(x2 / img_width),
                    float(y2 / img_height)
                )

                detections.append(Detection(
                    bbox=bbox,
                    confidence=conf,
                    label="person"
                ))

        return detections

    def _detect_faces(
        self,
        image: np.ndarray,
        img_width: int,
        img_height: int
    ) -> list[Detection]:
        """Run face detection using OpenCV Haar cascade.

        Args:
            image: OpenCV image (BGR)
            img_width: Image width in pixels
            img_height: Image height in pixels

        Returns:
            List of Detection objects for faces
        """
        # Convert to grayscale for face detection
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Detect faces
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30)
        )

        detections = []
        for (x, y, w, h) in faces:
            # Normalize coordinates to 0-1 range
            bbox = (
                float(x / img_width),
                float(y / img_height),
                float((x + w) / img_width),
                float((y + h) / img_height)
            )

            # Haar cascade doesn't provide confidence, estimate based on size
            # Larger faces are typically more reliable detections
            area = (w * h) / (img_width * img_height)
            confidence = min(0.9, 0.5 + area * 5)  # Scale confidence with face size

            detections.append(Detection(
                bbox=bbox,
                confidence=confidence,
                label="face"
            ))

        return detections

    def detect_with_preview(
        self,
        image_path: str | Path
    ) -> tuple[list[Detection], np.ndarray]:
        """Detect subjects and return image with bounding boxes drawn.

        Args:
            image_path: Path to the image file

        Returns:
            Tuple of (detections, annotated_image)
        """
        image_path = Path(image_path)
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Failed to load image: {image_path}")

        height, width = image.shape[:2]
        detections = self.detect(image_path)

        # Draw bounding boxes on image
        annotated = image.copy()
        for det in detections:
            x1 = int(det.bbox[0] * width)
            y1 = int(det.bbox[1] * height)
            x2 = int(det.bbox[2] * width)
            y2 = int(det.bbox[3] * height)

            color = (0, 255, 0) if det.label == "person" else (255, 0, 0)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            label = f"{det.label}: {det.confidence:.2f}"
            cv2.putText(
                annotated, label, (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2
            )

        return detections, annotated
