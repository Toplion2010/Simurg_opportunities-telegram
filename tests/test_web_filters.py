"""The admission rule: can a Kazakh student actually reach this?

The rule is reject-only-when-provably-closed, so the load-bearing tests here are
the ones asserting that UNKNOWN passes. A false admit costs one queue review; a
false reject is invisible and permanent.
"""
import pytest

from src.collector.web.base import WebItem
from src.collector.web.filters import (
    REASON_CITIZENSHIP,
    REASON_UNFUNDED_IN_PERSON,
    admits,
)


def item(**kwargs) -> WebItem:
    base = dict(
        source="test",
        external_id="x",
        title="Some Program",
        page_url="https://example.org/p/x",
    )
    base.update(kwargs)
    return WebItem(**base)


# --- limb 1: online is reachable regardless of price ----------------------


def test_online_is_admitted_even_when_expensive():
    admitted, _ = admits(item(is_online=True, cost_amount=500.0))
    assert admitted


def test_hybrid_counts_as_online_upstream():
    # The sources map MixedEventAttendanceMode -> True; this asserts the filter
    # honours that rather than second-guessing it.
    admitted, _ = admits(item(is_online=True, cost_amount=2000.0))
    assert admitted


# --- limb 3: free or a small fee -----------------------------------------


def test_in_person_free_is_admitted():
    admitted, _ = admits(item(is_online=False, cost_amount=0.0))
    assert admitted


def test_in_person_small_fee_is_admitted():
    admitted, _ = admits(item(is_online=False, cost_amount=12.5))
    assert admitted


def test_small_fee_threshold_is_inclusive():
    admitted, _ = admits(item(is_online=False, cost_amount=50.0), small_fee_usd=50.0)
    assert admitted


# --- limb 2: expensive and in person needs a funding signal ---------------


def test_in_person_expensive_without_funding_is_rejected():
    admitted, reason = admits(item(is_online=False, cost_amount=4000.0))
    assert not admitted
    assert reason == REASON_UNFUNDED_IN_PERSON


@pytest.mark.parametrize(
    "signal",
    [
        "Need-based financial aid is available.",
        "Full scholarships offered to international students.",
        "A travel grant covers airfare.",
        "Fee waiver available on request.",
        "Participants receive a stipend.",
        "Программа бесплатная для победителей отбора.",
    ],
)
def test_in_person_expensive_with_funding_is_admitted(signal):
    admitted, _ = admits(
        item(is_online=False, cost_amount=4000.0, description=signal)
    )
    assert admitted, signal


# --- the hard bar: citizenship beats every other limb ---------------------


@pytest.mark.parametrize(
    "eligibility",
    [
        "Open to U.S. citizens only.",
        "Applicants must be US citizens or permanent residents.",
        "Must be a United States citizen.",
        "Domestic students only.",
        "Restricted to American undergraduates.",
        "Students enrolled in US high schools are eligible.",
    ],
)
def test_citizenship_bar_rejects(eligibility):
    admitted, reason = admits(item(eligibility=eligibility))
    assert not admitted, eligibility
    assert reason == REASON_CITIZENSHIP


def test_citizenship_bar_beats_online_and_free():
    # No amount of "online" or "free" lifts a legal eligibility restriction —
    # this is the NSF-REU family and it is the highest-volume exclusion.
    admitted, reason = admits(
        item(
            is_online=True,
            cost_amount=0.0,
            eligibility="Open only to U.S. citizens and permanent residents.",
        )
    )
    assert not admitted
    assert reason == REASON_CITIZENSHIP


def test_kazakhstan_residency_requirement_is_not_a_bar():
    # "must be a resident of" is only a bar when it points somewhere else.
    admitted, _ = admits(
        item(is_online=False, cost_amount=0.0, eligibility="Must be a resident of Kazakhstan.")
    )
    assert admitted


# --- unknown must pass, in every shape -----------------------------------


def test_all_unknown_is_admitted():
    admitted, _ = admits(item())
    assert admitted


def test_unknown_format_with_high_price_is_admitted():
    # is_online is None, not False: we do not know it is in person, so the
    # expensive-in-person rule must not fire.
    admitted, _ = admits(item(is_online=None, cost_amount=4000.0))
    assert admitted


def test_unknown_price_in_person_is_admitted():
    # SIREL states "Paid" with no amount. Unknown is unknown, not expensive.
    admitted, _ = admits(item(is_online=False, cost_amount=None, cost_text="Paid"))
    assert admitted


# --- explicitly closed listings ------------------------------------------


@pytest.mark.parametrize(
    "deadline",
    ["Applications closed", "Closed", "applications are closed",
     "No longer accepting applications", "Deadline has passed"],
)
def test_explicitly_closed_is_rejected(deadline):
    from src.collector.web.filters import REASON_CLOSED

    admitted, reason = admits(item(is_online=True, deadline=deadline))
    assert not admitted, deadline
    assert reason == REASON_CLOSED


@pytest.mark.parametrize(
    "deadline",
    ["Rolling applications", "March 1, 2027", "Opens in January", None,
     "Closes March 2027"],
)
def test_open_or_unknown_deadlines_are_admitted(deadline):
    # A missing deadline is unknown, not closed. "Closes March 2027" is a
    # future closing date, not a statement that it already closed.
    admitted, _ = admits(item(is_online=True, deadline=deadline))
    assert admitted, deadline
