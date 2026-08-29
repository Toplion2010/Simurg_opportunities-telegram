from __future__ import annotations

import json
from datetime import date

import config
from pipeline.generic_enrich import generic_enrich
from sources.base import Hackathon


def _h(**overrides) -> Hackathon:
    defaults = dict(
        source="reskilll", source_id="1", title="Test Hack",
        url="https://example.com/test-hack", starts_at=None, ends_at=None,
        is_online=None, prize_text=None, location=None, themes=[], raw={},
    )
    defaults.update(overrides)
    return Hackathon(**defaults)


# --- Tier 1: JSON-LD sniff (no API key needed) ----------------------------

def test_jsonld_tier_fills_description_prize_dates_online(fixture_response, monkeypatch):
    response = fixture_response("generic_enrich_jsonld.html")
    monkeypatch.setattr("pipeline.generic_enrich.get", lambda *a, **k: response)

    enriched = generic_enrich(_h(), gemini_api_key=None)

    assert enriched.description == "A fun hackathon with a $40,000 prize pool for everyone to enjoy."
    assert enriched.prize_text == "$40,000"
    assert enriched.is_online is False
    assert enriched.starts_at == date(2026, 9, 1)
    assert enriched.ends_at == date(2026, 9, 3)
    assert enriched.title == "Test Hack"  # untouched


def test_jsonld_tier_never_overwrites_existing_fields(fixture_response, monkeypatch):
    response = fixture_response("generic_enrich_jsonld.html")
    monkeypatch.setattr("pipeline.generic_enrich.get", lambda *a, **k: response)

    original = _h(prize_text="already have this", is_online=True, starts_at=date(2020, 1, 1))
    enriched = generic_enrich(original, gemini_api_key=None)

    assert enriched.prize_text == "already have this"
    assert enriched.is_online is True
    assert enriched.starts_at == date(2020, 1, 1)
    # fields that WERE empty still get filled
    assert enriched.description


def test_no_jsonld_and_no_api_key_returns_unchanged(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("pipeline.generic_enrich.get", lambda *a, **k: FakeResponse("<html><body>plain page</body></html>"))
    original = _h()
    assert generic_enrich(original, gemini_api_key=None) == original


def test_fetch_failure_returns_unchanged(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("pipeline.generic_enrich.get", _raise)
    original = _h()
    assert generic_enrich(original, gemini_api_key="fake-key") == original


# --- Tier 2: Gemini text extraction ----------------------------------------

def _fake_gemini_json_response(payload: dict):
    from conftest import FakeResponse
    body = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}}
        ]
    }
    return FakeResponse(json.dumps(body))


def test_ai_tier_runs_when_jsonld_missing_and_key_present(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>No structured data, just prose about a great hackathon.</body></html>"),
    )

    ai_payload = {
        "description": "A weekend hackathon for students to build AI projects.",
        "prize_amount": 5000,
        "prize_currency": "$",
        "eligibility": "Students only",
        "is_online": True,
        "location": None,
        "links": [{"label": "Rules", "url": "https://example.com/rules"}],
    }
    monkeypatch.setattr(
        "pipeline.generic_enrich.requests.post",
        lambda url, json, timeout: _fake_gemini_json_response(ai_payload),
    )

    enriched = generic_enrich(_h(), gemini_api_key="fake-key")

    assert enriched.description == "A weekend hackathon for students to build AI projects."
    assert enriched.prize_text == "$5,000"
    assert enriched.eligibility == "Students only"
    assert enriched.is_online is True
    assert enriched.links == [{"label": "Rules", "url": "https://example.com/rules"}]


# --- Tier 3: Firecrawl-rendered text (JS-only shells) ----------------------

