"""Devfolio source — https://devfolio.co/hackathons.

The list isn't in plain markup cards; it's a React Query cache dehydrated
into `<script id="__NEXT_DATA__" type="application/json">`, under
props.pageProps.dehydratedState.queries[].state.data.open_hackathons. We
walk defensively for that key instead of hardcoding the query index, since
Next.js can reorder queries.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

HACKATHONS_URL = "https://devfolio.co/hackathons"
_DATA_SCRIPT_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _parse_iso(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        return None


def _find_open_hackathons(obj) -> list[dict] | None:
    if isinstance(obj, dict):
        if isinstance(obj.get("open_hackathons"), list):
            return obj["open_hackathons"]
        for value in obj.values():
            found = _find_open_hackathons(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_open_hackathons(item)
            if found is not None:
                return found
    return None


class DevfolioSource(Source):
    name = "devfolio"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(HACKATHONS_URL)
            response.raise_for_status()

            match = _DATA_SCRIPT_RE.search(response.text)
            if not match:
                logger.warning(
                    "devfolio: expected __NEXT_DATA__ script tag not found, "
                    "selectors may have rotted"
                )
                return []

            data = json.loads(match.group(1))
            entries = _find_open_hackathons(data)
            if entries is None:
                logger.warning(
                    "devfolio: could not locate open_hackathons in page data, "
                    "selectors may have rotted"
                )
                return []

            hackathons: list[Hackathon] = []
            for entry in entries:
                hackathon = self._parse_entry(entry)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("devfolio: fetch failed, returning []", exc_info=True)
            return []

    def _parse_entry(self, entry: dict) -> Hackathon | None:
        try:
            slug = entry.get("slug")
            if not slug:
                return None
            url = f"https://{slug}.devfolio.co/"

            themes = [
                t.get("theme", {}).get("name")
                for t in entry.get("themes", [])
                if t.get("theme", {}).get("name")
            ]

            return Hackathon(
                source=self.name,
                source_id=url,
                title=entry.get("name", ""),
                url=url,
                starts_at=_parse_iso(entry.get("starts_at")),
                ends_at=_parse_iso(entry.get("ends_at")),
                is_online=entry.get("is_online"),
                prize_text=None,
                location=None,
                themes=themes,
                raw=entry,
            )
        except Exception:
            logger.warning("devfolio: failed to parse entry %r", entry.get("slug"), exc_info=True)
            return None
