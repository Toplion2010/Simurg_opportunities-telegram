"""Category and profile-relevance for scraped items, from the source's own taxonomy.

Both fields were originally left None, on the reasoning that CategoryClassifier
would fill the category and that a fabricated relevance would corrupt the
queue's ranking. Watching real items land in the admin queue showed that was
wrong on both counts:

  * Category rendered as "Unknown". The keyword classifier reads title +
    description, and a listing called "Student Leadership Academy" contains no
    keyword from its map — while SIREL had told us outright that the item is a
    `type-of-activity: Program`. The data was collected into WebItem.subjects
    and then ignored.

  * Relevance stayed NULL, which is not merely a missing star line:
    OpportunityRepository.get_pending sorts `relevance IS NULL` last, so every
    scraped item queued behind every Telegram item, permanently. With ~1,900 of
    them that is not a ranking, it is a burial.

What is derived here is keyword-derived, not an LLM's judgement, and it says so
in relevance_reason so the admin can see exactly what produced the number.
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
# processor/classifier._KEYWORD_MAP: these are words that appear in catalog
# LISTING titles ("...Academy", "...Challenge") and would be far too loose to
# apply to free-text Telegram posts.
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


# Profile fit, using the SAME 1-5 scale the extractor prompt defines:
#   5 = core fit, 4 = adjacent STEM/business, 3 = general with real tech or
#   business content, 2 = little tech/business, 1 = off-profile.
_RELEVANCE_TERMS: list[tuple[int, str]] = [
    (5, r"computer science|artificial intelligence|\bai\b|machine learning|"
        r"cybersecurity|robotic|hackathon|programming|software|data science|"
        r"\bhacking\b|informatics|\bcoding\b|competitive programming"),
    (5, r"mathematic|\bmath\b|olympiad|entrepreneur|startup|\bbusiness\b"),
    (4, r"engineering|physics|aerospace|technology|\bstem\b|biotech|"
        r"synthetic biology|neuroscience|science research|\binnovation\b"),
    (3, r"\bscience\b|biology|chemistry|medicine|biomedic|environmental|"
        r"marine|geography|psychology|\bgeneral\b|economics|finance"),
    (2, r"writing|debate|model un|journalism|policy|history|philosoph|"
        r"leadership|language"),
    (1, r"\bart\b|\barts\b|music|theat|dance|sport|athlet|film|photograph|choir"),
]
_RELEVANCE_RULES = [(s, re.compile(p, re.IGNORECASE)) for s, p in _RELEVANCE_TERMS]

# Nothing matched. 2 is the extractor's own "little tech/business", which is
# the honest reading of a listing whose subject we could not identify — and it
# still sorts above a genuine off-profile 1.
_DEFAULT_RELEVANCE = 2
_DEFAULT_REASON = "no profile keywords matched"


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

    haystack = " ".join(filter(None, [title, description]))
    for pattern, category in _TITLE_RULES:
        if pattern.search(haystack):
            return category
    return None


def relevance_from(item) -> tuple[int, str]:
    """(score, reason) against the operator's profile.

    Takes the HIGHEST-scoring signal present rather than the first: a
    "Robotics and Art Camp" is a robotics opportunity that also does art, not
    an art one. The reason names the matched text so a wrong score is
    diagnosable from the queue card itself.
    """
    return relevance_from_parts(item.title, item.description, item.subjects)


def relevance_from_parts(
    title: str | None, description: str | None, subjects: list[str] | None = None
) -> tuple[int, str]:
    haystack = " ".join(
        filter(None, [title, " ".join(subjects or []), description])
    )
    best: tuple[int, str] | None = None
    for score, pattern in _RELEVANCE_RULES:
        match = pattern.search(haystack)
        if match and (best is None or score > best[0]):
            best = (score, match.group(0).strip().lower())

    if best is None:
        return (_DEFAULT_RELEVANCE, _DEFAULT_REASON)
    return (best[0], f"keyword: {best[1]}")
