from __future__ import annotations

from datetime import date

from sources.hackclub import HackClubSource


def test_hackclub_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("hackclub.html")
    monkeypatch.setattr("sources.hackclub.get", lambda *a, **k: response)

    hackathons = HackClubSource().fetch()

    assert len(hackathons) == 8
    titles = [h.title for h in hackathons]
    assert "Hackside Down" in titles
    assert "Animal Hack" in titles

    in_person = next(h for h in hackathons if h.title == "Hackside Down")
    assert in_person.source == "hackclub"
    assert in_person.source_id == "0PvIqX"
    assert in_person.is_online is False
    assert in_person.location == "Faridabad, Haryana, India"
    assert in_person.starts_at == date(2026, 8, 29)
    assert in_person.ends_at == date(2026, 8, 30)
    assert in_person.themes == ["highschool"]
    assert in_person.url.startswith("https://")

    virtual = next(h for h in hackathons if h.title == "Animal Hack")
    assert virtual.is_online is True
    assert virtual.location is None


def test_hackclub_returns_empty_when_next_data_missing(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.hackclub.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    assert HackClubSource().fetch() == []


def test_hackclub_fetch_never_raises_on_network_error(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.hackclub.get", _raise)
    assert HackClubSource().fetch() == []


def test_hackclub_skips_event_missing_required_fields(monkeypatch):
    import json
    from conftest import FakeResponse

    mini = {"props": {"pageProps": {"events": [
        {"id": "abc", "name": "No Website Hack", "website": None},
        {"id": "def", "name": "Good Hack", "website": "https://example.com", "virtual": True, "start": None, "end": None},
    ]}}}
    html = '<html><body><script id="__NEXT_DATA__" type="application/json">' + json.dumps(mini) + "</script></body></html>"
    monkeypatch.setattr("sources.hackclub.get", lambda *a, **k: FakeResponse(html))

    hackathons = HackClubSource().fetch()
    assert len(hackathons) == 1
    assert hackathons[0].title == "Good Hack"
    assert hackathons[0].starts_at is None
