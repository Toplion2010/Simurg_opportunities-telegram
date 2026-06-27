"""Icons — Lucide inline SVG, accent-tinted.

Replace emoji metadata icons with crisp SVG icons.  Consistent stroke
weight, on-brand, tinted to the card's accent colour (system.md).

All icons are 24×24 viewBox, returned as self-contained inline SVG strings
with fill/stroke set to the accent colour.
"""
from __future__ import annotations

# Icon name → raw SVG path data (24×24 viewBox, stroke-based).
# From Lucide icon set (https://lucide.dev).
_ICON_PATHS: dict[str, dict[str, str]] = {
    "calendar": {
        "paths": (
            '<rect x="3" y="4" width="18" height="18" rx="2" ry="2" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<line x1="16" y1="2" x2="16" y2="6" stroke="COLOR" stroke-width="2"/>'
            '<line x1="8" y1="2" x2="8" y2="6" stroke="COLOR" stroke-width="2"/>'
            '<line x1="3" y1="10" x2="21" y2="10" stroke="COLOR" stroke-width="2"/>'
        )
    },
    "map-pin": {
        "paths": (
            '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<circle cx="12" cy="10" r="3" fill="none" stroke="COLOR" stroke-width="2"/>'
        )
    },
    "award": {
        "paths": (
            '<circle cx="12" cy="8" r="7" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88" fill="none" stroke="COLOR" stroke-width="2"/>'
        )
    },
    "building-2": {
        "paths": (
            '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<path d="M10 6h4" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<path d="M10 10h4" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<path d="M10 14h4" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<path d="M10 18h4" fill="none" stroke="COLOR" stroke-width="2"/>'
        )
    },
    "briefcase": {
        "paths": (
            '<rect x="2" y="7" width="20" height="14" rx="2" ry="2" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" fill="none" stroke="COLOR" stroke-width="2"/>'
        )
    },
    "globe": {
        "paths": (
            '<circle cx="12" cy="12" r="10" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<line x1="2" y1="12" x2="22" y2="12" stroke="COLOR" stroke-width="2"/>'
            '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" fill="none" stroke="COLOR" stroke-width="2"/>'
        )
    },
    "dollar-sign": {
        "paths": (
            '<line x1="12" y1="1" x2="12" y2="23" stroke="COLOR" stroke-width="2"/>'
            '<path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" fill="none" stroke="COLOR" stroke-width="2"/>'
        )
    },
    "clock": {
        "paths": (
            '<circle cx="12" cy="12" r="10" fill="none" stroke="COLOR" stroke-width="2"/>'
            '<polyline points="12 6 12 12 16 14" fill="none" stroke="COLOR" stroke-width="2"/>'
        )
    },
}

# Field → icon name mapping (used for meta rows).
FIELD_ICON: dict[str, str] = {
    "deadline": "calendar",
    "location": "map-pin",
    "prize": "dollar-sign",
    "organizer": "building-2",
    "duration": "clock",
}

DEFAULT_ICON_SIZE = 18  # px


def icon_svg(name: str, accent: str, size: int = DEFAULT_ICON_SIZE) -> str:
    """Return an inline SVG string for the named Lucide icon, tinted to ``accent``.

    The SVG is self-contained (no external CSS) and safe for inline HTML.
    Falls back to an empty string for unknown icon names.
    """
    icon = _ICON_PATHS.get(name)
    if icon is None:
        return ""

    paths = icon["paths"].replace("COLOR", accent)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{accent}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{paths}</svg>'
    )


def get_available_icons() -> list[str]:
    """Return sorted list of available icon names."""
    return sorted(_ICON_PATHS.keys())
