from __future__ import annotations

from datetime import date

from sources.base import Hackathon
from sources.ethglobal import EthGlobalSource, _parse_date_range


def test_ethglobal_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("ethglobal.html")
    monkeypatch.setattr("sources.ethglobal.get", lambda *a, **k: response)

    hackathons = EthGlobalSource().fetch()

    assert len(hackathons) > 0
    # every returned item must be a real hackathon, not a meetup/co-working/conference
    titles = [h.title for h in hackathons]
    assert "ETHGlobal Lisbon 2026" in titles
    assert "HackMoney 2026" in titles
    assert not any("Happy Hour" in t for t in titles)
    assert not any("Coworking" in t or "Cowork" in t for t in titles)

    lisbon = next(h for h in hackathons if h.title == "ETHGlobal Lisbon 2026")
    assert lisbon.source == "ethglobal"
    assert lisbon.source_id == "lisbon2026"
    assert lisbon.url == "https://ethglobal.com/events/lisbon2026"
    assert lisbon.is_online is False
    assert lisbon.location == "Lisbon, Portugal"
    assert lisbon.starts_at == date(2026, 7, 24)
    assert lisbon.ends_at == date(2026, 7, 26)
    assert lisbon.themes == ["web3"]
    assert lisbon.organizer == "ETHGlobal"

    hackmoney = next(h for h in hackathons if h.title == "HackMoney 2026")
    assert hackmoney.is_online is True
    assert hackmoney.location is None


def test_ethglobal_returns_empty_when_selectors_rot(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.ethglobal.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    assert EthGlobalSource().fetch() == []


def test_ethglobal_fetch_never_raises_on_network_error(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.ethglobal.get", _raise)
    assert EthGlobalSource().fetch() == []


def test_parse_date_range_year_only_on_second_date():
    start, end = _parse_date_range(["Jul 24th", "Jul 26th, 2026"])
    assert start == date(2026, 7, 24)
    assert end == date(2026, 7, 26)


def test_parse_date_range_single_date():
    start, end = _parse_date_range(["Jan 31st, 2026"])
    assert start == date(2026, 1, 31)
    assert end == date(2026, 1, 31)


def test_parse_date_range_empty():
    assert _parse_date_range([]) == (None, None)


def _bare_hackathon() -> Hackathon:
    return Hackathon(
        source="ethglobal", source_id="1", title="Test Hack",
        url="https://ethglobal.com/events/newyork2026", starts_at=date(2026, 9, 1),
        ends_at=date(2026, 9, 3), is_online=False, prize_text=None,
        location="New York, USA", themes=["web3"], raw={},
    )


def test_ethglobal_enrich_parses_prize_from_fixture(fixture_response, monkeypatch):
    response = fixture_response("ethglobal_detail.html")
    monkeypatch.setattr("sources.ethglobal.get", lambda *a, **k: response)

    enriched = EthGlobalSource().enrich(_bare_hackathon())
    assert enriched.prize_text == "$175,000"
    assert enriched.title == "Test Hack"  # listing fields untouched


def test_ethglobal_enrich_returns_unchanged_when_no_prizes_section(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.ethglobal.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    original = _bare_hackathon()
    assert EthGlobalSource().enrich(original) == original


def test_ethglobal_enrich_returns_unchanged_on_fetch_failure(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.ethglobal.get", _raise)
    original = _bare_hackathon()
    assert EthGlobalSource().enrich(original) == original
