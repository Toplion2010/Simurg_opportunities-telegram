"""Devfolio source — https://devfolio.co/hackathons.

The list isn't in plain markup cards; it's a React Query cache dehydrated
into `<script id="__NEXT_DATA__" type="application/json">`, under
props.pageProps.dehydratedState.queries[].state.data.open_hackathons. We
walk defensively for that key instead of hardcoding the query index, since
Next.js can reorder queries.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import date, datetime

import config
from pipeline.text import strip_markdown
from sources.base import Hackathon, Source
from sources.http import get

logger = logging.getLogger(__name__)

HACKATHONS_URL = "https://devfolio.co/hackathons"
_DATA_SCRIPT_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

DESCRIPTION_MAX_CHARS = 400
# Common markdown noise devfolio organizers' "desc" text carries — stripped
# rather than rendered, since the Telegram caption is plain text.


def _parse_iso(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        return None


_strip_markdown = strip_markdown


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
            settings = entry.get("settings", {}) or {}
            image_url = settings.get("featured_cover_img_v2") or settings.get("featured_cover_img")

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
                image_url=image_url or None,
                organizer=None,
                themes=themes,
                raw=entry,
            )
        except Exception:
            logger.warning("devfolio: failed to parse entry %r", entry.get("slug"), exc_info=True)
            return None

    def enrich(self, hackathon: Hackathon) -> Hackathon:
        """Each event's own devfolio.co subdomain (a devfolio-controlled
        template, not the organizer's arbitrary site) embeds real prize and
        description data the listing page doesn't carry."""
        try:
            response = get(
                hackathon.url, timeout=config.ENRICH_DETAIL_TIMEOUT, retries=config.ENRICH_DETAIL_RETRIES
            )
            response.raise_for_status()
        except Exception:
            logger.warning("devfolio: enrich: fetch failed for %s", hackathon.url, exc_info=True)
            return hackathon

        match = _DATA_SCRIPT_RE.search(response.text)
        if not match:
            logger.warning(
                "devfolio: enrich: __NEXT_DATA__ not found for %s, page structure may have changed",
                hackathon.url,
            )
            return hackathon

        try:
            data = json.loads(match.group(1))
            page_props = data["props"]["pageProps"]
        except Exception:
            logger.warning("devfolio: enrich: failed to parse page data for %s", hackathon.url, exc_info=True)
            return hackathon

        return dataclasses.replace(
            hackathon,
            description=self._extract_description(page_props),
            prize_text=self._extract_prize(page_props),
            sponsors=self._extract_sponsors(page_props),
        )

    def _extract_description(self, page_props: dict) -> str | None:
        try:
            h = page_props.get("hackathon") or {}
            raw = h.get("desc") or h.get("tagline")
            if not raw:
                return None
            text = _strip_markdown(raw)
            if not text:
                return None
            if len(text) <= DESCRIPTION_MAX_CHARS:
                return text
            return text[:DESCRIPTION_MAX_CHARS].rsplit(" ", 1)[0] + "…"
        except Exception:
            logger.warning("devfolio: enrich: failed to extract description", exc_info=True)
            return None

    def _extract_prize(self, page_props: dict) -> str | None:
        try:
            value = page_props.get("aggregatePrizeValue")
            currency = page_props.get("aggregatePrizeCurrency")
            if not value:
                return None
            amount = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
            return f"{currency} {amount}" if currency else amount
        except Exception:
            logger.warning("devfolio: enrich: failed to extract prize", exc_info=True)
            return None

    def _extract_sponsors(self, page_props: dict) -> list[str]:
        try:
            h = page_props.get("hackathon") or {}
            names = []
            for tier in h.get("sponsor_tiers", []) or []:
                for sponsor in tier.get("sponsors", []) or []:
                    name = sponsor.get("name")
                    if name:
                        names.append(name)
            return names
        except Exception:
            logger.warning("devfolio: enrich: failed to extract sponsors", exc_info=True)
            return []
