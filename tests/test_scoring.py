"""The shared 0-100 relevance score (src/core/scoring.py): six axes --
affordability (0-25), attendance-ability (0-25), selectivity (0-5),
prestige/brand (0-20), topic fit (0-15), output value (0-10).

v3 of this scorer: v2 combined coolness (0-40) + fit (0-40) + prestige
(0-20); this version splits coolness's conflated "affordable" and
"attendable" ideas into their own axes, and splits prestige's bundled
selectivity/brand/prize signals into three. Used by both collector
pipelines.
"""
import pytest

from src.core.scoring import (
    affordability_score,
    attendance_ability_score,
    fit_tier,
    infer_cost_amount,
    infer_is_online,
    output_value_score,
    prestige_score,
    score,
    selectivity_score,
    topic_fit_score,
)

# --- affordability_score: cost/funding language, independent of format/location


def test_affordability_fully_funded_maxes_the_score():
    value, label = affordability_score(5000.0, "This program is fully funded.")
    assert value == 25
    assert "fully funded" in label


def test_affordability_travel_and_lodging_both_covered_is_fully_funded():
    value, _ = affordability_score(
        5000.0, "Selected participants receive travel reimbursement and accommodation is provided."
    )
    assert value == 25


def test_affordability_travel_alone_without_lodging_is_only_partial():
    value, _ = affordability_score(5000.0, "A travel grant is available. Scholarship for tuition.")
    assert value < 25


def test_affordability_partial_funding_scales_with_distinct_signal_count():
    one_signal, _ = affordability_score(2500.0, "A scholarship is available.")
    two_signals, _ = affordability_score(2500.0, "A scholarship and a stipend are available.")
    assert one_signal == 17  # base 15 + 2*1
    assert two_signals == 19  # base 15 + 2*2
    assert two_signals > one_signal


def test_affordability_free_beats_a_fee_near_the_cap():
    free, _ = affordability_score(0.0, "Art camp", small_fee_usd=50.0)
    near_cap, _ = affordability_score(45.0, "Art camp", small_fee_usd=50.0)
    assert free == 20
    assert near_cap == 11  # round(10 + 10*0.1)
    assert free > near_cap


def test_affordability_unfunded_expensive_is_zero():
    value, label = affordability_score(5000.0, "Art camp")
    assert value == 0
    assert "no funding" in label


def test_affordability_unknown_cost_gets_a_flat_middling_value():
    value, _ = affordability_score(None, "Robotics club")
    assert value == 8


def test_affordability_citizenship_bar_clamps_to_zero():
    value, label = affordability_score(0.0, "Open only to U.S. citizens.")
    assert value == 0
    assert "citizenship" in label


@pytest.mark.parametrize(
    "cost,text",
    [
        (None, ""),
        (5000.0, "Fully funded, all expenses paid."),
        (2500.0, "Scholarship and stipend and financial aid available."),
        (0.0, "Art camp"),
        (5000.0, "Art camp"),
    ],
)
def test_affordability_never_leaves_its_0_to_25_range(cost, text):
    value, _ = affordability_score(cost, text)
    assert 0 <= value <= 25


# --- attendance_ability_score: online/local/travel-required ----------------


def test_attendance_online_is_the_max_regardless_of_location():
    value, label = attendance_ability_score(True, "Boston, US", "")
    assert value == 25
    assert "online" in label


def test_attendance_kazakhstan_local_is_below_online_but_still_strong():
    value, label = attendance_ability_score(False, "Almaty, Kazakhstan", "Robotics workshop")
    assert value == 22
    assert "Kazakhstan" in label
    assert value < 25


def test_attendance_unknown_format_and_not_local_is_a_flat_middling_value():
    value, label = attendance_ability_score(None, "Boston, US", "Robotics club")
    assert value == 10
    assert "unknown" in label


