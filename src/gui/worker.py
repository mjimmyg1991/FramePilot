"""Background worker thread for image processing."""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Callable

import cv2

from ..crop_calculator import CropRegion, calculate_crop_for_detection, select_primary_subject
from ..detector import Detection, SubjectDetector
from ..xmp_handler import write_crop_to_xmp


@dataclass
class ProcessingResult:
    """Result of processing a single image."""

    file_path: Path
    status: str  # "success", "no_subject", "error"
    detections: list[Detection] = field(default_factory=list)
    primary_detection: Detection | None = None
    crop: CropRegion | None = None
    error_message: str = ""
    image_size: tuple[int, int] = (0, 0)  # width, height


class ProcessingWorker:
    """Background worker for processing images."""

    def __init__(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_file_complete: Callable[[ProcessingResult], None] | None = None,
        on_complete: Callable[[list[ProcessingResult]], None] | None = None,
    ):
        """Initialize the worker.

        Args:
            on_progress: Callback(current, total, message) for progress updates
            on_file_complete: Callback(result) when a file is processed
            on_complete: Callback(results) when all files are done
        """
        self.on_progress = on_progress
        self.on_file_complete = on_file_complete
        self.on_complete = on_complete

        self._thread: threading.Thread | None = None
        self._cancel_flag = threading.Event()
        self._detector: SubjectDetector | None = None

    @property
    def is_running(self) -> bool:
        """Check if worker is currently processing."""
        return self._thread is not None and self._thread.is_alive()

    def start_processing(
        self,
        files: list[Path],
        aspect_ratio: tuple[int, int] = (4, 5),
        padding: float = 0.15,
        strategy: str = "highest_confidence",
    ) -> None:
        """Start processing files in background thread.

        Args:
            files: List of image file paths
            aspect_ratio: Target aspect ratio (width, height)
            padding: Padding around subject
            strategy: Subject selection strategy
        """
        if self.is_running:
            return

        self._cancel_flag.clear()
        self._thread = threading.Thread(
            target=self._process_files,
            args=(files, aspect_ratio, padding, strategy),
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Cancel the current processing."""
        self._cancel_flag.set()

    def _process_files(
        self,
        files: list[Path],
        aspect_ratio: tuple[int, int],
        padding: float,
        strategy: str,
    ) -> None:
        """Process files (runs in background thread)."""
        # Lazy-load detector
        if self._detector is None:
            if self.on_progress:
                self.on_progress(0, len(files), "Loading detection model...")
            self._detector = SubjectDetector()

        results = []
        for i, file_path in enumerate(files):
            if self._cancel_flag.is_set():
                break

            if self.on_progress:
                self.on_progress(i, len(files), f"Processing {file_path.name}...")

            result = self._process_single_file(file_path, aspect_ratio, padding, strategy)
            results.append(result)

            if self.on_file_complete:
                self.on_file_complete(result)

        if self.on_progress:
            self.on_progress(len(files), len(files), "Complete")

        if self.on_complete:
            self.on_complete(results)

    def _process_single_file(
        self,
        file_path: Path,
        aspect_ratio: tuple[int, int],
        padding: float,
        strategy: str,
    ) -> ProcessingResult:
        """Process a single image file."""
        result = ProcessingResult(file_path=file_path, status="pending")

        try:
            # Get image dimensions
            image = cv2.imread(str(file_path))
            if image is None:
                result.status = "error"
                result.error_message = "Failed to load image"
                return result

            height, width = image.shape[:2]
            result.image_size = (width, height)

            # Detect subjects
            detections = self._detector.detect(file_path)
            result.detections = detections

            if not detections:
                result.status = "no_subject"
                return result

            # Select primary subject
            primary = select_primary_subject(detections, strategy)
            result.primary_detection = primary

            # Calculate crop
            crop = calculate_crop_for_detection(
                primary,
                image_width=width,
                image_height=height,
                target_aspect=aspect_ratio,
                padding=padding,
            )
            result.crop = crop
            result.status = "success"

        except Exception as e:
            result.status = "error"
            result.error_message = str(e)

        return result


def write_xmp_for_results(
    results: list[ProcessingResult],
    output_dir: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[Path, bool, str]]:
    """Write XMP files for processed results.

    Args:
        results: List of ProcessingResult objects
        output_dir: Optional output directory
        on_progress: Callback(current, total) for progress

    Returns:
        List of (path, success, message) tuples
    """
    xmp_results = []

    successful = [r for r in results if r.status == "success" and r.crop is not None]

    for i, result in enumerate(successful):
        if on_progress:
            on_progress(i, len(successful))

        try:
            xmp_path = write_crop_to_xmp(
                result.file_path,
                result.crop,
                output_dir=output_dir,
                backup=True,
            )
            xmp_results.append((xmp_path, True, "XMP written"))
        except Exception as e:
            xmp_results.append((result.file_path, False, str(e)))

    if on_progress:
        on_progress(len(successful), len(successful))

    return xmp_results


def export_cropped_images(
    results: list[ProcessingResult],
    output_dir: Path,
    jpeg_quality: int = 92,
    suffix: str = "_cropped",
    max_dimension: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[Path, bool, str]]:
    """Export cropped images as JPEG files.

    Args:
        results: List of ProcessingResult objects
        output_dir: Output directory for cropped images
        jpeg_quality: JPEG quality (1-100)
        suffix: Suffix to add to filename (e.g., "_cropped")
        max_dimension: Maximum width or height in pixels (None = no limit)
        on_progress: Callback(current, total) for progress

    Returns:
        List of (output_path, success, message) tuples
    """
    from PIL import Image

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    export_results = []
    successful = [r for r in results if r.status == "success" and r.crop is not None]

    for i, result in enumerate(successful):
        if on_progress:
            on_progress(i, len(successful))

        try:
            # Load image
            img = Image.open(result.file_path)
            width, height = img.size

            # Calculate crop box in pixels
            crop = result.crop
            left = int(crop.left * width)
            top = int(crop.top * height)
            right = int(crop.right * width)
            bottom = int(crop.bottom * height)

            # Crop the image
            cropped = img.crop((left, top, right, bottom))

            # Resize if max_dimension is specified
            if max_dimension:
                crop_w, crop_h = cropped.size
                if crop_w > max_dimension or crop_h > max_dimension:
                    scale = max_dimension / max(crop_w, crop_h)
                    new_w = int(crop_w * scale)
                    new_h = int(crop_h * scale)
                    cropped = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Generate output filename
            stem = result.file_path.stem
            output_path = output_dir / f"{stem}{suffix}.jpg"

            # Handle duplicates
            counter = 1
            while output_path.exists():
                output_path = output_dir / f"{stem}{suffix}_{counter}.jpg"
                counter += 1

            # Save as JPEG
            # Convert to RGB if necessary (for PNG with alpha, etc.)
            if cropped.mode in ("RGBA", "P"):
                cropped = cropped.convert("RGB")

            cropped.save(output_path, "JPEG", quality=jpeg_quality)
            export_results.append((output_path, True, "Exported"))

        except Exception as e:
            export_results.append((result.file_path, False, str(e)))

    if on_progress:
        on_progress(len(successful), len(successful))

    return export_results
