"""Category and relevance derived from the source's own taxonomy.

Both were originally left None. Real queue cards then rendered as
"🏷 Unknown" with no star line — and, worse, NULL relevance sorts last in
get_pending, so every scraped item queued behind every Telegram item forever.
"""
import pytest

from src.collector.web.base import WebItem
from src.collector.web.classify import category_from, relevance_from
from src.collector.web.to_dto import build_dto
from src.core.enums import Category


def item(**kw) -> WebItem:
    base = dict(source="t", external_id="x", title="Some Thing",
                page_url="https://cat.example/p/x")
    base.update(kw)
    return WebItem(**base)


# --- category from the source taxonomy -----------------------------------


@pytest.mark.parametrize(
    "term,expected",
    [
        ("Competition", Category.Competition),
        ("Research", Category.Research),
        ("Scholarship", Category.Scholarship),
        ("Summer Program", Category.SummerProgram),
        ("Volunteer Opportunity", Category.Volunteer),
        ("College Course", Category.SummerProgram),
        ("Program", Category.SummerProgram),
        ("Club", Category.Volunteer),
    ],
)
def test_sirel_type_of_activity_maps_to_category(term, expected):
    assert category_from(item(subjects=[term])) == expected


def test_taxonomy_beats_the_title():
    it = item(title="Robotics Challenge", subjects=["Research"])
    assert category_from(it) == Category.Research


def test_title_fallback_when_taxonomy_is_generic():
    # ExtracurricularHub's occupationalCategory is almost always "STEM Program".
    assert category_from(item(title="Princeton Math Contest", subjects=[])) == Category.Competition


def test_the_case_that_rendered_as_unknown():
    """The listing that prompted this: no keyword in the processor's map."""
    assert category_from(item(title="Student Leadership Academy")) == Category.SummerProgram


def test_unmatched_title_stays_none_for_the_classifier():
    assert category_from(item(title="Zonta Young Women Award XYZ", subjects=[])) is not None
    assert category_from(item(title="Qqq Wwwzzz", subjects=[])) is None


# --- relevance against the operator's profile ----------------------------


@pytest.mark.parametrize(
    "subject,score",
    [
        ("Computer Science", 5), ("Artificial Intelligence", 5),
        ("Cybersecurity", 5), ("Robotics", 5), ("Mathematics", 5),
        ("Engineering", 4), ("Physics", 4),
        ("Biology", 3), ("Medicine", 3),
        ("Writing", 2),
    ],
)
def test_sirel_subject_areas_score_against_the_profile(subject, score):
    assert relevance_from(item(subjects=[subject]))[0] == score


def test_highest_signal_wins_not_the_first():
    # A robotics camp that also does art is a robotics opportunity.
    score, reason = relevance_from(item(title="Robotics and Art Summer Camp"))
    assert score == 5
    assert "robotic" in reason


def test_unmatched_gets_a_conservative_default_not_null():
    # NULL is what buried these items; 2 is the extractor's own
    # "little tech/business" and still sorts above a real off-profile 1.
    score, reason = relevance_from(item(title="Qqq Wwwzzz"))
    assert score == 2
    assert reason == "no profile keywords matched"


def test_reason_names_the_matched_text():
    _, reason = relevance_from(item(subjects=["Computer Science"]))
    assert "computer science" in reason


# --- end to end through the DTO ------------------------------------------


def test_dto_carries_both_so_the_card_renders():
    dto = build_dto(item(title="AI Research Institute", subjects=["Research"]))
    assert dto.category == Category.Research
    assert dto.relevance == 5
    assert dto.relevance_reason
    assert len(dto.relevance_reason) <= 120


def test_relevance_is_always_in_range():
    for t in ("Art Camp", "Computer Science Olympiad", "Qqq", "Volunteer Choir"):
        assert 1 <= build_dto(item(title=t)).relevance <= 5
