"""SIREL (sirel.org) — 174 verified STEM programs, read from its WordPress API.

Metadata comes from the open WP REST API (`/wp-json/wp/v2/program`), which is
clean, paginated and gives every taxonomy as term ids we resolve to names once
per run.

The official program URL is the one thing the API does NOT expose: the
"Go To Website" button is rendered by Elementor into the /database/ listing,
and the program detail pages carry no outbound link at all. Since apply_link is
what Simurg hashes for dedup, falling back to a sirel.org URL would both send
students one hop short and stop scraped items from colliding with the same
opportunity posted on Telegram. So we walk the listing to build a
post_id -> official_url map.

That listing paginates only through JetEngine's admin-ajax handler — every GET
variant (?jet_paged, /page/2/, ?_page, ?pagenum) serves page 1. We therefore
lift the request payload verbatim out of the grid's own `data-nav` attribute
rather than hardcoding it, so a settings change on their side is carried along
instead of breaking us. If any of that fails the item still ships, with
apply_url=None and the sirel.org page as the link — degraded, never dropped.

Note sirel.org intermittently answers 403 to automated clients; Fetcher retries
that status for exactly this reason.
"""
import html
import json
import re

from src.collector.web.base import WebItem, WebSource
from src.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://sirel.org"
API_URL = f"{BASE_URL}/wp-json/wp/v2/program"
LISTING_URL = f"{BASE_URL}/database/"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"

# rest_base -> WebItem-facing role. All seven are program-only taxonomies.
TAXONOMIES = (
    "grade",
    "subject-area",
    "skill-level",
    "duration",
    "tuition",
    "format",
    "type-of-activity",
)

_TAG_RE = re.compile(r"<[^>]+>")
_POST_ID_RE = re.compile(r'data-post-id="(\d+)"')
_ANCHOR_RE = re.compile(r'<a\b[^>]*href="(https?://[^"]+)"', re.I)
_GO_TO_SITE_RE = re.compile(r"go\s*to\s*website", re.I)
_DATA_NAV_RE = re.compile(r'data-nav="([^"]*)"')
_DATA_PAGES_RE = re.compile(r'data-pages="(\d+)"')

# Cap the listing walk. 174 programs / 10 per page = 18, so this is headroom,
# not a limit we expect to hit — but an unbounded loop against someone else's
# AJAX endpoint is not something to ship.
MAX_LISTING_PAGES = 25

_FORMAT_ONLINE = {
    "remote": True,
    "online": True,
    "virtual": True,
    "hybrid": True,
    "in person": False,
    "in-person": False,
    "onsite": False,
}


def _strip(fragment: str | None) -> str | None:
    if not fragment:
        return None
    value = html.unescape(_TAG_RE.sub(" ", fragment))
    value = " ".join(value.split())
    return value or None


