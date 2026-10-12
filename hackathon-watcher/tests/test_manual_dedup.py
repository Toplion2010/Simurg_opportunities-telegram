"""Hand-posted items (manual_post.py) must block the watcher from reposting
the same event later, even when an aggregator lists it under another URL or
a slightly different title."""

from __future__ import annotations

import json
from datetime import date

import manual_post
from pipeline.dedup import is_new, title_core
from sources.base import Hackathon


def _h(title, url, starts_at=date(2026, 9, 16)):
    return Hackathon(
        source="devpost", source_id=title, title=title, url=url, starts_at=starts_at,
        ends_at=None, is_online=True, prize_text=None, location=None,
    )


MANUAL = {"x": {"title": "Diamond Challenge 2026–27", "url": "https://diamondchallenge.org", "manual": True}}


def test_title_core_drops_season_numbers():
    assert title_core("Diamond Challenge 2026–27") == "diamond challenge"
    assert title_core("Diamond Challenge") == "diamond challenge"


def test_manual_entry_blocks_same_event_from_another_source():
    assert not is_new(_h("Diamond Challenge", "https://devpost.com/diamond"), MANUAL)
    assert not is_new(_h("DIAMOND CHALLENGE 2027", "https://other.test/dc"), MANUAL)
    assert not is_new(_h("The Diamond Challenge", "https://other.test/the"), MANUAL)


def test_manual_entry_blocks_same_url():
    assert not is_new(_h("Anything", "https://diamondchallenge.org"), MANUAL)


def test_unrelated_event_still_new():
    assert is_new(_h("Ruby Challenge", "https://ruby.test"), MANUAL)


def test_title_guard_only_applies_to_manual_entries():
    # Watcher's own entries keep the old rule: same title + new URL = new event.
    auto = {"x": {"title": "AI Challenge", "url": "https://a.devpost.com"}}
    assert is_new(_h("AI Challenge", "https://b.devpost.com", date(2026, 10, 1)), auto)


def test_record_only_writes_manual_entry(tmp_path, monkeypatch):
    spec = tmp_path / "dc.json"
    spec.write_text(json.dumps({
        "title": "Diamond Challenge 2026–27", "url": "https://diamondchallenge.org/",
        "ends_at": "2027-01-14", "location": "Worldwide",
    }), encoding="utf-8")
    saved = {}
    monkeypatch.setattr(manual_post, "load_seen", lambda: {})
    monkeypatch.setattr(manual_post, "save_seen", lambda s: saved.update(s))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["manual_post.py", str(spec), "--record-only",
                                     "--posted", "@simurg_hackathons:296"])
    assert manual_post.main() == 0
    (entry,) = saved.values()
    assert entry["manual"] is True
    assert entry["url"] == "https://diamondchallenge.org"
    assert entry["ends_at"] == "2027-01-14"
    assert entry["posts"] == [{"chat": "@simurg_hackathons", "message_id": 296}]
