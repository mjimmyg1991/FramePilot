"""CLI entry point for Lightroom Subject Crop."""

from pathlib import Path
from typing import Annotated, Optional

import cv2
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .crop_calculator import (
    CropRegion,
    calculate_crop_for_detection,
    select_primary_subject,
)
from .detector import Detection, SubjectDetector
from .xmp_handler import get_xmp_path, write_crop_to_xmp

app = typer.Typer(
    name="lightroom-subject-crop",
    help="Analyze photos, detect subjects, and generate XMP crop data for Lightroom.",
    no_args_is_help=True,
)
console = Console()

# Supported image extensions
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf"
}


def parse_aspect_ratio(value: str) -> tuple[int, int]:
    """Parse aspect ratio string like '4:5' or '9:16'."""
    try:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        raise typer.BadParameter(
            f"Invalid aspect ratio '{value}'. Use format like '4:5' or '9:16'"
        )


def get_image_files(path: Path) -> list[Path]:
    """Get list of supported image files from path."""
    if path.is_file():
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [path]
        else:
            console.print(f"[yellow]Unsupported file type: {path.suffix}[/yellow]")
            return []
    elif path.is_dir():
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(path.glob(f"*{ext}"))
            files.extend(path.glob(f"*{ext.upper()}"))
        return sorted(set(files))
    else:
        console.print(f"[red]Path not found: {path}[/red]")
        return []


def draw_crop_preview(
    image_path: Path,
    crop: CropRegion,
    detection: Detection | None,
    output_path: Path
) -> None:
    """Draw crop overlay on image and save preview."""
    image = cv2.imread(str(image_path))
    if image is None:
        return

    height, width = image.shape[:2]

    # Draw detection bounding box (green)
    if detection is not None:
        x1 = int(detection.bbox[0] * width)
        y1 = int(detection.bbox[1] * height)
        x2 = int(detection.bbox[2] * width)
        y2 = int(detection.bbox[3] * height)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)

        label = f"{detection.label}: {detection.confidence:.2f}"
        cv2.putText(
            image, label, (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
        )

    # Draw crop region (blue rectangle)
    cx1 = int(crop.left * width)
    cy1 = int(crop.top * height)
    cx2 = int(crop.right * width)
    cy2 = int(crop.bottom * height)
    cv2.rectangle(image, (cx1, cy1), (cx2, cy2), (255, 0, 0), 3)

    # Darken areas outside crop
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (width, cy1), (0, 0, 0), -1)  # Top
    cv2.rectangle(overlay, (0, cy2), (width, height), (0, 0, 0), -1)  # Bottom
    cv2.rectangle(overlay, (0, cy1), (cx1, cy2), (0, 0, 0), -1)  # Left
    cv2.rectangle(overlay, (cx2, cy1), (width, cy2), (0, 0, 0), -1)  # Right
    cv2.addWeighted(overlay, 0.5, image, 0.5, 0, image)

    # Re-draw crop border on top
    cv2.rectangle(image, (cx1, cy1), (cx2, cy2), (255, 0, 0), 3)

    cv2.imwrite(str(output_path), image)


