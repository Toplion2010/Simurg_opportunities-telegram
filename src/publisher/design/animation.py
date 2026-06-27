"""Animation tokens — hover/fade/transition/scale.

Unused by Telegram (static images) but defined now so the future Simurg
website inherits the same motion language (system.md).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnimationTokens:
    """Motion tokens for the future Simurg website."""

    # Transition timing
    transition_fast: str = "150ms ease"
    transition_normal: str = "250ms ease"
    transition_slow: str = "400ms ease"

    # Easing curves
    ease_out: str = "cubic-bezier(0.4, 0, 0.2, 1)"
    ease_in_out: str = "cubic-bezier(0.4, 0, 0.6, 1)"
    ease_bounce: str = "cubic-bezier(0.68, -0.55, 0.265, 1.55)"

    # Fade durations
    fade_in_duration: str = "300ms"
    fade_out_duration: str = "200ms"

    # Scale factors for hover/interaction
    scale_hover: float = 1.02
    scale_active: float = 0.98

    # Stagger delay for sequential reveals
    stagger_delay: str = "50ms"


DEFAULT = AnimationTokens()


def css_transition(property: str = "all", timing: str = "normal") -> str:
    """Generate a CSS transition string."""
    durations = {
        "fast": DEFAULT.transition_fast,
        "normal": DEFAULT.transition_normal,
        "slow": DEFAULT.transition_slow,
    }
    duration = durations.get(timing, DEFAULT.transition_normal)
    return f"{property} {duration}"


def css_hover_effect() -> str:
    """Generate CSS for a standard hover effect."""
    return (
        f"transition: {DEFAULT.transition_normal};\n"
        f"transform: scale({DEFAULT.scale_hover});"
    )
