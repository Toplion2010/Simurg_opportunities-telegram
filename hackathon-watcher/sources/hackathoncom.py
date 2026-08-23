"""hackathon.com source — https://www.hackathon.com/online.

The site has no single "all hackathons" listing; it's organized by
theme/location/online tabs instead. We use the /online tab specifically —
it's the one tab that doesn't require picking a theme, and it lines up with
this pipeline's own ONLINE_ONLY default filter, so nothing fetched here is
wasted on events the pipeline would drop anyway. Server-rendered, single
page (no pagination seen at current volume).
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

ONLINE_URL = "https://www.hackathon.com/online"
BASE_URL = "https://www.hackathon.com"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# "01 Jul - 12:00 AM" — day, month, no year (listing is upcoming-only).
_DATE_RE = re.compile(r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3,9})")


def _parse_date(text: str | None, today: date | None = None) -> date | None:
    """No year is ever shown, so assume the current year, rolling to next
    year if that would land in the past (the listing is upcoming-only)."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group("month")[:3].lower())
    if month is None:
        return None
    today = today or date.today()
    try:
        result = date(today.year, month, int(m.group("day")))
    except ValueError:
        return None
    if result < today:
        try:
            result = date(today.year + 1, month, int(m.group("day")))
        except ValueError:
            return None
    return result


class HackathonComSource(Source):
    name = "hackathoncom"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(ONLINE_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            cards = soup.select("div.ht-event-card")
            if not cards:
                logger.warning(
                    "hackathoncom: expected event cards not found, selectors may have rotted"
                )
                return []

            hackathons: list[Hackathon] = []
            for card in cards:
                hackathon = self._parse_card(card)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("hackathoncom: fetch failed, returning []", exc_info=True)
            return []

    def _parse_card(self, card) -> Hackathon | None:
        try:
            title_el = card.select_one("a.ht-event-card__title")
            if title_el is None:
                return None
            title = title_el.get_text(strip=True)
            href = title_el.get("href")
            if not title or not href:
                return None
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            source_id = href.rstrip("/").rsplit("/", 1)[-1]

            date_el = card.select_one(".ht-event-card__date")
            starts_at = _parse_date(date_el.get_text(strip=True) if date_el else None)

            location_el = card.select_one(".ht-event-card__location")
            location_text = location_el.get_text(strip=True) if location_el else None
            is_online = location_text is not None and "online" in location_text.lower()
            location = None if is_online else location_text

            desc_el = card.select_one(".ht-event-card__desc")
            description = desc_el.get_text(" ", strip=True) if desc_el else None

            themes = [
                t.get_text(strip=True)
                for t in card.select(".ht-event-topics__tag")
                if t.get_text(strip=True)
            ]

            banner_el = card.select_one("a.ht-event-card__banner")
            image_url = None
            if banner_el is not None:
                style = banner_el.get("style", "")
                m = re.search(r'url\(["\']?([^"\')]+)', style)
                image_url = m.group(1) if m else None

            return Hackathon(
                source=self.name,
                source_id=source_id,
                title=title,
                url=url,
                starts_at=starts_at,
                ends_at=None,
                is_online=is_online,
                prize_text=None,
                location=location,
                image_url=image_url,
                organizer=None,
                themes=themes,
                raw={"description": description} if description else {},
            )
        except Exception:
            logger.warning("hackathoncom: failed to parse card", exc_info=True)
            return None
