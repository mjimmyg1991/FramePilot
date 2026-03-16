"""Subject detection module using YOLO and face detection."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from ultralytics import YOLO

from src import resource_path


@dataclass
class Detection:
    """Represents a detected subject in an image."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized (0-1)
    confidence: float
    label: str  # "person" or "face"
    sharpness: float = 0.0  # Laplacian variance - higher = sharper/more in focus
    mask: np.ndarray | None = None  # Segmentation mask (binary, original image size)
    original_bbox: tuple[float, float, float, float] | None = None  # Original YOLO bbox before tightening

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


def bbox_from_mask(
    mask: np.ndarray,
    img_width: int,
    img_height: int,
    padding_pct: float = 0.02
) -> tuple[float, float, float, float]:
    """Compute tight bounding box from segmentation mask.

    Args:
        mask: Binary mask (H x W, values 0 or 1)
        img_width: Original image width
        img_height: Original image height
        padding_pct: Small padding to add (fraction of image dimension)

    Returns:
        Normalized bbox (x1, y1, x2, y2) where values are 0-1
    """
    coords = np.argwhere(mask > 0)
    if len(coords) == 0:
        return (0.0, 0.0, 1.0, 1.0)

    # coords are (row, col) = (y, x)
    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)

    mask_h, mask_w = mask.shape[:2]

    # Add small padding to avoid overly tight crops
    pad_x = int(mask_w * padding_pct)
    pad_y = int(mask_h * padding_pct)

    x_min = max(0, x_min - pad_x)
    y_min = max(0, y_min - pad_y)
    x_max = min(mask_w - 1, x_max + pad_x)
    y_max = min(mask_h - 1, y_max + pad_y)

    return (
        float(x_min / mask_w),
        float(y_min / mask_h),
        float((x_max + 1) / mask_w),
        float((y_max + 1) / mask_h)
    )


class SubjectDetector:
    """Unified interface for subject detection using YOLO and face detection."""

    PERSON_CLASS_ID = 0  # COCO class ID for person

    def __init__(
        self,
        model_type: Literal["yolo", "face"] = "yolo",
        yolo_model: str = "yolov8m.pt",
        confidence_threshold: float = 0.5,
        use_tight_bbox: bool = False
    ):
        """Initialize the detector.

        Args:
            model_type: Primary detection model to use ("yolo" or "face")
            yolo_model: YOLO model variant to use (default: fast detection model)
            confidence_threshold: Minimum confidence for detections
            use_tight_bbox: Whether to derive tight bbox from segmentation mask
        """
        self.model_type = model_type
        self.yolo_model_name = yolo_model
        self.confidence_threshold = confidence_threshold
        self.use_tight_bbox = use_tight_bbox

        self._yolo_model: YOLO | None = None
        self._face_cascade: cv2.CascadeClassifier | None = None
        self._yolo_face_model: YOLO | None = None

    @property
    def yolo_model(self) -> YOLO:
        """Lazy-load YOLO model."""
        if self._yolo_model is None:
            model_path = resource_path(self.yolo_model_name)
            if model_path.exists():
                self._yolo_model = YOLO(str(model_path))
            else:
                # Fallback: let YOLO search/download
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
        """Run YOLO segmentation detection for persons.

        Uses segmentation masks to derive tighter bounding boxes than
        standard object detection when available.

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
            masks = getattr(result, 'masks', None)

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

                # Get original bounding box (xyxy format)
                box = boxes.xyxy[i].cpu().numpy()
                x1, y1, x2, y2 = box

                original_bbox = (
                    float(x1 / img_width),
                    float(y1 / img_height),
                    float(x2 / img_width),
                    float(y2 / img_height)
                )

                # Try to derive tight bbox from segmentation mask
                mask_array = None
                tight_bbox = original_bbox

                if self.use_tight_bbox and masks is not None:
                    try:
                        mask_data = masks.data[i].cpu().numpy()
                        # Resize mask to original image size if needed
                        if mask_data.shape != (img_height, img_width):
                            mask_resized = cv2.resize(
                                (mask_data > 0.5).astype(np.uint8),
                                (img_width, img_height),
                                interpolation=cv2.INTER_NEAREST
                            )
                        else:
                            mask_resized = (mask_data > 0.5).astype(np.uint8)

                        tight_bbox = bbox_from_mask(mask_resized, img_width, img_height)
                        # Don't store full-resolution mask — it consumes too much memory in batches
                    except Exception:
                        # Fall back to original bbox if mask processing fails
                        tight_bbox = original_bbox

                detections.append(Detection(
                    bbox=tight_bbox,
                    confidence=conf,
                    label="person",
                    mask=None,
                    original_bbox=original_bbox
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
                label="face",
                mask=None,
                original_bbox=bbox
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
