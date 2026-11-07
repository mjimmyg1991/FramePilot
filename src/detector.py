"""Subject detection module using RF-DETR and face detection."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import cv2
import numpy as np

from src import resource_path

if TYPE_CHECKING:
    from rfdetr import RFDETR


@dataclass
class Detection:
    """Represents a detected subject in an image."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized (0-1)
    confidence: float
    label: str  # "person" or "face"
    sharpness: float = 0.0  # Laplacian variance - higher = sharper/more in focus
    mask: np.ndarray | None = None  # Segmentation mask (binary, original image size)
    original_bbox: tuple[float, float, float, float] | None = None  # Original detector bbox before tightening
    kit_color: tuple[float, float, float] | None = None  # Median CIE Lab colour of the torso

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


# Fractions of a subject box (x1, y1, x2, y2) measured for sharpness
SHARPNESS_CORE = (0.2, 0.05, 0.8, 0.6)
SHARPNESS_HEIGHT = 256
# Fractions of a person box covering the shirt, below the head and above the waist
TORSO_REGION = (0.3, 0.2, 0.7, 0.45)


@dataclass
class SceneDetections:
    """People and sports balls found in one image."""

    people: list[Detection]
    balls: list[Detection]
    image_size: tuple[int, int]  # width, height


def calculate_kit_color(
    image: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float] | None:
    """Median CIE Lab colour of a person's torso (shirt).

    Args:
        image: Full image (BGR)
        bbox: Person bounding box (x1, y1, x2, y2) normalized 0-1

    Returns:
        (L, a, b) with L in 0-100, or None when the torso is too small to sample
    """
    h, w = image.shape[:2]
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    x1 = max(0, int((bbox[0] + bw * TORSO_REGION[0]) * w))
    y1 = max(0, int((bbox[1] + bh * TORSO_REGION[1]) * h))
    x2 = min(w, int((bbox[0] + bw * TORSO_REGION[2]) * w))
    y2 = min(h, int((bbox[1] + bh * TORSO_REGION[3]) * h))
    if x2 - x1 < 3 or y2 - y1 < 3:
        return None
    patch = image[y1:y2, x1:x2].astype(np.float32) / 255.0
    region = cv2.cvtColor(patch, cv2.COLOR_BGR2Lab).reshape(-1, 3)
    return tuple(float(v) for v in np.median(region, axis=0))


def calculate_sharpness(image: np.ndarray, bbox: tuple[float, float, float, float]) -> float:
    """Calculate sharpness of a region using Laplacian variance.

    Higher values indicate sharper/more in-focus regions. Only the core of
    the box (head and torso for a person) is measured, so busy backgrounds
    around the subject don't count as detail.

    Args:
        image: Full image (BGR)
        bbox: Bounding box (x1, y1, x2, y2) normalized 0-1

    Returns:
        Sharpness score (Laplacian variance)
    """
    h, w = image.shape[:2]
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    core = (
        bbox[0] + bw * SHARPNESS_CORE[0],
        bbox[1] + bh * SHARPNESS_CORE[1],
        bbox[0] + bw * SHARPNESS_CORE[2],
        bbox[1] + bh * SHARPNESS_CORE[3],
    )
    if (core[2] - core[0]) * w >= 8 and (core[3] - core[1]) * h >= 8:
        bbox = core

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

    # Compare regions at a similar scale so large subjects aren't penalized
    if gray.shape[0] > SHARPNESS_HEIGHT:
        scale = SHARPNESS_HEIGHT / gray.shape[0]
        gray = cv2.resize(gray, (max(1, int(gray.shape[1] * scale)), SHARPNESS_HEIGHT),
                          interpolation=cv2.INTER_AREA)

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


# RF-DETR sizes released under Apache-2.0 (detection, then segmentation), with the
# class name and bundled weights file of each (slim_weights.py writes the "-slim"
# files from Roboflow's downloads). Atto, Femto, Pico, XL and 2XL are under the
# non-permissive PML 1.0 and are deliberately not listed.
DETR_MODELS = {
    "nano": ("RFDETRNano", "rf-detr-nano-slim.pth"),
    "small": ("RFDETRSmall", "rf-detr-small-slim.pth"),
    "medium": ("RFDETRMedium", "rf-detr-medium-slim.pth"),
    "large": ("RFDETRLarge", "rf-detr-large-2026-slim.pth"),
    "seg-nano": ("RFDETRSegNano", "rf-detr-seg-nano-slim.pt"),
    "seg-small": ("RFDETRSegSmall", "rf-detr-seg-small-slim.pt"),
    "seg-medium": ("RFDETRSegMedium", "rf-detr-seg-medium-slim.pt"),
    "seg-large": ("RFDETRSegLarge", "rf-detr-seg-large-slim.pt"),
}
DEFAULT_DETR_MODEL = "medium"
DEFAULT_PRECISE_DETR_MODEL = "seg-medium"


def default_detr_model(precise: bool) -> str:
    """Model key for fast mode (boxes) or precise mode (segmentation masks)."""
    return DEFAULT_PRECISE_DETR_MODEL if precise else DEFAULT_DETR_MODEL


