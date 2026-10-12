"""Simurg branding for every image the watcher posts.

Composited with Pillow on top of the cover art (Gemini-generated, or the
source's own photo), so a copied image still reads as Simurg content:

  * a faint diagonal pattern of "SIMURG HACKATHONS • @simurg_hackathons"
    across the whole frame -- there is no corner you can crop to lose it
  * a bottom band: logo mark + SIMURG HACKATHONS + @handle on the left,
    "✓ Checked by Simurg · 11 Oct" on the right
  * a small logo emblem top-right

The logo is a transparent PNG at config.LOGO_PATH (SIMURG_LOGO_PATH), so it is
swapped by replacing a file. Never raises: if anything here fails, the
unbranded image is posted, never nothing.
"""

from __future__ import annotations

import io
import logging
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

logger = logging.getLogger(__name__)

WIDTH = 1200
HEIGHT = 628

BRAND_NAME = "SIMURG HACKATHONS"
GREEN = (124, 255, 79)        # the logo's neon green
GREEN_SOFT = (164, 255, 128)
INK = (3, 12, 6)              # near-black with a green cast, for the band

_BOLD_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_REGULAR_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


@lru_cache(maxsize=None)
def _font(size: int, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    explicit = config.CARD_FONT_BOLD_PATH if bold else config.CARD_FONT_PATH
    for path in ([explicit] if explicit else []) + (_BOLD_FONTS if bold else _REGULAR_FONTS):
        if path and Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=4)
def _logo(path: str) -> Image.Image | None:
    try:
        with Image.open(path) as img:
            return img.convert("RGBA")
    except Exception:
        logger.warning("branding: logo not loadable at %s, branding without it", path)
        return None


def _logo_at_height(height: int, opacity: float = 1.0) -> Image.Image | None:
    logo = _logo(config.LOGO_PATH)
    if logo is None:
        return None
    width = max(1, round(logo.width * height / logo.height))
    scaled = logo.resize((width, height), Image.LANCZOS)
    if opacity < 1.0:
        alpha = scaled.getchannel("A").point(lambda a: round(a * opacity))
        scaled.putalpha(alpha)
    return scaled


def _text_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: int = 0) -> int:
    if not text:
        return 0
    width = draw.textlength(text, font=font)
    return round(width + tracking * (len(text) - 1))


def _draw_tracked(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font,
                  fill, tracking: int = 0) -> None:
    """Letter-spaced text — the logo's wordmark is set wide, so the band's is too."""
    if not tracking:
        draw.text(xy, text, font=font, fill=fill)
        return
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


# Distance between watermark rows. 128px (was 92) = ~28% fewer repetitions:
# still no crop-safe corner, but it no longer competes with the artwork.
WATERMARK_LINE_GAP = 128


