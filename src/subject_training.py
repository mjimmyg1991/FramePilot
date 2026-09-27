"""Label, evaluate and train Smart Select's subject weights on your own photos.

Usage:
    python -m src.subject_training label PHOTO_FOLDER
    python -m src.subject_training evaluate PHOTO_FOLDER [--report DIR]
    python -m src.subject_training train PHOTO_FOLDER [--output FILE]

Labels are stored in PHOTO_FOLDER/subjects.json as the bounding box of the
chosen person, so they stay valid when the detector changes. Training fits
the feature weights with a softmax (conditional logit) model: in each photo,
the labelled person should outscore everyone else.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Optional

import cv2
import numpy as np
import typer

from src import resource_path

from .detector import Detection, SubjectDetector
from .subject_scoring import (
    WEIGHTS_PATH,
    SubjectWeights,
    load_subject_weights,
    save_subject_weights,
    subject_features,
)


LABELS_FILENAME = "subjects.json"
MATCH_IOU = 0.5
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
WINDOW_NAME = "FramePilot - click the main subject"
MAX_WINDOW_SIZE = (1400, 900)


@dataclass
class TrainingExample:
    """One labelled photo with more than one person."""

    name: str
    features: np.ndarray
    label_index: int
    people: list[Detection] = field(default_factory=list)
    balls: list[Detection] = field(default_factory=list)


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Intersection over union of two (x1, y1, x2, y2) boxes."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_label(people: list[Detection], bbox: tuple[float, ...]) -> int | None:
    """Index of the detection matching a labelled box, if any overlaps enough."""
    best_index, best_iou = None, MATCH_IOU
    for i, person in enumerate(people):
        overlap = iou(person.bbox, bbox)
        if overlap >= best_iou:
            best_index, best_iou = i, overlap
    return best_index


def box_at_point(people: list[Detection], point: tuple[float, float]) -> int | None:
    """Index of the smallest detection containing a normalized point."""
    containing = [
        i for i, p in enumerate(people)
        if p.bbox[0] <= point[0] <= p.bbox[2] and p.bbox[1] <= point[1] <= p.bbox[3]
    ]
    if not containing:
        return None
    return min(containing, key=lambda i: people[i].area)


def load_labels(folder: Path) -> dict[str, dict]:
    """Read PHOTO_FOLDER/subjects.json (empty when missing)."""
    path = folder / LABELS_FILENAME
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("labels", {})


def save_labels(folder: Path, labels: dict[str, dict]) -> None:
    """Write PHOTO_FOLDER/subjects.json."""
    path = folder / LABELS_FILENAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "labels": labels}, f, indent=1, sort_keys=True)
        f.write("\n")


def build_examples(
    folder: Path,
    labels: dict[str, dict],
    detector: SubjectDetector,
) -> tuple[list[TrainingExample], list[str]]:
    """Detect people in labelled photos and pair them with their labels.

    Photos with one person are left out since there is nothing to choose.

    Returns:
        Tuple of (examples, names of photos whose label matched no detection)
    """
    examples, unmatched = [], []
    for name, label in sorted(labels.items()):
        if "bbox" not in label or not (folder / name).exists():
            continue
        scene = detector.detect_scene(folder / name)
        if len(scene.people) < 2:
            continue
        index = match_label(scene.people, tuple(label["bbox"]))
        if index is None:
            unmatched.append(name)
            continue
        examples.append(TrainingExample(
            name=name,
            features=subject_features(scene.people, scene.balls, scene.image_size),
            label_index=index,
            people=scene.people,
            balls=scene.balls,
        ))
    return examples, unmatched


def predict(example: TrainingExample, weights: SubjectWeights) -> int:
    """Index of the person the weights would select."""
    return int(np.argmax(example.features @ weights.as_vector()))


def accuracy(examples: list[TrainingExample], weights: SubjectWeights) -> float:
    """Fraction of examples where the labelled person is selected."""
    if not examples:
        return 0.0
    return sum(predict(ex, weights) == ex.label_index for ex in examples) / len(examples)


def fit_weights(
    examples: list[TrainingExample],
    initial: SubjectWeights,
    l2: float = 0.05,
    iterations: int = 2000,
    learning_rate: float = 0.2,
) -> SubjectWeights:
    """Fit weights by maximizing the softmax likelihood of the labelled people.

    The L2 term pulls weights towards ``initial``, so small label sets refine
    the defaults rather than replacing them.

    Args:
        examples: Labelled photos
        initial: Starting weights, also the regularization target
        l2: Strength of the pull towards ``initial``
        iterations: Gradient ascent steps
        learning_rate: Step size

    Returns:
        Fitted SubjectWeights
    """
    prior = initial.as_vector()
    weights = prior.copy()
    if not examples:
        return initial

    for _ in range(iterations):
        gradient = np.zeros_like(weights)
        for ex in examples:
            scores = ex.features @ weights
            probs = np.exp(scores - scores.max())
            probs /= probs.sum()
            gradient += ex.features[ex.label_index] - probs @ ex.features
        # Implicit step for the L2 pull, stable for any l2 * learning_rate
        weights = (weights + learning_rate * (gradient / len(examples) + l2 * prior)) / (
            1 + learning_rate * l2
        )

    return SubjectWeights.from_vector(weights)


def cross_validate(
    examples: list[TrainingExample],
    initial: SubjectWeights,
    folds: int = 5,
    **fit_options: float,
) -> float:
    """Held-out accuracy of fitting on the other folds (leave-one-out if few)."""
    if len(examples) < 2:
        return accuracy(examples, initial)
    folds = min(folds, len(examples))
    correct = 0
    for k in range(folds):
        held_out = examples[k::folds]
        training = [ex for i, ex in enumerate(examples) if i % folds != k]
        fitted = fit_weights(training, initial, **fit_options)
        correct += sum(predict(ex, fitted) == ex.label_index for ex in held_out)
    return correct / len(examples)


def _draw_people(
    image: np.ndarray,
    people: list[Detection],
    highlight: dict[int, tuple[int, int, int]] | None = None,
) -> np.ndarray:
    canvas = image.copy()
    h, w = canvas.shape[:2]
    thickness = max(2, int(round(max(h, w) / 600)))
    for i, person in enumerate(people):
        color = (highlight or {}).get(i, (255, 200, 0))
        x1, y1, x2, y2 = (int(v) for v in (person.bbox[0] * w, person.bbox[1] * h,
                                            person.bbox[2] * w, person.bbox[3] * h))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)
        cv2.putText(canvas, str(i), (x1 + 4, y1 + 12 * thickness), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5 * thickness, color, thickness)
    return canvas


app = typer.Typer(help="Label photos and tune Smart Select's subject weights.", no_args_is_help=True)


@app.command()
def label(
    folder: Annotated[Path, typer.Argument(help="Folder of photos to label")],
    precise: Annotated[bool, typer.Option(help="Use the segmentation model")] = False,
) -> None:
    """Click the main subject in each photo (s = skip, q = save and quit)."""
    labels = load_labels(folder)
    detector = SubjectDetector(
        yolo_model="yolov8m-seg.pt" if precise else "yolov8m.pt", use_tight_bbox=precise
    )
    todo = [p for p in sorted(folder.iterdir())
            if p.suffix.lower() in IMAGE_EXTENSIONS and p.name not in labels]
    typer.echo(f"{len(todo)} photo(s) to label, {len(labels)} already labelled")

    try:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    except cv2.error:
        typer.echo("Labelling needs opencv-python with GUI support (not the headless build).")
        raise typer.Exit(1)

    clicked: list[tuple[float, float]] = []
    view = {"scale": 1.0, "size": (1, 1)}

    def on_mouse(event: int, x: int, y: int, *_: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            width, height = view["size"]
            clicked.append((x / width, y / height))

    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    for position, path in enumerate(todo, 1):
        scene = detector.detect_scene(path)
        if len(scene.people) < 2:
            labels[path.name] = (
                {"bbox": list(scene.people[0].bbox)} if scene.people else {"skip": "no people detected"}
            )
            save_labels(folder, labels)
            continue

        image = cv2.imread(str(path))
        canvas = _draw_people(image, scene.people)
        h, w = canvas.shape[:2]
        scale = min(MAX_WINDOW_SIZE[0] / w, MAX_WINDOW_SIZE[1] / h, 1.0)
        shown = cv2.resize(canvas, (int(w * scale), int(h * scale)))
        view["size"] = (shown.shape[1], shown.shape[0])
        cv2.imshow(WINDOW_NAME, shown)
        cv2.setWindowTitle(WINDOW_NAME, f"[{position}/{len(todo)}] {path.name} - click the main subject")
        clicked.clear()

        choice = None
        while choice is None:
            key = cv2.waitKey(50) & 0xFF
            if clicked:
                index = box_at_point(scene.people, clicked.pop())
                if index is not None:
                    choice = {"bbox": list(scene.people[index].bbox)}
            elif ord("0") <= key <= ord("9") and key - ord("0") < len(scene.people):
                choice = {"bbox": list(scene.people[key - ord("0")].bbox)}
            elif key == ord("s"):
                choice = {"skip": "no clear subject"}
            elif key in (ord("q"), 27):
                save_labels(folder, labels)
                cv2.destroyAllWindows()
                typer.echo("Saved. Run label again to continue.")
                return
        labels[path.name] = choice
        save_labels(folder, labels)

    cv2.destroyAllWindows()
    typer.echo(f"Done: {len(labels)} photo(s) labelled in {folder / LABELS_FILENAME}")


@app.command()
def evaluate(
    folder: Annotated[Path, typer.Argument(help="Folder with photos and subjects.json")],
    weights_file: Annotated[Optional[Path], typer.Option("--weights", help="Weights JSON to test")] = None,
    report: Annotated[Optional[Path], typer.Option(help="Folder for annotated images of misses")] = None,
) -> None:
    """Report how often Smart Select picks the labelled subject."""
    weights = load_subject_weights(weights_file)
    examples, unmatched = build_examples(folder, load_labels(folder), SubjectDetector())
    _print_dataset_summary(examples, unmatched)
    typer.echo(f"Accuracy: {accuracy(examples, weights):.0%} on {len(examples)} multi-person photo(s)")

    misses = [ex for ex in examples if predict(ex, weights) != ex.label_index]
    for ex in misses:
        typer.echo(f"  miss: {ex.name} (picked #{predict(ex, weights)}, labelled #{ex.label_index})")
    if report and misses:
        report.mkdir(parents=True, exist_ok=True)
        for ex in misses:
            image = cv2.imread(str(folder / ex.name))
            colors = {ex.label_index: (0, 200, 0), predict(ex, weights): (0, 0, 255)}
            cv2.imwrite(str(report / ex.name), _draw_people(image, ex.people, colors))
        typer.echo(f"Wrote {len(misses)} annotated miss(es) to {report} (green = labelled, red = picked)")


@app.command()
def train(
    folder: Annotated[Path, typer.Argument(help="Folder with photos and subjects.json")],
    output: Annotated[Optional[Path], typer.Option(help="Where to write the weights JSON")] = None,
    l2: Annotated[float, typer.Option(help="Pull towards the current weights")] = 0.05,
    force: Annotated[bool, typer.Option(help="Save even if held-out accuracy doesn't improve")] = False,
) -> None:
    """Fit Smart Select weights to your labels."""
    output = output or resource_path(WEIGHTS_PATH)
    current = load_subject_weights()
    examples, unmatched = build_examples(folder, load_labels(folder), SubjectDetector())
    _print_dataset_summary(examples, unmatched)
    if not examples:
        typer.echo("No multi-person labelled photos to train on.")
        raise typer.Exit(1)

    baseline = accuracy(examples, current)
    held_out = cross_validate(examples, current, l2=l2)
    fitted = fit_weights(examples, current, l2=l2)
    typer.echo(f"Current weights:            {baseline:.0%}")
    typer.echo(f"Trained, held-out photos:   {held_out:.0%}")
    typer.echo(f"Trained, all photos:        {accuracy(examples, fitted):.0%}")
    for name in SubjectWeights.names():
        typer.echo(f"  {name:15s} {getattr(current, name):6.2f} -> {getattr(fitted, name):6.2f}")

    if held_out < baseline and not force:
        typer.echo("Not saved: trained weights did worse on held-out photos. Label more photos or use --force.")
        raise typer.Exit(1)

    save_subject_weights(fitted, output, metadata={
        "photos": len(examples),
        "baseline_accuracy": round(baseline, 4),
        "held_out_accuracy": round(held_out, 4),
        "l2": l2,
    })
    typer.echo(f"Saved weights to {output}")


def _print_dataset_summary(examples: list[TrainingExample], unmatched: list[str]) -> None:
    with_ball = sum(1 for ex in examples if ex.balls)
    typer.echo(f"{len(examples)} multi-person photo(s), {with_ball} with a ball detected")
    if unmatched:
        typer.echo(f"{len(unmatched)} label(s) matched no detection: {', '.join(unmatched[:5])}"
                   + (" ..." if len(unmatched) > 5 else ""))


if __name__ == "__main__":
    app()