class SubjectDetector:
    """Unified interface for subject detection using RF-DETR and face detection."""

    PERSON_LABEL = "person"
    SPORTS_BALL_LABEL = "sports ball"
    BALL_CONFIDENCE_THRESHOLD = 0.25

    def __init__(
        self,
        model_type: Literal["detr", "face"] = "detr",
        detr_model: str = DEFAULT_DETR_MODEL,
        confidence_threshold: float = 0.5,
        use_tight_bbox: bool = False
    ):
        """Initialize the detector.

        Args:
            model_type: Primary detection model to use ("detr" or "face")
            detr_model: Key of DETR_MODELS; a "seg-" size is needed for tight boxes
            confidence_threshold: Minimum confidence for people
            use_tight_bbox: Whether to derive tight bbox from segmentation mask
        """
        if detr_model not in DETR_MODELS:
            raise ValueError(f"Unknown detection model {detr_model!r}; choose from {', '.join(DETR_MODELS)}")
        self.model_type = model_type
        self.detr_model_name = detr_model
        self.confidence_threshold = confidence_threshold
        self.use_tight_bbox = use_tight_bbox

        self._detr_model: RFDETR | None = None
        self._face_cascade: cv2.CascadeClassifier | None = None

    @property
    def detr_model(self) -> "RFDETR":
        """Lazy-load RF-DETR model, preferring the weights bundled with the app."""
        if self._detr_model is None:
            # Imported here so the engine's --version and --verify modes start fast
            import rfdetr

            class_name, weights = DETR_MODELS[self.detr_model_name]
            kwargs = {}
            if resource_path(weights).exists():
                kwargs["pretrain_weights"] = str(resource_path(weights))
            self._detr_model = getattr(rfdetr, class_name)(**kwargs)
        return self._detr_model

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
        return self.detect_scene(image_path).people

    def detect_scene(self, image_path: str | Path) -> SceneDetections:
        """Detect people and sports balls in an image.

        Args:
            image_path: Path to the image file

        Returns:
            SceneDetections with people sorted by confidence (highest first)
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
        detections, balls = self._detect_detr(image, width, height)

        # If no person detected, try face detection as fallback
        if not detections:
            detections = self._detect_faces(image, width, height)

        # Calculate sharpness for each detection
        for det in detections:
            det.sharpness = calculate_sharpness(image, det.bbox)

        for det in detections:
            det.kit_color = calculate_kit_color(image, det.bbox)

        # Sort by confidence (highest first)
        detections.sort(key=lambda d: d.confidence, reverse=True)
        balls.sort(key=lambda d: d.confidence, reverse=True)

        return SceneDetections(people=detections, balls=balls, image_size=(width, height))

    def _detect_detr(
        self,
        image: np.ndarray,
        img_width: int,
        img_height: int
    ) -> tuple[list[Detection], list[Detection]]:
        """Run RF-DETR detection for persons and sports balls.

        Uses segmentation masks to derive tighter bounding boxes than
        standard object detection when a segmentation model is loaded.

        Args:
            image: OpenCV image (BGR)
            img_width: Image width in pixels
            img_height: Image height in pixels

        Returns:
            Tuple of (person detections, sports ball detections)
        """
        found = self.detr_model.predict(
            cv2.cvtColor(image, cv2.COLOR_BGR2RGB),
            threshold=min(self.confidence_threshold, self.BALL_CONFIDENCE_THRESHOLD),
        )
        detections = []
        balls = []

        for i in range(len(found)):
            label = found.data["class_name"][i]
            conf = float(found.confidence[i])
            x1, y1, x2, y2 = found.xyxy[i]
            original_bbox = (
                float(x1 / img_width),
                float(y1 / img_height),
                float(x2 / img_width),
                float(y2 / img_height)
            )

            if label == self.SPORTS_BALL_LABEL:
                if conf >= self.BALL_CONFIDENCE_THRESHOLD:
                    balls.append(Detection(
                        bbox=original_bbox, confidence=conf, label="sports_ball", original_bbox=original_bbox
                    ))
                continue

            if label != self.PERSON_LABEL or conf < self.confidence_threshold:
                continue

            # Try to derive tight bbox from segmentation mask
            mask_array = None
            tight_bbox = original_bbox

            if self.use_tight_bbox and found.mask is not None:
                try:
                    mask_array = found.mask[i].astype(np.uint8)
                    # Resize mask to original image size if needed
                    if mask_array.shape != (img_height, img_width):
                        mask_array = cv2.resize(
                            mask_array, (img_width, img_height), interpolation=cv2.INTER_NEAREST
                        )
                    tight_bbox = bbox_from_mask(mask_array, img_width, img_height)
                except Exception:
                    # Fall back to original bbox if mask processing fails
                    tight_bbox = original_bbox
                    mask_array = None

            detections.append(Detection(
                bbox=tight_bbox,
                confidence=conf,
                label="person",
                mask=mask_array,
                original_bbox=original_bbox
            ))

        return detections, balls

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
