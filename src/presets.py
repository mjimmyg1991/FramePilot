"""Presets for shoot types, destinations, and export settings."""

from dataclasses import dataclass
from enum import Enum


class SubjectStrategy(Enum):
    """Subject selection strategies with consumer-friendly names."""

    SMART_SELECT = "highest_confidence"
    MAIN_SUBJECT = "largest"
    CENTER_STAGE = "centered"

    @classmethod
    def display_name(cls, strategy: "SubjectStrategy") -> str:
        """Get the display name for a strategy."""
        names = {
            cls.SMART_SELECT: "Smart Select",
            cls.MAIN_SUBJECT: "Main Subject",
            cls.CENTER_STAGE: "Center Stage",
        }
        return names.get(strategy, strategy.name)

    @classmethod
    def description(cls, strategy: "SubjectStrategy") -> str:
        """Get the description for a strategy."""
        descriptions = {
            cls.SMART_SELECT: "AI picks the best subject automatically",
            cls.MAIN_SUBJECT: "Focuses on the largest person in frame",
            cls.CENTER_STAGE: "Prioritizes whoever's most centered",
        }
        return descriptions.get(strategy, "")

    @classmethod
    def from_display_name(cls, name: str) -> "SubjectStrategy":
        """Get strategy from display name."""
        for strategy in cls:
            if cls.display_name(strategy) == name:
                return strategy
        return cls.SMART_SELECT


@dataclass
class ShootTypePreset:
    """Preset settings for a type of photography shoot."""

    name: str
    description: str
    default_strategy: SubjectStrategy
    default_padding: float
    suggested_aspects: list[tuple[int, int]]
    keywords: list[str]  # For auto-detection hints


@dataclass
class DestinationPreset:
    """Preset settings for an export destination."""

    name: str
    description: str
    jpeg_quality: int
    suggested_aspects: list[tuple[int, int]]
    format: str  # "JPEG" or "TIFF"
    max_dimension: int | None  # None = no resize


# Shoot type presets
SHOOT_TYPES: dict[str, ShootTypePreset] = {
    "wedding": ShootTypePreset(
        name="Wedding & Events",
        description="Ceremonies, receptions, and celebrations",
        default_strategy=SubjectStrategy.SMART_SELECT,
        default_padding=0.15,
        suggested_aspects=[(4, 5), (2, 3), (5, 7)],
        keywords=["wedding", "bride", "groom", "ceremony", "reception", "celebration",
                  "bouquet", "dress", "cake", "ring", "altar", "church"],
    ),
    "sports": ShootTypePreset(
        name="Sports & Action",
        description="Athletic events and fast-moving subjects",
        default_strategy=SubjectStrategy.MAIN_SUBJECT,
        default_padding=0.12,
        suggested_aspects=[(4, 5), (9, 16), (2, 3)],
        keywords=["sports", "game", "match", "athlete", "player", "ball", "field",
                  "court", "stadium", "running", "action", "competition"],
    ),
    "portrait": ShootTypePreset(
        name="Portraits",
        description="Individual or small group portraits",
        default_strategy=SubjectStrategy.SMART_SELECT,
        default_padding=0.18,
        suggested_aspects=[(4, 5), (2, 3), (5, 7)],
        keywords=["portrait", "headshot", "face", "person", "model", "studio",
                  "profile", "closeup", "posed"],
    ),
    "street": ShootTypePreset(
        name="Street & Travel",
        description="Candid street photography and travel shots",
        default_strategy=SubjectStrategy.SMART_SELECT,
        default_padding=0.15,
        suggested_aspects=[(4, 5), (1, 1), (9, 16)],
        keywords=["street", "travel", "city", "urban", "candid", "documentary",
                  "architecture", "market", "crowd"],
    ),
    "auto": ShootTypePreset(
        name="Auto-Detect",
        description="AI analyzes your photos and suggests settings",
        default_strategy=SubjectStrategy.SMART_SELECT,
        default_padding=0.15,
        suggested_aspects=[(4, 5)],
        keywords=[],
    ),
}


# Destination presets
DESTINATIONS: dict[str, DestinationPreset] = {
    "social": DestinationPreset(
        name="Instagram / Social",
        description="Optimized for social media platforms",
        jpeg_quality=85,
        suggested_aspects=[(4, 5), (9, 16), (1, 1)],
        format="JPEG",
        max_dimension=2048,
    ),
    "client": DestinationPreset(
        name="Client Gallery",
        description="High quality for client delivery",
        jpeg_quality=92,
        suggested_aspects=[(4, 5), (2, 3), (5, 7)],
        format="JPEG",
        max_dimension=None,
    ),
    "print": DestinationPreset(
        name="Print / Magazine",
        description="Maximum quality for professional printing",
        jpeg_quality=100,
        suggested_aspects=[(4, 5), (2, 3), (5, 7), (8, 10)],
        format="JPEG",
        max_dimension=None,
    ),
    "web": DestinationPreset(
        name="Web / Portfolio",
        description="Balanced quality for websites and portfolios",
        jpeg_quality=88,
        suggested_aspects=[(4, 5), (2, 3), (16, 9)],
        format="JPEG",
        max_dimension=3000,
    ),
}


def get_shoot_type_names() -> list[str]:
    """Get list of shoot type display names."""
    return [preset.name for preset in SHOOT_TYPES.values()]


def get_destination_names() -> list[str]:
    """Get list of destination display names."""
    return [preset.name for preset in DESTINATIONS.values()]


def get_shoot_type_by_name(name: str) -> ShootTypePreset | None:
    """Get shoot type preset by display name."""
    for preset in SHOOT_TYPES.values():
        if preset.name == name:
            return preset
    return None


def get_destination_by_name(name: str) -> DestinationPreset | None:
    """Get destination preset by display name."""
    for preset in DESTINATIONS.values():
        if preset.name == name:
            return preset
    return None


def get_strategy_names() -> list[str]:
    """Get list of strategy display names."""
    return [SubjectStrategy.display_name(s) for s in SubjectStrategy]


def get_recommended_settings(
    shoot_type: str | None = None,
    destination: str | None = None,
) -> dict:
    """Get recommended settings based on shoot type and destination.

    Returns dict with:
        - aspect_ratio: tuple[int, int]
        - strategy: str (technical name)
        - padding: float
        - jpeg_quality: int
        - format: str
        - max_dimension: int | None
    """
    settings = {
        "aspect_ratio": (4, 5),
        "strategy": "highest_confidence",
        "padding": 0.15,
        "jpeg_quality": 92,
        "format": "JPEG",
        "max_dimension": None,
    }

    # Apply shoot type settings
    shoot_preset = get_shoot_type_by_name(shoot_type) if shoot_type else None
    if shoot_preset:
        settings["strategy"] = shoot_preset.default_strategy.value
        settings["padding"] = shoot_preset.default_padding
        if shoot_preset.suggested_aspects:
            settings["aspect_ratio"] = shoot_preset.suggested_aspects[0]

    # Apply destination settings (these take priority for quality)
    dest_preset = get_destination_by_name(destination) if destination else None
    if dest_preset:
        settings["jpeg_quality"] = dest_preset.jpeg_quality
        settings["format"] = dest_preset.format
        settings["max_dimension"] = dest_preset.max_dimension
        # If shoot type didn't set aspect, use destination's suggestion
        if not shoot_preset and dest_preset.suggested_aspects:
            settings["aspect_ratio"] = dest_preset.suggested_aspects[0]

    return settings
