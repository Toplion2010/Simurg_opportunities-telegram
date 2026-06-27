"""Layout Strategy — configuration, not templates (grammar.md).

A layout is a config object, never an ``if template == N`` branch:

    Layout(
        text_anchor="left",
        image_focus="right",
        title_width=620,
        footer="bottom",
        density="comfortable",
    )

Named presets are *data*.  The engine selects a preset using the image's
``primary_safe_area`` (from metadata.json) plus the content.
Adding a layout requires no Rendering Pipeline change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.publisher.background_manager import SafeArea


@dataclass(frozen=True)
class Layout:
    """Layout strategy — a configuration object, not a rendering branch.

    Attributes:
        name: Human-readable preset name (for logging/debugging).
        text_anchor: Where the text column sits ("left", "center", "right").
        image_focus: Where the image subject should be ("left", "center", "right").
        title_width: Maximum title width in pixels.
        footer: Footer position ("bottom", "none").
        density: Content density ("comfortable", "compact").
    """

    name: str = "default"
    text_anchor: str = "left"
    image_focus: str = "right"
    title_width: int = 620
    footer: str = "bottom"
    density: str = "comfortable"


# ------------------------------------------------------------------ Presets

# Text-left / image-right — the default for most images.
LAYOUT_LEFT = Layout(
    name="text-left",
    text_anchor="left",
    image_focus="right",
    title_width=620,
    footer="bottom",
    density="comfortable",
)

# Centered — for images with safe area in the center.
LAYOUT_CENTERED = Layout(
    name="centered",
    text_anchor="center",
    image_focus="center",
    title_width=720,
    footer="bottom",
    density="comfortable",
)

# Photo-top / text-bottom — for images with subject in the top half.
LAYOUT_PHOTO_TOP = Layout(
    name="photo-top",
    text_anchor="left",
    image_focus="top",
    title_width=820,
    footer="bottom",
    density="compact",
)

# Diagonal — text bottom-left, image focus top-right.
LAYOUT_DIAGONAL = Layout(
    name="diagonal",
    text_anchor="left",
    image_focus="right",
    title_width=580,
    footer="bottom",
    density="compact",
)

# All presets registry (data, not code branches).
ALL_LAYOUTS: frozenset[Layout] = frozenset(
    {LAYOUT_LEFT, LAYOUT_CENTERED, LAYOUT_PHOTO_TOP, LAYOUT_DIAGONAL}
)

# Named lookup for convenience.
LAYOUT_BY_NAME: dict[str, Layout] = {l.name: l for l in ALL_LAYOUTS}


# ------------------------------------------------------------------ Selection


def select_layout(safe_area: "SafeArea | None", num_meta_fields: int = 0) -> Layout:
    """Pick a layout preset from the image's primary_safe_area and content.

    The safe_area rectangle tells us where the image is calm enough for text.
    If the safe area is left-biased (x < 0.2), use text-left.
    If centred (0.25 <= x <= 0.5), use centered.
    If the safe area is short (h < 0.6), use photo-top.
    If many meta fields (>4), force compact density.

    Falls back to LAYOUT_LEFT when safe_area is None.
    """
    if safe_area is None:
        return LAYOUT_LEFT

    # Short safe area → photo-top layout
    if safe_area.h < 0.6:
        return LAYOUT_PHOTO_TOP

    # Centred safe area
    if 0.25 <= safe_area.x <= 0.5 and safe_area.w >= 0.4:
        return LAYOUT_CENTERED

    # Narrow safe area → diagonal (compact)
    if safe_area.w < 0.35:
        return LAYOUT_DIAGONAL

    # Default: text-left, possibly compact for dense content
    if num_meta_fields > 4:
        return LAYOUT_DIAGONAL  # compact density

    return LAYOUT_LEFT


def get_layout_by_name(name: str) -> Layout | None:
    """Look up a layout preset by name."""
    return LAYOUT_BY_NAME.get(name)
