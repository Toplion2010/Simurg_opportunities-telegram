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
        relevance=8,
        relevance_reason="online + keyword: ai",
        min_age=18,
        source_url="https://t.me/somechannel/42",
        category=Category.Hackathon,
    )
    card = _card_text(opp)
    # relevance is 1-10 (src/core/scoring.py); the star GLYPH count is
    # ceil(relevance/2) so it stays a readable 5 stars, but the number shown
    # is always the honest /10.
    assert "⭐⭐⭐⭐☆ 8/10 · online + keyword: ai" in card
    assert "🏷 Hackathon · 🔞 18+" in card
    assert 'https://t.me/somechannel/42' in card
    assert "🔞 18+" in card
    assert "March 1, 2026" in card


def test_star_glyph_count_is_ceil_of_relevance_over_two():
    # round()'s banker's rounding would collapse 5&6 and 8&9 to identical
    # glyph counts; ceil() pairs cleanly (1-2->1, 3-4->2, ..., 9-10->5).
    cases = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5}
    for relevance, filled in cases.items():
        card = _card_text(_make_opp(relevance=relevance, relevance_reason=None))
        assert card.count("⭐") == filled, f"relevance={relevance}"
        assert f"{relevance}/10" in card


def test_min_age_under_18_has_no_badge():
    opp = _make_opp(min_age=14)
    card = _card_text(opp)
    assert "🔞" not in card
