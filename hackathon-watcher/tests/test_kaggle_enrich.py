from __future__ import annotations

import pytest

from pipeline.kaggle_enrich import enrich_kaggle, is_kaggle_competition_url
from sources.base import Hackathon


def _h(**overrides) -> Hackathon:
    defaults = dict(
        source="mlcontests", source_id="1", title="Test Comp",
        url="https://www.kaggle.com/competitions/some-slug", starts_at=None,
        ends_at=None, is_online=True, prize_text="$1,000", location=None,
        themes=[], raw={},
    )
    defaults.update(overrides)
    return Hackathon(**defaults)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_is_kaggle_competition_url():
    assert is_kaggle_competition_url("https://www.kaggle.com/competitions/some-slug")
    assert not is_kaggle_competition_url("https://www.kaggle.com/datasets/foo")
    assert not is_kaggle_competition_url(None)
    assert not is_kaggle_competition_url("https://devpost.com/hackathons/foo")


def test_enrich_kaggle_fills_description_when_match_found(monkeypatch):
    payload = [
        {"ref": "other-slug", "description": "Wrong one"},
        {"ref": "some-slug", "description": "A real competition subtitle."},
    ]
    monkeypatch.setattr(
        "pipeline.kaggle_enrich.requests.get",
        lambda *a, **k: _FakeResponse(payload),
    )

    enriched = enrich_kaggle(_h(), "user", "key")

    assert enriched.description == "A real competition subtitle."
    assert enriched.title == "Test Comp"  # untouched


def test_enrich_kaggle_never_overwrites_existing_description(monkeypatch):
    payload = [{"ref": "some-slug", "description": "New one"}]
    monkeypatch.setattr(
        "pipeline.kaggle_enrich.requests.get",
        lambda *a, **k: _FakeResponse(payload),
    )

    enriched = enrich_kaggle(_h(description="Already have one"), "user", "key")

    assert enriched.description == "Already have one"


def test_enrich_kaggle_no_match_returns_unchanged(monkeypatch):
    payload = [{"ref": "totally-different-slug", "description": "..."}]
    monkeypatch.setattr(
        "pipeline.kaggle_enrich.requests.get",
        lambda *a, **k: _FakeResponse(payload),
    )

    original = _h()
    enriched = enrich_kaggle(original, "user", "key")

    assert enriched == original


def test_enrich_kaggle_non_kaggle_url_returns_unchanged():
    original = _h(url="https://example.com/not-kaggle")
    enriched = enrich_kaggle(original, "user", "key")
    assert enriched == original


def test_enrich_kaggle_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "pipeline.kaggle_enrich.requests.get",
        lambda *a, **k: _FakeResponse({}, status_code=401),
    )
    with pytest.raises(RuntimeError):
        enrich_kaggle(_h(), "user", "key")
