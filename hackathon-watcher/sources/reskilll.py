"""reskilll source — https://reskilll.com/discover.

Most of the page is a client-rendered SPA shell (skeleton loaders never
populated by plain HTTP), but the actual event cards for the current
"featured/trending" set ARE server-rendered as `<a target="_blank">` cards
carrying a calendar icon (dates), a map-pin icon (location), a trophy icon
(prize), and a top-right badge ("Online" / "In person"). We select on that
icon structure rather than utility-class soup, since Tailwind class names
are the first thing to rot on a redesign.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

DISCOVER_URL = "https://reskilll.com/discover"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# Month is optional so a range's second half — reskilll often renders it as
# a bare day, e.g. "Sep 20 - 21, 2026" — still matches.
_MONTH_DAY_RE = re.compile(
    r"(?:(?P<month>[A-Za-z]{3,9})\s+)?(?<!\d)(?P<day>\d{1,2})(?!\d)"
)
_YEAR_RE = re.compile(r"\b(\d{4})\b")


def _parse_date_range(text: str | None) -> tuple[date | None, date | None]:
    """reskilll shows dates like 'May 15 - Jun 14, 2026' or 'Aug 30, 2026'.
    Never raises; unparseable input yields (None, None)."""
    if not text:
        return None, None
    try:
        year_match = _YEAR_RE.search(text)
        year = int(year_match.group(1)) if year_match else date.today().year

        matches = list(_MONTH_DAY_RE.finditer(text))
        if not matches:
            return None, None

        def _to_date(m: re.Match, fallback_month: int | None) -> date | None:
            month_name = m.group("month")
            month = _MONTHS.get(month_name[:3].lower()) if month_name else fallback_month
            if month is None:
                return None
            try:
                return date(year, month, int(m.group("day")))
            except ValueError:
                return None

        start = _to_date(matches[0], None)
        end = _to_date(matches[-1], fallback_month=start.month if start else None) if len(matches) > 1 else start
        return start, end
    except Exception:
        logger.warning("reskilll: failed to parse date range %r", text, exc_info=True)
        return None, None


def _icon_span_text(card, icon_class: str) -> str | None:
    icon = card.select_one(f"svg.{icon_class}")
    if icon is None:
        return None
    span = icon.find_parent("span")
    if span is None:
        return None
    text = span.get_text(strip=True)
    return text or None


class ReskilllSource(Source):
    name = "reskilll"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(DISCOVER_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            cards = [
                a for a in soup.select('a[target="_blank"]')
                if a.select_one("h3") and a.select_one("svg.lucide-calendar")
            ]
            if not cards:
                logger.warning(
                    "reskilll: expected event cards not found, selectors may have rotted"
                )
                return []

            hackathons: list[Hackathon] = []
            for card in cards:
                hackathon = self._parse_card(card)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("reskilll: fetch failed, returning []", exc_info=True)
            return []

    def _parse_card(self, card) -> Hackathon | None:
        try:
            url = card.get("href")
            if not url:
                return None
            title_el = card.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""

            date_text = _icon_span_text(card, "lucide-calendar")
            starts_at, ends_at = _parse_date_range(date_text)

            location = _icon_span_text(card, "lucide-map-pin")
            prize_text = _icon_span_text(card, "lucide-trophy")

            is_online = None
            badge = card.select_one("span.absolute.top-3.right-3")
            if badge:
                badge_text = badge.get_text(strip=True).lower()
                if "online" in badge_text:
                    is_online = True
                elif "person" in badge_text:
                    is_online = False

            themes = [
                t.get_text(strip=True)
                for t in card.select("span.rounded-full.border")
                if t.get_text(strip=True)
            ]

            cover_img = card.select_one('img[data-nimg="fill"]')
            image_url = cover_img.get("src") if cover_img else None

            organizer_span = card.select_one("div.flex.items-center.gap-2 span.truncate")
            organizer = organizer_span.get_text(strip=True) if organizer_span else None

            return Hackathon(
                source=self.name,
                source_id=url,
                title=title,
                url=url,
                starts_at=starts_at,
                ends_at=ends_at,
                is_online=is_online,
                prize_text=prize_text,
                location=location,
                image_url=image_url,
                organizer=organizer,
                themes=themes,
                raw={"html": str(card)[:2000]},
            )
        except Exception:
            logger.warning("reskilll: failed to parse card", exc_info=True)
            return None
