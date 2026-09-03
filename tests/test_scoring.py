"""The shared 1-10 relevance rubric (src/core/scoring.py).

Used by both collector pipelines. The reachability axis is new: previously
only web items had any accessibility signal at all (via the separate
admits() gate), and it never touched the score. Fit is now keyword-derived
for both sources, replacing the Groq-judged 1-5 that used to exist only for
Telegram items.
"""
import pytest

from src.core.scoring import (
    R1,
    R2,
    R3,
    R4,
    _SCORE_TABLE,
    fit_tier,
    infer_cost_amount,
    infer_is_online,
    reachability_tier,
    score,
)

# --- the table itself: every one of the 16 cells, individually -----------


@pytest.mark.parametrize(
    "reach,fit,expected",
    [
        (R4, 4, 10), (R4, 3, 9), (R4, 2, 7), (R4, 1, 6),
        (R3, 4, 8),  (R3, 3, 6), (R3, 2, 5), (R3, 1, 3),
        (R2, 4, 5),  (R2, 3, 4), (R2, 2, 3), (R2, 1, 2),
        (R1, 4, 3),  (R1, 3, 2), (R1, 2, 2), (R1, 1, 1),
    ],
)
def test_table_cell(reach, fit, expected):
    # Guards the table itself: a future edit to _SCORE_TABLE is now a visible,
    # deliberate diff against every one of these sixteen lines, not a silent
    # change to a formula.
    assert _SCORE_TABLE[(reach, fit)] == expected


def test_table_uses_every_value_one_through_ten():
    assert set(_SCORE_TABLE.values()) == set(range(1, 11))


def test_table_is_monotonic_in_both_axes():
    for fit in (1, 2, 3, 4):
        values = [_SCORE_TABLE[(r, fit)] for r in (R1, R2, R3, R4)]
        assert values == sorted(values), f"fit={fit} not monotonic in reach: {values}"
    for reach in (R1, R2, R3, R4):
        values = [_SCORE_TABLE[(reach, f)] for f in (1, 2, 3, 4)]
        assert values == sorted(values), f"reach={reach} not monotonic in fit: {values}"


# --- reachability tiers ----------------------------------------------------


def test_online_is_r4_regardless_of_price():
    tier, _ = reachability_tier(True, 9999.0, None, "")
    assert tier == R4


def test_fully_funded_phrase_is_r4():
    tier, label = reachability_tier(False, 5000.0, "Boston, US", "This program is fully funded.")
    assert tier == R4
    assert "fully funded" in label


def test_travel_and_lodging_both_covered_is_r4_even_without_the_magic_phrase():
    tier, _ = reachability_tier(
        False, 5000.0, "Boston, US",
        "Selected participants receive travel reimbursement and accommodation is provided.",
    )
    assert tier == R4


def test_travel_alone_without_lodging_is_not_full_funding():
    # Only ONE of the two costs covered — real partial funding, not full.
    tier, _ = reachability_tier(
        False, 5000.0, "Boston, US", "A travel grant is available. Scholarship for tuition."
    )
    assert tier == R3


def test_kazakhstan_local_with_free_cost_is_r4():
    tier, label = reachability_tier(False, 0.0, "Almaty, Kazakhstan", "Robotics workshop")
    assert tier == R4
    assert "Kazakhstan" in label


def test_kazakhstan_local_with_partial_funding_is_r4_not_r3():
    """The refinement you asked for: partial funding (tuition only, no
    flight) is R3 anywhere else, but in Kazakhstan there is no flight to fund
    in the first place, so it should read the same as full funding."""
    tier, _ = reachability_tier(
        False, 5000.0, "Almaty, Kazakhstan", "Scholarship covers registration fee."
    )
    assert tier == R4


def test_kazakhstan_but_unfunded_and_expensive_is_not_automatically_r4():
    # Local removes the FLIGHT problem, not the whole price tag — an
    # expensive, unfunded local program is still not the best tier.
    tier, _ = reachability_tier(False, 5000.0, "Almaty, Kazakhstan", "Robotics workshop")
    assert tier != R4


def test_partial_funding_not_local_is_r3():
    tier, label = reachability_tier(
        False, 2500.0, "Boston, US", "Need-based financial aid available."
    )
    assert tier == R3
    assert "partial" in label


def test_free_in_person_no_funding_language_is_r2():
    tier, _ = reachability_tier(False, 0.0, "Boston, US", "Art camp")
    assert tier == R2


def test_small_fee_in_person_no_funding_is_r2():
    tier, _ = reachability_tier(False, 30.0, "Boston, US", "Art camp", small_fee_usd=50.0)
    assert tier == R2


def test_unfunded_expensive_in_person_is_r1():
    tier, _ = reachability_tier(False, 5000.0, "Boston, US", "Art camp")
    assert tier == R1


