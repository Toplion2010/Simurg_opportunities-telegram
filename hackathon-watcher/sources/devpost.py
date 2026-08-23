"""Devpost source — JSON API, easiest to verify.

GET https://devpost.com/api/hackathons?status[]=open&order_by=recently-added&page=N
"""

from __future__ import annotations

import dataclasses
import html as html_module
import json
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

import config
from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

API_URL = "https://devpost.com/api/hackathons"

DESCRIPTION_MAX_CHARS = 400
DESCRIPTION_MIN_CHARS = 40  # below this, likely Devpost's own truncated boilerplate stub

# Present on nearly every Devpost hackathon regardless of actual audience —
# not a meaningful restriction, so excluded from the surfaced eligibility.
_ELIGIBILITY_BOILERPLATE = ("legal age", "all countries")

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


def _organizer(name: str | None) -> str | None:
    """Devpost's own API sometimes echoes back the literal placeholder
    'other' (an unfilled category selector, not a real org name)."""
    if name and name.strip().lower() != "other":
        return name
    return None


def _absolute_url(url: str | None) -> str | None:
    """devpost's thumbnail_url is sometimes protocol-relative ('//host/...'),
    and when an organizer never uploaded a real thumbnail it's Devpost's own
    generic gray icon-grid placeholder — not a real image, so treated as
    none (the pipeline falls back to a generated image or text-only)."""
    if not url:
        return None
    if "thumbnail-placeholder" in url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    try:
        cleaned = BeautifulSoup(text, "html.parser").get_text(strip=True)
        return cleaned or None
    except Exception:
        logger.warning("devpost: failed to strip HTML from prize text", exc_info=True)
        return text


def _parse_json_ld(soup: BeautifulSoup) -> dict | None:
    tag = soup.select_one("#challenge-json-ld")
    if tag is None or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except Exception:
        logger.warning("devpost: enrich: failed to parse challenge-json-ld", exc_info=True)
        return None


def _extract_description(ld: dict) -> str | None:
    try:
        raw = ld.get("description")
        if not raw:
            return None
        unescaped = html_module.unescape(raw)
        text = BeautifulSoup(unescaped, "html.parser").get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < DESCRIPTION_MIN_CHARS:
            # Organizers who never wrote a real description leave Devpost's
            # own short auto-generated stub (e.g. "About the challenge Get
            # starte[d]") — not worth showing over no description at all.
            return None
        if len(text) <= DESCRIPTION_MAX_CHARS:
            return text
        truncated = text[:DESCRIPTION_MAX_CHARS].rsplit(" ", 1)[0]
        return truncated + "…"
    except Exception:
        logger.warning("devpost: enrich: failed to extract description", exc_info=True)
        return None


def _extract_deadline(ld: dict) -> date | None:
    try:
        end_date = ld.get("endDate")
        if not end_date:
            return None
        return datetime.fromisoformat(end_date).date()
    except Exception:
        logger.warning("devpost: enrich: failed to extract deadline", exc_info=True)
        return None


def _extract_prize_breakdown(soup: BeautifulSoup) -> list[str]:
    try:
        breakdown = []
        for item in soup.select('div[id^="prize_"]'):
            title_el = item.select_one(".prize-title")
            value_el = item.select_one(".prize-value")
            if title_el is None or value_el is None:
                continue
            title = title_el.get_text(" ", strip=True)
            value = re.sub(r"\s+", " ", value_el.get_text(" ", strip=True)).strip()
            value = re.sub(r"([$€£₹])\s+(?=\d)", r"\1", value)
            if title and value:
                breakdown.append(f"{title}: {value}")
        return breakdown
    except Exception:
        logger.warning("devpost: enrich: failed to extract prize breakdown", exc_info=True)
        return []


def _extract_eligibility(soup: BeautifulSoup) -> str | None:
    try:
        items = soup.select("#eligibility-list li")
        restrictions = []
        for li in items:
            text = li.get_text(" ", strip=True)
            if not text:
                continue
            if any(text.lower().startswith(b) or b in text.lower() for b in _ELIGIBILITY_BOILERPLATE):
                continue
            restrictions.append(text)
        return "; ".join(restrictions) or None
    except Exception:
        logger.warning("devpost: enrich: failed to extract eligibility", exc_info=True)
        return None


def _extract_sponsors(soup: BeautifulSoup) -> list[str]:
    try:
        tiles = soup.select_one("#sponsor-tiles")
        if tiles is None:
            return []
        return [img.get("alt") for img in tiles.select("img[alt]") if img.get("alt")]
    except Exception:
        logger.warning("devpost: enrich: failed to extract sponsors", exc_info=True)
        return []


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
                image_url=_absolute_url(entry.get("thumbnail_url")),
                organizer=_organizer(entry.get("organization_name")),
                themes=[t.get("name") for t in entry.get("themes", []) if t.get("name")],
                raw=entry,
            )
        except Exception:
            logger.warning("devpost: failed to parse entry %r", entry.get("id"), exc_info=True)
            return None

    def enrich(self, hackathon: Hackathon) -> Hackathon:
        try:
            response = get(
                hackathon.url,
                timeout=config.ENRICH_DETAIL_TIMEOUT,
                retries=config.ENRICH_DETAIL_RETRIES,
            )
            response.raise_for_status()
        except Exception:
            logger.warning("devpost: enrich: fetch failed for %s", hackathon.url, exc_info=True)
            return hackathon

        soup = BeautifulSoup(response.text, "html.parser")
        ld = _parse_json_ld(soup)
        if ld is None:
            logger.warning(
                "devpost: enrich: no challenge-json-ld found for %s, "
                "page structure may have changed",
                hackathon.url,
            )
            return hackathon

        return dataclasses.replace(
            hackathon,
            description=_extract_description(ld),
            prize_breakdown=_extract_prize_breakdown(soup),
            eligibility=_extract_eligibility(soup),
            required_tech=[],  # no reliable structured source on Devpost
            deadline=_extract_deadline(ld),
            sponsors=_extract_sponsors(soup),
        )
