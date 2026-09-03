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
        relevance=78,
        relevance_reason="cool 44/60 (online) + fit 34/40 (core: ai)",
        min_age=18,
        source_url="https://t.me/somechannel/42",
        category=Category.Hackathon,
    )
    card = _card_text(opp)
    # relevance is 0-100 (src/core/scoring.py); the star GLYPH count is
    # ceil(relevance/20) so it stays a readable 5 stars, but the number shown
    # is always the honest /100.
    assert "⭐⭐⭐⭐☆ 78/100 · cool 44/60 (online) + fit 34/40 (core: ai)" in card
    assert "🏷 Hackathon · 🔞 18+" in card
    assert 'https://t.me/somechannel/42' in card
    assert "🔞 18+" in card
    assert "March 1, 2026" in card


def test_star_glyph_count_is_ceil_of_relevance_over_twenty():
    # round()'s banker's rounding would collapse boundary values to identical
    # glyph counts; ceil() pairs cleanly (1-20->1, 21-40->2, ..., 81-100->5).
    cases = {0: 0, 1: 1, 20: 1, 21: 2, 40: 2, 41: 3, 60: 3, 61: 4, 80: 4, 81: 5, 100: 5}
    for relevance, filled in cases.items():
        card = _card_text(_make_opp(relevance=relevance, relevance_reason=None))
        assert card.count("⭐") == filled, f"relevance={relevance}"
        assert f"{relevance}/100" in card


def test_min_age_under_18_has_no_badge():
    opp = _make_opp(min_age=14)
    card = _card_text(opp)
    assert "🔞" not in card
