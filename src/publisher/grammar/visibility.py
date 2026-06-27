"""Visibility Rules — decide what to show / hide (grammar.md).

Deciding *what to remove* is distinct from *how to resize*:
    - When the card is overloaded, drop the lowest-priority field.
    - Hide empty rows (no deadline → no deadline row).
    - **Invariant: never hide the Title.**

This module takes the available fields, the priority order, and the
maximum number of fields that fit, and returns the subset to render.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Maximum meta rows that fit on a card without crowding.
MAX_META_FIELDS = 4
MAX_META_FIELDS_COMPACT = 5


@dataclass(frozen=True)
class VisibilityResult:
    """Which fields should be rendered.

    Attributes:
        visible_fields: Set of field names that should be shown.
        hidden_fields: Set of field names that were dropped.
        field_order: Rendering order for visible fields (priority-sorted).
    """

    visible_fields: frozenset[str]
    hidden_fields: frozenset[str]
    field_order: tuple[str, ...]


def compute_visibility(
    available_fields: set[str],
    priority_order: tuple[str, ...],
    density: str = "comfortable",
) -> VisibilityResult:
    """Decide which fields to show based on priority and available space.

    Args:
        available_fields: Set of field names that have non-empty values.
        priority_order: Field priority from the Priority Engine (highest first).
        density: "comfortable" or "compact" (affects max fields).

    Returns:
        VisibilityResult with visible/hidden sets and render order.

    Note:
        The Title is never part of ``available_fields`` here — it is always
        visible (Core Invariant).  This function only controls meta fields.
    """
    max_fields = MAX_META_FIELDS_COMPACT if density == "compact" else MAX_META_FIELDS

    # Sort available fields by priority (highest first).
    ranked = [f for f in priority_order if f in available_fields]

    # Keep the top N fields.
    visible = frozenset(ranked[:max_fields])
    hidden = frozenset(ranked[max_fields:])

    # Render order: priority order, filtered to visible fields.
    field_order = tuple(f for f in priority_order if f in visible)

    return VisibilityResult(
        visible_fields=visible,
        hidden_fields=hidden,
        field_order=field_order,
    )


def get_available_fields(
    deadline: str | None = None,
    location: str | None = None,
    prize: str | None = None,
    organizer: str | None = None,
    duration: str | None = None,
    eligibility: str | None = None,
    apply_link: str | None = None,
) -> set[str]:
    """Return the set of field names that have non-empty values.

    This is a helper that inspects the opportunity data and returns
    the fields that *could* be shown (before visibility pruning).
    """

    def has_value(text: str | None, min_len: int = 1) -> bool:
        return text is not None and len(text.strip()) >= min_len

    fields: set[str] = set()
    if has_value(deadline):
        fields.add("deadline")
    if has_value(location):
        fields.add("location")
    if has_value(prize):
        fields.add("prize")
    if has_value(organizer):
        fields.add("organizer")
    if has_value(duration):
        fields.add("duration")
    if has_value(eligibility, min_len=5):
        fields.add("eligibility")
    if has_value(apply_link, min_len=10):
        fields.add("apply_link")
    return fields
