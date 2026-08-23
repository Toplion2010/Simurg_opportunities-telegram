from __future__ import annotations

from datetime import date

import config
from sources.allhackathons import AllHackathonsSource, _parse_date_range


def test_allhackathons_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("allhackathons.html")
    monkeypatch.setattr("sources.allhackathons.get", lambda *a, **k: response)
    monkeypatch.setattr(config, "ALLHACKATHONS_PAGE_CAP", 1)

    hackathons = AllHackathonsSource().fetch()

    assert len(hackathons) == 10
    titles = [h.title for h in hackathons]
    assert "Build Vision AI- Online" in titles
    assert "DevNetwork [API + Cloud + AI] Hackathon 2026" in titles

    online_one = next(h for h in hackathons if h.title == "Build Vision AI- Online")
    assert online_one.source == "allhackathons"
    assert online_one.is_online is True
    assert online_one.location is None
    assert online_one.starts_at == date(2026, 8, 31)
    assert online_one.ends_at == date(2026, 8, 31)
    assert "ai" in [t.lower() for t in online_one.themes]

    in_person = next(h for h in hackathons if h.title == "DevNetwork [API + Cloud + AI] Hackathon 2026")
    assert in_person.is_online is False
    assert in_person.starts_at == date(2026, 8, 17)
    assert in_person.ends_at == date(2026, 9, 3)


def test_allhackathons_stops_pagination_when_page_returns_no_cards(fixture_response, monkeypatch):
    from conftest import FakeResponse

    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs.get("params", {}))
        page = kwargs.get("params", {}).get("page", 1)
        if page == 1:
            return fixture_response("allhackathons.html")
        return FakeResponse("<html><body></body></html>")

    monkeypatch.setattr("sources.allhackathons.get", fake_get)
    monkeypatch.setattr(config, "ALLHACKATHONS_PAGE_CAP", 5)

    hackathons = AllHackathonsSource().fetch()
    assert len(hackathons) == 10
    assert len(calls) == 2  # page 1 (has cards), page 2 (empty, stops)


def test_allhackathons_returns_empty_when_selectors_rot(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.allhackathons.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    assert AllHackathonsSource().fetch() == []


def test_allhackathons_fetch_never_raises_on_network_error(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.allhackathons.get", _raise)
    assert AllHackathonsSource().fetch() == []


def test_parse_date_range_single_day():
    start, end = _parse_date_range("Aug. 31, 2026 - Aug. 31, 2026")
    assert start == date(2026, 8, 31)
    assert end == date(2026, 8, 31)


def test_parse_date_range_multi_day():
    start, end = _parse_date_range("Aug. 17, 2026 - Sept. 3, 2026")
    assert start == date(2026, 8, 17)
    assert end == date(2026, 9, 3)


def test_parse_date_range_none():
    assert _parse_date_range(None) == (None, None)
