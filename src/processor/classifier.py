import re

from src.core.enums import Category
from src.core.logging import get_logger
from src.processor.extractor import OpportunityDTO

logger = get_logger(__name__)

# Word-anchored, in priority order. Previously a dict of plain substrings tested
# with `in`, which mis-fired badly: "intern" was the first key and also matches
# "International", so EVERY opportunity mentioning that word — International
# Olympiad, International Research Conference, ACM International Collegiate
# Programming Contest — was filed as an Internship. Verified against live rows.
#
# Prefixes are kept where they are deliberate ("scholar" -> scholarship/scholars,
# "accelerat" -> accelerator/accelerating); only the endings that would
# over-match are pinned. Order still decides ties, so the specific categories
# come before the generic Job catch-alls at the bottom.
_KEYWORD_PATTERNS: list[tuple[str, Category]] = [
    (r"\bintern(?:ship|ships|s)?\b|\btraineeship", Category.Internship),
    (r"\bscholar", Category.Scholarship),
    (r"\bfellowship", Category.Fellowship),
    (r"\bhackathon", Category.Hackathon),
    (r"\bolympiad", Category.Olympiad),
    (r"\bresearch", Category.Research),
    (r"\bcompetition|\bcontest\b|\bchallenge\b", Category.Competition),
    (r"\bstartup|\bstart-up", Category.Startup),
    (r"\baccelerat", Category.Accelerator),
    (r"\bincubat", Category.Incubator),
    (r"\bgrants?\b", Category.Grant),
    (r"\bconference|\bsymposium", Category.Conference),
    (r"\bsummer (?:program|programme|school|camp)", Category.SummerProgram),
    (r"\bexchange", Category.Exchange),
    (r"\bvolunteer", Category.Volunteer),
    (r"\bhiring\b|\bvacanc(?:y|ies)\b", Category.Job),
    (r"\bjobs?\b", Category.Job),
    (r"\bposition\b", Category.Job),
]
_KEYWORD_RULES = [(re.compile(p, re.IGNORECASE), c) for p, c in _KEYWORD_PATTERNS]


class CategoryClassifier:
    def classify(self, dto: OpportunityDTO, original_text: str = "") -> Category | None:
        if dto.category is not None:
            return dto.category

        combined = " ".join(filter(None, [
            dto.title, dto.description, original_text
        ])).lower()

        for pattern, category in _KEYWORD_RULES:
            match = pattern.search(combined)
            if match:
                logger.debug(
                    "category_keyword_match", keyword=match.group(0), category=category
                )
                return category

        return None
