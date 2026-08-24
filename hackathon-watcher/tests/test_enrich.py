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


def test_source_enrich_exception_falls_back_to_generic_enrich(monkeypatch):
    """A custom enrich() that raises is no longer a dead end — it falls
    back to generic_enrich, same as a source with no custom enrich() at
    all that yields nothing (mirrors the ethglobal case: its own enrich()
    finds nothing live, so the generic fallback gets a shot too)."""
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _RaisingSource)
    _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)
    from conftest import FakeResponse
    monkeypatch.setattr("pipeline.generic_enrich.get", lambda *a, **k: FakeResponse("<html><body>no jsonld</body></html>"))

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


def test_no_op_source_falls_back_to_generic_enrich_and_sleeps(monkeypatch):
    """A source that never overrides enrich() no longer means "skip
    entirely" — it falls back to generic_enrich (schema.org JSON-LD sniff,
    then optionally Gemini), which does a real fetch and so still counts
    as one for sleep-pacing purposes."""
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    _no_op_cache(monkeypatch)

    slept = []
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: slept.append(s))
    from conftest import FakeResponse
    monkeypatch.setattr("pipeline.generic_enrich.get", lambda *a, **k: FakeResponse("<html><body>no jsonld here</body></html>"))

    class _PlainSource(Source):
        name = "devpost"
        def fetch(self):
            return []

    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _PlainSource)

    result = enrich([_h()])

    assert slept == [config.ENRICH_SLEEP_SECONDS]
    assert result[0].title == "Test Hack"  # unenriched but present, never dropped


def test_kaggle_url_uses_kaggle_enrich_when_credentials_present(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)
    monkeypatch.setenv("KAGGLE_USERNAME", "user")
    monkeypatch.setenv("KAGGLE_KEY", "key")

    class _PlainSource(Source):
        name = "mlcontests"
        def fetch(self):
            return []

    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _PlainSource)

    called = {}
    def _fake_enrich_kaggle(h, username, key):
        called["args"] = (username, key)
        import dataclasses
        return dataclasses.replace(h, description="kaggle description")
    monkeypatch.setattr("pipeline.enrich.enrich_kaggle", _fake_enrich_kaggle)

    import dataclasses
    h = dataclasses.replace(_h(title="Kaggle Comp"), url="https://www.kaggle.com/competitions/some-slug")

    result = enrich([h])

    assert called["args"] == ("user", "key")
    assert result[0].description == "kaggle description"


def test_kaggle_url_falls_back_to_generic_enrich_without_credentials(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)

    class _PlainSource(Source):
        name = "mlcontests"
        def fetch(self):
            return []

    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _PlainSource)

    from conftest import FakeResponse
    monkeypatch.setattr("pipeline.generic_enrich.get", lambda *a, **k: FakeResponse("<html><body>no jsonld</body></html>"))

    def _boom(*a, **k):
        raise AssertionError("enrich_kaggle should not be called without credentials")
    monkeypatch.setattr("pipeline.enrich.enrich_kaggle", _boom)

    import dataclasses
    h = dataclasses.replace(_h(title="Kaggle Comp"), url="https://www.kaggle.com/competitions/some-slug")

    result = enrich([h])

    assert result[0].title == "Kaggle Comp"


class _EthGlobalLikeSource(Source):
    """Mirrors ethglobal.py: has its own enrich() but the target site is a
    JS-only shell, so it consistently returns the hackathon unchanged."""
    name = "devpost"

    def fetch(self):
        return []

    def enrich(self, hackathon):
        return hackathon


def test_custom_enrich_that_finds_nothing_falls_back_to_generic_enrich(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _EthGlobalLikeSource)
    _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)

    from conftest import FakeResponse
    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>No structured data, real prose here.</body></html>"),
    )

    import json as _json

    def _fake_post(url, **kwargs):
        payload = {
            "description": "found via the generic fallback", "prize_amount": None,
            "prize_currency": None, "eligibility": None, "is_online": None,
            "location": None, "links": [],
        }
        body = {"candidates": [{"content": {"parts": [{"text": _json.dumps(payload)}]}}]}
        return FakeResponse(_json.dumps(body))

    monkeypatch.setattr("pipeline.generic_enrich.requests.post", _fake_post)

    result = enrich([_h()], gemini_api_key="fake-key")

    assert result[0].description == "found via the generic fallback"


def test_custom_enrich_with_real_data_skips_generic_fallback(monkeypatch):
    monkeypatch.setattr(config, "ENRICH_ENABLED", True)
    monkeypatch.setattr("pipeline.enrich.get_source_class", lambda module: _WorkingSource)
    _no_op_cache(monkeypatch)
    monkeypatch.setattr("pipeline.enrich.time.sleep", lambda s: None)

    def _boom(*a, **k):
        raise AssertionError("generic_enrich's get() should not be called")
    monkeypatch.setattr("pipeline.generic_enrich.get", _boom)

    result = enrich([_h()])

    assert result[0].description == "a real description"


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