def test_firecrawl_tier_used_when_raw_page_too_thin(monkeypatch):
    from conftest import FakeResponse

    # A near-empty raw fetch, like ethglobal.com/kaggle.com's real JS shells.
    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>Some Event Title</body></html>"),
    )

    ai_payload = {
        "description": "A hackathon rendered only via JS, now readable.",
        "prize_amount": None, "prize_currency": None, "eligibility": None,
        "is_online": None, "location": None, "links": [],
    }
    calls = []

    def _fake_post(url, **kwargs):
        calls.append(url)
        if "firecrawl" in url:
            return FakeResponse(json.dumps({"data": {
                "markdown": "Real rendered content about the hackathon.",
                "rawHtml": "<html><body>Real rendered content about the hackathon.</body></html>",
            }}))
        return _fake_gemini_json_response(ai_payload)

    monkeypatch.setattr("pipeline.generic_enrich.requests.post", _fake_post)

    enriched = generic_enrich(_h(), gemini_api_key="fake-key", firecrawl_api_key="fc-key")

    assert any("firecrawl" in c for c in calls)
    assert enriched.description == "A hackathon rendered only via JS, now readable."


def test_firecrawl_tier_skipped_when_raw_page_has_enough_text(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse(f"<html><body>{'Plenty of real prose. ' * 20}</body></html>"),
    )
    calls = []

    def _fake_post(url, **kwargs):
        calls.append(url)
        return _fake_gemini_json_response({
            "description": "from raw text", "prize_amount": None, "prize_currency": None,
            "eligibility": None, "is_online": None, "location": None, "links": [],
        })

    monkeypatch.setattr("pipeline.generic_enrich.requests.post", _fake_post)

    generic_enrich(_h(), gemini_api_key="fake-key", firecrawl_api_key="fc-key")

    assert not any("firecrawl" in c for c in calls)


def test_firecrawl_tier_skipped_without_key_even_if_page_thin(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>thin</body></html>"),
    )
    calls = []

    def _fake_post(url, **kwargs):
        calls.append(url)
        return _fake_gemini_json_response({
            "description": None, "prize_amount": None, "prize_currency": None,
            "eligibility": None, "is_online": None, "location": None, "links": [],
        })

    monkeypatch.setattr("pipeline.generic_enrich.requests.post", _fake_post)

    generic_enrich(_h(), gemini_api_key="fake-key", firecrawl_api_key=None)

    assert not any("firecrawl" in c for c in calls)


def test_firecrawl_failure_falls_back_to_raw_ai_extraction(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>thin</body></html>"),
    )

    def _fake_post(url, **kwargs):
        if "firecrawl" in url:
            raise ConnectionError("firecrawl down")
        return _fake_gemini_json_response({
            "description": "fallback description", "prize_amount": None, "prize_currency": None,
            "eligibility": None, "is_online": None, "location": None, "links": [],
        })

    monkeypatch.setattr("pipeline.generic_enrich.requests.post", _fake_post)

    enriched = generic_enrich(_h(), gemini_api_key="fake-key", firecrawl_api_key="fc-key")

    assert enriched.description == "fallback description"


def test_blocked_fetch_falls_through_to_firecrawl(monkeypatch):
    """A site that 403s this bot's user agent (dev.events does) is still
    readable through Firecrawl's browser infrastructure."""
    from conftest import FakeResponse

    def _raise(*a, **k):
        raise ConnectionError("403 Forbidden")

    monkeypatch.setattr("pipeline.generic_enrich.get", _raise)

    def _fake_post(url, **kwargs):
        if "firecrawl" in url:
            return FakeResponse(json.dumps({"data": {
                "markdown": "Real content behind the 403.",
                "rawHtml": "<html><body>Real content behind the 403.</body></html>",
            }}))
        return _fake_gemini_json_response({
            "description": "recovered via firecrawl", "prize_amount": None,
            "prize_currency": None, "eligibility": None, "is_online": None,
            "location": None, "links": [],
        })

    monkeypatch.setattr("pipeline.generic_enrich.requests.post", _fake_post)

    enriched = generic_enrich(_h(), gemini_api_key="fake-key", firecrawl_api_key="fc-key")

    assert enriched.description == "recovered via firecrawl"


