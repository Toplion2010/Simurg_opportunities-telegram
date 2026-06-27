"""Grammar Engine — main entry point.

Ties Layout, Priority, Responsive, and Visibility together into a
single ``CardGrammar`` that the Rendering Pipeline consumes.

The Rendering Pipeline calls ``resolve(opp, bg_entry)`` and gets back
a frozen configuration object with everything it needs to decide
what to render and in what order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.publisher.grammar.layout import Layout, select_layout
from src.publisher.grammar.priority import resolve_priority
from src.publisher.grammar.responsive import ResponsiveConfig, compute_responsive, truncate
from src.publisher.grammar.visibility import (
    VisibilityResult,
    compute_visibility,
    get_available_fields,
)

if TYPE_CHECKING:
    from src.db.models.opportunity import Opportunity
    from src.publisher.background_manager import ImageEntry


@dataclass(frozen=True)
class MetaField:
    """A single meta row to render.

    Attributes:
        name: Field name (e.g. "deadline").
        label: Display label (e.g. "Deadline").
        value: Truncated display value.
        icon: Icon name for the design system.
    """

    name: str
    label: str
    value: str
    icon: str


@dataclass(frozen=True)
class CardGrammar:
    """Complete grammar result for one card.

    The Rendering Pipeline reads this object and renders the card.
    It is the bridge between Grammar (behavior) and Design (appearance).

    Attributes:
        layout: Selected layout strategy.
        responsive: Responsive sizing adjustments.
        visibility: Which fields are visible.
        meta_fields: Ordered list of meta rows to render.
        title: Escaped title text (always present).
        category: Category name for badge.
        hook_display: Hook badge display value, if any.
        has_hook: Whether a hook badge should be shown.
    """

    layout: Layout
    responsive: ResponsiveConfig
    visibility: VisibilityResult
    meta_fields: tuple[MetaField, ...]
    title: str
    category: str
    hook_display: str | None = None
    has_hook: bool = False


# Human-readable labels for meta fields.
_FIELD_LABELS: dict[str, str] = {
    "deadline": "Deadline",
    "location": "Location",
    "prize": "Prize",
    "organizer": "Organizer",
    "duration": "Duration",
    "eligibility": "Eligibility",
    "apply_link": "Apply",
}

# Icon names for meta fields (from design/icons.py FIELD_ICON).
_FIELD_ICONS: dict[str, str] = {
    "deadline": "calendar",
    "location": "map-pin",
    "prize": "dollar-sign",
    "organizer": "building-2",
    "duration": "clock",
    "eligibility": "briefcase",
    "apply_link": "globe",
}


def resolve(opp: "Opportunity", bg_entry: "ImageEntry | None" = None) -> CardGrammar:
    """Resolve the complete grammar for one card.

    This is the single entry point for the Rendering Pipeline.
    It runs the four Grammar layers in order:
        1. Priority — field importance for this category
        2. Layout — which preset fits the background + content
        3. Responsive — size/density adjustments for this content
        4. Visibility — what to drop when overloaded

    Args:
        opp: The opportunity to render.
        bg_entry: The selected background (for safe_area-based layout).

    Returns:
        CardGrammar: Frozen configuration for rendering.
    """
    import html as _html

    # --- 1. Priority ---
    category = opp.category.value if opp.category else None
    priority = resolve_priority(category)

    # --- Gather raw values ---
    prize = opp.rewards or opp.cost
    available = get_available_fields(
        deadline=opp.deadline,
        location=opp.location,
        prize=prize,
        organizer=opp.organizer,
        duration=opp.duration,
        eligibility=opp.eligibility,
        apply_link=opp.apply_link,
    )

    # --- 2. Layout ---
    safe_area = bg_entry.primary_safe_area if bg_entry else None
    layout = select_layout(safe_area, num_meta_fields=len(available))

    # --- 3. Responsive ---
    title_text = opp.title or "Opportunity"
    has_long = (
        (opp.location and len(opp.location) > 55)
        or (prize and len(prize) > 55)
        or (opp.organizer and len(opp.organizer) > 40)
    )
    responsive = compute_responsive(title_text, len(available), has_long)

    # Use responsive density (may override layout density)
    density = responsive.density

    # --- 4. Visibility ---
    visibility = compute_visibility(available, priority.field_order, density)

    # --- Build meta field list ---
    truncation = responsive.truncation or {}
    meta_fields: list[MetaField] = []

    for field_name in visibility.field_order:
        label = _FIELD_LABELS.get(field_name, field_name)
        icon = _FIELD_ICONS.get(field_name, "award")

        # Get raw value
        if field_name == "deadline":
            raw = opp.deadline
        elif field_name == "location":
            raw = opp.location
        elif field_name == "prize":
            raw = prize
        elif field_name == "organizer":
            raw = opp.organizer
        elif field_name == "duration":
            raw = opp.duration
        elif field_name == "eligibility":
            raw = opp.eligibility
        elif field_name == "apply_link":
            raw = opp.apply_link
        else:
            raw = None

        if raw is None:
            continue

        max_chars = truncation.get(field_name, 55)
        value = truncate(raw, max_chars)

        meta_fields.append(MetaField(name=field_name, label=label, value=value, icon=icon))

    # --- Hook badge ---
    from src.core.enums import HookLabel

    _HOOK_VALUE_TO_NAME: dict[str, str] = {label.value: label.name for label in HookLabel}
    hook_values: list[str] = opp.hooks or []
    hook_display_value = next((v for v in hook_values if _HOOK_VALUE_TO_NAME.get(v)), None)

    # --- Title (always present — Core Invariant) ---
    title_escaped = _html.escape(title_text)

    return CardGrammar(
        layout=layout,
        responsive=responsive,
        visibility=visibility,
        meta_fields=tuple(meta_fields),
        title=title_escaped,
        category=category or "",
        hook_display=hook_display_value,
        has_hook=hook_display_value is not None,
    )
