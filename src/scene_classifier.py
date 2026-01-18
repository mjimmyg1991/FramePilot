"""Scene classification using CLIP for auto-detecting shoot type."""

from pathlib import Path
from typing import Callable

import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from .presets import SHOOT_TYPES, ShootTypePreset


class SceneClassifier:
    """Classifies photography scenes using CLIP zero-shot classification."""

    # Scene descriptions for CLIP classification
    SCENE_PROMPTS = {
        "wedding": [
            "a wedding ceremony photo",
            "a bride and groom photo",
            "a wedding reception photo",
            "people at a wedding celebration",
            "a formal event with people in formal attire",
        ],
        "sports": [
            "a sports photography shot",
            "athletes playing a game",
            "an action sports photo",
            "people playing sports on a field",
            "a competitive sporting event",
        ],
        "portrait": [
            "a portrait photograph of a person",
            "a headshot photo",
            "a posed portrait session",
            "a professional portrait photo",
            "a close-up photo of a person",
        ],
        "street": [
            "street photography",
            "candid photo of people in a city",
            "urban photography",
            "travel photography",
            "documentary style photo",
        ],
    }

    def __init__(self):
        """Initialize the classifier. Model loaded lazily on first use."""
        self._model: CLIPModel | None = None
        self._processor: CLIPProcessor | None = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"

    def _load_model(self):
        """Load CLIP model if not already loaded."""
        if self._model is None:
            self._model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
            self._processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
            self._model.to(self._device)
            self._model.eval()

    def classify_image(self, image_path: Path) -> tuple[str, float, dict[str, float]]:
        """Classify a single image.

        Args:
            image_path: Path to the image file

        Returns:
            Tuple of (best_match_key, confidence, all_scores)
            - best_match_key: Key from SHOOT_TYPES (e.g., "wedding", "sports")
            - confidence: Confidence score (0-1)
            - all_scores: Dict of all category scores
        """
        self._load_model()

        # Load and preprocess image
        image = Image.open(image_path).convert("RGB")

        # Build all text prompts
        all_prompts = []
        prompt_to_category = {}
        for category, prompts in self.SCENE_PROMPTS.items():
            for prompt in prompts:
                all_prompts.append(prompt)
                prompt_to_category[prompt] = category

        # Get CLIP embeddings
        inputs = self._processor(
            text=all_prompts,
            images=image,
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)
            logits_per_image = outputs.logits_per_image
            probs = logits_per_image.softmax(dim=1).cpu().numpy()[0]

        # Aggregate scores by category (average of all prompts for that category)
        category_scores: dict[str, list[float]] = {cat: [] for cat in self.SCENE_PROMPTS}
        for prompt, prob in zip(all_prompts, probs):
            category = prompt_to_category[prompt]
            category_scores[category].append(float(prob))

        # Average scores per category
        final_scores = {
            cat: sum(scores) / len(scores)
            for cat, scores in category_scores.items()
        }

        # Normalize to sum to 1
        total = sum(final_scores.values())
        if total > 0:
            final_scores = {k: v / total for k, v in final_scores.items()}

        # Find best match
        best_category = max(final_scores, key=final_scores.get)
        best_confidence = final_scores[best_category]

        return best_category, best_confidence, final_scores

    def classify_batch(
        self,
        image_paths: list[Path],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[str, float, dict[str, float]]:
        """Classify multiple images and return aggregate result.

        Analyzes up to 5 images for efficiency, returns the most common classification.

        Args:
            image_paths: List of image paths
            on_progress: Optional progress callback(current, total)

        Returns:
            Tuple of (best_match_key, confidence, all_scores)
        """
        # Sample up to 5 images for efficiency
        sample_size = min(5, len(image_paths))
        if len(image_paths) > sample_size:
            # Take evenly spaced samples
            step = len(image_paths) // sample_size
            samples = [image_paths[i * step] for i in range(sample_size)]
        else:
            samples = image_paths

        # Aggregate scores across all samples
        aggregate_scores: dict[str, list[float]] = {cat: [] for cat in self.SCENE_PROMPTS}

        for i, path in enumerate(samples):
            if on_progress:
                on_progress(i, len(samples))

            try:
                _, _, scores = self.classify_image(path)
                for cat, score in scores.items():
                    aggregate_scores[cat].append(score)
            except Exception:
                continue  # Skip problematic images

        if on_progress:
            on_progress(len(samples), len(samples))

        # Average across all samples
        final_scores = {}
        for cat, scores in aggregate_scores.items():
            if scores:
                final_scores[cat] = sum(scores) / len(scores)
            else:
                final_scores[cat] = 0.0

        # Normalize
        total = sum(final_scores.values())
        if total > 0:
            final_scores = {k: v / total for k, v in final_scores.items()}

        # Find best match
        if final_scores:
            best_category = max(final_scores, key=final_scores.get)
            best_confidence = final_scores[best_category]
        else:
            best_category = "portrait"  # Default fallback
            best_confidence = 0.25
            final_scores = {cat: 0.25 for cat in self.SCENE_PROMPTS}

        return best_category, best_confidence, final_scores

    def get_shoot_type_preset(self, category_key: str) -> ShootTypePreset | None:
        """Get the ShootTypePreset for a category key."""
        return SHOOT_TYPES.get(category_key)


# Singleton instance for reuse
_classifier: SceneClassifier | None = None


def get_classifier() -> SceneClassifier:
    """Get or create the singleton classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = SceneClassifier()
    return _classifier


def auto_detect_shoot_type(
    image_paths: list[Path],
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[str, ShootTypePreset, float, dict[str, float]]:
    """Auto-detect shoot type from a list of images.

    Args:
        image_paths: List of image paths to analyze
        on_progress: Optional progress callback

    Returns:
        Tuple of (category_key, preset, confidence, all_scores)
    """
    classifier = get_classifier()
    category_key, confidence, scores = classifier.classify_batch(image_paths, on_progress)
    preset = SHOOT_TYPES[category_key]
    return category_key, preset, confidence, scores
