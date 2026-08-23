from __future__ import annotations

from datetime import date

import config
from sources.lablab import LablabSource


def test_lablab_parses_listing_and_detail_fixtures(fixture_response, monkeypatch):
    listing = fixture_response("lablab_listing.html")
    detail = fixture_response("lablab_detail.html")

    def fake_get(url, **kwargs):
        return listing if url == "https://lablab.ai/ai-hackathons" else detail

    monkeypatch.setattr("sources.lablab.get", fake_get)
    monkeypatch.setattr(config, "LABLAB_DETAIL_CAP", 2)

    hackathons = LablabSource().fetch()

    assert len(hackathons) == 2
    first = hackathons[0]
    assert first.source == "lablab"
    assert first.title == "Alpaca AI Trading Agents Hackathon"
    assert first.url == "https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon"
    assert first.is_online is True
    assert first.location is None
    assert first.starts_at == date(2026, 8, 28)
    assert first.ends_at == date(2026, 9, 4)
    assert first.prize_text == "$6,000"
    assert first.themes == ["ai"]
    assert first.organizer == "lablab.ai"


def test_lablab_caps_detail_fetches(fixture_response, monkeypatch):
    listing = fixture_response("lablab_listing.html")
    detail = fixture_response("lablab_detail.html")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return listing if url == "https://lablab.ai/ai-hackathons" else detail

    monkeypatch.setattr("sources.lablab.get", fake_get)
    monkeypatch.setattr(config, "LABLAB_DETAIL_CAP", 1)

    hackathons = LablabSource().fetch()
    assert len(hackathons) == 1
    assert len(calls) == 2  # 1 listing + 1 detail


def test_lablab_returns_empty_when_itemlist_missing(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.lablab.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    assert LablabSource().fetch() == []


def test_lablab_fetch_never_raises_on_network_error(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.lablab.get", _raise)
    assert LablabSource().fetch() == []


def test_lablab_skips_item_when_detail_fetch_fails(fixture_response, monkeypatch):
    listing = fixture_response("lablab_listing.html")

    def fake_get(url, **kwargs):
        if url == "https://lablab.ai/ai-hackathons":
            return listing
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.lablab.get", fake_get)
    monkeypatch.setattr(config, "LABLAB_DETAIL_CAP", 3)

    assert LablabSource().fetch() == []
