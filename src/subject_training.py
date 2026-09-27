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

from .crop_calculator import CropRegion, calculate_crop_for_subject
from .crop_candidates import (
    LOW_HEAD_LIMIT,
    balls_in_reach,
    cuts_ball,
    cuts_head,
    crop_terms,
    rank_crops,
    visible_fraction,
)
from .detector import Detection, SubjectDetector
from .subject_modes import SubjectMode, choose_subject
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
    mode: str = "single"
    member_indices: list[int] = field(default_factory=list)
    image_size: tuple[int, int] | None = None

    def is_hit(self, index: int) -> bool:
        """True if the index is the labelled subject or, for a duel or group, one of its members."""
        return index == self.label_index or index in self.member_indices


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
        members = [match_label(scene.people, tuple(box)) for box in label.get("members", [])]
        examples.append(TrainingExample(
            name=name,
            features=subject_features(scene.people, scene.balls, scene.image_size),
            label_index=index,
            people=scene.people,
            balls=scene.balls,
            mode=label.get("mode", "single"),
            member_indices=sorted({m for m in members if m is not None}),
            image_size=scene.image_size,
        ))
    return examples, unmatched


def predict(example: TrainingExample, weights: SubjectWeights) -> int:
    """Index of the person the weights would select."""
    return int(np.argmax(example.features @ weights.as_vector()))


def accuracy(examples: list[TrainingExample], weights: SubjectWeights) -> float:
    """Fraction of examples where the subject (or a duel/group member) is selected."""
    if not examples:
        return 0.0
    return sum(ex.is_hit(predict(ex, weights)) for ex in examples) / len(examples)


