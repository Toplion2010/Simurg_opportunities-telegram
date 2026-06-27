"""Responsive Rules — adapt sizes to content length (grammar.md).

Long title → smaller font / more lines.
Short title → larger font.
Long organizer/location → truncate with ellipsis.
Minimum margins and density switches based on how much content fits.
"""
from __future__ import annotations

from dataclasses import dataclass

# Title length thresholds (characters).
TITLE_SHORT_MAX = 30
TITLE_NORMAL_MAX = 70
TITLE_LONG_MAX = 120

# Truncation limits for meta values.
META_VALUE_MAX = 55
META_ORGANIZER_MAX = 40

# Density thresholds (number of non-empty meta fields).
DENSITY_COMPACT_AT = 5


@dataclass(frozen=True)
class ResponsiveConfig:
    """Responsive adjustments for a card's content.

    Attributes:
        title_size: Override title font size (px).  None = use default scale.
        title_max_lines: Maximum clamped lines for the title.
        density: "comfortable" or "compact".
        truncation: Dict of field_name → max_chars for this render.
    """

    title_size: int | None = None
    title_max_lines: int = 3
    density: str = "comfortable"
    truncation: dict[str, int] | None = None


def compute_responsive(
    title: str | None,
    num_meta_fields: int,
    has_long_values: bool = False,
) -> ResponsiveConfig:
    """Compute responsive adjustments based on content length.

    Args:
        title: The card title text.
        num_meta_fields: Number of non-empty meta fields (deadline, location, etc.).
        has_long_values: Whether any meta values exceed their truncation limit.

    Returns:
        ResponsiveConfig with title size, line clamp, density, and truncation.
    """
    title_len = len(title or "")

    # Title sizing
    if title_len <= TITLE_SHORT_MAX:
        title_size: int | None = None  # use default (larger for short titles)
        title_max_lines = 2
    elif title_len <= TITLE_NORMAL_MAX:
        title_size = None
        title_max_lines = 3
    elif title_len <= TITLE_LONG_MAX:
        title_size = 38  # shrink for long titles
        title_max_lines = 4
    else:
        title_size = 32  # shrink further for very long titles
        title_max_lines = 4

    # Density switch
    density = "compact" if num_meta_fields >= DENSITY_COMPACT_AT or has_long_values else "comfortable"

    # Truncation limits
    truncation = {
        "location": META_VALUE_MAX,
        "prize": META_VALUE_MAX,
        "organizer": META_ORGANIZER_MAX,
        "deadline": META_VALUE_MAX,
        "eligibility": 60,
    }

    return ResponsiveConfig(
        title_size=title_size,
        title_max_lines=title_max_lines,
        density=density,
        truncation=truncation,
    )


def truncate(text: str | None, max_length: int = META_VALUE_MAX) -> str:
    """Truncate text with ellipsis if it exceeds max_length."""
    if text is None:
        return ""
    text = text.strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
