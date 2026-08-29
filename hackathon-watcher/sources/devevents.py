"""dev.events source — RSS feed, filtered to hackathon-tagged entries.

Falls back to scraping https://dev.events/hackathons if the feed doesn't
carry enough hackathon-tagged entries (defensive against the feed dropping
the category or being restructured).
"""

from __future__ import annotations

import dataclasses
import html as html_module
import json
import logging
import re
from datetime import date, datetime

import feedparser
from bs4 import BeautifulSoup

import config
from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

RSS_URL = "https://dev.events/rss.xml"
FALLBACK_URL = "https://dev.events/hackathons"
MIN_EXPECTED_ENTRIES = 1

DESCRIPTION_MAX_CHARS = 400
# dev.events auto-generates a description from the event's category and format
# ("Crypto / Blockchain hackathon Online"), which says nothing the card doesn't
# already show. Same floor as Devpost's boilerplate-stub guard.
DESCRIPTION_MIN_CHARS = 40

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


def _extract_embedded_event_url(soup: BeautifulSoup) -> str | None:
    """dev.events pages for externally-hosted events are a thin wrapper that
    iframes the real event site (dorahacks.io, ...). The wrapper carries no
    description of its own and frequently renders "Something went wrong while
    talking to the server", so the iframe target is both the only source of
    real content and the better link to post."""
    iframe = soup.select_one("div.iframe-wrapper iframe[src]")
    if iframe is None:
        return None
    src = (iframe.get("src") or "").strip()
    if not src.startswith(("http://", "https://")) or "dev.events" in src:
        return None
    return src


def _parse_json_ld(soup: BeautifulSoup) -> dict | None:
    """dev.events renders its detail pages client-side, so the served HTML has
    almost no body text. The schema.org block is the only structured data in it."""
    for tag in soup.select('script[type="application/ld+json"]'):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
        except Exception:
            continue
        if isinstance(data, list):
            data = next(
                (d for d in data if isinstance(d, dict) and "event" in str(d.get("@type", "")).lower()),
                None,
            )
        if isinstance(data, dict) and "event" in str(data.get("@type", "")).lower():
            return data
    return None


def _extract_end_date(ld: dict) -> date | None:
    """The RSS feed carries only a start date; endDate is detail-page only."""
    try:
        raw = ld.get("endDate")
        if not raw:
            return None
        return datetime.fromisoformat(raw).date()
    except Exception:
        logger.warning("devevents: enrich: failed to parse endDate %r", ld.get("endDate"))
        return None


def _extract_description(ld: dict) -> str | None:
    try:
        raw = ld.get("description")
        if not raw:
            return None
        text = BeautifulSoup(html_module.unescape(raw), "html.parser").get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < DESCRIPTION_MIN_CHARS:
            return None
        if len(text) <= DESCRIPTION_MAX_CHARS:
            return text
        return text[:DESCRIPTION_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    except Exception:
        logger.warning("devevents: enrich: failed to extract description", exc_info=True)
        return None


def _extract_is_online(ld: dict) -> bool | None:
    mode = str(ld.get("eventAttendanceMode", ""))
    if "OnlineEventAttendanceMode" in mode:
        return True
    if "OfflineEventAttendanceMode" in mode:
        return False
    return None  # mixed or unspecified — leave the listing's value alone


def _extract_organizer(ld: dict, title: str) -> str | None:
    """dev.events often fills performer/organizer with the event's own name,
    which would just repeat the headline on the card."""
    for key in ("organizer", "performer"):
        node = ld.get(key)
        if isinstance(node, list):
            node = node[0] if node else None
        if isinstance(node, dict):
            name = (node.get("name") or "").strip()
        elif isinstance(node, str):
            name = node.strip()
        else:
            name = ""
        if name and name.casefold() != (title or "").strip().casefold():
            return name
    return None


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

    def enrich(self, hackathon: Hackathon) -> Hackathon:
        """Pull the detail page's schema.org block for the fields RSS omits.

        The feed gives only title/start date/location/tags, so an end date never
        reached the card. Anything the page doesn't improve on keeps its
        listing-level value rather than being overwritten with None.
        """
        try:
            response = get(
                hackathon.url,
                timeout=config.ENRICH_DETAIL_TIMEOUT,
                retries=config.ENRICH_DETAIL_RETRIES,
            )
            response.raise_for_status()
        except Exception:
            logger.warning("devevents: enrich: fetch failed for %s", hackathon.url, exc_info=True)
            return hackathon

        soup = BeautifulSoup(response.text, "html.parser")

        # Repoint at the real event site before anything else: the wrapper's
        # own schema.org description is dev.events boilerplate ("Crypto /
        # Blockchain hackathon Online"), so leaving the url here would leave
        # the generic fallback nothing to read either.
        embedded_url = _extract_embedded_event_url(soup)

        ld = _parse_json_ld(soup)
        if ld is None:
            logger.warning(
                "devevents: enrich: no schema.org event block found for %s, "
                "page structure may have changed",
                hackathon.url,
            )
            return dataclasses.replace(hackathon, url=embedded_url) if embedded_url else hackathon

        updates = dict(
            ends_at=_extract_end_date(ld) or hackathon.ends_at,
            description=_extract_description(ld),
            is_online=(
                is_online if (is_online := _extract_is_online(ld)) is not None
                else hackathon.is_online
            ),
            organizer=_extract_organizer(ld, hackathon.title) or hackathon.organizer,
        )
        if embedded_url:
            updates["url"] = embedded_url
        return dataclasses.replace(hackathon, **updates)

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