def test_attendance_in_person_abroad_is_zero_even_if_fully_funded():
    # Deliberate: funding is affordability_score()'s job, not this axis's --
    # a fully-funded program still requires the same international flight.
    value, label = attendance_ability_score(
        False, "Boston, US", "This program is fully funded, all expenses paid."
    )
    assert value == 0
    assert "international travel" in label


def test_attendance_citizenship_bar_clamps_to_zero_even_online():
    value, label = attendance_ability_score(True, None, "Open only to U.S. citizens.")
    assert value == 0
    assert "citizenship" in label


@pytest.mark.parametrize(
    "is_online,location,text",
    [
        (True, None, ""),
        (False, "Almaty, Kazakhstan", "Robotics workshop"),
        (None, "Boston, US", "Robotics club"),
        (False, "Boston, US", "Art camp"),
        (False, None, "Open only to U.S. citizens."),
    ],
)
def test_attendance_never_leaves_its_0_to_25_range(is_online, location, text):
    value, _ = attendance_ability_score(is_online, location, text)
    assert 0 <= value <= 25


# --- selectivity_score: numeric claim > institution floor > vague language --


def test_selectivity_numeric_claim_maxes_the_score():
    value, reason = selectivity_score("Only 20 spots available this year.")
    assert value == 5
    assert "20 spots" in reason


def test_selectivity_flagship_institution_with_no_number_is_a_floor():
    value, reason = selectivity_score("MIT summer research program")
    assert value == 3
    assert "floor" in reason


def test_selectivity_numeric_claim_beats_institution_floor():
    value, _ = selectivity_score("MIT summer program, only 20 spots available.")
    assert value == 5


def test_selectivity_vague_language_with_no_institution_is_weakest():
    value, reason = selectivity_score("Admission is highly selective.")
    assert value == 2
    assert "highly selective" in reason


def test_selectivity_no_signal_is_zero():
    value, reason = selectivity_score("Open enrollment webinar, no cap on registrations.")
    assert value == 0
    assert reason == "no selectivity signal"


def test_selectivity_handles_none_text():
    value, reason = selectivity_score(None)
    assert value == 0
    assert reason


@pytest.mark.parametrize(
    "text",
    ["", "MIT, 15% acceptance, highly selective", "Riverside Community College", "Open enrollment"],
)
def test_selectivity_never_leaves_its_0_to_5_range(text):
    value, _ = selectivity_score(text)
    assert 0 <= value <= 5


# --- prestige_score: brand recognition only, decoupled from selectivity ----


def test_prestige_flagship_institution_alone():
    value, reason = prestige_score("MIT summer research program")
    assert 16 <= value <= 20
    assert "mit" in reason.lower()


def test_prestige_flagship_bonus_for_additional_distinct_institutions():
    one, _ = prestige_score("MIT summer program")
    two, _ = prestige_score("MIT and Stanford host this summer program")
    assert one == 16
    assert two == 18  # base 16 + 2*(2-1)


def test_prestige_flagship_caps_at_twenty():
    value, _ = prestige_score("MIT, Stanford, Harvard, Caltech, Princeton, Yale all co-host this.")
    assert value == 20


def test_prestige_does_not_score_selectivity_numbers():
    # A number alone, with no institution/org name, must not earn any
    # prestige points -- that's selectivity_score()'s job now.
    value, reason = prestige_score("Only 20 spots available, 15% acceptance rate.")
    assert value == 0


def test_prestige_notable_non_flagship_org_name():
    value, reason = prestige_score("Hosted by Riverside Community College.")
    assert value == 8
    assert "college" in reason.lower()


def test_prestige_generic_has_no_brand_signal():
    value, reason = prestige_score("Open enrollment webinar, no cap on registrations.")
    assert value == 0
    assert reason == "no institution/brand signal"


def test_prestige_handles_none_text():
    value, reason = prestige_score(None)
    assert value == 0
    assert reason


