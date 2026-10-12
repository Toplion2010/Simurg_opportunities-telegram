from __future__ import annotations

import io
from datetime import date

from PIL import Image

import config
from pipeline.branding import HEIGHT, WIDTH, brand_image


def _jpeg(size=(WIDTH, HEIGHT), color=(20, 30, 60)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


def test_brands_to_card_size_and_changes_pixels():
    src = _jpeg()
    out = brand_image(src, date(2026, 10, 11))
    assert out != src
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (WIDTH, HEIGHT)
        # Bottom band is darker than the flat source color; watermark lightens
        # some pixels in the middle of the frame.
        assert img.getpixel((WIDTH // 2, HEIGHT - 5))[2] < 60
        middle = [img.getpixel((x, HEIGHT // 2))[0] for x in range(0, WIDTH, 3)]
        assert max(middle) > 20


def test_non_card_aspect_is_cropped_to_card():
    out = brand_image(_jpeg(size=(800, 800)))
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (WIDTH, HEIGHT)


def test_disabled_returns_input(monkeypatch):
    monkeypatch.setattr(config, "CARD_BRANDING_ENABLED", False)
    src = _jpeg()
    assert brand_image(src) is src


def test_garbage_input_returns_input_never_raises():
    assert brand_image(b"not an image") == b"not an image"


def test_missing_logo_still_brands(monkeypatch):
    from pipeline import branding

    branding._logo.cache_clear()
    monkeypatch.setattr(config, "LOGO_PATH", "/nonexistent/logo.png")
    src = _jpeg()
    try:
        assert brand_image(src) != src
    finally:
        branding._logo.cache_clear()


def test_brand_name_follows_channel_handle():
    from pipeline.branding import brand_name_for

    assert brand_name_for("@simurg_opportunities") == "SIMURG OPPORTUNITIES"
    assert brand_name_for(None) == "SIMURG HACKATHONS"
    assert brand_image(_jpeg(), handle="@simurg_opportunities") != brand_image(_jpeg())
