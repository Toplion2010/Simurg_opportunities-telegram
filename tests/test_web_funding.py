"""The funding limb of the admission rule.

Measured on real data before this existed: across 45 ExtracurricularHub
listings, ZERO contained any funding language, so this limb could never fire on
catalog data alone — the filter was effectively "online or free only". Of the
12 items it rejected as unaffordable, 6 of 6 checked turned out to offer a
scholarship or need-based aid on their official page.
"""
from src.collector.web.base import WebItem
from src.collector.web.filters import (
    REASON_UNFUNDED_IN_PERSON,
    admits,
    find_funding,
)
from src.collector.web.to_dto import build_dto


def item(**kw) -> WebItem:
    base = dict(source="t", external_id="x", title="Summer Institute",
                page_url="https://cat.example/p/x")
    base.update(kw)
    return WebItem(**base)


def test_catalog_record_alone_still_rejects():
    # Nothing changed for the catalog-only verdict: it is the *second look*
    # that rescues these, not a loosening of the rule.
    it = item(is_online=False, cost_amount=1395.0)
    assert admits(it) == (False, REASON_UNFUNDED_IN_PERSON)


def test_find_funding_extracts_distinct_signals():
    text = "Tuition is $1,395. Need-based financial aid and a scholarship are available."
    assert find_funding(text) == ["financial aid", "need-based", "scholarship"]


def test_find_funding_is_empty_on_silence_and_none():
    assert find_funding("Tuition is $1,395. Register by March.") == []
    assert find_funding(None) == []
    assert find_funding("") == []


def test_funding_signals_surface_to_the_admin():
    """A reviewer seeing a $18,195 programme in the queue must be told why it
    is there, and that the aid still needs verifying."""
    dto = build_dto(
        item(is_online=False, cost_amount=18195.0, cost_currency="USD"),
        funding_signals=["financial aid", "scholarship"],
    )
    assert "Financial aid available" in dto.rewards
    assert "18195 USD" in dto.extra_notes
    assert "financial aid" in dto.extra_notes and "scholarship" in dto.extra_notes
    assert "Verify" in dto.extra_notes


def test_no_signals_leaves_notes_untouched():
    dto = build_dto(item(is_online=False, cost_amount=1395.0))
    assert dto.extra_notes is None
    assert dto.rewards is None


def test_free_item_keeps_its_own_rewards_line():
    # "Free to enter" must not be overwritten by an aid line.
    dto = build_dto(item(cost_amount=0.0), funding_signals=["scholarship"])
    assert dto.rewards == "Free to enter"


def test_card_rewards_stays_within_its_cap():
    dto = build_dto(
        item(is_online=False, cost_amount=9999.0),
        funding_signals=["financial aid", "need-based", "scholarship", "fee waiver"],
    )
    assert len(dto.card_rewards) <= 90
