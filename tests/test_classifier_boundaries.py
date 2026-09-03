"""CategoryClassifier keyword matching must respect word boundaries.

It previously used a dict of plain substrings tested with `in`, and "intern"
was the FIRST key. So every opportunity whose text contained "International"
was classified as an Internship — International Olympiad, International
Research Conference, ACM International Collegiate Programming Contest. Found on
live rows: opportunity #759 (ICPC) was sitting in the queue as an Internship.

This affected the Telegram pipeline too, not just scraped items.
"""
import pytest

from src.core.enums import Category
from src.processor.classifier import CategoryClassifier
from src.processor.extractor import OpportunityDTO


def classify(text: str) -> Category | None:
    return CategoryClassifier().classify(OpportunityDTO(title=text), text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ACM International Collegiate Programming Contest", Category.Competition),
        ("International Mathematical Olympiad", Category.Olympiad),
        ("International Research Conference", Category.Research),
        ("International Scholarship for Women", Category.Scholarship),
        ("Международная олимпиада", None),
    ],
)
def test_international_is_not_an_internship(text, expected):
    assert classify(text) == expected


@pytest.mark.parametrize(
    "text",
    ["Summer Internship at IBM", "Interns wanted", "Paid internships available",
     "Traineeship in Berlin"],
)
def test_real_internships_still_match(text):
    assert classify(text) == Category.Internship


@pytest.mark.parametrize(
    "text,expected",
    [
        ("PhD Scholarship", Category.Scholarship),          # prefix kept
        ("Scholars Program", Category.Scholarship),         # prefix kept
        ("Startup Accelerator Batch 12", Category.Startup),
        ("Business incubation programme", Category.Incubator),
        ("Volunteer at the shelter", Category.Volunteer),
        ("We are hiring a backend developer", Category.Job),
        ("Research Grant for PhD students", Category.Research),
        ("Summer school in Prague", Category.SummerProgram),
    ],
)
def test_intended_prefixes_still_work(text, expected):
    assert classify(text) == expected


def test_unmatched_text_stays_none():
    assert classify("Random announcement about nothing") is None


def test_an_explicit_dto_category_always_wins():
    dto = OpportunityDTO(title="Internship", category=Category.Hackathon)
    assert CategoryClassifier().classify(dto, "internship") == Category.Hackathon
