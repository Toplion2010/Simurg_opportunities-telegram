"""Spacing — margins, gaps, paddings, baseline rhythm.

All spacing values derive from a 4 px baseline grid so spacing is
harmonious across every card.  Empty space is intentional (principles.md).
"""
from __future__ import annotations

from dataclasses import dataclass

# Baseline unit (everything is a multiple of 4 px).
BASE = 4


@dataclass(frozen=True)
class SpacingTokens:
    """Spacing values for card layout."""

    # Content area insets
    content_top: int = 48
    content_left: int = 64
    content_right: int = 340  # right margin from content edge
    content_bottom: int = 68

    # Section gaps
    section_gap: int = 20  # between badges, title, divider
    meta_gap: int = 10  # between meta rows
    badge_gap: int = 10  # between category badge and hook badge

    # Meta row internal spacing
    meta_row_gap: int = 10
    meta_label_min_width: int = 88

    # Footer
    footer_height: int = 52
    footer_padding_horizontal: int = 64

    # Accent elements
    accent_bar_width: int = 8
    accent_top_height: int = 3

    # Divider
    divider_width: int = 56
    divider_height: int = 4


DEFAULT = SpacingTokens()


@dataclass(frozen=True)
class CompactSpacing(SpacingTokens):
    """Tighter spacing for compact density."""

    content_top: int = 40
    content_left: int = 48
    content_bottom: int = 60
    section_gap: int = 16
    meta_gap: int = 8
    badge_gap: int = 8
    meta_row_gap: int = 8


COMPACT = CompactSpacing()


def get_spacing(density: str = "comfortable") -> SpacingTokens:
    if density == "compact":
        return COMPACT
    return DEFAULT