@pytest.mark.parametrize(
    "text",
    ["", "MIT and Stanford", "Riverside Community College hosts a webinar", "Open enrollment"],
)
def test_prestige_never_leaves_its_0_to_20_range(text):
    value, _ = prestige_score(text)
    assert 0 <= value <= 20


# --- topic_fit_score: profile-specific (competitive programming, AI/ML,
# founder, full-stack — NOT chess, math olympiad, or sports) ----------------


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
    tier, reason = fit_tier("Chess olympiad with computer-assisted training")
    assert tier == 1
    assert "chess" in reason


def test_bare_competition_is_not_enough_for_tier_4():
    tier, _ = fit_tier("Regional science competition")
    assert tier != 4


def test_fit_takes_the_highest_signal_not_the_first():
    tier, label = fit_tier("Robotics Camp and AI Hackathon")
    assert tier == 4
    assert "hackathon" in label or "ai" in label


def test_fit_unmatched_defaults_to_zero_not_middling():
    tier, reason = fit_tier("Qqq Wwwzzz")
    assert tier == 1
    assert reason == "no profile keywords matched"


def test_research_counts_as_core_fit_only_with_a_tech_context():
    tier, _ = fit_tier("Research internship in software engineering")
    assert tier == 4

    tier, _ = fit_tier("Research program in marine biology")
    assert tier != 4


def test_topic_fit_score_tier4_base_with_one_signal():
    value, reason = topic_fit_score("Codeforces round")
    assert value == 13
    assert reason == "core: codeforces"


def test_topic_fit_score_tier4_bonus_for_a_second_distinct_signal():
    value, reason = topic_fit_score("AI hackathon")
    assert value == 15  # base 13 + 2*(2-1), capped at 15
    assert reason == "core: ai, hackathon"


def test_topic_fit_score_tier3_base():
    value, reason = topic_fit_score("Data science internship")
    assert value == 8
    assert reason == "adjacent: data science"


def test_topic_fit_score_tier2_base():
    value, reason = topic_fit_score("STEM summer program")
    assert value == 4
    assert reason == "general: stem"


def test_topic_fit_score_off_profile_is_zero():
    value, reason = topic_fit_score("Chess tournament for youth")
    assert value == 0
    assert reason == "off-profile: chess"


def test_topic_fit_score_bonus_caps_at_two():
    value, _ = topic_fit_score(
        "AI machine learning computer vision hackathon startup founder accelerator"
    )
    assert value == 13 + 2  # bonus capped even with many distinct matches


@pytest.mark.parametrize(
    "text",
    ["", "Qqq Wwwzzz", "Chess tournament", "STEM program", "AI hackathon"],
)
def test_topic_fit_score_never_leaves_its_0_to_15_range(text):
    value, _ = topic_fit_score(text)
    assert 0 <= value <= 15


# --- output_value_score: prize/scholarship-amount or publication language --


def test_output_value_prize_language_scores_above_zero():
    value, reason = output_value_score("Winners receive a $500 cash prize.")
    assert value > 0


def test_output_value_bonus_for_additional_distinct_signals():
    one, _ = output_value_score("Winners receive a $500 cash prize.")
    two, _ = output_value_score(
        "Winners receive a $500 cash prize. Finalists' work will be published."
    )
    assert one == 6
    assert two == 8  # base 6 + 2*(2-1)
    assert two > one


def test_output_value_caps_at_ten():
    value, _ = output_value_score(
        "Cash prize, scholarship award, grand prize worth $10,000, published, demo day."
    )
    assert value == 10


def test_output_value_does_not_read_a_program_cost_as_a_prize():
    # A bare dollar figure with no prize/award/scholarship/grant word next to
    # it is a price tag, not a prize -- confirmed against real backlog data,
    # where paid summer camps ("Camp costs $1,875") were scoring a "prize"
    # purely off their tuition figure before this pattern was tightened.
    value, reason = output_value_score("Tuition for the summer session is $1,875.")
    assert value == 0
    assert reason == "no prize/output signal"


