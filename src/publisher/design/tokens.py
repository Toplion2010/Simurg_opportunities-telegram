"""Design tokens — the single source of visual values.

Every other design module imports from here. The Rendering Pipeline reads
these tokens but never mutates them (invariant from system.md).

Tokens are organised by concern:
    - Card dimensions
    - Category accent colours
    - Hook accent overrides
    - Brand footer
    - Scrim defaults
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------- Card dimensions

CARD_WIDTH = 1200
CARD_HEIGHT = 628

# ---------------------------------------------------------------------- Category accents

# Category name → (accent_hex, glow_hex)
# The accent is the *only* loud colour on the card (brand.md).
CATEGORY_ACCENTS: dict[str, tuple[str, str]] = {
    "Hackathon": ("#00D4FF", "#00D4FF"),
    "Scholarship": ("#FFD700", "#FFD700"),
    "Internship": ("#00E676", "#00E676"),
    "Fellowship": ("#B388FF", "#B388FF"),
    "Competition": ("#FF4081", "#FF4081"),
    "Olympiad": ("#FF9F43", "#FF9F43"),
    "Grant": ("#69F0AE", "#69F0AE"),
    "Conference": ("#4FC3F7", "#4FC3F7"),
    "Research": ("#80DEEA", "#80DEEA"),
    "Startup": ("#FF6B35", "#FF6B35"),
    "Accelerator": ("#FFA000", "#FFA000"),
    "Incubator": ("#A5D6A7", "#A5D6A7"),
    "SummerProgram": ("#FFE082", "#FFE082"),
    "Exchange": ("#80CBC4", "#80CBC4"),
    "Volunteer": ("#EF9A9A", "#EF9A9A"),
    "Job": ("#90CAF9", "#90CAF9"),
}

DEFAULT_ACCENT = "#00D4FF"
DEFAULT_GLOW = "#00D4FF"

# ---------------------------------------------------------------------- Hook accent overrides

# Hook name (enum name) → accent override
HOOK_ACCENT_OVERRIDES: dict[str, str] = {
    "premium": "#FFD700",
    "early_access": "#FF6B35",
    "limited_spots": "#B388FF",
    "paid": "#69F0AE",
    "highly_recommended": "#FF4081",
    "exclusive": "#E040FB",
    "closing_soon": "#FF5252",
    "worldwide": "#40C4FF",
}

# ---------------------------------------------------------------------- Brand footer

FOOTER_BRAND_TEXT = "SIMURG OPPORTUNITIES"
FOOTER_URL_TEXT = "t.me/simurg_opportunities"

# ---------------------------------------------------------------------- Scrim defaults

# Fallback brightness when metadata is missing.
DEFAULT_BRIGHTNESS = 0.5

# ---------------------------------------------------------------------- Aggregated token set


@dataclass(frozen=True)
class CardTokens:
    """Immutable token snapshot for a single card render.

    Built from the global defaults + category/hook overrides.
    The Rendering Pipeline receives this object and reads from it;
    it never modifies the global TOKENS dict.
    """

    accent: str
    glow: str
    width: int = CARD_WIDTH
    height: int = CARD_HEIGHT
    footer_brand: str = FOOTER_BRAND_TEXT
    footer_url: str = FOOTER_URL_TEXT


def resolve_tokens(
    category: str | None,
    hook_names: list[str] | None = None,
) -> CardTokens:
    """Build an immutable token snapshot for one card.

    Category determines the base accent.  Hook overrides can replace it.
    """
    if category and category in CATEGORY_ACCENTS:
        accent, glow = CATEGORY_ACCENTS[category]
    else:
        accent, glow = DEFAULT_ACCENT, DEFAULT_GLOW

    # Hook override (first matching hook wins)
    for hook_name in hook_names or []:
        if hook_name in HOOK_ACCENT_OVERRIDES:
            accent = HOOK_ACCENT_OVERRIDES[hook_name]
            glow = accent
            break

    return CardTokens(accent=accent, glow=glow)
