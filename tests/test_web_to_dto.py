"""The LLM-free DTO builder.

The card renderer's length caps are hard, and the fields left deliberately None
(category, relevance) are load-bearing: guessing either would misroute an item
or corrupt the admin queue's ranking.
"""
from src.collector.web.base import WebItem
from src.collector.web.to_dto import build_dto


def item(**kwargs) -> WebItem:
    base = dict(
        source="test",
        external_id="x",
        title="Some Program",
        page_url="https://catalog.example/p/x",
    )
    base.update(kwargs)
    return WebItem(**base)


def test_official_link_becomes_apply_link():
    dto = build_dto(item(apply_url="https://official.example/apply"))
    assert dto.apply_link == "https://official.example/apply"
    # The catalog page is kept, not lost — it often carries context.
    assert "https://catalog.example/p/x" in dto.additional_links


def test_apply_link_falls_back_to_the_catalog_page():
    dto = build_dto(item(apply_url=None))
    assert dto.apply_link == "https://catalog.example/p/x"
    assert dto.additional_links == []


def test_category_is_left_for_the_classifier():
    # A wrong guess here routes an item to the wrong channel; the free keyword
    # classifier runs downstream either way.
    assert build_dto(item()).category is None


def test_relevance_is_left_unrated():
    # Faking a profile-fit score would corrupt the queue ordering. Unrated
    # items sort last, which is right for unreviewed scraped input.
    dto = build_dto(item())
    assert dto.relevance is None
    assert dto.relevance_reason is None


def test_card_fields_respect_their_caps():
    dto = build_dto(
        item(
            title="A Very Long Programme Name That Goes On " * 4,
            eligibility="Open to students in grades nine through twelve " * 4,
            cost_text="Free",
        )
    )
    assert len(dto.card_summary) <= 130
    assert len(dto.card_eligibility) <= 90
    assert len(dto.card_rewards) <= 90


def test_card_fields_never_cut_mid_word():
    long_title = "Supercalifragilistic " * 20
    dto = build_dto(item(title=long_title))
    assert not dto.card_summary.endswith("Supercalifragilis")
    assert dto.card_summary.split()[-1] in long_title.split()


def test_min_age_uses_the_shared_parser():
    dto = build_dto(item(eligibility="Open to applicants 16+"))
    assert dto.min_age == 16


def test_min_age_is_none_when_unstated():
    assert build_dto(item(eligibility="High school students")).min_age is None


def test_audience_school_from_grades():
    dto = build_dto(item(grades=["9th", "10th", "Middle School"]))
    assert dto.audience == "school"


def test_audience_university_from_eligibility():
    dto = build_dto(item(eligibility="Undergraduate students only"))
    assert dto.audience == "university"


def test_mixed_signals_default_to_both():
    # None means "both" downstream. Never guess narrowly — the same rule the
    # extractor prompt states.
    dto = build_dto(item(grades=["12th", "College"]))
    assert dto.audience is None


def test_unknown_audience_defaults_to_both():
    assert build_dto(item()).audience is None


def test_online_with_no_country_reads_as_online():
    assert build_dto(item(is_online=True)).location == "Online"


def test_country_is_kept_for_a_hybrid():
    assert build_dto(item(is_online=True, country="US")).location == "US / Online"


def test_in_person_keeps_only_the_country():
    assert build_dto(item(is_online=False, country="US")).location == "US"


def test_zero_cost_renders_as_free():
    dto = build_dto(item(cost_amount=0.0))
    assert dto.cost == "Free"
    assert dto.rewards == "Free to enter"


def test_priced_cost_renders_without_a_trailing_decimal():
    assert build_dto(item(cost_amount=25.0, cost_currency="USD")).cost == "25 USD"


def test_fractional_cost_is_preserved():
    assert build_dto(item(cost_amount=12.5, cost_currency="USD")).cost == "12.5 USD"


def test_description_is_composed_when_the_catalog_has_none():
    dto = build_dto(
        item(
            description=None,
            organizer="Some University",
            eligibility="Up to age 19",
            deadline="March 1, 2027",
            is_online=True,
        )
    )
    assert "Some Program" in dto.description
    assert "Some University" in dto.description
    assert "Up to age 19" in dto.description
    assert "March 1, 2027" in dto.description


def test_start_date_is_not_presented_as_a_deadline():
    dto = build_dto(item(description=None, deadline=None, starts_at="2026-11-21"))
    assert dto.deadline is None
    assert "Deadline" not in dto.description
    assert "Starts: 2026-11-21" in dto.description


def test_an_all_unknown_item_still_builds():
    dto = build_dto(item())
    assert dto.is_opportunity is True
    assert dto.title == "Some Program"
    assert dto.card_summary


def test_bare_grade_ordinals_read_as_school():
    """SIREL's grade taxonomy labels are bare ordinals with no following
    'grade' word. Missing them classified school programs as university-only
    and hid them from the school channel."""
    assert build_dto(item(grades=["9th", "10th", "11th", "12th"])).audience == "school"


def test_a_high_ordinal_in_prose_is_not_a_school_year():
    dto = build_dto(item(eligibility="Undergraduates, in its 20th anniversary year"))
    assert dto.audience == "university"


def test_plural_university_words_are_recognised():
    """A trailing \b after a bare stem does not match "Undergraduates", and
    catalogs write these in the plural far more often than the singular."""
    for phrase in ("Undergraduates only", "Open to college students",
                   "For universities in the region", "PhDs welcome"):
        assert build_dto(item(eligibility=phrase)).audience == "university", phrase
