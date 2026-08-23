from __future__ import annotations

from datetime import date

from sources.devpost import DevpostSource


def test_devpost_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("devpost.json")
    monkeypatch.setattr("sources.devpost.get", lambda *a, **k: response)

    hackathons = DevpostSource().fetch()

    assert len(hackathons) == 2
    first = hackathons[0]
    assert first.source == "devpost"
    assert first.source_id == "12345"
    assert first.title == "Test Hackathon"
    assert first.starts_at == date(2026, 9, 1)
    assert first.ends_at == date(2026, 9, 15)
    assert first.is_online is True
    assert first.prize_text == "$1,000"
    assert first.themes == ["Machine Learning/AI", "Web"]
    assert first.image_url == "https://d2dmyh35ffsxbl.cloudfront.net/test-thumb.png"
    assert first.organizer == "Test Org"

    second = hackathons[1]
    assert second.starts_at == date(2026, 10, 10)
    assert second.ends_at == date(2026, 10, 10)
    assert second.is_online is False
    assert second.location == "Austin, TX"


def test_devpost_returns_empty_on_malformed_json(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.devpost.get", lambda *a, **k: FakeResponse("not json"))
    assert DevpostSource().fetch() == []