def _stack(examples: list[TrainingExample]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """All people's features in one matrix, each photo's start row, and a target mask."""
    features = np.vstack([ex.features for ex in examples])
    starts = np.cumsum([0] + [len(ex.features) for ex in examples[:-1]])
    targets = np.zeros(len(features), dtype=bool)
    for start, ex in zip(starts, examples):
        for index in set(ex.member_indices) | {ex.label_index}:
            targets[start + index] = True
    return features, starts, targets


def fit_weights(
    examples: list[TrainingExample],
    initial: SubjectWeights,
    l2: float = 0.05,
    iterations: int = 2000,
    learning_rate: float = 0.2,
) -> SubjectWeights:
    """Fit weights by maximizing the softmax likelihood of the labelled people.

    For a duel or group, probability on any labelled member counts. The L2
    term pulls weights towards ``initial``, so small label sets refine the
    defaults rather than replacing them.

    Args:
        examples: Labelled photos
        initial: Starting weights, also the regularization target
        l2: Strength of the pull towards ``initial``
        iterations: Gradient ascent steps
        learning_rate: Step size

    Returns:
        Fitted SubjectWeights
    """
    if not examples:
        return initial
    prior = initial.as_vector()
    weights = prior.copy()
    features, starts, targets = _stack(examples)
    sizes = np.diff(np.append(starts, len(features)))

    for _ in range(iterations):
        scores = features @ weights
        scores -= np.repeat(np.maximum.reduceat(scores, starts), sizes)
        exp = np.exp(scores)
        probs = exp / np.repeat(np.add.reduceat(exp, starts), sizes)
        target_probs = probs * targets
        target_share = target_probs / np.repeat(np.add.reduceat(target_probs, starts), sizes)
        gradient = (target_share - probs) @ features
        # Implicit step for the L2 pull, stable for any l2 * learning_rate
        weights = (weights + learning_rate * (gradient / len(examples) + l2 * prior)) / (
            1 + learning_rate * l2
        )

    return SubjectWeights.from_vector(weights)


def summarize(
    examples: list[TrainingExample],
    weights: SubjectWeights | None = None,
    predictions: list[int] | None = None,
) -> dict[str, tuple[int, int]]:
    """Hits and totals overall and per labelled mode.

    "strict" counts the exact labelled subject; the other rows accept any
    labelled member of a duel or group.

    Args:
        examples: Labelled photos
        weights: Weights to predict with (when predictions aren't given)
        predictions: Precomputed picks, e.g. from cross_validated_predictions

    Returns:
        Dict of name -> (hits, total)
    """
    if predictions is None:
        predictions = [predict(ex, weights or SubjectWeights()) for ex in examples]
    rows: dict[str, tuple[int, int]] = {}

    def add(key: str, hit: bool) -> None:
        hits, total = rows.get(key, (0, 0))
        rows[key] = (hits + int(hit), total + 1)

    for ex, picked in zip(examples, predictions):
        add("strict", picked == ex.label_index)
        add("any_member", ex.is_hit(picked))
        add(ex.mode, ex.is_hit(picked))
    return rows


MODES = [m.value for m in SubjectMode]


def mode_report(examples: list[TrainingExample], weights: SubjectWeights) -> dict:
    """How well Smart Select's single/duel/group decision matches the labels.

    Returns:
        Dict with "confusion" ({labelled: {predicted: count}}), "framing"
        ((hits, total) for single vs duel-or-group), and "member_recall" /
        "member_precision" ((found, total) over labelled duels and groups)
    """
    confusion = {m: {p: 0 for p in MODES} for m in MODES}
    framing = [0, 0]
    recall = [0, 0]
    precision = [0, 0]
    for ex in examples:
        choice = choose_subject(ex.people, ex.balls, ex.image_size, weights)
        predicted = choice.mode.value
        confusion[ex.mode][predicted] += 1
        framing[0] += int((ex.mode == "single") == (predicted == "single"))
        framing[1] += 1
        if ex.mode != "single" and ex.member_indices:
            chosen = {i for i, p in enumerate(ex.people) if any(p is m for m in choice.members)}
            labelled = set(ex.member_indices)
            recall[0] += len(chosen & labelled)
            recall[1] += len(labelled)
            precision[0] += len(chosen & labelled)
            precision[1] += len(chosen)
    return {
        "confusion": confusion,
        "framing": tuple(framing),
        "member_recall": tuple(recall),
        "member_precision": tuple(precision),
    }


CROP_CHECKS = ["head_cut", "ball_cut", "intruder", "extremity", "low_head"]
INTRUDER_VISIBLE = (0.2, 0.8)
INTRUDER_MIN_SCALE = 0.5


def crop_problems(crop: CropRegion, example: TrainingExample, choice, target_aspect: tuple[int, int]) -> set[str]:
    """Composition problems in a crop (see CROP_CHECKS)."""
    size = example.image_size or (3, 2)
    reachable = balls_in_reach(choice, example.balls, size[0] / size[1])
    terms = crop_terms(crop, choice, example.people, reachable, crop.height, target_aspect)
    member_ids = {id(m) for m in choice.members}
    problems = set()
    if cuts_head(crop, choice):
        problems.add("head_cut")
    if cuts_ball(crop, reachable):
        problems.add("ball_cut")
    if any(INTRUDER_VISIBLE[0] < visible_fraction(p.bbox, crop) < INTRUDER_VISIBLE[1]
           and p.height >= INTRUDER_MIN_SCALE * choice.primary.height
           for p in example.people if id(p) not in member_ids):
        problems.add("intruder")
    if terms["extremity"] > 0:
        problems.add("extremity")
    if target_aspect[0] < target_aspect[1] and terms["low_head"] > 0:
        problems.add("low_head")
    return problems


def crop_report(
    examples: list[TrainingExample],
    weights: SubjectWeights,
    target_aspect: tuple[int, int],
    padding: float = 0.15,
) -> dict[str, dict[str, int]]:
    """Count composition problems in the single computed crop and the best candidate.

    Returns:
        {"single": {check: count}, "candidates": {check: count}} plus "total"
    """
    counts = {"single": dict.fromkeys(CROP_CHECKS, 0), "candidates": dict.fromkeys(CROP_CHECKS, 0)}
    for ex in examples:
        size = ex.image_size or (3, 2)
        choice = choose_subject(ex.people, ex.balls, size, weights)
        base = calculate_crop_for_subject(choice, size[0], size[1], target_aspect, padding)
        best = rank_crops(choice, ex.people, ex.balls, size, target_aspect, padding)[0].crop
        for key, crop in (("single", base), ("candidates", best)):
            for problem in crop_problems(crop, ex, choice, target_aspect):
                counts[key][problem] += 1
    counts["total"] = {"photos": len(examples)}
    return counts


def cross_validated_predictions(
    examples: list[TrainingExample],
    initial: SubjectWeights,
    folds: int = 5,
    **fit_options: float,
) -> list[int]:
    """Pick for each photo using weights fitted on the other folds."""
    predictions = [0] * len(examples)
    if len(examples) < 2:
        return [predict(ex, initial) for ex in examples]
    folds = min(folds, len(examples))
    for k in range(folds):
        training = [ex for i, ex in enumerate(examples) if i % folds != k]
        fitted = fit_weights(training, initial, **fit_options)
        for i in range(k, len(examples), folds):
            predictions[i] = predict(examples[i], fitted)
    return predictions


def cross_validate(
    examples: list[TrainingExample],
    initial: SubjectWeights,
    folds: int = 5,
    **fit_options: float,
) -> float:
    """Held-out hit rate of fitting on the other folds (leave-one-out if few)."""
    if not examples:
        return 0.0
    predictions = cross_validated_predictions(examples, initial, folds, **fit_options)
    return sum(ex.is_hit(p) for ex, p in zip(examples, predictions)) / len(examples)


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
    cross_validated: Annotated[bool, typer.Option(
        "--cross-validate", help="Also report held-out accuracy of training on the other folds")] = False,
    l2: Annotated[float, typer.Option(help="Pull towards the current weights when cross-validating")] = 0.05,
) -> None:
    """Report how often Smart Select picks the labelled subject."""
    weights = load_subject_weights(weights_file)
    examples, unmatched = build_examples(folder, load_labels(folder), SubjectDetector())
    _print_dataset_summary(examples, unmatched)
    typer.echo("Current weights:")
    _print_summary(summarize(examples, weights))
    _print_mode_report(mode_report(examples, weights))
    for target_aspect in ((4, 5), (9, 16)):
        _print_crop_report(crop_report(examples, weights, target_aspect), target_aspect)
    if cross_validated:
        typer.echo("Trained on other folds, held-out photos:")
        _print_summary(summarize(examples, predictions=cross_validated_predictions(examples, weights, l2=l2)))

    misses = [ex for ex in examples if not ex.is_hit(predict(ex, weights))]
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


