"""Typography — font sets, type scale, weights, line-heights.

Chosen by Style + Brand + Density (system.md).  Each style has a fallback
chain so a missing bundled font degrades gracefully.

Fonts are bundled under ``assets/fonts/{editorial,minimal,corporate}/``
and embedded via ``@font-face`` base64 data-URIs (offline, no CDN).
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------- Font stacks

# Style → CSS font-family rule (fallback chain).
# Space Grotesk files live in assets/fonts/editorial/
FONT_STACKS: dict[str, str] = {
    "editorial": '"Space Grotesk", "Inter", system-ui, sans-serif',
    "corporate": '"Inter", system-ui, sans-serif',
    "minimal": '"Manrope", "Inter", system-ui, sans-serif',
}

# Default style used when no style is specified.
DEFAULT_STYLE = "editorial"


def font_stack(style: str = DEFAULT_STYLE) -> str:
    return FONT_STACKS.get(style, FONT_STACKS[DEFAULT_STYLE])


# ---------------------------------------------------------------------- Type scale

# Named sizes for card elements.  Values are in pixels (integer for CSS).


@dataclass(frozen=True)
class TypeScale:
    """Type scale tokens — sizes, weights, line-heights."""

    # Title (dominant element — brand.md)
    title_size: int = 48
    title_weight: int = 900
    title_line_height: float = 1.1
    title_letter_spacing: str = "-1px"
    title_max_lines: int = 3

    # Category badge
    badge_size: int = 12
    badge_weight: int = 800
    badge_letter_spacing: str = "2px"

    # Hook badge
    hook_size: int = 12
    hook_weight: int = 700
    hook_letter_spacing: str = "0.5px"

    # Summary (optional description line, between the title divider and meta rows)
    summary_size: int = 22
    summary_weight: int = 500
    summary_line_height: float = 1.4

    # Meta rows
    meta_label_size: int = 18
    meta_label_weight: int = 700
    meta_label_letter_spacing: str = "0.3px"

    meta_value_size: int = 19
    meta_value_weight: int = 400

    meta_row_size: int = 20
    meta_icon_size: int = 18

    # Footer
    footer_brand_size: int = 14
    footer_brand_weight: int = 800
    footer_brand_letter_spacing: str = "2.5px"

    footer_url_size: int = 13
    footer_url_letter_spacing: str = "0.3px"


# Default type scale — comfortable density.
DEFAULT = TypeScale()


@dataclass(frozen=True)
class CompactTypeScale(TypeScale):
    """Reduced sizes for compact density (more content on card)."""

    title_size: int = 38
    badge_size: int = 11
    summary_size: int = 19
    meta_label_size: int = 16
    meta_value_size: int = 17
    meta_row_size: int = 18
    meta_icon_size: int = 16


COMPACT = CompactTypeScale()


def get_scale(density: str = "comfortable") -> TypeScale:
    """Return the type scale for the given density."""
    if density == "compact":
        return COMPACT
    return DEFAULT


# ---------------------------------------------------------------------- Font embedding


def embed_fonts_base64(fonts_dir: str, style: str = DEFAULT_STYLE) -> str:
    """Return @font-face CSS rules for bundled fonts as base64 data-URIs.

    Scans ``assets/fonts/<style>/`` for ``.woff2`` / ``.ttf`` files and
    generates ``@font-face`` rules with inline base64 data.

    Returns empty string if fonts are not found (graceful degradation
    to system fallbacks).
    """
    import base64
    import mimetypes
    from pathlib import Path

    font_dir = Path(fonts_dir) / style
    if not font_dir.is_dir():
        return ""

    css_rules: list[str] = []
    for font_file in sorted(font_dir.glob("*.*")):
        if font_file.suffix.lower() not in (".woff2", ".woff", ".ttf", ".otf"):
            continue

        mime = mimetypes.guess_type(font_file.name)[0]
        if mime is None:
            mime = "font/woff2"

        data = base64.b64encode(font_file.read_bytes()).decode("ascii")
        family = font_file.stem.replace("-", " ").replace("_", " ").title()

        css_rules.append(
            f"@font-face {{\n"
            f"  font-family: '{family}';\n"
            f"  src: url('data:{mime};base64,{data}') format('{font_file.suffix[1:]}');\n"
            f"  font-weight: 400 900;\n"
            f"  font-style: normal;\n"
            f"  font-display: swap;\n"
            f"}}"
        )

    return "\n\n".join(css_rules)
