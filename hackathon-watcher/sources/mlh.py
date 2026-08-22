"""MLH source — https://mlh.io/events redirects to the current season page.

The event list isn't in plain markup; it's a JSON blob embedded in
`<script data-page="app" type="application/json">` (server-rendered props).
We extract that instead of CSS-selecting cards, but the same "defensive,
log-and-return-[] on drift" rule applies.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

EVENTS_URL = "https://mlh.io/events"
_DATA_SCRIPT_RE = re.compile(
    r'<script data-page="app" type="application/json">(.*?)</script>', re.S
)


def _parse_iso(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _find_events(obj) -> list[dict] | None:
    """The events list lives under props.upcomingEvents in current markup,
    but walk the tree defensively in case the path shifts."""
    if isinstance(obj, dict):
        for key in ("upcomingEvents", "events"):
            value = obj.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict) and "slug" in value[0]:
                return value
        for value in obj.values():
            found = _find_events(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_events(item)
            if found is not None:
                return found
    return None


class MlhSource(Source):
    name = "mlh"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(EVENTS_URL)
            response.raise_for_status()

            match = _DATA_SCRIPT_RE.search(response.text)
            if not match:
                logger.warning(
                    "mlh: expected data script tag not found, selectors may have rotted"
                )
                return []

            data = json.loads(match.group(1))
            events = _find_events(data)
            if not events:
                logger.warning(
                    "mlh: could not locate events list in page data, selectors may have rotted"
                )
                return []

            hackathons: list[Hackathon] = []
            for entry in events:
                hackathon = self._parse_entry(entry)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("mlh: fetch failed, returning []", exc_info=True)
            return []

    def _parse_entry(self, entry: dict) -> Hackathon | None:
        try:
            url = entry.get("websiteUrl") or entry.get("url", "")
            if not url:
                return None

            format_type = (entry.get("formatType") or "").lower()
            is_online = {"digital": True, "physical": False, "hybrid": False}.get(format_type)

            themes = entry.get("customFields", {}).get("hackathon_focus", []) or []

            return Hackathon(
                source=self.name,
                source_id=url,
                title=entry.get("name", ""),
                url=url,
                starts_at=_parse_iso(entry.get("startsAt")),
                ends_at=_parse_iso(entry.get("endsAt")),
                is_online=is_online,
                prize_text=None,
                location=entry.get("location"),
                themes=list(themes),
                raw=entry,
            )
        except Exception:
            logger.warning("mlh: failed to parse entry %r", entry.get("slug"), exc_info=True)
            return None
