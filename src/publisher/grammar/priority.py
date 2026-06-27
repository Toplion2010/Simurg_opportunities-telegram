"""Priority Engine — category default + overrides (grammar.md).

Field importance is a base order plus per-category overrides:

    Base: Title > Deadline > Prize > Location > Organizer

Overrides:
    Conference → Location over Prize
    Scholarship → Deadline first (already the case)
    Job → Location over Prize
    Hackathon → Deadline > Location > Prize

The engine resolves ``effective_priority = category_override or base``.

The Title is **never** reordered — it is always the dominant element
(Core Invariant from ARCHITECTURE.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Field names that can appear on a card (excluding Title, which is invariant).
FIELD_DEADLINE = "deadline"
FIELD_PRIZE = "prize"
FIELD_LOCATION = "location"
FIELD_ORGANIZER = "organizer"
FIELD_DURATION = "duration"
FIELD_ELIGIBILITY = "eligibility"
FIELD_APPLY = "apply_link"

# Base priority order (highest first).  Title is implicit — always first.
BASE_PRIORITY: tuple[str, ...] = (
    FIELD_DEADLINE,
    FIELD_PRIZE,
    FIELD_LOCATION,
    FIELD_ORGANIZER,
    FIELD_DURATION,
    FIELD_ELIGIBILITY,
    FIELD_APPLY,
)


# Per-category overrides.  Categories not listed use BASE_PRIORITY.
CATEGORY_OVERRIDES: dict[str, tuple[str, ...]] = {
    # Conference: location matters more than prize
    "Conference": (
        FIELD_DEADLINE,
        FIELD_LOCATION,
        FIELD_PRIZE,
        FIELD_ORGANIZER,
        FIELD_DURATION,
        FIELD_APPLY,
    ),
    # Job: location and organizer matter more than rewards
    "Job": (
        FIELD_LOCATION,
        FIELD_ORGANIZER,
        FIELD_DEADLINE,
        FIELD_PRIZE,
        FIELD_DURATION,
        FIELD_ELIGIBILITY,
        FIELD_APPLY,
    ),
    # Hackathon: deadline is critical, then location
    "Hackathon": (
        FIELD_DEADLINE,
        FIELD_LOCATION,
        FIELD_PRIZE,
        FIELD_ORGANIZER,
        FIELD_DURATION,
        FIELD_APPLY,
    ),
    # Exchange: location first, then duration
    "Exchange": (
        FIELD_LOCATION,
        FIELD_DURATION,
        FIELD_DEADLINE,
        FIELD_PRIZE,
        FIELD_ORGANIZER,
        FIELD_APPLY,
    ),
    # Grant: deadline and prize are most important
    "Grant": (
        FIELD_DEADLINE,
        FIELD_PRIZE,
        FIELD_ELIGIBILITY,
        FIELD_ORGANIZER,
        FIELD_APPLY,
    ),
    # Internship: deadline, location, organizer
    "Internship": (
        FIELD_DEADLINE,
        FIELD_LOCATION,
        FIELD_ORGANIZER,
        FIELD_PRIZE,
        FIELD_DURATION,
        FIELD_ELIGIBILITY,
        FIELD_APPLY,
    ),
}


def get_priority_order(category: str | None) -> tuple[str, ...]:
    """Return the effective field priority for the given category.

    Title is **never** included in the returned tuple — it is always
    the dominant element (Core Invariant).  The returned order controls
    the rendering order of meta fields and what gets dropped first
    when the card is overloaded.
    """
    if category and category in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[category]
    return BASE_PRIORITY


@dataclass(frozen=True)
class PriorityResult:
    """Result of priority resolution for one card."""

    # Fields in rendering order (highest priority first, Title excluded).
    field_order: tuple[str, ...]
    # Category used for resolution.
    category: str | None


def resolve_priority(category: str | None) -> PriorityResult:
    """Resolve the effective field priority for a card."""
    order = get_priority_order(category)
    return PriorityResult(field_order=order, category=category)
