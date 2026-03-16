"""Folder watcher for auto-processing new images."""

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from watchdog.observers import Observer

from .constants import SUPPORTED_EXTENSIONS
from .crop_calculator import CropRegion, calculate_crop_for_detection, select_primary_subject
from .detector import SubjectDetector
from .xmp_handler import write_crop_to_xmp

logger = logging.getLogger(__name__)


@dataclass
class WatcherResult:
    """Result of auto-processing a single watched file."""

    file_path: Path
    status: str  # "success", "no_subject", "error"
    xmp_path: Path | None = None
    error_message: str = ""


class _ImageHandler(FileSystemEventHandler):
    """Handles file system events for new images."""

    def __init__(
        self,
        on_new_file: Callable[[Path], None],
        debounce_seconds: float = 2.0,
    ):
        super().__init__()
        self._on_new_file = on_new_file
        self._debounce_seconds = debounce_seconds
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_created(self, event: FileCreatedEvent):
        if not event.is_directory:
            self._handle_file(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent):
        if not event.is_directory:
            self._handle_file(Path(event.dest_path))

    def _handle_file(self, path: Path):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return

        now = time.time()
        key = str(path)

        with self._lock:
            last_seen = self._seen.get(key, 0)
            if now - last_seen < self._debounce_seconds:
                return
            self._seen[key] = now

            # Prune old entries to prevent unbounded memory growth
            if len(self._seen) > 1000:
                cutoff = now - self._debounce_seconds * 10
                self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

        self._on_new_file(path)


class FolderWatcher:
    """Watches a folder for new images and auto-processes them with XMP output."""

    def __init__(
        self,
        watch_dir: str | Path,
        aspect_ratio: tuple[int, int] = (4, 5),
        padding: float = 0.15,
        strategy: str = "highest_confidence",
        debounce_seconds: float = 2.0,
        on_file_processed: Callable[[WatcherResult], None] | None = None,
    ):
        """Initialize the folder watcher.

        Args:
            watch_dir: Directory to watch for new images
            aspect_ratio: Target crop aspect ratio
            padding: Padding around detected subject
            strategy: Subject selection strategy
            debounce_seconds: Ignore duplicate events within this window
            on_file_processed: Callback when a file is processed
        """
        self.watch_dir = Path(watch_dir)
        self.aspect_ratio = aspect_ratio
        self.padding = padding
        self.strategy = strategy
        self.debounce_seconds = debounce_seconds
        self.on_file_processed = on_file_processed

        self._observer: Observer | None = None
        self._detector: SubjectDetector | None = None
        self._process_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._file_queue: list[Path] = []
        self._queue_lock = threading.Lock()
        self._processed_count = 0

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    @property
    def processed_count(self) -> int:
        return self._processed_count

    def start(self) -> None:
        """Start watching the folder."""
        if self.is_running:
            return

        if not self.watch_dir.is_dir():
            raise ValueError(f"Watch directory does not exist: {self.watch_dir}")

        self._stop_event.clear()
        self._processed_count = 0

        handler = _ImageHandler(
            on_new_file=self._enqueue_file,
            debounce_seconds=self.debounce_seconds,
        )

        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_dir), recursive=False)
        self._observer.start()

        # Start processing thread
        self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._process_thread.start()

        logger.info("Watching folder: %s", self.watch_dir)

    def stop(self) -> None:
        """Stop watching the folder."""
        self._stop_event.set()

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        if self._process_thread:
            self._process_thread.join(timeout=5)
            self._process_thread = None

        logger.info("Watcher stopped. Processed %d files.", self._processed_count)

    def _enqueue_file(self, path: Path) -> None:
        with self._queue_lock:
            self._file_queue.append(path)

    def _process_loop(self) -> None:
        """Background loop that processes queued files."""
        while not self._stop_event.is_set():
            path = None
            with self._queue_lock:
                if self._file_queue:
                    path = self._file_queue.pop(0)

            if path is None:
                self._stop_event.wait(timeout=0.5)
                continue

            # Wait for file to be fully written
            if not self._wait_for_stable_file(path):
                continue

            result = self._process_file(path)
            self._processed_count += 1

            if self.on_file_processed:
                self.on_file_processed(result)

    def _wait_for_stable_file(self, path: Path, timeout: float = 10.0) -> bool:
        """Wait for a file to stop being written to."""
        start = time.time()
        prev_size = -1

        while time.time() - start < timeout:
            if self._stop_event.is_set():
                return False

            if not path.exists():
                return False

            try:
                current_size = path.stat().st_size
            except OSError:
                return False

            if current_size == prev_size and current_size > 0:
                return True

            prev_size = current_size
            time.sleep(1.0)

        return path.exists()

    def _process_file(self, file_path: Path) -> WatcherResult:
        """Process a single image file."""
        import cv2

        result = WatcherResult(file_path=file_path, status="pending")

        try:
            # Lazy-load detector
            if self._detector is None:
                self._detector = SubjectDetector(yolo_model="yolov8m.pt")

            image = cv2.imread(str(file_path))
            if image is None:
                result.status = "error"
                result.error_message = "Failed to load image"
                return result

            height, width = image.shape[:2]

            detections = self._detector.detect(file_path)
            if not detections:
                result.status = "no_subject"
                logger.info("No subject detected: %s", file_path.name)
                return result

            primary = select_primary_subject(detections, self.strategy)
            crop = calculate_crop_for_detection(
                primary,
                image_width=width,
                image_height=height,
                target_aspect=self.aspect_ratio,
                padding=self.padding,
            )

            xmp_path = write_crop_to_xmp(file_path, crop, backup=True)
            result.status = "success"
            result.xmp_path = xmp_path
            logger.info("Processed: %s -> %s", file_path.name, xmp_path.name)

        except Exception as e:
            result.status = "error"
            result.error_message = str(e)
            logger.error("Error processing %s: %s", file_path.name, e)

        return result
