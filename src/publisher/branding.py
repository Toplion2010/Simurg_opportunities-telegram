"""Per-channel Simurg branding stamped onto a rendered opportunity card.

The card (image_gen.py) is rendered once per opportunity and sent to several
channels, so branding happens afterwards, per target, in sender._send_card:
each channel's copy carries that channel's own wordmark and @handle.

Over the 1200x628 card it adds:
  * a faint diagonal pattern of "<BRAND> • @handle" across the whole frame,
    so no crop removes it
  * a band painted over the card's own 52px footer strip: logo mark +
    wordmark + @handle on the left, "✓ Checked by Simurg · 11 Oct" on the right
  * a small logo emblem top-right

hackathon-watcher/pipeline/branding.py is the sibling for the hackathons bot
(it brands raw Gemini art with a taller gradient band instead); the two can't
share code because the watcher runs standalone from its own directory.

Pillow is imported here and nowhere on the Vercel path -- sender imports this
module lazily -- and every failure returns the unbranded card, never nothing.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from src.core.logging import get_logger

logger = get_logger(__name__)

ASSETS = Path(__file__).parent / "assets"
# Each channel family has its own logo and accent colour, taken from its logo:
# neon green for Simurg Hackathons, cyan for Simurg Opportunities.
HACKATHONS_LOGO = ASSETS / "simurg_hackathons_mark.png"
OPPORTUNITIES_LOGO = ASSETS / "simurg_opportunities_mark.png"
GREEN = (124, 255, 79)
GREEN_SOFT = (164, 255, 128)
CYAN = (51, 230, 250)
CYAN_SOFT = (150, 240, 255)
INK = (3, 10, 14)

FOOTER_HEIGHT = 52  # src/publisher/design/spacing.py footer_height
WATERMARK_LINE_GAP = 128

_BOLD_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_REGULAR_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


@dataclass(frozen=True)
class ChannelBrand:
    name: str     # wordmark, e.g. "SIMURG OPPORTUNITIES"
    handle: str   # "@simurg_opportunities"
    logo: Path = OPPORTUNITIES_LOGO
    accent: tuple[int, int, int] = CYAN
    accent_soft: tuple[int, int, int] = CYAN_SOFT


def opportunities_brand(handle: str) -> ChannelBrand:
    return ChannelBrand("SIMURG OPPORTUNITIES", handle, OPPORTUNITIES_LOGO, CYAN, CYAN_SOFT)


def hackathons_brand(handle: str) -> ChannelBrand:
    return ChannelBrand("SIMURG HACKATHONS", handle, HACKATHONS_LOGO, GREEN, GREEN_SOFT)


@lru_cache(maxsize=None)
def _font(size: int, bold: bool):
    from PIL import ImageFont

    for path in _BOLD_FONTS if bold else _REGULAR_FONTS:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=4)
def _logo(path: Path):
    from PIL import Image

    try:
        with Image.open(path) as img:
            return img.convert("RGBA")
    except Exception:  # noqa: BLE001
        logger.warning("branding_logo_missing", path=str(path))
        return None


def _logo_at_height(path: Path, height: int, opacity: float = 1.0):
    from PIL import Image

    logo = _logo(path)
    if logo is None:
        return None
    width = max(1, round(logo.width * height / logo.height))
    scaled = logo.resize((width, height), Image.LANCZOS)
    if opacity < 1.0:
        scaled.putalpha(scaled.getchannel("A").point(lambda a: round(a * opacity)))
    return scaled


def _tracked(draw, xy, text, font, fill, tracking=0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def _tracked_width(draw, text, font, tracking=0) -> int:
    return round(draw.textlength(text, font=font) + tracking * max(0, len(text) - 1))


def _watermark(size, brand: ChannelBrand):
    from PIL import Image, ImageDraw

    w, h = size
    diag = int(math.hypot(w, h)) + 40
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(22, bold=True)
    unit = f"{brand.name}   •   {brand.handle}   •   "
    unit_w = max(1, _tracked_width(draw, unit, font, 3))
    row = unit * (diag // unit_w + 2)
    for i, y in enumerate(range(-WATERMARK_LINE_GAP, diag, WATERMARK_LINE_GAP)):
        x = -((i * unit_w) // 3) % unit_w - unit_w
        _tracked(draw, (x + 2, y + 2), row, font, (0, 0, 0, 12), 3)
        _tracked(draw, (x, y), row, font, (255, 255, 255, 17), 3)
    rotated = layer.rotate(24, resample=Image.BICUBIC)
    left, top = (diag - w) // 2, (diag - h) // 2
    return rotated.crop((left, top, left + w, top + h))


def _footer_band(size, brand: ChannelBrand, checked_on: date):
    from PIL import Image, ImageDraw

    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    top = h - FOOTER_HEIGHT
    # Opaque: this replaces the card's own footer text, not decorates it.
    draw.rectangle((0, top, w, h), fill=INK + (255,))
    for x in range(w):
        edge = min(x, w - x) / 260
        alpha = round(110 * min(1.0, edge))
        if alpha:
            layer.putpixel((x, top), brand.accent + (alpha,))

    center_y = top + FOOTER_HEIGHT // 2
    x = 24
    mark = _logo_at_height(brand.logo, 38)
    if mark is not None:
        layer.alpha_composite(mark, (x, center_y - mark.height // 2))
        x += mark.width + 10
    _tracked(draw, (x, center_y - 19), brand.name, _font(17, bold=True), (255, 255, 255, 245), 2)
    draw.text((x + 1, center_y + 2), brand.handle, font=_font(14, bold=False), fill=brand.accent_soft + (235,))

    label = f"Checked by Simurg · {checked_on.day} {checked_on.strftime('%b')}"
    label_font = _font(15, bold=False)
    label_w = _tracked_width(draw, label, label_font)
    check_w, pad, pill_h = 14, 12, 30
    x1 = w - 24
    x0 = x1 - (pad + check_w + 8 + label_w + pad)
    y0 = center_y - pill_h // 2
    # ImageDraw REPLACES pixels on an RGBA layer rather than blending, so a
    # translucent pill drawn straight onto the band would punch a hole through
    # it (the card's old footer text showed through). Draw it on its own layer.
    pill = Image.new("RGBA", size, (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(pill)
    pdraw.rounded_rectangle((x0, y0, x1, y0 + pill_h), radius=pill_h // 2,
                            fill=brand.accent + (34,), outline=brand.accent + (150,), width=2)
    layer.alpha_composite(pill)
    cx = x0 + pad
    draw.line([(cx, center_y + 1), (cx + 5, center_y + 6), (cx + check_w, center_y - 6)],
              fill=brand.accent + (255,), width=3, joint="curve")
    text_h = label_font.getbbox("Ag")[3] if hasattr(label_font, "getbbox") else 15
    draw.text((cx + check_w + 8, center_y - text_h // 2 - 1), label, font=label_font,
              fill=(255, 255, 255, 240))
    return layer


def _emblem(size, brand: ChannelBrand):
    from PIL import Image, ImageDraw, ImageFilter

    w, _ = size
    mark = _logo_at_height(brand.logo, 40, opacity=0.95)
    if mark is None:
        return None
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    x, y = w - 26 - mark.width, 20
    halo = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        (x - 12, y - 8, x + mark.width + 12, y + mark.height + 8), fill=INK + (110,)
    )
    layer.alpha_composite(halo.filter(ImageFilter.GaussianBlur(10)))
    layer.alpha_composite(mark, (x, y))
    return layer


def brand_card(image_bytes: bytes, brand: ChannelBrand, checked_on: date | None = None) -> bytes:
    """Branded JPEG bytes for one channel, or the input untouched on any error."""
    checked_on = checked_on or date.today()
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as src:
            canvas = src.convert("RGBA")
        canvas.alpha_composite(_watermark(canvas.size, brand))
        emblem = _emblem(canvas.size, brand)
        if emblem is not None:
            canvas.alpha_composite(emblem)
        canvas.alpha_composite(_footer_band(canvas.size, brand, checked_on))
        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception as e:  # noqa: BLE001
        logger.warning("card_branding_failed", error=str(e))
        return image_bytes