def _watermark_layer(size: tuple[int, int], brand_name: str, handle: str) -> Image.Image:
    """Diagonal repeated wordmark at very low opacity, in two tones (light
    with a dark offset) so it stays faintly visible on bright and dark art."""
    w, h = size
    diag = int(math.hypot(w, h)) + 40
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(22, bold=True)
    unit = f"{brand_name}   •   {handle}   •   " if handle else f"{brand_name}   •   "
    unit_w = max(1, _text_width(draw, unit, font, tracking=3))
    row = unit * (diag // unit_w + 2)
    line_gap = WATERMARK_LINE_GAP
    for i, y in enumerate(range(-line_gap, diag, line_gap)):
        x = -((i * unit_w) // 3) % unit_w - unit_w  # stagger rows like brickwork
        _draw_tracked(draw, (x + 2, y + 2), row, font, (0, 0, 0, 12), tracking=3)
        _draw_tracked(draw, (x, y), row, font, (255, 255, 255, 17), tracking=3)
    rotated = layer.rotate(24, resample=Image.BICUBIC)
    left, top = (diag - w) // 2, (diag - h) // 2
    return rotated.crop((left, top, left + w, top + h))


def _band_layer(size: tuple[int, int], checked_on: date, brand_name: str, handle: str) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))

    # Soft gradient so the band melts into the art instead of a hard box.
    band_top = h - 150
    gradient = Image.new("L", (1, 150))
    for i in range(150):
        t = i / 149
        gradient.putpixel((0, i), round(225 * (t ** 1.6)))
    shade = Image.new("RGBA", (w, 150), INK + (255,))
    shade.putalpha(gradient.resize((w, 150)))
    layer.alpha_composite(shade, (0, band_top))

    draw = ImageDraw.Draw(layer)
    margin = 30
    center_y = h - 42

    # Hairline accent that fades out toward both edges.
    line_y = h - 86
    for x in range(margin, w - margin):
        edge = min(x - margin, w - margin - x) / 220
        alpha = round(90 * min(1.0, edge))
        if alpha:
            layer.putpixel((x, line_y), GREEN + (alpha,))

    # Left: logo mark + wordmark + handle.
    x = margin
    mark = _logo_at_height(56)
    if mark is not None:
        layer.alpha_composite(mark, (x, center_y - mark.height // 2))
        x += mark.width + 14
    title_font = _font(25, bold=True)
    handle_font = _font(18, bold=False)
    _draw_tracked(draw, (x, center_y - 27), brand_name, title_font, (255, 255, 255, 245), tracking=3)
    if handle:
        draw.text((x + 1, center_y + 5), handle, font=handle_font, fill=GREEN_SOFT + (235,))

    # Right: verification pill with a drawn check mark (no glyph dependency).
    label = f"Checked by Simurg · {checked_on.day} {checked_on.strftime('%b')}"
    label_font = _font(19, bold=False)
    label_w = _text_width(draw, label, label_font)
    check_w, pad_x, pill_h = 18, 16, 40
    pill_w = pad_x + check_w + 10 + label_w + pad_x
    pill_x1 = w - margin
    pill_x0 = pill_x1 - pill_w
    pill_y0 = center_y - pill_h // 2
    # Own layer: ImageDraw replaces RGBA pixels instead of blending, so drawing
    # the translucent pill directly would cut a lighter hole in the gradient.
    pill = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle(
        (pill_x0, pill_y0, pill_x1, pill_y0 + pill_h), radius=pill_h // 2,
        fill=GREEN + (34,), outline=GREEN + (150,), width=2,
    )
    layer.alpha_composite(pill)
    cx = pill_x0 + pad_x
    draw.line(
        [(cx, center_y + 1), (cx + 6, center_y + 7), (cx + check_w, center_y - 7)],
        fill=GREEN + (255,), width=4, joint="curve",
    )
    text_h = label_font.getbbox("Ag")[3] if hasattr(label_font, "getbbox") else 19
    draw.text((cx + check_w + 10, center_y - text_h // 2 - 1), label, font=label_font,
              fill=(255, 255, 255, 240))
    return layer


def _emblem_layer(size: tuple[int, int]) -> Image.Image | None:
    w, _ = size
    mark = _logo_at_height(46, opacity=0.95)
    if mark is None:
        return None
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    x, y = w - 28 - mark.width, 22
    # Dark halo so the mark reads on bright art too.
    halo = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        (x - 14, y - 10, x + mark.width + 14, y + mark.height + 10), fill=INK + (120,)
    )
    layer.alpha_composite(halo.filter(ImageFilter.GaussianBlur(12)))
    layer.alpha_composite(mark, (x, y))
    return layer


def _fit(img: Image.Image, width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """Center-crop to the card's aspect ratio and resize."""
    src_w, src_h = img.size
    target = width / height
    if src_w / src_h > target:
        new_w = round(src_h * target)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        new_h = round(src_w / target)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))
    return img.resize((width, height), Image.LANCZOS)


def brand_name_for(handle: str | None) -> str:
    """'@simurg_opportunities' -> 'SIMURG OPPORTUNITIES'; default wordmark
    for the hackathons channel or no handle."""
    if not handle:
        return BRAND_NAME
    return handle.lstrip("@").replace("_", " ").upper()


def brand_image(image_bytes: bytes, checked_on: date | None = None,
                handle: str | None = None) -> bytes:
    """Returns branded JPEG bytes — or the input untouched if branding is
    disabled or fails for any reason. `handle` picks the channel the card is
    branded for (default config.CHANNEL_HANDLE, i.e. @simurg_hackathons);
    the wordmark follows it."""
    if not config.CARD_BRANDING_ENABLED:
        return image_bytes
    checked_on = checked_on or date.today()
    handle = config.CHANNEL_HANDLE if handle is None else handle
    brand_name = brand_name_for(handle)
    try:
        with Image.open(io.BytesIO(image_bytes)) as src:
            base = src.convert("RGB")
        if base.size != (WIDTH, HEIGHT):
            base = _fit(base)
        canvas = base.convert("RGBA")
        canvas.alpha_composite(_watermark_layer(canvas.size, brand_name, handle))
        emblem = _emblem_layer(canvas.size)
        if emblem is not None:
            canvas.alpha_composite(emblem)
        canvas.alpha_composite(_band_layer(canvas.size, checked_on, brand_name, handle))
        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception:
        logger.warning("branding: failed, posting the unbranded image", exc_info=True)
        return image_bytes


def fetch_and_brand_photo(url: str, checked_on: date | None = None) -> bytes | None:
    """The source's own cover photo, fetched and branded — used when Gemini
    generation is off or failed. None if it can't be fetched/decoded, in
    which case the caller sends the URL as before (unbranded)."""
    try:
        response = requests.get(url, timeout=config.IMAGE_GEN_TIMEOUT,
                                headers={"User-Agent": config.USER_AGENT})
        if not response.ok:
            return None
        mime = response.headers.get("Content-Type", "").split(";")[0].strip()
        if mime and not mime.startswith("image/"):
            return None
        branded = brand_image(response.content, checked_on)
        # brand_image returns its input on failure; only send what we branded.
        return branded if branded is not response.content else None
    except Exception:
        logger.warning("branding: could not fetch cover photo %s", url, exc_info=True)
        return None