@app.command()
def process(
    path: Annotated[
        Path,
        typer.Argument(help="Image file or directory to process")
    ],
    aspect_ratio: Annotated[
        str,
        typer.Option("--aspect-ratio", "-a", help="Target aspect ratio (e.g., 4:5, 9:16)")
    ] = "4:5",
    padding: Annotated[
        float,
        typer.Option("--padding", "-p", help="Padding around subject (0.0-1.0)")
    ] = 0.15,
    detection_model: Annotated[
        str,
        typer.Option("--model", "-m", help="Detection model: yolo or face")
    ] = "yolo",
    detection_strategy: Annotated[
        str,
        typer.Option("--strategy", "-s", help="Subject selection: largest, centered, highest_confidence")
    ] = "highest_confidence",
    output_dir: Annotated[
        Optional[Path],
        typer.Option("--output-dir", "-o", help="Output directory for XMP files")
    ] = None,
    write_xmp: Annotated[
        bool,
        typer.Option("--write-xmp/--no-write-xmp", help="Write XMP sidecar files")
    ] = True,
    preview: Annotated[
        bool,
        typer.Option("--preview", help="Generate preview images with crop overlay")
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would be done without writing files")
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output")
    ] = False,
) -> None:
    """Process images and generate XMP crop data for Lightroom."""
    # Parse aspect ratio
    target_aspect = parse_aspect_ratio(aspect_ratio)

    # Get image files
    image_files = get_image_files(path)
    if not image_files:
        console.print("[red]No supported image files found.[/red]")
        raise typer.Exit(1)

    console.print(f"Found [cyan]{len(image_files)}[/cyan] image(s) to process")
    console.print(f"Target aspect ratio: [cyan]{target_aspect[0]}:{target_aspect[1]}[/cyan]")
    console.print(f"Padding: [cyan]{padding:.0%}[/cyan]")
    console.print()

    # Initialize detector
    detector = SubjectDetector(model_type=detection_model)

    # Track results
    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=not verbose
    ) as progress:
        task = progress.add_task("Processing...", total=len(image_files))

        for image_path in image_files:
            progress.update(task, description=f"Processing {image_path.name}")

            result = {
                "file": image_path.name,
                "status": "skipped",
                "detection": None,
                "crop": None,
                "xmp_path": None,
            }

            try:
                # Detect subjects
                detections = detector.detect(image_path)

                if not detections:
                    result["status"] = "no_subject"
                    if verbose:
                        console.print(f"  [yellow]No subject detected[/yellow]")
                else:
                    # Select primary subject
                    primary = select_primary_subject(detections, detection_strategy)
                    result["detection"] = primary

                    if verbose:
                        console.print(
                            f"  Detected {len(detections)} subject(s), "
                            f"primary: {primary.label} ({primary.confidence:.2f})"
                        )

                    # Get image dimensions
                    image = cv2.imread(str(image_path))
                    if image is None:
                        result["status"] = "error"
                        result["error"] = "Failed to load image"
                    else:
                        height, width = image.shape[:2]

                        # Calculate crop
                        crop = calculate_crop_for_detection(
                            primary,
                            image_width=width,
                            image_height=height,
                            target_aspect=target_aspect,
                            padding=padding
                        )
                        result["crop"] = crop

                        if verbose:
                            console.print(
                                f"  Crop: L={crop.left:.3f}, R={crop.right:.3f}, "
                                f"T={crop.top:.3f}, B={crop.bottom:.3f}"
                            )

                        # Write XMP
                        if write_xmp and not dry_run:
                            xmp_path = write_crop_to_xmp(
                                image_path,
                                crop,
                                output_dir=output_dir,
                                backup=True
                            )
                            result["xmp_path"] = xmp_path
                            result["status"] = "success"
                        elif dry_run:
                            xmp_path = get_xmp_path(image_path)
                            if output_dir:
                                xmp_path = output_dir / xmp_path.name
                            result["xmp_path"] = xmp_path
                            result["status"] = "dry_run"
                        else:
                            result["status"] = "success"

                        # Generate preview
                        if preview and not dry_run:
                            preview_dir = output_dir or image_path.parent
                            preview_path = preview_dir / f"{image_path.stem}_preview.jpg"
                            draw_crop_preview(image_path, crop, primary, preview_path)
                            if verbose:
                                console.print(f"  Preview: {preview_path}")

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
                if verbose:
                    console.print(f"  [red]Error: {e}[/red]")

            results.append(result)
            progress.update(task, advance=1)

    # Print summary
    console.print()
    console.print("[bold]Summary[/bold]")

    table = Table()
    table.add_column("Status")
    table.add_column("Count")

    status_counts = {}
    for r in results:
        status = r["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    for status, count in sorted(status_counts.items()):
        color = {
            "success": "green",
            "dry_run": "cyan",
            "no_subject": "yellow",
            "error": "red",
            "skipped": "dim",
        }.get(status, "white")
        table.add_row(f"[{color}]{status}[/{color}]", str(count))

    console.print(table)

    if dry_run:
        console.print("\n[cyan]Dry run complete. No files were written.[/cyan]")


@app.command()
def version():
    """Show version information."""
    from . import __version__
    console.print(f"lightroom-subject-crop v{__version__}")


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
