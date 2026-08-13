from src.core.enums import Audience, Category, OpportunityStatus
from src.db.models.opportunity import Opportunity
from src.publisher.formatter import format_opportunity


def _make_opp(**overrides) -> Opportunity:
    defaults = dict(
        title=None,
        category=Category.Hackathon,
        audience=Audience.both,
        status=OpportunityStatus.pending,
    )
    defaults.update(overrides)
    return Opportunity(**defaults)


def test_hackathon_all_optional_fields_null_still_renders():
    opp = _make_opp()
    text = format_opportunity(opp)
    assert "<b>✨ Opportunity</b>" in text
    assert "#Hackathon #SimurgOpportunities" in text
    # Nothing crashes and no NULL-ish placeholder leaks through.
    assert "None" not in text


def test_hackathon_layout_orders_prize_and_deadline_first():
    opp = _make_opp(
        title="Global Hack 2026",
        rewards="$10,000",
        deadline="March 1, 2026",
        location="Remote",
        duration="48 hours",
        eligibility="University students worldwide",
        description="Build something great.",
        apply_link="https://example.com/apply",
    )
    text = format_opportunity(opp)
    prize_pos = text.index("Prize pool:")
    deadline_pos = text.index("Registration closes:")
    format_pos = text.index("Format:")
    eligibility_pos = text.index("Who can enter:")
    assert prize_pos < deadline_pos < format_pos < eligibility_pos


def test_hackathon_omits_missing_prize_line():
    opp = _make_opp(title="No Prize Hack", rewards=None, cost=None)
    text = format_opportunity(opp)
    assert "Prize pool" not in text


def test_non_hackathon_category_routes_to_generic_formatter():
    opp = _make_opp(title="A Scholarship", category=Category.Scholarship)
    text = format_opportunity(opp)
    assert "#Scholarship #SimurgOpportunities" in text
    assert "Register" not in text
