"""Category, from the source's own taxonomy, for scraped items.

Originally left None on the theory that CategoryClassifier would fill it.
Watching real items land in the admin queue showed that was wrong: that
classifier reads title + description, and a listing called "Student
Leadership Academy" contains no keyword from its map -- while SIREL had told
us outright that the item is a `type-of-activity: Program`. The data was
collected into WebItem.subjects and then ignored.

Relevance scoring lives in src/core/scoring.py now, shared with the Telegram
pipeline -- see that module's docstring for why it moved and how the 1-10
rubric works.
"""
import re

from src.core.enums import Category

# The source's own taxonomy term -> Category. SIREL's `type-of-activity` uses
# exactly these labels; ExtracurricularHub's `occupationalCategory` is almost
# always the generic "STEM Program", which is why the title fallback below
# exists at all.
_TAXONOMY_TO_CATEGORY: dict[str, Category] = {
    "competition": Category.Competition,
    "research": Category.Research,
    "scholarship": Category.Scholarship,
    "summer program": Category.SummerProgram,
    "volunteer opportunity": Category.Volunteer,
    "college course": Category.SummerProgram,
    "internship": Category.Internship,
    "fellowship": Category.Fellowship,
    "conference": Category.Conference,
    # "Club" and "Program" are real SIREL terms with no Category equivalent.
    # Mapped to the closest honest bucket rather than left Unknown.
    "club": Category.Volunteer,
    "program": Category.SummerProgram,
    "stem program": Category.SummerProgram,
}

# Title-shape fallback, ordered most specific first. Deliberately separate from
# processor/classifier._KEYWORD_PATTERNS: these are words that appear in
# catalog LISTING titles ("...Academy", "...Challenge") and would be far too
# loose to apply to free-text Telegram posts.
_TITLE_PATTERNS: list[tuple[str, Category]] = [
    (r"\bhackathon\b", Category.Hackathon),
    (r"\bolympiad\b", Category.Olympiad),
    (r"\b(?:internship|intern)\b", Category.Internship),
    (r"\bfellowship\b", Category.Fellowship),
    (r"\bscholarship\b", Category.Scholarship),
    (r"\bgrant\b", Category.Grant),
    (r"\b(?:conference|symposium|summit)\b", Category.Conference),
    (r"\b(?:competition|contest|challenge|tournament|award|prize|bee|bowl)\b",
     Category.Competition),
    (r"\bresearch\b", Category.Research),
    (r"\b(?:accelerator|incubator)\b", Category.Accelerator),
    (r"\bexchange\b", Category.Exchange),
    (r"\bvolunteer\b", Category.Volunteer),
    (r"\b(?:summer|camp|academy|institute|bootcamp|workshop|program|programme)\b",
     Category.SummerProgram),
]
_TITLE_RULES = [(re.compile(p, re.IGNORECASE), c) for p, c in _TITLE_PATTERNS]


def category_from(item) -> Category | None:
    """The source's taxonomy first, the title's shape second."""
    return category_from_parts(item.title, item.description, item.subjects)


def category_from_parts(
    title: str | None, description: str | None, subjects: list[str] | None = None
) -> Category | None:
    """Same rules, from loose parts.

    Exists so already-ingested rows can be re-classified in place: an
    Opportunity keeps title and description but not the source taxonomy, so it
    falls through to the title rules.
    """
    for subject in subjects or []:
        hit = _TAXONOMY_TO_CATEGORY.get((subject or "").strip().lower())
        if hit is not None:
            return hit

    # Title alone, first. Caught live: "Amazon Future Engineers Scholarship"
    # was reclassified as Internship because its DESCRIPTION happens to
    # mention "a paid internship at Amazon" as a bundled perk, and
    # "internship" sits earlier than "scholarship" in _TITLE_PATTERNS. A
    # program's own title is a much stronger signal than an incidental word
    # in its prose, so it gets first, exclusive refusal.
    if title:
        for pattern, category in _TITLE_RULES:
            if pattern.search(title):
                return category

    # Title alone matched nothing -- fall back to title+description together.
    haystack = " ".join(filter(None, [title, description]))
    for pattern, category in _TITLE_RULES:
        if pattern.search(haystack):
            return category
    return None
