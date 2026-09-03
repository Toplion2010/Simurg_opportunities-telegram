"""The shared 0-100 relevance score (src/core/scoring.py): coolness (0-60,
reachability) + fit (0-40, profile match).

Used by both collector pipelines. The reachability axis is unchanged from
the 1-10 rubric this replaced — only how it's turned into points changed,
from a table lookup to a continuous tier-floor-plus-bonus. Fit is rewritten
around a specific profile (competitive programming, AI/ML, founder,
full-stack) rather than generic STEM.
"""
import pytest

from src.core.scoring import (
    R1,
    R2,
    R3,
    R4,
    coolness_score,
    fit_score,
    fit_tier,
    infer_cost_amount,
    infer_is_online,
    reachability_tier,
    score,
)

# --- reachability tiers (unchanged by this rewrite) -----------------------


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
    tier, _ = reachability_tier(
        False, 5000.0, "Boston, US", "A travel grant is available. Scholarship for tuition."
    )
    assert tier == R3


def test_kazakhstan_local_with_free_cost_is_r4():
    tier, label = reachability_tier(False, 0.0, "Almaty, Kazakhstan", "Robotics workshop")
    assert tier == R4
    assert "Kazakhstan" in label


def test_kazakhstan_local_with_partial_funding_is_r4_not_r3():
    tier, _ = reachability_tier(
        False, 5000.0, "Almaty, Kazakhstan", "Scholarship covers registration fee."
    )
    assert tier == R4


def test_kazakhstan_but_unfunded_and_expensive_is_not_automatically_r4():
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
    tier, label = reachability_tier(
        True, 0.0, None, "Open only to U.S. citizens and permanent residents."
    )
    assert tier == R1
    assert "citizenship" in label


def test_unknown_online_and_unknown_cost_defaults_to_r2_not_r4():
    tier, label = reachability_tier(None, None, None, "Robotics club")
    assert tier == R2
    assert "unknown" in label


def test_unknown_online_but_known_cheap_cost_is_r2():
    tier, _ = reachability_tier(None, 10.0, None, "Robotics club")
    assert tier == R2


def test_known_good_signal_wins_over_uncertainty():
    tier, _ = reachability_tier(None, 5000.0, "Boston, US", "Fully funded research program")
    assert tier == R4


# --- coolness_score: tier floors + within-tier bonus -----------------------


def test_coolness_r1_is_the_zero_floor():
    value, _ = coolness_score(False, 5000.0, "Boston, US", "Art camp")
    assert value == 0


def test_coolness_citizenship_bar_is_zero_even_online():
    value, label = coolness_score(True, 0.0, None, "Open only to U.S. citizens.")
    assert value == 0
    assert "citizenship" in label


def test_coolness_online_maxes_the_score():
    value, _ = coolness_score(True, None, None, "")
    assert value == 60


def test_coolness_fully_funded_maxes_the_score():
    value, _ = coolness_score(False, 5000.0, "Boston, US", "This program is fully funded.")
    assert value == 60


def test_coolness_kazakhstan_local_is_below_full_funding():
    # A local program still costs the price of a bus ticket at worst — the
    # bonus is strong but not the absolute max online/fully-funded gets.
    value, _ = coolness_score(False, 0.0, "Almaty, Kazakhstan", "Robotics workshop")
    assert value == 57
    assert value < 60


def test_coolness_partial_funding_scales_with_distinct_signal_count():
    one_signal, _ = coolness_score(False, 2500.0, "Boston, US", "A scholarship is available.")
    two_signals, _ = coolness_score(
        False, 2500.0, "Boston, US", "A scholarship and a stipend are available."
    )
    assert one_signal == 37  # floor 30 + (5 + 2*1)
    assert two_signals == 39  # floor 30 + (5 + 2*2)


def test_coolness_free_in_person_beats_a_fee_near_the_cap():
    free, _ = coolness_score(False, 0.0, "Boston, US", "Art camp", small_fee_usd=50.0)
    near_cap, _ = coolness_score(False, 45.0, "Boston, US", "Art camp", small_fee_usd=50.0)
    assert free == 25  # floor 15 + 10
    assert near_cap == 16  # floor 15 + round(10 * 0.1)
    assert free > near_cap


def test_coolness_unknown_cost_gets_a_flat_middling_bonus():
    value, _ = coolness_score(None, None, None, "Robotics club")
    assert value == 20  # floor 15 + flat 5


@pytest.mark.parametrize(
    "is_online,cost,location,text",
    [
        (True, None, None, ""),
        (False, 5000.0, "Boston, US", "Fully funded, all expenses paid."),
        (False, 2500.0, "Boston, US", "Scholarship and stipend and financial aid available."),
        (False, 0.0, "Boston, US", "Art camp"),
        (False, 5000.0, "Boston, US", "Art camp"),
        (None, None, None, ""),
    ],
)
def test_coolness_never_leaves_its_0_to_60_range(is_online, cost, location, text):
    value, _ = coolness_score(is_online, cost, location, text)
    assert 0 <= value <= 60


# --- fit tiers: profile-specific (competitive programming, AI/ML, founder,
# full-stack — NOT chess, math olympiad, or sports) -------------------------


