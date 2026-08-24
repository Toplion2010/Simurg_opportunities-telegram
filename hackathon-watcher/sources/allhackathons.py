"""allhackathons.com source — https://allhackathons.com/themes/online/.

Server-rendered, paginated (~60 pages at current volume, sorted
newest-added-first — not by date, so page 1 mixes upcoming/open/ended
items). Capped to config.ALLHACKATHONS_PAGE_CAP pages: we only care about
recently added listings, and the pipeline's own still_open filter drops
anything already ended regardless of which page it came from.
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

BASE_URL = "https://allhackathons.com"
ONLINE_THEME_URL = f"{BASE_URL}/themes/online/"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# "Aug. 31, 2026" — trailing period on the month is optional.
_DATE_RE = re.compile(r"(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})")


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group("month")[:3].lower())
    if month is None:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


def _parse_date_range(text: str | None) -> tuple[date | None, date | None]:
    """'Aug. 31, 2026 - Sept. 3, 2026' -> (start, end)."""
    if not text:
        return None, None
    parts = text.split(" - ", 1)
    start = _parse_date(parts[0])
    end = _parse_date(parts[1]) if len(parts) > 1 else start
    return start, end


class AllHackathonsSource(Source):
    name = "allhackathons"

    def fetch(self) -> list[Hackathon]:
        hackathons: list[Hackathon] = []
        try:
            for page in range(1, config.ALLHACKATHONS_PAGE_CAP + 1):
                params = {"page": page} if page > 1 else {}
                response = get(ONLINE_THEME_URL, params=params)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                cards = soup.select("div.row.align-items-center.bg-white.mb-4.py-5.px-4")
                if not cards:
                    if page == 1:
                        logger.warning(
                            "allhackathons: expected event cards not found, selectors may have rotted"
                        )
                    break

                for card in cards:
                    hackathon = self._parse_card(card)
                    if hackathon is not None:
                        hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("allhackathons: fetch failed, returning what was collected so far", exc_info=True)
            return hackathons

    def _parse_card(self, card) -> Hackathon | None:
        try:
            title_el = card.select_one("a.h5.text-darkblue")
            if title_el is None:
                return None
            title = title_el.get_text(strip=True)
            href = title_el.get("href")
            if not title or not href:
                return None
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            source_id = href.rstrip("/").rsplit("/", 1)[-1]

            date_el = card.select_one("p")
            starts_at, ends_at = _parse_date_range(date_el.get_text(strip=True) if date_el else None)

            badge_el = card.select_one("span.badge")
            badge = badge_el.get_text(strip=True).lower() if badge_el else ""
            is_online = "online" in badge if badge else None
            location = None if is_online else (badge.title() if badge else None)

            desc_el = card.select_one("p.text-muted")
            description = desc_el.get_text(" ", strip=True) if desc_el else None

            themes = [
                t.get_text(strip=True)
                for t in card.select('a[href^="/themes/"]')
                if t.get_text(strip=True)
            ]

            img_el = card.select_one("img")
            image_url = img_el.get("src") if img_el else None
            if image_url and not image_url.startswith("http"):
                image_url = f"{BASE_URL}{image_url}"

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
                organizer=None,
                themes=themes,
                description=description,
                raw={},
            )
        except Exception:
            logger.warning("allhackathons: failed to parse card", exc_info=True)
            return None