def _flatten(prefix: str, obj, out: dict) -> dict:
    """urlencode a nested dict the way jQuery does, which is what the AJAX
    handler expects."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            _flatten(f"{prefix}[{key}]", value, out)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _flatten(f"{prefix}[{index}]", value, out)
    elif obj is None or obj is False:
        out[prefix] = ""
    elif obj is True:
        out[prefix] = "1"
    else:
        out[prefix] = str(obj)
    return out


class SirelSource(WebSource):
    name = "sirel"

    def __init__(self, fetcher) -> None:
        self._fetcher = fetcher
        self._programs: dict[str, dict] = {}
        self._terms: dict[str, dict[int, str]] = {}
        self._link_map: dict[int, str] | None = None

    # ---------------------------------------------------------------- discover

    def discover(self) -> list[str]:
        self._programs = {}
        page = 1
        while True:
            try:
                response = self._fetcher.get(
                    API_URL, params={"per_page": 100, "page": page}
                )
            except Exception:
                logger.exception("sirel_api_failed", page=page)
                break

            try:
                batch = response.json()
            except ValueError:
                logger.exception("sirel_api_not_json", page=page)
                break
            if not isinstance(batch, list) or not batch:
                break

            for program in batch:
                slug = program.get("slug")
                if slug:
                    self._programs[slug] = program

            total_pages = int(response.headers.get("x-wp-totalpages", page) or page)
            if page >= total_pages:
                break
            page += 1

        logger.info("sirel_discovered", count=len(self._programs))
        return list(self._programs)

    # ------------------------------------------------------------------- fetch

    def fetch(self, external_ids: list[str]) -> list[WebItem]:
        if not external_ids:
            return []
        if not self._programs:
            self.discover()

        self._load_terms()
        link_map = self._load_link_map()

        items: list[WebItem] = []
        for slug in external_ids:
            program = self._programs.get(slug)
            if program is None:
                continue
            try:
                items.append(self._build(program, link_map))
            except Exception:
                logger.exception("sirel_item_failed", slug=slug)
        return items

    def _build(self, program: dict, link_map: dict[int, str]) -> WebItem:
        names = {
            taxonomy: [
                self._terms.get(taxonomy, {}).get(term_id)
                for term_id in program.get(taxonomy) or []
            ]
            for taxonomy in TAXONOMIES
        }

        def first(taxonomy: str) -> str | None:
            values = [v for v in names.get(taxonomy, []) if v]
            return values[0] if values else None

        fmt = (first("format") or "").strip().lower()
        tuition = first("tuition")

        # "Paid" with no amount is UNKNOWN, not expensive. Inventing a number
        # here would let the admission filter reject on a value we made up.
        cost_amount = 0.0 if (tuition or "").strip().lower() == "free" else None

        return WebItem(
            source=self.name,
            external_id=program["slug"],
            title=_strip((program.get("title") or {}).get("rendered")) or program["slug"],
            page_url=program.get("link") or f"{BASE_URL}/program/{program['slug']}/",
            apply_url=link_map.get(program.get("id")),
            description=_strip((program.get("content") or {}).get("rendered"))
            or _strip((program.get("excerpt") or {}).get("rendered")),
            organizer=None,  # SIREL does not record the running organisation
            deadline=None,  # nor a deadline — do not infer one from dates
            starts_at=None,
            cost_amount=cost_amount,
            cost_currency="USD" if cost_amount else None,
            cost_text=tuition,
            eligibility=", ".join(v for v in names.get("grade", []) if v) or None,
            duration=first("duration"),
            country=None,
            is_online=_FORMAT_ONLINE.get(fmt),
            grades=[v for v in names.get("grade", []) if v],
            subjects=[v for v in names.get("subject-area", []) if v]
            + [v for v in names.get("type-of-activity", []) if v],
            image_url=None,
            raw={"skill_level": first("skill-level"), "format": first("format")},
        )

    # ------------------------------------------------------------- taxonomies

    def _load_terms(self) -> None:
        for taxonomy in TAXONOMIES:
            if taxonomy in self._terms:
                continue
            mapping: dict[int, str] = {}
            try:
                response = self._fetcher.get(
                    f"{BASE_URL}/wp-json/wp/v2/{taxonomy}", params={"per_page": 100}
                )
                for term in response.json():
                    if isinstance(term, dict) and "id" in term:
                        mapping[term["id"]] = _strip(term.get("name")) or ""
            except Exception:
                logger.exception("sirel_taxonomy_failed", taxonomy=taxonomy)
            self._terms[taxonomy] = mapping

    # --------------------------------------------------------------- link map

    def _load_link_map(self) -> dict[int, str]:
        """post_id -> official program URL, walked from the /database/ listing.

        Cached for the life of the source instance (one run). Every failure
        path returns whatever was collected so far: a partial map costs some
        items their official link, which is strictly better than losing them.
        """
        if self._link_map is not None:
            return self._link_map

        mapping: dict[int, str] = {}
        self._link_map = mapping

        try:
            page_html = self._fetcher.get(LISTING_URL).text
        except Exception:
            logger.exception("sirel_listing_failed")
            return mapping

        mapping.update(self._parse_cards(page_html))

        nav_match = _DATA_NAV_RE.search(page_html)
        pages_match = _DATA_PAGES_RE.search(page_html)
        if not nav_match or not pages_match:
            logger.warning("sirel_listing_no_pagination", found=len(mapping))
            return mapping

        try:
            nav = json.loads(html.unescape(nav_match.group(1)))
        except ValueError:
            logger.exception("sirel_nav_unparsable")
            return mapping

        total_pages = min(int(pages_match.group(1)), MAX_LISTING_PAGES)
        base_body = {"action": "jet_engine_ajax", "handler": "listing_load_more"}
        _flatten("query", nav.get("query") or {}, base_body)
        _flatten("widget_settings", nav.get("widget_settings") or {}, base_body)

        for page in range(2, total_pages + 1):
            body = dict(base_body, page=str(page), **{"query[page]": str(page)})
            try:
                response = self._fetcher.post(
                    AJAX_URL,
                    data=body,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": LISTING_URL,
                    },
                )
                fragment = (response.json().get("data") or {}).get("html", "")
            except Exception:
                logger.exception("sirel_listing_page_failed", page=page)
                break
            if not fragment:
                break
            mapping.update(self._parse_cards(fragment))

        logger.info("sirel_link_map", entries=len(mapping), pages=total_pages)
        return mapping

    @staticmethod
    def _parse_cards(fragment: str) -> dict[int, str]:
        """Split the grid into per-card chunks and take each card's outbound link.

        Anchored on the "Go To Website" label rather than "first off-site href"
        so a share button or a sponsor logo can never be mistaken for the
        program's own URL.
        """
        mapping: dict[int, str] = {}
        boundaries = [m.start() for m in _POST_ID_RE.finditer(fragment)]
        for index, start in enumerate(boundaries):
            end = boundaries[index + 1] if index + 1 < len(boundaries) else len(fragment)
            card = fragment[start:end]
            post_id = int(_POST_ID_RE.search(card).group(1))
            label = _GO_TO_SITE_RE.search(card)
            if not label:
                continue
            anchors = [
                m.group(1)
                for m in _ANCHOR_RE.finditer(card[: label.start()])
                if "sirel.org" not in m.group(1)
            ]
            if anchors:
                mapping[post_id] = html.unescape(anchors[-1])
        return mapping