@pytest.mark.parametrize(
    "text,tier",
    [
        ("AI hackathon for high schoolers", 4),
        ("ICPC regional qualifier", 4),
        ("Codeforces Div 2 round", 4),
        ("Startup accelerator for student founders", 4),
        ("Full-stack web development bootcamp", 3),
        ("Data science internship", 3),
        ("STEM summer program", 2),
        ("Chess tournament for youth", 1),
        ("National Math Olympiad", 1),
        ("International Mathematical Olympiad training camp", 1),
        ("Varsity swimming camp", 1),
        ("Choir and theatre camp", 1),
    ],
)
def test_fit_tiers(text, tier):
    assert fit_tier(text)[0] == tier


def test_chess_is_off_profile_even_with_a_loosely_adjacent_word_present():
    """The refinement you asked for: chess, pure math olympiads, and sports
    are real CV lines but not this profile's focus, and must not inflate the
    score just because some other, non-qualifying word shares the text."""
    tier, reason = fit_tier("Chess olympiad with computer-assisted training")
    assert tier == 1
    assert "chess" in reason


def test_bare_competition_is_not_enough_for_tier_4():
    # Only the specific CS/AI/competitive-programming terms reach tier 4 —
    # a generic "competition" alone must not.
    tier, _ = fit_tier("Regional science competition")
    assert tier != 4


def test_fit_takes_the_highest_signal_not_the_first():
    tier, label = fit_tier("Robotics Camp and AI Hackathon")
    assert tier == 4
    assert "hackathon" in label or "ai" in label


def test_fit_unmatched_defaults_to_zero_not_middling():
    # Unlike the old rubric's conservative "2 = general" default, an item
    # naming none of this profile's signals is genuinely off-profile (0),
    # not assumed to have "real content" worth a mid-tier score.
    tier, reason = fit_tier("Qqq Wwwzzz")
    assert tier == 1
    assert reason == "no profile keywords matched"


def test_research_counts_as_core_fit_only_with_a_tech_context():
    tier, _ = fit_tier("Research internship in software engineering")
    assert tier == 4

    tier, _ = fit_tier("Research program in marine biology")
    assert tier != 4


# --- fit_score: base + multi-signal bonus -----------------------------------


def test_fit_score_tier4_base_with_one_signal():
    value, reason = fit_score("Codeforces round")
    assert value == 34
    assert reason == "core: codeforces"


def test_fit_score_tier4_bonus_for_a_second_distinct_signal():
    value, reason = fit_score("AI hackathon")
    assert value == 36  # base 34 + 2*(2-1)
    assert reason == "core: ai, hackathon"


def test_fit_score_tier3_base():
    value, reason = fit_score("Data science internship")
    assert value == 22
    assert reason == "adjacent: data science"


def test_fit_score_tier2_base():
    value, reason = fit_score("STEM summer program")
    assert value == 10
    assert reason == "general: stem"


def test_fit_score_off_profile_is_zero():
    value, reason = fit_score("Chess tournament for youth")
    assert value == 0
    assert reason == "off-profile: chess"


def test_fit_score_bonus_caps_at_six():
    value, _ = fit_score(
        "AI machine learning computer vision hackathon startup founder accelerator"
    )
    assert value == 34 + 6  # bonus capped even with many distinct matches


@pytest.mark.parametrize(
    "text",
    ["", "Qqq Wwwzzz", "Chess tournament", "STEM program", "AI hackathon"],
)
def test_fit_score_never_leaves_its_0_to_40_range(text):
    value, _ = fit_score(text)
    assert 0 <= value <= 40


# --- infer_is_online / infer_cost_amount (unchanged by this rewrite) ------


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
    assert infer_cost_amount("Completely free of charge to all applicants") == 0.0


def test_infer_cost_amount_ignores_non_usd_currency():
    assert infer_cost_amount("5000 KZT") is None
    assert infer_cost_amount("5000 rub") is None
    assert infer_cost_amount("100 EUR") is None
    assert infer_cost_amount("$50") == 50.0
    assert infer_cost_amount("50 USD") == 50.0


# --- end to end: score() ----------------------------------------------


def test_score_combines_coolness_and_fit():
    value, reason = score(True, None, None, "AI hackathon")
    assert value == 60 + 36
    assert "cool 60/60" in reason
    assert "fit 36/40" in reason


def test_score_is_always_in_the_0_to_100_range():
    cases = [
        (True, None, None, "art camp"),
        (False, 5000.0, "Boston", "Qqq"),
        (None, None, None, ""),
        (False, 0.0, "Almaty, Kazakhstan", "robotics"),
    ]
    for is_online, cost, location, text in cases:
        value, _ = score(is_online, cost, location, text)
        assert 0 <= value <= 100


def test_score_handles_none_text():
    value, reason = score(True, None, None, None)
    assert 0 <= value <= 100
    assert reason


def test_kazakhstan_local_priced_in_tenge_still_gets_the_local_override():
    value, reason = score(False, infer_cost_amount("5000 KZT"), "Almaty, Kazakhstan", "Art Workshop")
    assert "Kazakhstan" in reason
    assert value >= 57  # coolness alone is already >= the R4 floor + KZ bonus


def test_score_reason_never_exceeds_the_relevance_reason_column_limit():
    # Opportunity.relevance_reason is a String(120) column, and the Telegram
    # path assigns it post-construction, bypassing pydantic's own truncating
    # validator — the cap has to live in scoring.py itself.
    text = (
        "AI machine learning computer vision hackathon startup founder "
        "accelerator incubator entrepreneurship. Fully funded, all expenses "
        "paid, scholarship, stipend, financial aid, need-based aid, bursary."
    )
    _, reason = score(False, 5000.0, "Boston, US", text)
    assert len(reason) <= 120
