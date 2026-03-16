"""Background worker thread for image processing."""

import logging
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Callable

import cv2

logger = logging.getLogger(__name__)

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
        precise_mode: bool = False,
    ) -> None:
        """Start processing files in background thread.

        Args:
            files: List of image file paths
            aspect_ratio: Target aspect ratio (width, height)
            padding: Padding around subject
            strategy: Subject selection strategy
            precise_mode: Use segmentation model for tighter crops (slower)
        """
        if self.is_running:
            return

        self._cancel_flag.clear()
        self._precise_mode = precise_mode
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
        # Determine model based on precise_mode
        precise_mode = getattr(self, '_precise_mode', False)
        model_name = "yolov8m-seg.pt" if precise_mode else "yolov8m.pt"
        use_tight = precise_mode

        # Reload detector if model changed or not loaded
        if self._detector is None or getattr(self._detector, 'yolo_model_name', '') != model_name:
            if self.on_progress:
                mode_str = "precise" if precise_mode else "fast"
                self.on_progress(0, len(files), f"Loading {mode_str} detection model...")
            self._detector = SubjectDetector(yolo_model=model_name, use_tight_bbox=use_tight)

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
            # Get image dimensions without full decode (detector will load separately)
            from PIL import Image
            with Image.open(file_path) as img:
                width, height = img.size
            result.image_size = (width, height)

            if width == 0 or height == 0:
                result.status = "error"
                result.error_message = "Invalid image dimensions"
                return result

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
            logger.error("Error processing %s:\n%s", file_path.name, traceback.format_exc())

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


def apply_watermark(
    image: "Image.Image",
    watermark_path: str,
    position: str = "Bottom Right",
    opacity: float = 0.5,
    size: float = 0.15,
) -> "Image.Image":
    """Apply a watermark to an image.

    Args:
        image: PIL Image to watermark
        watermark_path: Path to watermark image file
        position: One of "Bottom Right", "Bottom Left", "Top Right", "Top Left", "Center"
        opacity: Opacity of watermark (0-1)
        size: Size of watermark as fraction of image width (0-1)

    Returns:
        Watermarked image
    """
    from PIL import Image

    # Load watermark
    watermark = Image.open(watermark_path)

    # Ensure watermark has alpha channel
    if watermark.mode != "RGBA":
        watermark = watermark.convert("RGBA")

    # Calculate watermark size
    img_w, img_h = image.size
    wm_target_width = int(img_w * size)
    wm_scale = wm_target_width / watermark.width
    wm_new_height = int(watermark.height * wm_scale)
    watermark = watermark.resize((wm_target_width, wm_new_height), Image.Resampling.LANCZOS)

    # Apply opacity
    if opacity < 1.0:
        alpha = watermark.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        watermark.putalpha(alpha)

    # Calculate position
    margin = int(img_w * 0.02)  # 2% margin
    wm_w, wm_h = watermark.size

    if position == "Bottom Right":
        x = img_w - wm_w - margin
        y = img_h - wm_h - margin
    elif position == "Bottom Left":
        x = margin
        y = img_h - wm_h - margin
    elif position == "Top Right":
        x = img_w - wm_w - margin
        y = margin
    elif position == "Top Left":
        x = margin
        y = margin
    else:  # Center
        x = (img_w - wm_w) // 2
        y = (img_h - wm_h) // 2

    # Ensure image is RGBA for compositing
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    # Paste watermark
    image.paste(watermark, (x, y), watermark)

    return image


def export_cropped_images(
    results: list[ProcessingResult],
    output_dir: Path,
    jpeg_quality: int = 92,
    suffix: str = "_cropped",
    max_dimension: int | None = None,
    watermark: dict | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[Path, bool, str]]:
    """Export cropped images as JPEG files.

    Args:
        results: List of ProcessingResult objects
        output_dir: Output directory for cropped images
        jpeg_quality: JPEG quality (1-100)
        suffix: Suffix to add to filename (e.g., "_cropped")
        max_dimension: Maximum width or height in pixels (None = no limit)
        watermark: Optional dict with keys: path, position, opacity, size
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

            # Preserve EXIF metadata
            exif_data = img.info.get("exif")

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

            # Apply watermark if specified
            if watermark:
                cropped = apply_watermark(
                    cropped,
                    watermark["path"],
                    position=watermark.get("position", "Bottom Right"),
                    opacity=watermark.get("opacity", 0.5),
                    size=watermark.get("size", 0.15),
                )

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

            save_kwargs = {"quality": jpeg_quality}
            if exif_data:
                save_kwargs["exif"] = exif_data
            cropped.save(output_path, "JPEG", **save_kwargs)
            export_results.append((output_path, True, "Exported"))

        except Exception as e:
            export_results.append((result.file_path, False, str(e)))

    if on_progress:
        on_progress(len(successful), len(successful))

    return export_results
