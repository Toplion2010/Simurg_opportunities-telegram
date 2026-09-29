import asyncio
import pathlib
from types import SimpleNamespace

from src.collector.web import http as web_http
from src.collector.web.sources.doqworld import DoqWorldSource
from src.collector.web.to_dto import build_dto
from src.core.enums import Audience, OpportunityStatus
from src.db.models.opportunity import Opportunity
from src.processor.deduplicator import Deduplicator
from src.publisher.formatter import format_opportunity

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "web"
PAGE_URL = "https://doq.world/competitions/art-for-equity-competition"
OFFICIAL_URL = "https://www.legaleaglebee.com/art-for-equity-competition"


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeFetcher:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes

    def get(self, url, **kwargs):
        for marker, body in self.routes.items():
            if marker in url:
                if isinstance(body, Exception):
                    raise body
                return FakeResponse(str(body))
        raise AssertionError(f"unexpected URL: {url}")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def parsed_item(page: str | None = None):
    source = DoqWorldSource(FakeFetcher({"art-for-equity": page or fixture("doq_art_for_equity.html")}))
    return source.fetch(["art-for-equity-competition"])[0]


def test_discover_returns_only_unique_competition_slugs():
    source = DoqWorldSource(FakeFetcher({"sitemap.xml": fixture("doq_sitemap.xml")}))
    assert source.discover() == ["art-for-equity-competition", "ippf"]


def test_parses_visible_opportunity_facts_and_organizer_link():
    item = parsed_item()
    assert item.title == "Art for Equity Competition"
    assert item.organizer == "Legal Eagle Bee"
    assert item.apply_url == OFFICIAL_URL
    assert item.deadline == "Jul 31, 2026, 11:59 PM (UTC-7)"
    assert item.eligibility == "Ages 14–22"
    assert item.cost_amount == 0
    assert item.is_online is True
    assert item.rewards.startswith("$100 cash")
    assert "Registration Window:" in item.extra_notes
    assert "Editorial prestige" not in item.raw["opportunity_text"]


def test_link_provenance_excludes_button_metadata_and_listing_url():
    item = parsed_item()
    retained = {entry["url"] for entry in item.raw["link_provenance"]}
    assert retained == {OFFICIAL_URL}
    assert "https://application.example/register" not in retained
    assert "https://metadata-only.example/apply" not in retained
    assert PAGE_URL not in retained


def test_multiple_visible_relevant_links_are_preserved():
    page = fixture("doq_art_for_equity.html").replace(
        '<a href="https://application.example/register">Apply</a>',
        '<a href="https://registration.example/register">registration.example</a>',
    )
    dto = build_dto(parsed_item(page))
    assert dto.apply_link == OFFICIAL_URL
    assert dto.additional_links == ["https://registration.example/register"]


def test_no_link_item_never_falls_back_to_doq_listing():
    page = fixture("doq_art_for_equity.html")
    page = page.replace(
        '<a href="https://www.legaleaglebee.com/art-for-equity-competition" target="_blank">legaleaglebee.com</a>',
        "<span>Official website unavailable</span>",
    ).replace(
        '<a href="https://www.legaleaglebee.com/art-for-equity-competition" target="_blank">Legal Eagle Bee</a>',
        "<span>Legal Eagle Bee</span>",
    )
    dto = build_dto(parsed_item(page))
    assert dto.apply_link is None
    assert dto.additional_links == []

    opp = Opportunity(
        title=dto.title,
        category=dto.category,
        audience=Audience.both,
        status=OpportunityStatus.pending,
        apply_link=dto.apply_link,
        additional_links=dto.additional_links,
        source_url=PAGE_URL,
        hooks=[],
    )
    assert "doq.world" not in format_opportunity(opp)


def test_three_second_pacing_is_enforced_without_sleeping(monkeypatch):
    clock = [100.0]
    sleeps = []

    monkeypatch.setattr(web_http.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(web_http.time, "sleep", fake_sleep)
    fetcher = web_http.Fetcher(
        user_agent="ua", sleep_seconds=3.0, prefer_curl_cffi=False
    )
    try:
        fetcher._pace()
        fetcher._pace()
    finally:
        fetcher.close()
    assert sleeps == [3.0]


def test_dedupe_hash_matches_another_source_when_title_and_link_match():
    settings = SimpleNamespace(DEDUP_TTL_SECONDS=3600, ENABLE_EMBEDDING_DEDUP=False)
    dedupe = Deduplicator(None, settings, None)
    dto = build_dto(parsed_item())
    same = dto.model_copy(update={"title": dto.title, "apply_link": OFFICIAL_URL})
    assert dedupe.make_hash(dto) == dedupe.make_hash(same)


def test_linkless_item_uses_exact_title_dedupe_fallback():
    match = SimpleNamespace(id=42, title="Art for Equity Competition")

    class Repo:
        async def exists_by_hash(self, *args):
            return False

        async def find_recent_by_title(self, *args):
            return match

    settings = SimpleNamespace(DEDUP_TTL_SECONDS=3600, ENABLE_EMBEDDING_DEDUP=False)
    dedupe = Deduplicator(None, settings, None)
    dto = build_dto(parsed_item()).model_copy(update={"apply_link": None})
    assert asyncio.run(dedupe.check(dto, Repo())) is True
