"""ZhasLink scraper, against four real rows of its public `opportunities` table.

No network. The cases that matter: credentials are lifted from the site's own
bundle (and a missing bundle degrades to empty, never raises), finished events
the site forgot to archive are dropped, and a tenge price never reaches the
USD-denominated admission filter as a raw number.
"""
import json
import pathlib
from datetime import date

import pytest

from src.collector.web.filters import admits
from src.collector.web.sources import zhaslink
from src.collector.web.sources.zhaslink import ZhasLinkSource, _cost, _is_stale, _slug

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "web"

API = "https://abcdefgh.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.c2lnbmF0dXJl"
LISTING = '<html><script type="module" src="/assets/index-AbC123.js"></script></html>'
BUNDLE = f'const u="{API}",k="{KEY}";createClient(u,k)'

CAMP = "b5297c59-ab7d-48b7-894d-b19275423af7"  # Astana, ended 2026-03-28
VERITAS = "8a856d83-2b84-4b80-b144-6821558993d7"  # online, "paid", no dates
OLYMPIAD = "e8900573-0a68-4dd8-b57e-c4c189ff275a"  # Astana, no dates
GEOMETRY = "8f620c1e-0451-416f-988e-3a5deedb7f42"  # online, "10.000 тенге"


def _rows() -> list[dict]:
    return json.loads(
        (FIXTURES / "zhaslink_opportunities.json").read_text(encoding="utf-8")
    )


class FakeResponse:
    def __init__(self, text: str = "", payload=None) -> None:
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeFetcher:
    def __init__(self, rows=None, listing: str = LISTING, bundle: str = BUNDLE) -> None:
        self.rows = _rows() if rows is None else rows
        self.listing = listing
        self.bundle = bundle
        self.api_calls: list[dict] = []

    def get(self, url, **kwargs):
        if url == zhaslink.LISTING_URL:
            return FakeResponse(self.listing)
        if url.endswith("/assets/index-AbC123.js"):
            return FakeResponse(self.bundle)
        if url == f"{API}/rest/v1/opportunities":
            self.api_calls.append(kwargs)
            offset = int(kwargs["params"]["offset"])
            return FakeResponse(payload=self.rows[offset : offset + zhaslink.PAGE_SIZE])
        raise AssertionError(f"unexpected GET: {url}")


@pytest.fixture
def before_camp_ended(monkeypatch):
    """Pin 'today' to while the camp was still upcoming, so all four rows are live."""

    class FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 3, 1)

    monkeypatch.setattr(zhaslink, "date", FixedDate)


def test_credentials_come_from_the_bundle_and_query_is_public_only(before_camp_ended):
    fetcher = FakeFetcher()
    ids = ZhasLinkSource(fetcher).discover()

    assert set(ids) == {CAMP, VERITAS, OLYMPIAD, GEOMETRY}
    (call,) = fetcher.api_calls
    assert call["headers"] == {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    assert call["params"]["archived"] == "eq.false"
    # Explicit columns: their user ids never enter our database.
    assert "created_by" not in call["params"]["select"]
    assert call["params"]["select"] != "*"


def test_finished_events_are_dropped_at_discover():
    ids = ZhasLinkSource(FakeFetcher()).discover()
    assert CAMP not in ids
    assert {VERITAS, OLYMPIAD, GEOMETRY} <= set(ids)


def test_is_stale_uses_latest_end_date_and_treats_no_dates_as_open():
    today = date(2026, 9, 29)
    assert _is_stale({"end_date": "2026-03-28"}, today)
    assert not _is_stale({"end_date": "2026-03-28", "event_date": "2026-10-01"}, today)
    assert not _is_stale({"start_date": "2025-10-13"}, today)
    assert not _is_stale({}, today)


def test_item_fields(before_camp_ended):
    source = ZhasLinkSource(FakeFetcher())
    source.discover()
    items = {i.external_id: i for i in source.fetch([CAMP, VERITAS, OLYMPIAD, GEOMETRY])}

    camp = items[CAMP]
    assert camp.title == "Engineering Camp for Teens 2026"  # leading emoji gone
    assert camp.page_url == (
        "https://zhaslink.invisionu.education/en/opportunities/"
        "engineering-camp-for-teens-2026-b5297c59"
    )
    assert camp.apply_url == "https://forms.gle/QUicAuizbaazZaq37"
    assert camp.organizer == "American Corner & Makerspace Astana"
    assert camp.is_online is False
    assert camp.country == "Astana, Kazakhstan"
    assert camp.cost_amount == 0.0
    assert camp.starts_at == "2026-03-26"
    assert "Grade 9" in camp.grades
    assert camp.subjects[0] == "Course"
    assert camp.description.startswith("Engineering Camp is a three-day")
    assert "**" not in camp.description

    veritas = items[VERITAS]
    assert veritas.is_online is True
    assert veritas.country is None
    assert veritas.cost_amount is None  # "paid" with no number is unknown
    assert veritas.cost_text == "Paid"

    geometry = items[GEOMETRY]
    assert geometry.cost_amount is None
    assert geometry.cost_text == "10.000 тенге"


def test_tenge_price_does_not_trip_the_usd_fee_filter(before_camp_ended):
    """An in-person Kazakh event priced in tenge must not read as $10,000."""
    row = next(r for r in _rows() if r["id"] == GEOMETRY)
    row = dict(row, region="Almaty")
    source = ZhasLinkSource(FakeFetcher(rows=[row]))
    source.discover()
    (item,) = source.fetch([GEOMETRY])
    assert item.is_online is False
    assert admits(item) == (True, "admitted")


def test_cost_parsing():
    assert _cost("free") == (0.0, None, "Free")
    assert _cost("paid") == (None, None, "Paid")
    assert _cost("$238 - $276 ") == (238.0, "USD", "$238 - $276")
    assert _cost("$1,200") == (1200.0, "USD", "$1,200")
    assert _cost("2000 Тенге") == (None, None, "2000 Тенге")
    assert _cost(None) == (None, None, None)


def test_slug_matches_site_urls():
    # Both taken from the site's own sitemap.
    assert (
        _slug("National IT Championship 2025–2026", "1f999497-x")
        == "national-it-championship-20252026-1f999497"
    )
    assert (
        _slug(
            "UNOPS Competition for the EU Civil Society Facility in Central Asia",
            "21ed5812-x",
        )
        == "unops-competition-for-the-eu-civil-society-facility-in-centr-21ed5812"
    )
    assert _slug("", "abcdef12-x") == "abcdef12"


@pytest.mark.parametrize(
    "listing,bundle",
    [
        ("<html>redesigned, no module script</html>", BUNDLE),
        (LISTING, "bundle with no supabase config"),
    ],
)
def test_markup_change_degrades_to_empty(listing, bundle):
    assert ZhasLinkSource(FakeFetcher(listing=listing, bundle=bundle)).discover() == []


def test_network_failure_never_raises():
    class Broken:
        def get(self, url, **kwargs):
            raise ConnectionError("down")

    source = ZhasLinkSource(Broken())
    assert source.discover() == []
    assert source.fetch([VERITAS]) == []
