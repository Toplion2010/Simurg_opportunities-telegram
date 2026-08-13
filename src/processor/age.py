"""Parse an explicit minimum age out of free-text opportunity descriptions.

A naive `\\b(1[89]|2[01])\\s*(years|лет)` gets "applicants aged 14-18" wrong
(the floor is 14, not 18) — the difference between correctly gating 18+
content out of the school channel and needlessly blocking a school post.
"""
import re

# --- Guard context (checked around every candidate digit match) -----------

_BAD_BEFORE = re.compile(
    r"(?:[$€£₸]\s*|\bgrade\s*|\bclass\s*(?:of\s*)?|\bsince\s*|©\s*)$",
    re.IGNORECASE,
)
_BAD_AFTER = re.compile(r"^\s*(?:%|,\d{3})")


def _has_bad_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 12) : start]
    after = text[end : end + 12]
    return bool(_BAD_BEFORE.search(before) or _BAD_AFTER.search(after))


# --- Patterns, checked in this order: ranges, then floors, then words -----

_RANGE_PATTERNS = [
    re.compile(r"\b(?:ages?|aged)\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*years?(?:\s*old)?\b", re.IGNORECASE),
    re.compile(r"\bparticipants?\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bот\s+(\d{1,2})\s+до\s+(\d{1,2})\s*лет\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*лет\b", re.IGNORECASE),
]

_FLOOR_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s*\+", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*(?:years?\s*old\s*)?(?:or\s+older|and\s+above|or\s+above)\b", re.IGNORECASE),
    re.compile(r"\bat\s+least\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bminimum\s+age\s+(?:of\s+)?(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bот\s+(\d{1,2})\s*лет\b", re.IGNORECASE),
    re.compile(r"\bстарше\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bне\s+младше\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*(?:лет\s*)?или\s+старше\b", re.IGNORECASE),
]

_WORD_PATTERNS = [
    re.compile(r"\badults?\s+only\b", re.IGNORECASE),
    re.compile(r"\bсовершеннолетн\w*\b", re.IGNORECASE),
]

_MIN_VALID = 5
_MAX_VALID = 99


def _first_valid_group_value(text: str, patterns: list[re.Pattern], group: int) -> int | None:
    for pattern in patterns:
        for match in pattern.finditer(text):
            span = match.span(group)
            if _has_bad_context(text, *span):
                continue
            return int(match.group(group))
    return None


def parse_min_age(text: str) -> int | None:
    if not text:
        return None

    for pattern in _RANGE_PATTERNS:
        for match in pattern.finditer(text):
            lo_span = match.span(1)
            if _has_bad_context(text, *lo_span):
                continue
            age = int(match.group(1))
            return age if _MIN_VALID <= age <= _MAX_VALID else None

    for pattern in _FLOOR_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span(1)
            if _has_bad_context(text, *span):
                continue
            age = int(match.group(1))
            return age if _MIN_VALID <= age <= _MAX_VALID else None

    for pattern in _WORD_PATTERNS:
        if pattern.search(text):
            return 18

    return None
