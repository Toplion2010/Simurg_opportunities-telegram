"""Best-effort date parsing for the free-text `deadline` field.

`Opportunity.deadline` is a String(200) filled by the LLM extractor, which is
told to emit "a date string or description" -- so it holds "12 September 2026",
"March 20, 2025", "2026-09-12" and also "Rolling", "TBA" and prose. There is no
parsed-date column to sort on, and adding one would not help the rows already
in the table, so publishing parses the text at read time instead.

Two rules keep this conservative, because the cost of the two failure modes is
not symmetric: sorting a live post late is a nuisance, dropping one as expired
is lost content the channel never sees.

  * Anything not confidently understood returns None -- which sorts last and is
    NEVER treated as expired.
  * An ambiguous all-numeric date (12/09/2026 -- day-first or month-first?)
    returns None rather than guessing, unless one component is > 12 and settles
    it.
"""

import re
from datetime import date

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Rolling", "ongoing", "no deadline" are real, common values and mean "not
# dated", not "unparseable" -- but both answer None here, so they need no
# separate branch. They are listed only so a reader knows they were considered.

_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DAY_RE = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR_RE = r"(\d{4})"

# ISO first: 2026-09-12 (also 2026/09/12). Unambiguous, so it wins outright.
_ISO = re.compile(rf"\b{_YEAR_RE}[-/](\d{{1,2}})[-/](\d{{1,2}})\b")
# "12 September 2026", "12 Sept 2026"
_DAY_MONTH_YEAR = re.compile(rf"\b{_DAY_RE}\s+{_MONTH_RE}\s+{_YEAR_RE}\b", re.I)
# "September 12, 2026", "Sept 12 2026"
_MONTH_DAY_YEAR = re.compile(rf"\b{_MONTH_RE}\s+{_DAY_RE},?\s+{_YEAR_RE}\b", re.I)
# Year-less: "12 September" / "September 12". Resolved against `today` below.
_DAY_MONTH = re.compile(rf"\b{_DAY_RE}\s+{_MONTH_RE}\b", re.I)
_MONTH_DAY = re.compile(rf"\b{_MONTH_RE}\s+{_DAY_RE}\b", re.I)
# All-numeric: 12/09/2026, 12.09.2026
_NUMERIC = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")


def _build(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:  # 31 February, month 13, and other LLM slips
        return None


def parse_deadline(text: str | None, today: date | None = None) -> date | None:
    """The date `text` refers to, or None if it does not confidently name one.

    `today` only resolves a year-less deadline ("12 September"), which is read
    as the next such date not yet past -- the reading that cannot retire a
    still-open opportunity.
    """
    if not text:
        return None
    today = today or date.today()

    if m := _ISO.search(text):
        return _build(int(m[1]), int(m[2]), int(m[3]))

    if m := _DAY_MONTH_YEAR.search(text):
        return _build(int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1]))

    if m := _MONTH_DAY_YEAR.search(text):
        return _build(int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2]))

    if m := _NUMERIC.search(text):
        first, second, year = int(m[1]), int(m[2]), int(m[3])
        if first > 12 and second <= 12:
            return _build(year, second, first)  # day-first, settled
        if second > 12 and first <= 12:
            return _build(year, first, second)  # month-first, settled
        return None  # genuinely ambiguous -- do not guess

    for pattern, day_first in ((_DAY_MONTH, True), (_MONTH_DAY, False)):
        if m := pattern.search(text):
            day = int(m[1]) if day_first else int(m[2])
            month = _MONTHS[(m[2] if day_first else m[1])[:3].lower()]
            for year in (today.year, today.year + 1):
                if (parsed := _build(year, month, day)) and parsed >= today:
                    return parsed
            return None

    return None


def is_expired(text: str | None, today: date | None = None) -> bool:
    """Whether `text` names a date that has already passed.

    Deadline == today is NOT expired: an application due "12 September" is open
    for all of the 12th.
    """
    parsed = parse_deadline(text, today)
    return parsed is not None and parsed < (today or date.today())


def deadline_sort_key(text: str | None, today: date | None = None) -> tuple[bool, date]:
    """Sort key putting the soonest deadline first and undated rows last.

    The bool leads so undated rows sort after every dated one regardless of the
    date beside it; `date.max` is filler that never compares against a real date.
    """
    parsed = parse_deadline(text, today)
    return (parsed is None, parsed or date.max)