def test_citizenship_bar_clamps_to_r1_even_online_and_free():
    """No amount of online-ness or price lifts a legal eligibility
    restriction — the same posture collector/web/filters.admits() takes, but
    this is the first time it means anything for a Telegram-sourced item,
    which has no separate reject gate at all."""
    tier, label = reachability_tier(
        True, 0.0, None, "Open only to U.S. citizens and permanent residents."
    )
    assert tier == R1
    assert "citizenship" in label


def test_unknown_online_and_unknown_cost_defaults_to_r2_not_r4():
    # Unknown must not be scored as though it were confirmed online — that
    # charity belongs to the admission GATE (worth a look), not the score
    # (how good is it, really).
    tier, label = reachability_tier(None, None, None, "Robotics club")
    assert tier == R2
    assert "unknown" in label


def test_unknown_online_but_known_cheap_cost_is_r2():
    tier, _ = reachability_tier(None, 10.0, None, "Robotics club")
    assert tier == R2


def test_known_good_signal_wins_over_uncertainty():
    # is_online is unknown, but online-ness doesn't matter here because the
    # item is confirmed fully funded — a real signal always beats "unknown".
    tier, _ = reachability_tier(None, 5000.0, "Boston, US", "Fully funded research program")
    assert tier == R4


# --- fit tiers -------------------------------------------------------------


@pytest.mark.parametrize(
    "text,tier",
    [
        ("Computer science hackathon", 4),
        ("Robotics and mathematics olympiad", 4),
        ("Mechanical engineering internship", 3),
        ("Biology research program", 2),
        ("Choir and theatre camp", 1),
    ],
)
def test_fit_tiers(text, tier):
    assert fit_tier(text)[0] == tier


def test_fit_takes_the_highest_signal_not_the_first():
    # A robotics camp that also does art is a robotics opportunity.
    tier, label = fit_tier("Robotics and Art Summer Camp")
    assert tier == 4
    assert "robotic" in label


def test_fit_unmatched_defaults_conservative_not_off_profile():
    tier, reason = fit_tier("Qqq Wwwzzz")
    assert tier == 2
    assert reason == "no profile keywords matched"


def test_mathcounts_matches_as_a_prefix():
    # \bmath\b would miss real program names; regression for the fix that
    # shipped alongside the web-item repair script.
    assert fit_tier("Mathcounts")[0] == 4


def test_mathew_is_not_math():
    assert fit_tier("Mathew Scholars Fund")[0] != 4


# --- infer_is_online / infer_cost_amount (Telegram-side derivation) -------


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Online", True), ("Remote", True), ("Hybrid", True),
        ("Worldwide", True), ("Boston, MA", False), ("Almaty, Kazakhstan", False),
        (None, None), ("", None), ("   ", None),
    ],
)
def test_infer_is_online(location, expected):
    assert infer_is_online(location) is expected


@pytest.mark.parametrize(
    "cost_text,expected",
    [
        ("Free", 0.0), ("free of charge", 0.0), ("$50", 50.0),
        ("$1,200 per session", 1200.0), ("Paid", None), (None, None), ("", None),
    ],
)
def test_infer_cost_amount(cost_text, expected):
    assert infer_cost_amount(cost_text) == expected


def test_infer_cost_amount_free_of_charge_is_not_matched_as_a_fee():
    # "free of charge" contains "free" — must resolve to 0.0, not fall through
    # to a stray digit search.
    assert infer_cost_amount("Completely free of charge to all applicants") == 0.0


# --- end to end: score() ----------------------------------------------


def test_score_returns_a_table_value():
    value, reason = score(True, None, None, "AI robotics hackathon")
    assert value == 10
    assert "online" in reason
    assert "ai" in reason or "robotic" in reason


def test_score_is_always_in_range():
    cases = [
        (True, None, None, "art camp"),
        (False, 5000.0, "Boston", "Qqq"),
        (None, None, None, ""),
        (False, 0.0, "Almaty, Kazakhstan", "robotics"),
    ]
    for is_online, cost, location, text in cases:
        value, _ = score(is_online, cost, location, text)
        assert 1 <= value <= 10


def test_score_handles_none_text():
    value, reason = score(True, None, None, None)
    assert 1 <= value <= 10
    assert reason


def test_infer_cost_amount_ignores_non_usd_currency():
    """A number next to a non-USD marker must not be trusted as dollars — a
    currency-blind parse of "5000 KZT" (roughly $10) as $5000 would misjudge
    a cheap, reachable, Kazakhstan-local item as unaffordable. Discovered
    live: exactly the population the KZ-local override exists for."""
    assert infer_cost_amount("5000 KZT") is None
    assert infer_cost_amount("5000 rub") is None
    assert infer_cost_amount("100 EUR") is None
    assert infer_cost_amount("$50") == 50.0
    assert infer_cost_amount("50 USD") == 50.0


def test_kazakhstan_local_priced_in_tenge_still_gets_the_local_override():
    value, reason = score(False, infer_cost_amount("5000 KZT"), "Almaty, Kazakhstan", "Art Workshop")
    assert "Kazakhstan" in reason
    assert value >= 6
