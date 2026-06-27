"""Color — palette, accent system, badge colors, scrim computation.

One accent per card (brand.md).  The accent is the only loud colour;
backgrounds stay muted under the scrim.

Smart scrim strength is derived from the background's precomputed metrics
(brightness, contrast, visual_complexity) — never computed at render time.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------- Static palette

# Text colour (always white on dark scrim — readable in Telegram dark mode).
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "rgba(255,255,255,0.85)"
TEXT_MUTED = "rgba(255,255,255,0.35)"

# Footer background
FOOTER_BG = "rgba(0,0,0,0.5)"
FOOTER_BLUR = 8  # backdrop-filter blur radius in px

# Default dark background (used for procedural fallback).
BG_DARK = "#050D1A"

# Grid overlay (procedural fallback)
GRID_COLOR = "rgba(255,255,255,0.04)"
GRID_SIZE = 52  # px


# ---------------------------------------------------------------------- Scrim


@dataclass(frozen=True)
class ScrimConfig:
    """Legibility overlay parameters.

    Derived from precomputed image metrics (ADR-004).
    Brighter / busier images get a stronger scrim automatically.
    """

    # Gradient stops: left (darkest), mid, right
    left: float
    mid: float
    right: float


DEFAULT_BRIGHTNESS = 0.5


def compute_scrim(
    brightness: float | None,
    contrast: float | None = None,
    visual_complexity: float | None = None,
) -> ScrimConfig:
    """Compute scrim strength from precomputed metrics.

    Brightness: base driver — lighter images need more overlay.
    Contrast: high-contrast images need slightly more overlay.
    Visual complexity: busy images need more overlay to suppress detail.

    All values are clamped so text remains readable in every scenario.
    """
    b = brightness if brightness is not None else DEFAULT_BRIGHTNESS
    c = contrast if contrast is not None else 0.0
    v = visual_complexity if visual_complexity is not None else 0.0

    # Base scrim from brightness (dominant factor)
    left = min(0.92, 0.62 + b * 0.30)
    mid = min(0.80, 0.40 + b * 0.30)
    right = min(0.65, 0.20 + b * 0.30)

    # Extra overlay for high-contrast or busy images
    extra = min(0.15, c * 0.10 + v * 0.10)
    left = min(0.95, left + extra)
    mid = min(0.90, mid + extra * 0.7)
    right = min(0.80, right + extra * 0.5)

    return ScrimConfig(
        left=round(left, 2),
        mid=round(mid, 2),
        right=round(right, 2),
    )


def scrim_css(scrim: ScrimConfig) -> str:
    """Return CSS for the legibility scrim gradient."""
    return (
        f"rgba(0,0,0,{scrim.left:.2f}) 0%,"
        f"rgba(0,0,0,{scrim.mid:.2f}) 45%,"
        f"rgba(0,0,0,{scrim.right:.2f}) 100%"
    )
