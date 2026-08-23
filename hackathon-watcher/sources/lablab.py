"""lablab.ai source — https://lablab.ai/ai-hackathons.

The listing page's card grid is client-rendered (Next.js bails to
client-side rendering for the body), but the page still embeds a real
schema.org ItemList in a server-rendered `<script type="application/ld+json">`
tag: title + url for the first ~24 hackathons, in the site's own default
(soonest/featured-first) order. Each hackathon's own detail page similarly
embeds a real schema.org Event with dates, attendance mode, and a
prize-pool figure inside its description text — also server-rendered JSON-LD,
not part of the client-rendered shell. No browser needed for either step.

Two requests per item (listing + each detail page) is heavier than most
sources, so detail fetches are capped at config.LABLAB_DETAIL_CAP.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import config
from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

LISTING_URL = "https://lablab.ai/ai-hackathons"

_LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_PRIZE_RE = re.compile(r"\$[\d,]+(?:\.\d+)?\s*Prize Pool", re.IGNORECASE)


def _parse_iso(text: str | None):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _extract_ld_blocks(html: str) -> list[dict]:
    blocks = []
    for m in _LD_JSON_RE.finditer(html):
        try:
            blocks.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return blocks


class LablabSource(Source):
    name = "lablab"

    def fetch(self) -> list[Hackathon]:
        try:
            response = get(LISTING_URL)
            response.raise_for_status()
            items = self._extract_listing_items(response.text)
            if not items:
                logger.warning(
                    "lablab: expected ItemList JSON-LD not found, page structure may have changed"
                )
                return []

            hackathons: list[Hackathon] = []
            for item in items[: config.LABLAB_DETAIL_CAP]:
                hackathon = self._fetch_detail(item)
                if hackathon is not None:
                    hackathons.append(hackathon)
            return hackathons
        except Exception:
            logger.warning("lablab: fetch failed, returning []", exc_info=True)
            return []

    def _extract_listing_items(self, html: str) -> list[dict]:
        for block in _extract_ld_blocks(html):
            graph = block.get("@graph") if isinstance(block, dict) else None
            if not graph:
                continue
            item_list = next((g for g in graph if g.get("@type") == "ItemList"), None)
            if item_list:
                return [
                    {"name": el.get("name"), "url": el.get("url")}
                    for el in item_list.get("itemListElement", [])
                    if el.get("name") and el.get("url")
                ]
        return []

    def _fetch_detail(self, item: dict) -> Hackathon | None:
        try:
            response = get(
                item["url"], timeout=config.ENRICH_DETAIL_TIMEOUT, retries=config.ENRICH_DETAIL_RETRIES
            )
            response.raise_for_status()
        except Exception:
            logger.warning("lablab: detail fetch failed for %s", item["url"], exc_info=True)
            return None

        event = next(
            (b for b in _extract_ld_blocks(response.text) if isinstance(b, dict) and b.get("@type") == "Event"),
            None,
        )
        if event is None:
            logger.warning("lablab: no Event JSON-LD found for %s", item["url"])
            return None

        return self._parse_event(item["url"], event)

    def _parse_event(self, url: str, event: dict) -> Hackathon | None:
        try:
            title = event.get("name")
            if not title:
                return None

            mode = event.get("eventAttendanceMode") or ""
            is_online = "Online" in mode if mode else None

            location = None
            loc = event.get("location")
            if isinstance(loc, dict) and loc.get("@type") != "VirtualLocation":
                address = loc.get("address")
                if isinstance(address, dict):
                    parts = [address.get(k) for k in ("addressLocality", "addressCountry") if address.get(k)]
                    location = ", ".join(parts) if parts else loc.get("name")
                else:
                    location = loc.get("name")

            description = event.get("description") or ""
            prize_match = _PRIZE_RE.search(description)
            prize_text = prize_match.group(0).replace("Prize Pool", "").strip() if prize_match else None

            source_id = url.rstrip("/").rsplit("/", 1)[-1]

            return Hackathon(
                source=self.name,
                source_id=source_id,
                title=title,
                url=event.get("url") or url,
                starts_at=_parse_iso(event.get("startDate")),
                ends_at=_parse_iso(event.get("endDate")),
                is_online=is_online,
                prize_text=prize_text,
                location=location,
                image_url=event.get("image"),
                organizer="lablab.ai",
                themes=["ai"],
                raw={},
            )
        except Exception:
            logger.warning("lablab: failed to parse event for %s", url, exc_info=True)
            return None
