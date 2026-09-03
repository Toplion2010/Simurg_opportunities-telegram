"""Category derived from the source's own taxonomy.

Originally left None. Real queue cards then rendered as "🏷 Unknown", while
SIREL's own type-of-activity taxonomy already carried the answer.

Relevance moved to src/core/scoring.py, shared with the Telegram pipeline —
see tests/test_scoring.py.
"""
import pytest

from src.collector.web.base import WebItem
from src.collector.web.classify import category_from, category_from_parts
from src.collector.web.to_dto import build_dto
from src.core.enums import Category


def item(**kw) -> WebItem:
    base = dict(source="t", external_id="x", title="Some Thing",
                page_url="https://cat.example/p/x")
    base.update(kw)
    return WebItem(**base)


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


# --- re-classifying already-ingested rows --------------------------------


def test_parts_helper_works_without_the_source_taxonomy():
    """An Opportunity row keeps title and description but not `subjects`, so
    the repair path must reach the same answer from the title alone."""
    assert category_from_parts("Student Leadership Academy", None) == Category.SummerProgram
    assert category_from_parts("Princeton Math Contest", None) == Category.Competition


def test_parts_helper_tolerates_missing_text():
    assert category_from_parts(None, None) is None


def test_item_and_parts_agree():
    it = item(title="AI Research Institute", subjects=["Research"])
    assert category_from(it) == category_from_parts(it.title, it.description, it.subjects)


# --- end to end through the DTO ------------------------------------------


def test_dto_category_renders():
    dto = build_dto(item(title="AI Research Institute", subjects=["Research"]))
    assert dto.category == Category.Research
