from __future__ import annotations

import json

import pytest

import config
from pipeline.telegram import (
    CHAT_DESCRIPTION_MAX,
    pin_message,
    send_message_returning_id,
    set_chat_description,
)
from setup_channel import DESCRIPTION, SOURCE_LABELS, build_nav_message


class _Resp:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = json.dumps(payload or {})

    def json(self):
        return json.loads(self.text)


# --- the navigation post ---------------------------------------------------

def test_every_enabled_source_has_a_label():
    """A source added to config without a label would silently vanish from the
    pinned post; building the message must fail loudly instead."""
    for name, entry in config.SOURCES.items():
        if entry.get("enabled"):
            assert name in SOURCE_LABELS, f"no SOURCE_LABELS entry for {name!r}"


def test_nav_message_lists_every_enabled_source():
    message = build_nav_message()
    for name, entry in config.SOURCES.items():
        if entry.get("enabled"):
            assert SOURCE_LABELS[name] in message


def test_nav_message_source_count_matches_enabled_sources():
    enabled = sum(1 for e in config.SOURCES.values() if e.get("enabled"))
    assert f"Tracked sources ({enabled})" in build_nav_message()


def test_nav_message_fits_telegram_limit():
    assert len(build_nav_message()) <= 4096


def test_nav_message_raises_on_unlabelled_source(monkeypatch):
    monkeypatch.setitem(config.SOURCES, "brandnew", {"module": "x", "priority": 99, "enabled": True})
    with pytest.raises(KeyError):
        build_nav_message()


def test_about_description_fits_telegram_limit():
    assert len(DESCRIPTION) <= CHAT_DESCRIPTION_MAX


# --- the API helpers -------------------------------------------------------

def test_send_message_returning_id_extracts_the_id(monkeypatch):
    monkeypatch.setattr(
        "pipeline.telegram.requests.post",
        lambda *a, **k: _Resp({"ok": True, "result": {"message_id": 4242}}),
    )
    assert send_message_returning_id("tok", "@chan", "hi") == 4242


def test_send_message_returning_id_is_none_on_failure(monkeypatch):
    monkeypatch.setattr(
        "pipeline.telegram.requests.post", lambda *a, **k: _Resp({"ok": False}, status_code=400)
    )
    assert send_message_returning_id("tok", "@chan", "hi") is None


def test_send_message_returning_id_is_none_when_id_missing(monkeypatch):
    monkeypatch.setattr(
        "pipeline.telegram.requests.post", lambda *a, **k: _Resp({"ok": True, "result": {}})
    )
    assert send_message_returning_id("tok", "@chan", "hi") is None


def test_pin_message_pins_silently(monkeypatch):
    captured = {}

    def _post(url, json=None, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        return _Resp({"ok": True})

    monkeypatch.setattr("pipeline.telegram.requests.post", _post)

    assert pin_message("tok", "@chan", 7) is True
    assert captured["url"].endswith("/pinChatMessage")
    assert captured["payload"]["message_id"] == 7
    assert captured["payload"]["disable_notification"] is True


def test_set_chat_description_rejects_overlong_text_without_calling_api(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not call the API with an over-limit description")

    monkeypatch.setattr("pipeline.telegram.requests.post", _boom)

    assert set_chat_description("tok", "@chan", "x" * (CHAT_DESCRIPTION_MAX + 1)) is False
