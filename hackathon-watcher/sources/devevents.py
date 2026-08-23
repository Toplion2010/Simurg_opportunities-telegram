"""dev.events source — RSS feed, filtered to hackathon-tagged entries.

Falls back to scraping https://dev.events/hackathons if the feed doesn't
carry enough hackathon-tagged entries (defensive against the feed dropping
the category or being restructured).
"""

from __future__ import annotations

import logging
import re
from datetime import date

import feedparser
from bs4 import BeautifulSoup

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

RSS_URL = "https://dev.events/rss.xml"
FALLBACK_URL = "https://dev.events/hackathons"
MIN_EXPECTED_ENTRIES = 1

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_DATE_RE = r"[A-Za-z]+ \d{1,2}, \d{4}"
_ONLINE_RE = re.compile(rf"^(?P<date>{_DATE_RE}), Online$")
_LOCATION_RE = re.compile(rf"^(?P<date>{_DATE_RE}) in (?P<location>.+)$")


def _parse_date(text: str) -> date | None:
    try:
        month_name, rest = text.split(" ", 1)
        day_str, year_str = rest.split(", ")
        month = _MONTHS.get(month_name.strip().lower())
        if month is None:
            return None
        return date(int(year_str), month, int(day_str.strip()))
    except Exception:
        return None


def _parse_description(description: str) -> tuple[date | None, bool | None, str | None]:
    """Description looks like 'X is happening on <date>[, Online | in <loc>].
    More information: <url>'. Returns (start_date, is_online, location)."""
    try:
        marker = "is happening on "
        idx = description.find(marker)
        if idx == -1:
            return None, None, None
        tail = description[idx + len(marker):]
        tail = tail.split(". More information:")[0].strip()

        m = _ONLINE_RE.match(tail)
        if m:
            return _parse_date(m.group("date")), True, "Online"

        m = _LOCATION_RE.match(tail)
        if m:
            return _parse_date(m.group("date")), False, m.group("location").strip()

        return None, None, None
    except Exception:
        logger.warning("devevents: failed to parse description %r", description, exc_info=True)
        return None, None, None


def _entry_is_hackathon(entry) -> bool:
    tags = [t.get("term", "").lower() for t in getattr(entry, "tags", [])]
    return "hackathon" in tags


class DevEventsSource(Source):
    name = "devevents"

    def fetch(self) -> list[Hackathon]:
        try:
            hackathons = self._fetch_from_rss()
            if len(hackathons) < MIN_EXPECTED_ENTRIES:
                logger.warning(
                    "devevents: RSS returned only %d hackathon entries, "
                    "falling back to scraping /hackathons",
                    len(hackathons),
                )
                fallback = self._fetch_from_scrape()
                if fallback:
                    return fallback
            return hackathons
        except Exception:
            logger.warning("devevents: fetch failed, returning []", exc_info=True)
            return []

    def _fetch_from_rss(self) -> list[Hackathon]:
        response = get(RSS_URL)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)

        hackathons: list[Hackathon] = []
        for entry in parsed.entries:
            if not _entry_is_hackathon(entry):
                continue
            hackathon = self._parse_entry(entry)
            if hackathon is not None:
                hackathons.append(hackathon)
        return hackathons

    def _parse_entry(self, entry) -> Hackathon | None:
        try:
            url = entry.get("link", "")
            title = entry.get("title", "")
            description = entry.get("description", "")
            starts_at, is_online, location = _parse_description(description)
            themes = [t.get("term") for t in getattr(entry, "tags", []) if t.get("term")]
            enclosures = getattr(entry, "enclosures", [])
            image_url = enclosures[0].get("href") if enclosures else None

            return Hackathon(
                source=self.name,
                source_id=url,
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
                raw=dict(entry) if hasattr(entry, "keys") else {},
            )
        except Exception:
            logger.warning("devevents: failed to parse entry", exc_info=True)
            return None

    def _fetch_from_scrape(self) -> list[Hackathon]:
        try:
            response = get(FALLBACK_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            cards = soup.select("a[href*='/conferences/'], a[href*='/hackathons/']")
            if not cards:
                logger.warning(
                    "devevents: expected event links not found on fallback page, "
                    "selectors may have rotted"
                )
                return []

            hackathons: list[Hackathon] = []
            seen_urls: set[str] = set()
            for card in cards:
                href = card.get("href")
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)
                url = href if href.startswith("http") else f"https://dev.events{href}"
                title = card.get_text(strip=True)
                if not title:
                    continue
                hackathons.append(
                    Hackathon(
                        source=self.name,
                        source_id=url,
                        title=title,
                        url=url,
                        starts_at=None,
                        ends_at=None,
                        is_online=None,
                        prize_text=None,
                        location=None,
                        themes=[],
                        raw={"href": href},
                    )
                )
            return hackathons
        except Exception:
            logger.warning("devevents: fallback scrape failed, returning []", exc_info=True)
            return []
