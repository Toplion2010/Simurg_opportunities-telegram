"""ETHGlobal source — https://ethglobal.com/events.

Server-rendered event list (no JS needed). Every event type (hackathon,
meetup, co-working, conference, summit) shares one card structure with a
type badge; only "Hackathon" (in-person) and "Online" badges are real
hackathons — the rest are meetups/conferences and are filtered out here.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

EVENTS_URL = "https://ethglobal.com/events"
BASE_URL = "https://ethglobal.com"

_HACKATHON_BADGES = {"hackathon", "online"}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# "Jul 24th" / "Feb 11th, 2026" — ordinal suffix and year both optional.
_DATE_RE = re.compile(
    r"(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,\s*(?P<year>\d{4}))?"
)


def _parse_date(text: str, fallback_year: int | None) -> date | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group("month")[:3].lower())
    if month is None:
        return None
    year_str = m.group("year")
    year = int(year_str) if year_str else fallback_year
    if year is None:
        return None
    try:
        return date(year, month, int(m.group("day")))
    except ValueError:
        return None


def _parse_date_range(times: list[str]) -> tuple[date | None, date | None]:
    """Two <time> texts, e.g. ["Jul 24th", "Jul 26th, 2026"] — the year
    usually only appears on the later one and applies to both."""
    if not times:
        return None, None
    end_year_match = _DATE_RE.search(times[-1])
    fallback_year = int(end_year_match.group("year")) if end_year_match and end_year_match.group("year") else None

    end = _parse_date(times[-1], fallback_year)
    start = _parse_date(times[0], fallback_year or (end.year if end else None))
    if start is None:
        start = end
    return start, end


class EthGlobalSource(Source):
    name = "ethglobal"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(EVENTS_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            cards = soup.select('a[href^="/events/"].cursor-pointer')
            if not cards:
                logger.warning(
                    "ethglobal: expected event cards not found, selectors may have rotted"
                )
                return []

            hackathons: list[Hackathon] = []
            for card in cards:
                hackathon = self._parse_card(card)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("ethglobal: fetch failed, returning []", exc_info=True)
            return []

    def _parse_card(self, card) -> Hackathon | None:
        try:
            badge_el = card.select_one("div.rounded-sm")
            badge = badge_el.get_text(strip=True).lower() if badge_el else ""
            if badge not in _HACKATHON_BADGES:
                return None

            href = card.get("href")
            if not href:
                return None
            url = f"{BASE_URL}{href}"
            source_id = href.rsplit("/", 1)[-1]

            title_el = card.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            time_texts = [t.get_text(strip=True) for t in card.select("time")]
            starts_at, ends_at = _parse_date_range(time_texts)

            is_online = badge == "online"
            location = None
            if not is_online:
                loc_ps = card.select("div.flex-4.hidden.md\\:flex.flex-col p")
                loc_parts = [p.get_text(strip=True) for p in loc_ps if p.get_text(strip=True)]
                location = ", ".join(loc_parts) if loc_parts else None

            img_el = card.select_one("img")
            image_url = img_el.get("src") if img_el else None

            return Hackathon(
                source=self.name,
                source_id=source_id,
                title=title,
                url=url,
                starts_at=starts_at,
                ends_at=ends_at,
                is_online=is_online,
                prize_text=None,
                location=location,
                image_url=image_url,
                organizer="ETHGlobal",
                themes=["web3"],
                raw={},
            )
        except Exception:
            logger.warning("ethglobal: failed to parse card", exc_info=True)
            return None