def test_wrapper_iframe_is_followed_to_the_real_event_page(monkeypatch):
    """dev.events serves a shell that iframes the real site; enrichment must
    read the target and repoint the posted url at it."""
    from conftest import FakeResponse

    wrapper = (
        '<html><body><div class="iframe-wrapper">'
        '<iframe src="https://dorahacks.io/hackathon/agent-economy/detail"></iframe>'
        "</div></body></html>"
    )
    real = "<html><body>" + ("Real event content with all the details. " * 12) + "</body></html>"

    def _fake_get(url, **kwargs):
        return FakeResponse(real if "dorahacks" in url else wrapper)

    monkeypatch.setattr("pipeline.generic_enrich.get", _fake_get)
    monkeypatch.setattr(
        "pipeline.generic_enrich.requests.post",
        lambda url, **k: _fake_gemini_json_response({
            "description": "From the real event page.", "prize_amount": 5000,
            "prize_currency": "USD", "eligibility": None, "is_online": None,
            "location": None, "links": [],
        }),
    )

    enriched = generic_enrich(_h(), gemini_api_key="fake-key")

    assert enriched.url == "https://dorahacks.io/hackathon/agent-economy/detail"
    assert enriched.description == "From the real event page."
    assert enriched.prize_text == "USD 5,000"


def test_same_domain_iframe_is_not_followed(monkeypatch):
    """Only an off-domain iframe signals a wrapper — a same-site embed
    (a video, a map) must not hijack the posted url."""
    from conftest import FakeResponse

    page = (
        '<html><body><div class="iframe-wrapper">'
        '<iframe src="https://example.com/embed/player"></iframe>'
        "</div></body></html>"
    )
    monkeypatch.setattr("pipeline.generic_enrich.get", lambda *a, **k: FakeResponse(page))
    monkeypatch.setattr(
        "pipeline.generic_enrich.requests.post",
        lambda url, **k: _fake_gemini_json_response({
            "description": None, "prize_amount": None, "prize_currency": None,
            "eligibility": None, "is_online": None, "location": None, "links": [],
        }),
    )

    original = _h()
    assert generic_enrich(original, gemini_api_key="fake-key").url == original.url


def test_blocked_fetch_without_firecrawl_key_returns_unchanged(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("403 Forbidden")

    monkeypatch.setattr("pipeline.generic_enrich.get", _raise)
    original = _h()
    assert generic_enrich(original, gemini_api_key="fake-key", firecrawl_api_key=None) == original


def test_ai_tier_skipped_without_api_key(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>No structured data here.</body></html>"),
    )
    calls = []
    monkeypatch.setattr(
        "pipeline.generic_enrich.requests.post",
        lambda *a, **k: calls.append(1),
    )

    enriched = generic_enrich(_h(), gemini_api_key=None)
    assert calls == []
    assert enriched.description is None


def test_ai_tier_drops_offdomain_or_malformed_links(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>No structured data, just prose.</body></html>"),
    )

    ai_payload = {
        "description": None,
        "prize_amount": None,
        "prize_currency": None,
        "eligibility": None,
        "is_online": None,
        "location": None,
        "links": [
            {"label": "Evil", "url": "https://evil.com/phish"},
            {"label": "Bad scheme", "url": "javascript:alert(1)"},
            {"label": "", "url": "https://example.com/empty-label"},
            {"label": "Good", "url": "https://example.com/rules"},
        ],
    }
    monkeypatch.setattr(
        "pipeline.generic_enrich.requests.post",
        lambda url, json, timeout: _fake_gemini_json_response(ai_payload),
    )

    enriched = generic_enrich(_h(url="https://example.com/test-hack"), gemini_api_key="fake-key")

    assert enriched.links == [{"label": "Good", "url": "https://example.com/rules"}]


def test_ai_tier_never_raises_on_api_failure(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>No structured data.</body></html>"),
    )

    def _raise(*a, **k):
        raise ConnectionError("gemini is down")

    monkeypatch.setattr("pipeline.generic_enrich.requests.post", _raise)

    original = _h()
    assert generic_enrich(original, gemini_api_key="fake-key") == original


def test_ai_tier_disabled_via_config(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr(config, "AI_ENRICH_ENABLED", False)
    monkeypatch.setattr(
        "pipeline.generic_enrich.get",
        lambda *a, **k: FakeResponse("<html><body>No structured data.</body></html>"),
    )
    calls = []
    monkeypatch.setattr("pipeline.generic_enrich.requests.post", lambda *a, **k: calls.append(1))

    generic_enrich(_h(), gemini_api_key="fake-key")
    assert calls == []
