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


def test_title_wins_over_an_incidental_word_in_the_description():
    """Caught live, about to write bad data on a real repair run: "Amazon
    Future Engineers Scholarship" reclassified as Internship because its
    description mentions "a paid internship at Amazon" as a bundled perk.
    "internship" sits earlier than "scholarship" in _TITLE_PATTERNS, and the
    old single-pass match scanned title+description together, so the
    description's incidental word beat the title's own explicit label."""
    title = "Amazon Future Engineers Scholarship"
    description = (
        "Amazon offers this scholarship to students from underserved backgrounds "
        "interested in pursuing computer science and engineering degrees. Winners "
        "receive scholarship funds and a paid internship at Amazon to gain "
        "industry experience."
    )
    assert category_from_parts(title, description) == Category.Scholarship


def test_description_still_used_when_title_alone_is_silent():
    # The fix is title-FIRST, not title-ONLY -- when the title carries no
    # signal at all, the description fallback must still work exactly as
    # before. "Elevate" alone matches nothing in _TITLE_PATTERNS.
    assert category_from_parts("Elevate", "A hackathon for students.") == Category.Hackathon
