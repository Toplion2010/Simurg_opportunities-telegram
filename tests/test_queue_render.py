from src.bot.routers.queue import _card_text
from src.core.enums import Audience, Category, OpportunityStatus
from src.db.models.opportunity import Opportunity


def _make_opp(**overrides) -> Opportunity:
    defaults = dict(
        title="Some Opportunity",
        category=Category.Scholarship,
        audience=Audience.both,
        status=OpportunityStatus.pending,
        deadline=None,
        relevance=None,
        relevance_reason=None,
        min_age=None,
        source_url=None,
    )
    defaults.update(overrides)
    return Opportunity(**defaults)


def test_unrated_row_omits_stars_and_source():
    opp = _make_opp()
    card = _card_text(opp)
    assert "⭐" not in card
    assert "🔗" not in card
    assert "🔞" not in card
    assert "Some Opportunity" in card


def test_fully_populated_row_shows_everything():
    opp = _make_opp(
        deadline="March 1, 2026",
        relevance=4,
        relevance_reason="Strong AI/ML fit",
        min_age=18,
        source_url="https://t.me/somechannel/42",
        category=Category.Hackathon,
    )
    card = _card_text(opp)
    assert "⭐⭐⭐⭐☆ 4/5 · Strong AI/ML fit" in card
    assert "🏷 Hackathon · 🔞 18+" in card
    assert 'https://t.me/somechannel/42' in card
    assert "🔞 18+" in card
    assert "March 1, 2026" in card


def test_min_age_under_18_has_no_badge():
    opp = _make_opp(min_age=14)
    card = _card_text(opp)
    assert "🔞" not in card
