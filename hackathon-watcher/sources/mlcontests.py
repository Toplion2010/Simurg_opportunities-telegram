"""ML Contests source — https://mlcontests.github.io/competitions.json.

A plain, openly published JSON file (no API key, no scraping) aggregating
the whole ML/data-science competition cluster — Kaggle, Zindi, AIcrowd,
DrivenData, CodaLab, and dozens more — that would otherwise each need their
own scraper or a browser. Tagged "competition" (not "hackathon") so this
whole cluster can be toggled off in one config line if it dominates the feed.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

DATA_URL = "https://mlcontests.github.io/competitions.json"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# "1 Aug 2026" / "06 Jan 2025" — day may or may not be zero-padded.
_DATE_RE = re.compile(r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3,9})\s+(?P<year>\d{4})")


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    month = _MONTHS.get(m.group("month")[:3].lower())
    if month is None:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


class MlContestsSource(Source):
    name = "mlcontests"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(DATA_URL)
            response.raise_for_status()
            payload = response.json()
            entries = payload.get("data", [])
            if not entries:
                logger.warning(
                    "mlcontests: competitions.json returned no data, schema may have changed"
                )
                return []

            hackathons: list[Hackathon] = []
            for entry in entries:
                hackathon = self._parse_entry(entry)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("mlcontests: fetch failed, returning []", exc_info=True)
            return []

    def _parse_entry(self, entry: dict) -> Hackathon | None:
        try:
            name = entry.get("name")
            url = entry.get("url")
            if not name or not url:
                return None

            platform = entry.get("platform") or ""
            is_online = platform.strip().lower() != "in-person"

            themes = ["competition"] + [t for t in entry.get("tags", []) if t]

            return Hackathon(
                source=self.name,
                source_id=url,
                title=name,
                url=url,
                starts_at=_parse_date(entry.get("launched")),
                ends_at=_parse_date(entry.get("deadline")),
                is_online=is_online,
                prize_text=entry.get("prize"),
                location=None if is_online else "In-person",
                organizer=entry.get("sponsor"),
                themes=themes,
                raw={"platform": platform} if platform else {},
            )
        except Exception:
            logger.warning("mlcontests: failed to parse entry", exc_info=True)
            return None
