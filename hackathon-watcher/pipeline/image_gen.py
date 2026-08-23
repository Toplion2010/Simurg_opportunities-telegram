"""Fallback cover image generation via Gemini, for posts whose source gave
no real photo (a filtered-out generic placeholder, or a source that never
provides one at all). Adapted from Simurg's own
src/publisher/live_background.py — same model, same "Hackathon" scene
hints, same negative prompt — but synchronous (this project has no asyncio
elsewhere) and without the HTML/CSS card-compositing step: there's no
overlay template here, so the raw generated image is posted as-is and all
factual text lives in the Telegram caption instead.

Never cached: nothing about the model's output is deterministic or worth
persisting, matching the rationale in the module this was adapted from.
Never raises — a failed generation just means no image, never a lost post.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from hashlib import md5

import requests
from PIL import Image

import config
from pipeline.dedup import dedup_key
from sources.base import Hackathon

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

TARGET_WIDTH = 1200
TARGET_HEIGHT = 628

_STYLES = [
    "colorful minimalist",
    "futuristic neon",
    "cinematic realistic",
    "clean geometric",
    "premium dark tech",
    "soft gradient illustration",
    "bold flat vector design with thick outlines",
    "vibrant glossy 3D render, toy-like material",
    "playful low-poly 3D illustration",
    "retro-futurist poster art with halftone texture",
    "energetic comic-book style illustration",
    "clean corporate 3D icon render on a solid color background",
    "chrome and metallic 3D render",
    "warm cinematic photographic style with bokeh",
    "collage-style vibrant poster art",
    "watercolor textured illustration",
]

_MOODS = [
    "energetic and bold",
    "prestigious and calm",
    "innovative and modern",
    "warm and inviting",
    "sleek and professional",
    "dynamic and inspiring",
    "playful and fun",
    "vibrant and youthful",
    "high-energy and celebratory",
    "bright and optimistic",
]

_PALETTES = [
    "deep navy and electric blue",
    "charcoal and gold",
    "forest green and emerald",
    "deep purple and violet",
    "midnight blue and cyan",
    "burgundy and warm cream",
    "obsidian and neon teal",
    "bright green and white",
    "sunny yellow and coral",
    "vivid cyan and hot pink",
    "candy pink and mint",
    "electric orange and deep teal",
    "tropical lime and navy",
    "vivid red and cream white",
]

# Same literal scene imagery as Simurg's Hackathon category — deliberately
# concrete, not abstract blobs, for a poster-illustration look.
_SCENE_HINTS = [
    "a laptop glowing with lines of code against a futuristic city skyline",
    "a team hunched over glowing screens in a dark hall, no visible faces",
    "a wall of sticky notes and diagrams under warm workshop light",
    "a giant countdown clock glowing above an empty stage",
    "server racks with streaking light trails in a dark data hall",
    "an abstract circuit-board landscape glowing at dusk",
    "a trophy resting on a glowing mechanical keyboard",
    "a night-time open-plan office of glowing screens, seen from above",
]

NEGATIVE_PROMPT = (
    "text, words, letters, numbers, typography, captions, subtitles, logos, "
    "watermark, signature, "
    "people's faces, hands, "
    "low quality, blurry, noisy, grainy, pixelated, "
    "screenshot, UI, interface, button, icon, frame, border"
)

_TRANSIENT_MARKERS = (
    "rate", "429", "resource_exhausted", "quota", "500", "502", "503", "504",
    "unavailable", "timeout", "overloaded", "internal",
)

_EXCERPT_MAX_CHARS = 400


def _pick(items: list[str], seed_text: str, stride: int) -> str:
    """Deterministic on the hackathon's dedup key (stable hash, not
    Python's process-randomized hash()) so re-running the same item within
    a run picks the same axis — doesn't matter much since nothing is
    cached, but costs nothing and mirrors the module this was adapted
    from."""
    n = int(md5(seed_text.encode("utf-8")).hexdigest(), 16)
    return items[(n * stride) % len(items)]


def _compose_prompt(h: Hackathon) -> str:
    seed = dedup_key(h)
    style = _pick(_STYLES, seed, 7)
    mood = _pick(_MOODS, seed, 3)
    palette = _pick(_PALETTES, seed, 5)
    scene = _pick(_SCENE_HINTS, seed, 11)

    subject = f'a hackathon poster about "{h.title}"'
    context_bits = []
    if h.organizer:
        context_bits.append(f"organized by {h.organizer}")
    if h.location and h.is_online is not True:
        context_bits.append(f"in {h.location}")
    context = (" " + ", ".join(context_bits)) if context_bits else ""

    excerpt_text = h.description or (", ".join(h.themes) if h.themes else None)
    excerpt_block = ""
    if excerpt_text:
        excerpt_block = (
            f'\nContext (for subject matter only — do not render any of this '
            f'text in the image): "{excerpt_text[:_EXCERPT_MAX_CHARS]}"'
        )

    return (
        f"Create a vivid, modern digital illustration for {subject}{context}.\n"
        f"Style: {style}. Mood: {mood}. Color palette: {palette}.\n"
        f"Scene: {scene}, rendered fully in the {style} style described above — "
        f"do not default to a dark navy or moody tech look unless that's what "
        f"the style and palette above actually call for.{excerpt_block}\n"
        f"High resolution, {TARGET_WIDTH}x{TARGET_HEIGHT}, professional "
        "poster-illustration quality."
    )


def _model_chain() -> list[str]:
    chain = [config.GEMINI_IMAGE_MODEL]
    for name in config.GEMINI_IMAGE_FALLBACK_MODELS:
        if name and name not in chain:
            chain.append(name)
    return chain


def _call_gemini(prompt: str, api_key: str, model: str) -> bytes:
    payload = {
        "contents": [{"parts": [{"text": f"{prompt}\n\nAvoid: {NEGATIVE_PROMPT}"}]}],
        "generationConfig": {"responseModalities": ["image", "text"]},
    }
    url = f"{_API_BASE}/{model}:generateContent?key={api_key}"
    response = requests.post(url, json=payload, timeout=config.IMAGE_GEN_TIMEOUT)

    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:300]}")

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
        raise RuntimeError(f"Gemini returned no image: {reason}")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    for part in parts:
        inline = part.get("inline_data") or part.get("inlineData")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])

    finish_reason = candidates[0].get("finishReason", "unknown")
    raise RuntimeError(f"Gemini returned no image part (finishReason={finish_reason})")


def _crop_resize(raw: bytes, width: int = TARGET_WIDTH, height: int = TARGET_HEIGHT) -> bytes:
    """Center-crop + resize to an exact target size, re-encoded as JPEG —
    Gemini doesn't accept explicit dimensions, so whatever aspect ratio
    comes back is normalized here."""
    with Image.open(io.BytesIO(raw)) as img:
        img = img.convert("RGB")
        src_w, src_h = img.size
        target_ratio = width / height
        src_ratio = src_w / src_h

        if src_ratio > target_ratio:
            new_w = round(src_h * target_ratio)
            left = (src_w - new_w) // 2
            box = (left, 0, left + new_w, src_h)
        else:
            new_h = round(src_w / target_ratio)
            top = (src_h - new_h) // 2
            box = (0, top, src_w, top + new_h)

        cropped = img.crop(box).resize((width, height), Image.LANCZOS)
        out = io.BytesIO()
        cropped.save(out, format="JPEG", quality=92)
        return out.getvalue()


def generate_image(h: Hackathon, api_key: str | None) -> bytes | None:
    """Best-effort JPEG bytes, or None on any failure/misconfiguration —
    never raises. A missing image must never cost a post."""
    if not api_key or not config.IMAGE_GEN_ENABLED:
        return None

    try:
        prompt = _compose_prompt(h)
    except Exception:
        logger.warning("image_gen: failed to compose prompt for %r", h.title, exc_info=True)
        return None

    models = _model_chain()
    last_error: Exception | None = None

    for attempt, delay in enumerate(config.IMAGE_GEN_RETRY_SCHEDULE, start=1):
        model = models[(attempt - 1) % len(models)]
        if delay:
            time.sleep(delay)
        try:
            raw = _call_gemini(prompt, api_key, model)
            return _crop_resize(raw)
        except Exception as e:
            last_error = e
            logger.warning(
                "image_gen: attempt %d (%s) failed for %r: %s",
                attempt, model, h.title, e,
            )
            if not any(marker in str(e).lower() for marker in _TRANSIENT_MARKERS):
                break  # a bad key or blocked prompt won't fix itself on retry

    logger.warning("image_gen: giving up for %r: %s", h.title, last_error)
    return None
