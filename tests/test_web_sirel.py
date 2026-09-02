"""SIREL scraper, against saved copies of its real WP API and listing markup.

No network. The interesting cases are the two things SIREL does badly:
its API omits the official program URL (so we join the listing by post id),
and it states "Paid" with no amount (which must read as unknown, not as
expensive — otherwise the admission filter rejects on a number we invented).
"""
import json
import pathlib

from src.collector.web.sources.sirel import SirelSource

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "web"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload=None, text: str = "", headers: dict | None = None) -> None:
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeFetcher:
    def __init__(self, listing_html: str = "", ajax_pages: list[str] | None = None) -> None:
        self.listing_html = listing_html
        self.ajax_pages = ajax_pages or []
        self.posts: list[str] = []

    def get(self, url, **kwargs):
        if "/wp-json/wp/v2/program" in url:
            page = (kwargs.get("params") or {}).get("page", 1)
            if int(page) > 1:
                return FakeResponse([], headers={"x-wp-totalpages": "1"})
            return FakeResponse(_load("sirel_programs.json"), headers={"x-wp-totalpages": "1"})
        for tax in (
            "grade", "subject-area", "skill-level", "duration",
            "tuition", "format", "type-of-activity",
        ):
            if url.endswith(f"/wp-json/wp/v2/{tax}"):
                return FakeResponse(_load(f"sirel_tax_{tax}.json"))
        if url.rstrip("/").endswith("/database"):
            return FakeResponse(text=self.listing_html)
        raise AssertionError(f"unexpected GET: {url}")

    def post(self, url, **kwargs):
        self.posts.append(url)
        if self.ajax_pages:
            return FakeResponse({"data": {"html": self.ajax_pages.pop(0)}})
        return FakeResponse({"data": {"html": ""}})


def _listing() -> str:
    return (FIXTURES / "sirel_listing_fragment.html").read_text(encoding="utf-8")


def test_discover_returns_every_program_slug():
    source = SirelSource(FakeFetcher())
    slugs = source.discover()
    assert slugs == ["national-science-bee", "junior-solar-sprint", "mathcounts"]


def test_taxonomy_ids_resolve_to_names():
    source = SirelSource(FakeFetcher())
    source.discover()
    (bee, sprint, _) = source.fetch(
        ["national-science-bee", "junior-solar-sprint", "mathcounts"]
    )
    assert bee.grades == ["Middle School"]
    assert bee.eligibility == "Middle School"
    assert bee.duration == "1 day"
    assert sprint.duration == "6 months"


def test_format_taxonomy_maps_to_is_online():
    source = SirelSource(FakeFetcher())
    source.discover()
    items = {i.external_id: i for i in source.fetch(["national-science-bee", "mathcounts"])}
    assert items["national-science-bee"].is_online is True  # Hybrid
    assert items["mathcounts"].is_online is True  # Remote


def test_free_tuition_becomes_a_zero_cost():
    source = SirelSource(FakeFetcher())
    source.discover()
    (item,) = source.fetch(["national-science-bee"])
    assert item.cost_text == "Free"
    assert item.cost_amount == 0.0


def test_paid_without_an_amount_stays_unknown():
    """SIREL's tuition taxonomy is only Free/Paid. Inventing a number for
    "Paid" would let the admission filter reject on a value we made up."""
    fetcher = FakeFetcher()
    source = SirelSource(fetcher)
    programs = _load("sirel_programs.json")
    programs[0]["tuition"] = [44]  # Paid
    source._programs = {p["slug"]: p for p in programs}
    source._load_terms()
    (item,) = source.fetch(["national-science-bee"])
    assert item.cost_text == "Paid"
    assert item.cost_amount is None


def test_html_is_stripped_from_the_rendered_description():
    source = SirelSource(FakeFetcher())
    source.discover()
    (item,) = source.fetch(["national-science-bee"])
    assert item.description
    assert "<p>" not in item.description
    assert "quiz competition" in item.description


def test_official_url_is_joined_from_the_listing_by_post_id():
    """The API exposes no outbound link, so apply_url comes from the listing
    card. Without this join every SIREL item would link to sirel.org and stop
    colliding with the same opportunity posted on Telegram."""
    source = SirelSource(FakeFetcher(listing_html=_listing()))
    source.discover()
    items = {i.external_id: i for i in source.fetch(["national-science-bee", "junior-solar-sprint"])}
    assert items["national-science-bee"].apply_url == "https://www.iacompetitions.com/emssciencebee/"
    assert items["junior-solar-sprint"].apply_url == "https://www.usaeop.com/program/jss/"


def test_missing_listing_degrades_to_no_apply_url():
    # Listing unreachable -> the item still ships, just without the official
    # link. Degraded, never dropped.
    source = SirelSource(FakeFetcher(listing_html=""))
    source.discover()
    (item,) = source.fetch(["national-science-bee"])
    assert item.apply_url is None
    assert item.page_url.startswith("https://sirel.org/program/")


def test_link_map_is_built_once_per_run():
    fetcher = FakeFetcher(listing_html=_listing())
    source = SirelSource(fetcher)
    source.discover()
    source.fetch(["national-science-bee"])
    first = source._link_map
    source.fetch(["mathcounts"])
    assert source._link_map is first


def test_fetch_of_unknown_slug_is_skipped_not_raised():
    source = SirelSource(FakeFetcher())
    source.discover()
    assert source.fetch(["does-not-exist"]) == []


def test_ajax_pagination_walks_the_rest_of_the_listing():
    """Pages 2..N exist only behind JetEngine's admin-ajax handler — every GET
    variant (?jet_paged, /page/2/, ?_page, ?pagenum) serves page 1. The payload
    is lifted from the grid's own data-nav rather than hardcoded, so this
    asserts we read it and keep walking."""
    nav = (
        '{&quot;query&quot;:{&quot;post_type&quot;:&quot;program&quot;},'
        '&quot;widget_settings&quot;:{&quot;lisitng_id&quot;:&quot;583&quot;}}'
    )
    page1 = f'<div data-nav="{nav}" data-page="1" data-pages="3">{_listing()}</div>'
    page2 = (
        '<div data-post-id="3001">'
        '<a href="https://example.edu/prog"><h2>Go To Website</h2></a></div>'
    )
    fetcher = FakeFetcher(listing_html=page1, ajax_pages=[page2, ""])
    source = SirelSource(fetcher)
    source.discover()
    source.fetch(["national-science-bee"])

    assert fetcher.posts, "expected the AJAX handler to be called for page 2"
    assert source._link_map[3001] == "https://example.edu/prog"
    # Page 1's entries survive the walk.
    assert source._link_map[3994] == "https://www.iacompetitions.com/emssciencebee/"


def test_card_without_a_go_to_website_label_is_skipped():
    """Anchored on the label, not on 'first off-site href', so a share button
    or sponsor logo can never be mistaken for the program's own URL."""
    nav = '{&quot;query&quot;:{},&quot;widget_settings&quot;:{}}'
    html = (
        f'<div data-nav="{nav}" data-page="1" data-pages="1">'
        '<div data-post-id="4242">'
        '<a href="https://facebook.com/share">Share</a></div></div>'
    )
    source = SirelSource(FakeFetcher(listing_html=html))
    source.discover()
    source.fetch(["national-science-bee"])
    assert 4242 not in source._link_map
