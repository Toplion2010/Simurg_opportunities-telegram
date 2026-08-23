from __future__ import annotations

from datetime import date

import config
from pipeline.dedup import dedup_key
from pipeline.enrich import enrich
from sources.base import Hackathon, Source


def _h(title="Test Hack", source="devpost", ends_at=None):
    return Hackathon(
        source=source, source_id=title, title=title, url=f"https://example.com/{title}",
        starts_at=date(2026, 9, 1), ends_at=ends_at, is_online=True, prize_text=None,
        location=None, themes=[], raw={},
    )


class _RaisingSource(Source):
    name = "devpost"

    def fetch(self):
        return []

    def enrich(self, hackathon):
        raise RuntimeError("boom")


class _WorkingSource(Source):
    name = "devpost"

    def fetch(self):
        return []

    def enrich(self, hackathon):
        import dataclasses
        return dataclasses.replace(hackathon, description="a real description", sponsors=["Acme"])


def _no_op_cache(monkeypatch):
    """Prevent tests from touching the real state/enriched.json file."""
    monkeypatch.setattr("pipeline.enrich.load_cache", lambda path: {})
    saved = {}
    monkeypatch.setattr("pipeline.enrich.save_cache", lambda data, path: saved.update(data) or saved.setdefault("_called", True))
    return saved


def test_enrich_disabled_returns_input_unchanged(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", False)
    h = _h()
    assert enrich([h]) == [h]


def test_enrich_empty_list_short_circuits(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    assert enrich([]) == []


def test_source_enrich_exception_passes_item_through_unchanged(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _RaisingSource)
    _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)

    h = _h()
    result = enrich([h])

    assert len(result) == 1
    assert result[0].description is None
    assert result[0].title == h.title


def test_working_source_enriches_and_caches(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _WorkingSource)
    cache = _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)

    h = _h()
    result = enrich([h])

    assert result[0].description == "a real description"
    assert result[0].sponsors == ["Acme"]
    assert dedup_key(h) in cache


def test_cache_hit_skips_source_enrich_entirely(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    h = _h()
    key = dedup_key(h)
    monkeypatch.setattr("pipeline.enrich.load_cache", lambda path: {
        key: {
            "ends_at": None, "description": "cached description",
            "prize_breakdown": ["1st: $100"], "eligibility": "Students only",
            "required_tech": [], "deadline": None, "sponsors": ["CachedCo"],
        }
    })
    monkeypatch.setattr("pipeline.enrich.save_cache", lambda data, path: None)

    def _boom(module):
        raise AssertionError("get_source_class should not be called on a cache hit")
    monkeypatch.setattr("pipeline.enrich.get_source_class", _boom)

    result = enrich([h])

    assert result[0].description == "cached description"
    assert result[0].sponsors == ["CachedCo"]
    assert result[0].eligibility == "Students only"


def test_no_op_source_does_not_sleep(monkeypatch):
    """A source that never overrides enrich() should count as no fetch —
    no sleep, since --no-enrich-style default behavior shouldn't slow
    down sources that don't do any enrichment work."""
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    _no_op_cache(monkeypatch)

    slept = []
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: slept.append(s))

    class _PlainSource(Source):
        name = "devpost"
        def fetch(self):
            return []

    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _PlainSource)

    enrich([_h()])

    assert slept == []


def test_total_time_cap_passes_remainder_through_unenriched(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    monkeypatch.setattr(config, "ENRICH_TIMEOUT_TOTAL", 10.0)
    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _WorkingSource)
    _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)

    # start=0.0; item 0's cap-check sees elapsed=0.5s (under the 10s cap,
    # processes normally); item 1's cap-check sees elapsed=999s (over) and
    # trips the cap for it and everything after.
    clock = iter([0.0, 0.5, 999.0, 999.0, 999.0, 999.0])
    monkeypatch.setattr("pipeline.enrich.time.monotonic", lambda: next(clock, 999.0))

    items = [_h(f"Hack {i}") for i in range(3)]
    result = enrich(items)

    assert len(result) == 3
    assert result[0].description == "a real description"  # processed before cap
    assert result[1].description is None  # passed through unenriched
    assert result[2].description is None


def test_dry_run_never_saves_cache(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _WorkingSource)
    monkeypatch.setattr("pipeline.enrich.load_cache", lambda path: {})
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)

    save_calls = []
    monkeypatch.setattr("pipeline.enrich.save_cache", lambda data, path: save_calls.append(data))

    enrich([_h()], dry_run=True)
    assert save_calls == []

    enrich([_h()], dry_run=False)
    assert len(save_calls) == 1
