"""Hack Club Hackathons source — https://hackathons.hackclub.com/.

Next.js page embedding the full event list as clean JSON in
`<script id="__NEXT_DATA__">` — no HTML scraping needed. Skews
high-school/student-run events; tagged with a "highschool" theme so the
whole cluster can be toggled off via EXCLUDE_THEMES if it turns out to
dominate the feed.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

LISTING_URL = "https://hackathons.hackclub.com/"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _parse_iso(text: str | None):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class HackClubSource(Source):
    name = "hackclub"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(LISTING_URL)
            response.raise_for_status()

            events = self._extract_events(response.text)
            if events is None:
                logger.warning(
                    "hackclub: __NEXT_DATA__ events not found, page structure may have changed"
                )
                return []

            hackathons: list[Hackathon] = []
            for event in events:
                hackathon = self._parse_event(event)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("hackclub: fetch failed, returning []", exc_info=True)
            return []

    def _extract_events(self, html: str) -> list[dict] | None:
        m = _NEXT_DATA_RE.search(html)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
            return data["props"]["pageProps"]["events"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _parse_event(self, event: dict) -> Hackathon | None:
        try:
            event_id = event.get("id")
            name = event.get("name")
            website = event.get("website")
            if not event_id or not name or not website:
                return None

            is_online = bool(event.get("virtual"))
            location = None
            if not is_online:
                parts = [p for p in (event.get("city"), event.get("state"), event.get("country")) if p]
                location = ", ".join(parts) if parts else None

            return Hackathon(
                source=self.name,
                source_id=str(event_id),
                title=name,
                url=website,
                starts_at=_parse_iso(event.get("start")),
                ends_at=_parse_iso(event.get("end")),
                is_online=is_online,
                prize_text=None,
                location=location,
                image_url=event.get("banner") or event.get("logo"),
                organizer=None,
                themes=["highschool"],
                raw={},
            )
        except Exception:
            logger.warning("hackclub: failed to parse event", exc_info=True)
            return None
