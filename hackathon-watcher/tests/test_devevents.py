from __future__ import annotations

from datetime import date

from sources.devevents import DevEventsSource


def test_devevents_filters_to_hackathon_tag(fixture_response, monkeypatch):
    response = fixture_response("devevents.xml")
    monkeypatch.setattr("sources.devevents.get", lambda *a, **k: response)

    hackathons = DevEventsSource().fetch()

    assert len(hackathons) == 2
    titles = {h.title for h in hackathons}
    assert titles == {"Test Hack Night", "Offline Build Sprint"}
    assert "Not A Hackathon Meetup" not in titles


def test_devevents_parses_online_and_location(fixture_response, monkeypatch):
    response = fixture_response("devevents.xml")
    monkeypatch.setattr("sources.devevents.get", lambda *a, **k: response)

    hackathons = {h.title: h for h in DevEventsSource().fetch()}

    online = hackathons["Test Hack Night"]
    assert online.is_online is True
    assert online.location == "Online"
    assert online.starts_at == date(2026, 8, 25)

    offline = hackathons["Offline Build Sprint"]
    assert offline.is_online is False
    assert offline.location == "Basel, Switzerland, Europe"
    assert offline.starts_at == date(2026, 10, 30)


def test_devevents_returns_empty_on_garbage(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.devevents.get", lambda *a, **k: FakeResponse("<not>rss</not>"))
    assert DevEventsSource().fetch() == []
