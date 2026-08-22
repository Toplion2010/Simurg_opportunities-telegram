"""Devpost source — JSON API, easiest to verify.

GET https://devpost.com/api/hackathons?status[]=open&order_by=recently-added&page=N
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

import config
from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

API_URL = "https://devpost.com/api/hackathons"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Matches "Nov 15, 2025", "November 15 2025", or a bare "15, 2025" /
# "15" continuation (the month is optional so a range's second half, which
# devpost often renders without repeating the month, still matches).
_DATE_RE = re.compile(
    r"(?:(?P<month>[A-Za-z]{3,})\.?\s+)?(?<!\d)(?P<day>\d{1,2})(?!\d)(?:,?\s+(?P<year>\d{4}))?"
)


def _parse_dates(text: str | None) -> tuple[date | None, date | None]:
    """Devpost's `submission_period_dates` is a free-text range like
    'Nov 01 - 30, 2025' or 'Nov 15, 2025 - Jan 10, 2026'. Extract up to two
    (month, day, year) tokens; a bare day-only second half inherits the
    first token's month, and either token missing a year inherits whichever
    year appears anywhere in the string. Returns (None, None) on anything we
    can't confidently parse — never raises."""
    if not text:
        return None, None
    try:
        matches = list(_DATE_RE.finditer(text))
        if not matches:
            return None, None

        year_found = None
        for m in matches:
            if m.group("year"):
                year_found = int(m.group("year"))
        if year_found is None:
            year_found = date.today().year

        def _to_date(m: re.Match, fallback_month: int | None) -> date | None:
            month_key = m.group("month")
            month = _MONTHS.get(month_key[:3].lower()) if month_key else fallback_month
            if month is None:
                return None
            day = int(m.group("day"))
            year = int(m.group("year")) if m.group("year") else year_found
            try:
                return date(year, month, day)
            except ValueError:
                return None

        start = _to_date(matches[0], None)
        if len(matches) > 1:
            end = _to_date(matches[-1], fallback_month=start.month if start else None)
        else:
            end = start
        return start, end
    except Exception:
        logger.warning("devpost: failed to parse date range %r", text, exc_info=True)
        return None, None


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    try:
        cleaned = BeautifulSoup(text, "html.parser").get_text(strip=True)
        return cleaned or None
    except Exception:
        logger.warning("devpost: failed to strip HTML from prize text", exc_info=True)
        return text


class DevpostSource(Source):
    name = "devpost"

    def fetch(self) -> list[Hackathon]:
        hackathons: list[Hackathon] = []
        try:
            page = 1
            total_count: int | None = None
            while page <= config.DEVPOST_PAGE_CAP:
                response = get(
                    API_URL,
                    params={
                        "status[]": "open",
                        "order_by": "recently-added",
                        "page": page,
                    },
                )
                response.raise_for_status()
                payload = response.json()

                entries = payload.get("hackathons", [])
                if not entries:
                    break

                for entry in entries:
                    hackathon = self._parse_entry(entry)
                    if hackathon is not None:
                        hackathons.append(hackathon)

                if total_count is None:
                    total_count = payload.get("meta", {}).get("total_count")
                fetched_so_far = page * len(entries)
                if total_count is not None and fetched_so_far >= total_count:
                    break

                page += 1

            return hackathons
        except Exception:
            logger.warning("devpost: fetch failed, returning []", exc_info=True)
            return []

    def _parse_entry(self, entry: dict) -> Hackathon | None:
        try:
            source_id = str(entry["id"])
            starts_at, ends_at = _parse_dates(entry.get("submission_period_dates"))
            location = entry.get("displayed_location", {}).get("location")
            is_online = None
            if location:
                is_online = "online" in location.lower()

            return Hackathon(
                source=self.name,
                source_id=source_id,
                title=entry.get("title", ""),
                url=entry.get("url", ""),
                starts_at=starts_at,
                ends_at=ends_at,
                is_online=is_online,
                prize_text=_strip_html(entry.get("prize_amount")),
                location=location,
                themes=[t.get("name") for t in entry.get("themes", []) if t.get("name")],
                raw=entry,
            )
        except Exception:
            logger.warning("devpost: failed to parse entry %r", entry.get("id"), exc_info=True)
            return None
