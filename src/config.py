"""Configuration loader for FramePilot."""

from pathlib import Path

import yaml

from . import resource_path

# Default settings (used when no config file is found)
DEFAULTS = {
    "detection": {
        "model_type": "yolo",
        "yolo_model": "yolov8m.pt",
        "confidence_threshold": 0.5,
    },
    "crop": {
        "default_aspect_ratio": [4, 5],
        "padding": 0.15,
        "subject_selection": "highest_confidence",
    },
    "output": {
        "backup_existing_xmp": True,
        "preview_quality": 85,
        "preview_max_size": 1920,
    },
    "watcher": {
        "enabled": False,
        "watch_dir": "",
        "auto_xmp": True,
        "debounce_seconds": 2,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, preferring override values."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> dict:
    """Load configuration from YAML file, falling back to defaults.

    Args:
        config_path: Path to config file. If None, searches for default_config.yaml
                     in the resource path.

    Returns:
        Merged configuration dict
    """
    if config_path is None:
        config_path = resource_path("config") / "default_config.yaml"

    if config_path.exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        return _deep_merge(DEFAULTS, user_config)

    return DEFAULTS.copy()


def validate_config(config: dict) -> list[str]:
    """Validate configuration values.

    Returns:
        List of warning messages (empty if valid)
    """
    warnings = []

    det = config.get("detection", {})
    if det.get("model_type") not in ("yolo", "face"):
        warnings.append(f"Invalid detection.model_type: {det.get('model_type')}")

    threshold = det.get("confidence_threshold", 0.5)
    if not (0.0 <= threshold <= 1.0):
        warnings.append(f"detection.confidence_threshold must be 0-1, got {threshold}")

    crop = config.get("crop", {})
    padding = crop.get("padding", 0.15)
    if not (0.0 <= padding <= 1.0):
        warnings.append(f"crop.padding must be 0-1, got {padding}")

    aspect = crop.get("default_aspect_ratio", [4, 5])
    if not (isinstance(aspect, list) and len(aspect) == 2 and all(isinstance(v, int) and v > 0 for v in aspect)):
        warnings.append(f"crop.default_aspect_ratio must be [w, h] with positive ints, got {aspect}")

    strategy = crop.get("subject_selection", "highest_confidence")
    valid_strategies = ("highest_confidence", "largest", "centered", "group")
    if strategy not in valid_strategies:
        warnings.append(f"crop.subject_selection must be one of {valid_strategies}, got {strategy}")

    return warnings
