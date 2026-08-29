"""Guards on what image generation is allowed to cost.

Every retry is a billed image generation, so the two things that quietly
multiply the bill are the model chain escalating to a pricier model and the
retry schedule being long. Both are asserted here rather than left to config
review — an August spend of ~$10 came almost entirely from these two.

Settings has many required fields (DB url, Telethon creds, channel ids), so
these read the declared defaults off the model rather than instantiating it.
"""

import asyncio
from types import SimpleNamespace

import pytest

from src.core.config import Settings
from src.publisher.live_background import _RETRY_SCHEDULE, _model_chain


def _default(name: str):
    return Settings.model_fields[name].default


def _configured_chain() -> list[str]:
    """The chain the app actually ships with, built from declared defaults."""
    return _model_chain(
        SimpleNamespace(
            GEMINI_IMAGE_MODEL=_default("GEMINI_IMAGE_MODEL"),
            GEMINI_IMAGE_FALLBACK_MODELS=_default("GEMINI_IMAGE_FALLBACK_MODELS"),
        )
    )


def test_pro_image_model_is_not_in_the_chain():
    """gemini-3-pro-image is $0.134-$0.24/image against $0.0336 for the lite
    model — 3.4-6x — and was previously reached on every 4th retry."""
    chain = _configured_chain()

    assert not any("pro" in model for model in chain), chain


def test_chain_starts_with_the_cheapest_model():
    assert _configured_chain()[0] == "gemini-3.1-flash-lite-image"


def test_chain_still_has_a_fallback():
    """Cost control must not cost resilience: the lite model is the one piece
    of this change that is unproven in production, so a sibling has to remain
    reachable when it 503s."""
    assert len(_configured_chain()) >= 2


def test_retry_schedule_stays_short():
    """Each extra attempt is another billed generation, and the ones that used
    to fire at 25s and 45s arrived long after the free procedural fallback in
    generate_card() would have produced a usable card."""
    assert len(_RETRY_SCHEDULE) <= 3, _RETRY_SCHEDULE


def test_kill_switch_is_independent_of_the_api_key():
    """Image spend must be stoppable without also disabling vision, which
    reads the same GEMINI_API_KEY."""
    assert _default("ENABLE_LIVE_BACKGROUND") is True
    assert _default("ENABLE_IMAGE_ANALYSIS") is True


def test_disabled_flag_raises_so_the_caller_degrades(monkeypatch):
    """generate_card() catches any exception from here and falls back to the
    procedural background, so raising is how the post still ships."""
    from src.publisher import live_background

    monkeypatch.setattr(
        "src.core.config.Settings",
        lambda: SimpleNamespace(ENABLE_LIVE_BACKGROUND=False, GEMINI_API_KEY="still-set"),
    )

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_BACKGROUND"):
        asyncio.run(live_background.generate_live_background(object()))
