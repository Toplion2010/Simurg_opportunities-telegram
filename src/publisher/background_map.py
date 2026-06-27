"""Category → theme mapping, brand-collection resolution, and render-time style descriptors.

This module is pure (no I/O, no DB). It turns an Opportunity into the small, stateless
``StyleDescriptor`` consumed by ``BackgroundManager`` to pick a fitting background.

Brand collections live under ``backgrounds/brands/<name>/``.  Theme folders live directly
under ``backgrounds/<theme>/``.  This separation lets the scanner treat the two hierarchies
independently while keeping the mental model simple (ADR-002).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.core.enums import Category

if TYPE_CHECKING:
    from src.db.models.opportunity import Opportunity


# Sub-directory that holds brand-specific background collections.
BRANDS_DIR = "brands"


# Known theme folders. A folder named "<theme>" or "<theme>_<variant>" (e.g. "academic_dark")
# belongs to that theme's pool. Any top-level folder NOT in this set (and not a variant of one)
# is treated as a brand collection (e.g. "google", "nasa").
KNOWN_THEMES: frozenset[str] = frozenset(
    {
        "academic",
        "business",
        "technology",
        "nature",
        "space",
        "finance",
        "medicine",
        "design",
        "startup",
        "hackathon",
        "research",
        "conference",
        "exchange",
        "volunteer",
        "general",
    }
)

GENERAL_THEME = "general"

# Category → theme folder. Unmapped / None falls back to GENERAL_THEME.
_CATEGORY_THEME: dict[Category, str] = {
    Category.Scholarship: "academic",
    Category.Fellowship: "academic",
    Category.SummerProgram: "academic",
    Category.Competition: "academic",
    Category.Olympiad: "academic",
    Category.Internship: "business",
    Category.Job: "business",
    Category.Startup: "startup",
    Category.Accelerator: "startup",
    Category.Incubator: "startup",
    Category.Hackathon: "hackathon",
    Category.Research: "research",
    Category.Conference: "conference",
    Category.Grant: "finance",
    Category.Exchange: "exchange",
    Category.Volunteer: "volunteer",
}

# Per-category palette + style tag seeds used only for scoring (tag_match_bonus).
_CATEGORY_PALETTE: dict[Category, str] = {
    Category.Hackathon: "blue",
    Category.Scholarship: "gold",
    Category.Internship: "green",
    Category.Fellowship: "purple",
    Category.Competition: "red",
    Category.Olympiad: "orange",
    Category.Grant: "green",
    Category.Conference: "blue",
    Category.Research: "teal",
    Category.Startup: "orange",
    Category.Accelerator: "orange",
    Category.Incubator: "green",
    Category.SummerProgram: "gold",
    Category.Exchange: "teal",
    Category.Volunteer: "red",
    Category.Job: "blue",
}

# Lightweight keyword → tags scan over title/description. Adds style signal without an LLM.
_KEYWORD_TAGS: dict[str, tuple[str, ...]] = {
    "ai": ("technology", "modern"),
    "artificial intelligence": ("technology", "modern"),
    "machine learning": ("technology", "modern"),
    "data": ("technology",),
    "software": ("technology",),
    "robot": ("technology",),
    "climate": ("nature", "green"),
    "environment": ("nature", "green"),
    "sustainab": ("nature", "green"),
    "space": ("space",),
    "astronom": ("space",),
    "nasa": ("space",),
    "design": ("design", "modern"),
    "art": ("design",),
    "health": ("medicine",),
    "medic": ("medicine",),
    "bio": ("medicine",),
    "finance": ("finance",),
    "fintech": ("finance", "technology"),
    "invest": ("finance",),
    "startup": ("startup", "modern"),
    "entrepreneur": ("startup",),
}


@dataclass(frozen=True)
class StyleDescriptor:
    """Render-time style hint for a single card. Deterministic; never persisted."""

    theme: str
    organizer: str | None = None
    title: str | None = None
    palette: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)


def theme_for_category(category: Category | None) -> str:
    if category is None:
        return GENERAL_THEME
    return _CATEGORY_THEME.get(category, GENERAL_THEME)


def is_theme_folder(folder: str, theme: str) -> bool:
    """True if ``folder`` is the theme itself or a ``<theme>_<variant>`` of it."""
    return folder == theme or folder.startswith(f"{theme}_")


def resolve_collection(folders: set[str], organizer: str | None, title: str | None) -> str | None:
    """Return a brand-collection folder name that matches the organizer/title, else None.

    A collection is any folder not in KNOWN_THEMES (and not a theme variant). Match is a
    case-insensitive whole-word-ish containment of the folder name in organizer or title.
    Longest folder name wins (so "stanford" beats a hypothetical "stan").
    """
    haystack = f"{organizer or ''} {title or ''}".lower()
    if not haystack.strip():
        return None

    candidates = sorted(
        (
            f
            for f in folders
            if f not in KNOWN_THEMES and not any(is_theme_folder(f, t) for t in KNOWN_THEMES)
        ),
        key=len,
        reverse=True,
    )
    for folder in candidates:
        name = folder.lower()
        if len(name) < 3:
            continue
        if name in haystack:
            return folder
    return None


def build_descriptor(opp: "Opportunity") -> StyleDescriptor:
    """Build a deterministic style descriptor from an opportunity (no LLM, no DB)."""
    category = opp.category
    theme = theme_for_category(category)
    palette = _CATEGORY_PALETTE.get(category) if category else None

    tags: set[str] = set()
    if palette:
        tags.add(palette)
    text = f"{opp.title or ''} {getattr(opp, 'description', '') or ''}".lower()
    for keyword, kw_tags in _KEYWORD_TAGS.items():
        if keyword in text:
            tags.update(kw_tags)

    return StyleDescriptor(
        theme=theme,
        organizer=opp.organizer,
        title=opp.title,
        palette=palette,
        tags=frozenset(tags),
    )