@pytest.mark.parametrize(
    "text",
    [
        "Winners receive a $500 cash prize.",
        "A $5,000 scholarship is awarded to the top applicant.",
        "Grand prize worth $10,000 goes to the winning team.",
    ],
)
def test_output_value_does_read_a_dollar_amount_next_to_prize_language(text):
    value, _ = output_value_score(text)
    assert value > 0


def test_output_value_generic_has_no_signal():
    value, reason = output_value_score("Open enrollment webinar, no cap on registrations.")
    assert value == 0
    assert reason == "no prize/output signal"


def test_output_value_handles_none_text():
    value, reason = output_value_score(None)
    assert value == 0
    assert reason


@pytest.mark.parametrize(
    "text",
    ["", "$5000 prize", "Riverside Community College hosts a webinar", "Open enrollment"],
)
def test_output_value_never_leaves_its_0_to_10_range(text):
    value, _ = output_value_score(text)
    assert 0 <= value <= 10


def test_axes_do_not_leak_into_each_other():
    # A bare institution name with no funding/location/prize/selectivity
    # language must not inflate any other axis -- each fires on disjoint
    # signals.
    text = "MIT hosts an event."
    fit_value, _ = topic_fit_score(text)
    aff_value, _ = affordability_score(5000.0, text)
    sel_value, _ = selectivity_score(text)
    out_value, _ = output_value_score(text)
    assert fit_value == 0
    assert aff_value == 0
    assert sel_value == 3  # institution floor is the one deliberate exception
    assert out_value == 0


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


# --- end to end: score() ----------------------------------------------------


def test_score_combines_all_six_axes():
    value, reason = score(True, None, None, "AI hackathon")
    aff, _ = affordability_score(None, "AI hackathon")
    att, _ = attendance_ability_score(True, None, "AI hackathon")
    sel, _ = selectivity_score("AI hackathon")
    pres, _ = prestige_score("AI hackathon")
    fit, _ = topic_fit_score("AI hackathon")
    out, _ = output_value_score("AI hackathon")
    assert value == aff + att + sel + pres + fit + out
    assert f"aff {aff}/25" in reason
    assert f"att {att}/25" in reason


def test_score_citizenship_bar_clamps_only_affordability_and_attendance():
    # Deliberate behavior: the citizenship/residency bar zeroes affordability
    # and attendance-ability, but selectivity/prestige/fit/output compute
    # normally and still contribute to the total, so a citizenship-barred but
    # otherwise excellent opportunity surfaces low-ranked instead of
    # vanishing.
    text = (
        "Open only to U.S. citizens. AI hackathon at MIT, 15% acceptance rate, "
        "$5000 cash prize."
    )
    value, reason = score(False, 0.0, None, text)
    aff, _ = affordability_score(0.0, text)
    att, _ = attendance_ability_score(False, None, text)
    sel, _ = selectivity_score(text)
    pres, _ = prestige_score(text)
    fit, _ = topic_fit_score(text)
    out, _ = output_value_score(text)
    assert aff == 0
    assert att == 0
    assert sel > 0
    assert pres > 0
    assert fit > 0
    assert out > 0
    assert value == sel + pres + fit + out
    assert "citizenship" in reason


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
    assert value >= 30  # attendance-ability alone is already >= the local floor


def test_score_reason_never_exceeds_the_relevance_reason_column_limit():
    # Opportunity.relevance_reason is a String(120) column, and the Telegram
    # path assigns it post-construction, bypassing pydantic's own truncating
    # validator — the cap has to live in scoring.py itself.
    text = (
        "AI machine learning computer vision hackathon startup founder "
        "accelerator incubator entrepreneurship. Fully funded, all expenses "
        "paid, scholarship, stipend, financial aid, need-based aid, bursary. "
        "MIT and Stanford, only 20 spots, cash prize of $5000, published."
    )
    _, reason = score(False, 5000.0, "Boston, US", text)
    assert len(reason) <= 120
