from __future__ import annotations

import base64
from datetime import date

import config
from pipeline.image_gen import _compose_prompt, generate_image
from sources.base import Hackathon


def _h(**overrides) -> Hackathon:
    defaults = dict(
        source="devpost", source_id="1", title="Test Hack",
        url="https://example.com/hack", starts_at=date(2026, 9, 1),
        ends_at=date(2026, 9, 3), is_online=True, prize_text=None,
        location="Online", themes=["AI"], raw={},
    )
    defaults.update(overrides)
    return Hackathon(**defaults)


def test_generate_image_returns_none_without_api_key():
    assert generate_image(_h(), None) is None
    assert generate_image(_h(), "") is None


def test_generate_image_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", False)
    assert generate_image(_h(), "fake-key") is None


def test_compose_prompt_includes_title_and_never_asks_for_text():
    prompt = _compose_prompt(_h(title="Cool Hack 2026"))
    assert "Cool Hack 2026" in prompt


def test_compose_prompt_includes_organizer_and_location():
    prompt = _compose_prompt(_h(organizer="Acme Club", is_online=False, location="Berlin"))
    assert "Acme Club" in prompt
    assert "Berlin" in prompt


def test_compose_prompt_omits_location_when_online():
    prompt = _compose_prompt(_h(is_online=True, location="Online"))
    # "Online" as a location isn't a real place worth describing in the scene
    assert "in Online" not in prompt


def test_compose_prompt_is_deterministic_for_same_hackathon():
    h = _h()
    assert _compose_prompt(h) == _compose_prompt(h)


def _fake_gemini_response(image_bytes: bytes) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inline_data": {"data": base64.b64encode(image_bytes).decode()}}
                    ]
                }
            }
        ]
    }


def _small_jpeg_bytes() -> bytes:
    import io
    from PIL import Image

    img = Image.new("RGB", (400, 300), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.text = str(json_data)

    def json(self):
        return self._json


def test_generate_image_success_returns_resized_jpeg(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", True)
    raw = _small_jpeg_bytes()
    monkeypatch.setattr(
        "pipeline.image_gen.requests.post",
        lambda *a, **k: _FakeResponse(_fake_gemini_response(raw)),
    )

    result = generate_image(_h(), "fake-key")

    assert result is not None
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(result))
    assert img.size == (1200, 628)
    assert img.format == "JPEG"


def test_generate_image_retries_on_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr(config, "IMAGE_GEN_RETRY_SCHEDULE", (0, 0))
    monkeypatch.setattr("pipeline.image_gen.time.sleep", lambda s: None)

    raw = _small_jpeg_bytes()
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResponse({"error": "503 unavailable"}, status_code=503)
        return _FakeResponse(_fake_gemini_response(raw))

    monkeypatch.setattr("pipeline.image_gen.requests.post", fake_post)

    result = generate_image(_h(), "fake-key")
    assert result is not None
    assert len(calls) == 2


def test_generate_image_gives_up_on_non_transient_error(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr(config, "IMAGE_GEN_RETRY_SCHEDULE", (0, 0, 0))
    monkeypatch.setattr("pipeline.image_gen.time.sleep", lambda s: None)

    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _FakeResponse({"error": "API key not valid"}, status_code=400)

    monkeypatch.setattr("pipeline.image_gen.requests.post", fake_post)

    result = generate_image(_h(), "fake-key")
    assert result is None
    assert len(calls) == 1  # non-transient error breaks immediately, no retries


def test_generate_image_never_raises_on_total_failure(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr(config, "IMAGE_GEN_RETRY_SCHEDULE", (0,))
    monkeypatch.setattr("pipeline.image_gen.time.sleep", lambda s: None)

    def fake_post(*a, **k):
        raise ConnectionError("network is down")

    monkeypatch.setattr("pipeline.image_gen.requests.post", fake_post)

    assert generate_image(_h(), "fake-key") is None
