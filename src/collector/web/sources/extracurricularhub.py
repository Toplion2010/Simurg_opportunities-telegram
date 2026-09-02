"""ExtracurricularHub — ~1,760 listings, read from schema.org JSON-LD.

Two-stage: sitemap-opportunities.xml gives every item slug, then one detail
page per new slug. Both are explicitly permitted by robots.txt, which
Allow:s /extracurriculars/ (and even allow-lists GPTBot) while disallowing
/api/ — so this reads the public pages a search engine reads, and never the
internal API.

Fields come from the page's JSON-LD rather than CSS selectors, so a visual
redesign does not break parsing. The one exception is the deadline, which is
only in a `<th scope="row">` key-facts table; that regex is narrow and failing
it yields None rather than a wrong date.
"""
import html
import json
import re

from src.collector.web.base import WebItem, WebSource
from src.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://extracurricularhub.com"
SITEMAP_URL = f"{BASE_URL}/sitemap-opportunities.xml"
ITEM_URL = f"{BASE_URL}/extracurriculars/{{slug}}"

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I
)
_KEY_FACT_RE = re.compile(
    r'<tr>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*</tr>', re.S | re.I
)
_TAG_RE = re.compile(r"<[^>]+>")

# ExtracurricularHub generates this description for every listing. It states
# nothing the structured fields do not already carry, and publishing it would
# put another site's name in our card copy, so it is dropped and to_dto
# composes a description from the facts instead.
_BOILERPLATE_RE = re.compile(
    r"is a .{0,40}opportunity listed on ExtracurricularHub", re.IGNORECASE
)

# Placeholders the key-facts table uses for "we don't know yet".
_EMPTY_VALUES = {
    "",
    "coming soon",
    "varies",
    "n/a",
    "na",
    "tbd",
    "tba",
    "not specified",
    "unknown",
    "—",
    "-",
}

_ATTENDANCE = {
    "onlineeventattendancemode": True,
    "offlineeventattendancemode": False,
    # Hybrid counts as reachable: a Kazakh student can take the online leg.
    "mixedeventattendancemode": True,
}


def _text(fragment: str | None) -> str | None:
    if not fragment:
        return None
    value = html.unescape(_TAG_RE.sub(" ", fragment))
    value = " ".join(value.split())
    return value or None


def _clean_value(fragment: str | None) -> str | None:
    value = _text(fragment)
    if value is None or value.strip().lower() in _EMPTY_VALUES:
        return None
    return value


def _ld_objects(page: str) -> list[dict]:
    """Every JSON-LD object on the page, @graph flattened."""
    objects: list[dict] = []
    for block in _LD_RE.findall(page):
        try:
            parsed = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for entry in parsed if isinstance(parsed, list) else [parsed]:
            if not isinstance(entry, dict):
                continue
            graph = entry.get("@graph")
            objects.extend(
                node
                for node in (graph if isinstance(graph, list) else [entry])
                if isinstance(node, dict)
            )
    return objects


def _first_of_type(objects: list[dict], type_name: str) -> dict:
    for node in objects:
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if type_name in types:
            return node
    return {}


def _nested_name(node: dict, key: str) -> str | None:
    value = node.get(key)
    if isinstance(value, dict):
        return value.get("name")
    if isinstance(value, str):
        return value
    return None


class ExtracurricularHubSource(WebSource):
    name = "extracurricularhub"

    def __init__(self, fetcher) -> None:
        self._fetcher = fetcher

    def discover(self) -> list[str]:
        try:
            response = self._fetcher.get(SITEMAP_URL)
        except Exception:
            logger.exception("ech_sitemap_failed", url=SITEMAP_URL)
            return []

        slugs: list[str] = []
        seen: set[str] = set()
        for loc in _LOC_RE.findall(response.text):
            if "/extracurriculars/" not in loc:
                continue
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            if slug and slug not in seen:
                seen.add(slug)
                slugs.append(slug)

        logger.info("ech_discovered", count=len(slugs))
        return slugs

    def fetch(self, external_ids: list[str]) -> list[WebItem]:
        items: list[WebItem] = []
        for slug in external_ids:
            try:
                item = self._fetch_one(slug)
            except Exception:
                logger.exception("ech_item_failed", slug=slug)
                continue
            if item is not None:
                items.append(item)
        return items

    def _fetch_one(self, slug: str) -> WebItem | None:
        url = ITEM_URL.format(slug=slug)
        page = self._fetcher.get(url).text
        objects = _ld_objects(page)
        if not objects:
            logger.warning("ech_no_jsonld", slug=slug)
            return None

        event = _first_of_type(objects, "Event")
        program = _first_of_type(objects, "EducationalOccupationalProgram")
        if not event and not program:
            logger.warning("ech_no_program_node", slug=slug)
            return None

        title = event.get("name") or program.get("name")
        if not title:
            return None

        offers = event.get("offers") or program.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        price = offers.get("price")
        try:
            cost_amount = float(price) if price is not None else None
        except (TypeError, ValueError):
            cost_amount = None

        mode = str(event.get("eventAttendanceMode") or "").rsplit("/", 1)[-1].lower()
        is_online = _ATTENDANCE.get(mode)
        if is_online is None:
            program_mode = str(program.get("educationalProgramMode") or "").lower()
            if program_mode == "online":
                is_online = True
            elif program_mode == "blended":
                is_online = True
            elif program_mode in ("onsite", "on-site", "full-time"):
                is_online = False

        address = {}
        location = event.get("location")
        if isinstance(location, dict):
            address = location.get("address") or {}
            if not isinstance(address, dict):
                address = {}

        facts = {
            (_text(label) or "").lower(): _clean_value(value)
            for label, value in _KEY_FACT_RE.findall(page)
        }

        description = program.get("description") or event.get("description")
        if description and _BOILERPLATE_RE.search(description):
            description = None

        return WebItem(
            source=self.name,
            external_id=slug,
            title=_text(title) or slug,
            page_url=url,
            apply_url=offers.get("url"),
            description=_text(description),
            organizer=_nested_name(event, "organizer") or _nested_name(program, "provider"),
            deadline=facts.get("application deadline") or facts.get("deadline"),
            starts_at=event.get("startDate"),
            cost_amount=cost_amount,
            cost_currency=offers.get("priceCurrency"),
            cost_text=facts.get("cost"),
            eligibility=program.get("programPrerequisites") or facts.get("eligibility"),
            country=address.get("addressCountry"),
            is_online=is_online,
            grades=[],
            subjects=[program.get("occupationalCategory")]
            if program.get("occupationalCategory")
            else [],
            image_url=event.get("image") if isinstance(event.get("image"), str) else None,
            raw={"facts": facts},
        )