def _print_summary(rows: dict[str, tuple[int, int]]) -> None:
    labels = {
        "strict": "Exact labelled subject",
        "any_member": "Subject or duel/group member",
        "single": "  single",
        "duel": "  duel",
        "group": "  group",
    }
    for key in ["strict", "any_member", "single", "duel", "group"]:
        if key in rows:
            hits, total = rows[key]
            typer.echo(f"{labels[key]:30s} {hits:4d}/{total:<4d} {hits / total:6.1%}")


def _print_mode_report(report: dict) -> None:
    typer.echo("Subject mode (rows labelled, columns picked):")
    typer.echo("            " + "".join(f"{m:>8s}" for m in MODES))
    for labelled in MODES:
        row = report["confusion"][labelled]
        typer.echo(f"  {labelled:10s}" + "".join(f"{row[p]:8d}" for p in MODES))
    for key, name in [("framing", "Single vs duel/group framing"),
                      ("member_recall", "Labelled members framed"),
                      ("member_precision", "Framed members labelled")]:
        hits, total = report[key]
        if total:
            typer.echo(f"{name:30s} {hits:4d}/{total:<4d} {hits / total:6.1%}")


def _print_crop_report(report: dict, target_aspect: tuple[int, int]) -> None:
    total = report["total"]["photos"]
    typer.echo(f"Crop problems at {target_aspect[0]}:{target_aspect[1]} "
               f"(photos affected of {total}; single computed crop -> best candidate):")
    for check in CROP_CHECKS:
        before, after = report["single"][check], report["candidates"][check]
        typer.echo(f"  {check:12s} {before:4d} -> {after:4d}")


def _print_dataset_summary(examples: list[TrainingExample], unmatched: list[str]) -> None:
    with_ball = sum(1 for ex in examples if ex.balls)
    typer.echo(f"{len(examples)} multi-person photo(s), {with_ball} with a ball detected")
    if unmatched:
        typer.echo(f"{len(unmatched)} label(s) matched no detection: {', '.join(unmatched[:5])}"
                   + (" ..." if len(unmatched) > 5 else ""))


if __name__ == "__main__":
    app()
