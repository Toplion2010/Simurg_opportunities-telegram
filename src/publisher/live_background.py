"""Live, per-post background generation via Gemini (``gemini-2.5-flash-image``, "Nano Banana").

A deliberate runtime generation path: every approved opportunity gets a freshly
generated, opportunity-specific illustration built from its actual title, category,
organizer, location and original source-channel text.

This module still raises on failure after its bounded retries. The recovery lives
one level up: ``image_gen.generate_card`` catches it and renders the procedural
background instead, so a Gemini outage degrades the card's look rather than
blocking the post entirely.

The image is required to contain **zero text** (see ``NEGATIVE_PROMPT``). Image
models are unreliable at rendering exact dates, numbers, currency and URLs, so none
of that is ever asked of the model — all factual text (title, deadline, prize, CTA)
is rendered separately by ``image_gen.py``'s HTML/CSS template, which is always
correct. The model only supplies mood/style/scene.
"""
from __future__ import annotations

import base64
import io
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PIL import Image, ImageStat

from src.core.logging import get_logger
from src.publisher.background_manager import SafeArea

if TYPE_CHECKING:
    from src.db.models.opportunity import Opportunity

logger = get_logger(__name__)

TARGET_WIDTH = 1200
TARGET_HEIGHT = 628

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_RAW_TEXT_EXCERPT_LEN = 400

# Seconds to wait before each attempt. A 503 ("high demand") is a capacity spike
# that outlasts a couple of seconds, so the old 5s/10s schedule almost always
# gave up while the model was still busy. Each attempt also rotates to the next
# model in the chain, because congestion is per-model — when one model is
# saturated a sibling usually answers immediately.
#
# Capped at 3 attempts: every attempt is a billed image generation, and the
# 25s/45s ones arrived long after the free procedural fallback in
# image_gen.generate_card() would have produced a perfectly good card. Three
# keeps the outage tolerance that motivated retrying at all.
_RETRY_SCHEDULE = (0, 4, 10)

_TRANSIENT_MARKERS = (
    "rate", "429", "resource_exhausted", "quota", "500", "502", "503", "504",
    "unavailable", "timeout", "overloaded", "internal",
)

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

# Category name -> literal scene imagery, deliberately concrete (not abstract
# blobs) to match a poster-illustration look rather than a plain gradient.
# Lists, not single strings: selection is deterministic on opp.id (see
# _compose_prompt), so the list length is what actually creates variety.
_SCENE_HINTS: dict[str, list[str]] = {
    "Scholarship": [
        "a graduation cap and glowing academic architecture, columns and light rays",
        "a stack of books radiating light beneath a glowing archway",
        "a scroll/diploma unfurling light rays over classical columns",
        "a glowing mortarboard cap tossed above a sunlit campus quad",
    ],
    "Fellowship": [
        "an open book radiating light beside classical academic architecture",
        "a glowing quill and manuscript on an ornate wooden desk",
        "a lit library reading room with tall glowing bookshelves",
    ],
    "Research": [
        "a scientist's workspace with glowing data visualizations and lab equipment",
        "a glowing microscope beside floating data charts",
        "a wall of glowing molecular/DNA diagrams in a dark lab",
        "a telescope silhouette against a glowing star field",
    ],
    "Conference": [
        "a modern stage with a glowing podium and an audience silhouette skyline",
        "rows of glowing conference seats facing a bright presentation screen",
        "a glowing microphone on a stand against a stage backdrop",
    ],
    "Hackathon": [
        "a laptop glowing with lines of code against a futuristic city skyline",
        "a team hunched over glowing screens in a dark hall, no visible faces",
        "a wall of sticky notes and diagrams under warm workshop light",
        "a giant countdown clock glowing above an empty stage",
        "server racks with streaking light trails in a dark data hall",
        "an abstract circuit-board landscape glowing at dusk",
        "a trophy resting on a glowing mechanical keyboard",
        "a night-time open-plan office of glowing screens, seen from above",
    ],
    "Competition": [
        "a glowing trophy surrounded by dynamic light trails",
        "a podium with a glowing spotlight beam from above",
        "a finish-line ribbon glowing under stadium lights",
    ],
    "Olympiad": [
        "a medal and glowing geometric podium with light rays",
        "a glowing laurel wreath over an abstract podium",
        "a chalkboard covered in glowing equations and geometric shapes",
    ],
    "Internship": [
        "a modern glass office tower with glowing windows at dusk",
        "a glowing laptop and coffee cup on a minimalist desk",
        "a bright open-plan office with glowing desks, seen from above",
    ],
    "Job": [
        "a sleek modern workspace with a glowing city skyline backdrop",
        "a glowing briefcase silhouette against a corporate skyline",
        "a handshake silhouette rendered in glowing light trails",
    ],
    "Startup": [
        "a rocket launch silhouette with a glowing futuristic cityscape",
        "a glowing upward arrow breaking through abstract clouds",
        "a lightbulb silhouette bursting into glowing light trails",
    ],
    "Accelerator": [
        "abstract upward-trending light trails over a city skyline",
        "a glowing speedometer/gauge motif with light streaks",
        "concentric glowing rings expanding outward, like a launch pad",
    ],
    "Incubator": [
        "a glowing seedling/sprout motif rendered in a tech aesthetic",
        "a glowing egg/nest motif in a soft warm gradient",
        "a glowing greenhouse silhouette with rising light particles",
    ],
    "Grant": [
        "a glowing coin or light-beam motif over abstract architecture",
        "a glowing envelope with light spilling out of it",
        "an abstract fountain of glowing light particles rising upward",
    ],
    "SummerProgram": [
        "sunlit academic campus architecture with a bright, warm glow",
        "a glowing sun above a stylized campus skyline",
        "a warm glowing beach/campus horizon line at golden hour",
    ],
    "Exchange": [
        "a globe with glowing flight-path arcs connecting cities",
        "two glowing passport/ticket silhouettes crossing paths",
        "a glowing world map with pinned city markers",
    ],
    "Volunteer": [
        "glowing hands forming a heart or circle over a soft cityscape",
        "a glowing tree with light-particle leaves over a community silhouette",
        "a circle of glowing silhouettes holding hands, no visible faces",
    ],
}
_DEFAULT_SCENE_HINT = [
    "an abstract symbol of achievement and opportunity",
    "a glowing upward staircase rendered in abstract light",
    "an open glowing door silhouette against abstract light rays",
]

NEGATIVE_PROMPT = (
    "text, words, letters, numbers, typography, captions, subtitles, logos, "
    "watermark, signature, "
    "people's faces, hands, "
    "low quality, blurry, noisy, grainy, pixelated, "
    "screenshot, UI, interface, button, icon, frame, border"
)


@dataclass(frozen=True)
class LiveBackground:
    """A freshly generated background image, held in memory only.

    Never written to disk — every post gets a new one, so nothing is cached.
    Duck-types the fields of ``background_manager.ImageEntry`` that
    ``image_gen.py`` and ``grammar/engine.py`` actually read (``brightness``,
    ``contrast``, ``visual_complexity``, ``primary_safe_area``), plus ``data``
    in place of a filesystem ``path``.
    """

    data: bytes
    brightness: float | None = None
    contrast: float | None = None
    visual_complexity: float | None = None
    primary_safe_area: SafeArea = field(default_factory=SafeArea)


def _pick(items: list[str], opp_id: int | None, stride: int) -> str:
    """Deterministic on opp_id (coprime stride so consecutive ids differ on
    every axis), falling back to random for the rare case of an unflushed
    opportunity with no id yet (e.g. scripts/render_preview.py)."""
    if opp_id is None:
        return random.choice(items)
    return items[(opp_id * stride) % len(items)]


def _compose_prompt(opp: "Opportunity") -> str:
    category_name = opp.category.value if opp.category else "opportunity"
    scenes = _SCENE_HINTS.get(category_name, _DEFAULT_SCENE_HINT)
    opp_id = getattr(opp, "id", None)

    # Strides are each coprime with every list length in play (16, 10, 13, and
    # every scene-list length from 3 to 8), so consecutive ids differ on all
    # four axes and the full tuple only repeats after lcm(16,10,13,len(scenes))
    # posts — randomness was the collision source, not the feature.
    style = _pick(_STYLES, opp_id, 7)
    mood = _pick(_MOODS, opp_id, 3)
    palette = _pick(_PALETTES, opp_id, 5)
    scene = _pick(scenes, opp_id, 11)

    subject = (
        f'a {category_name.lower()} opportunity poster about "{opp.title}"'
        if opp.title
        else f"a {category_name.lower()} opportunity poster"
    )
    context_bits = []
    if opp.organizer:
        context_bits.append(f"organized by {opp.organizer}")
    if opp.location:
        context_bits.append(f"in {opp.location}")
    context = (" " + ", ".join(context_bits)) if context_bits else ""

    source_excerpt = getattr(opp, "source_excerpt", None)
    if source_excerpt:
        excerpt_text = source_excerpt.strip()
    else:
        raw_message = getattr(opp, "raw_message", None)
        raw_text = getattr(raw_message, "text", None) if raw_message else None
        excerpt_text = raw_text.strip()[:_RAW_TEXT_EXCERPT_LEN] if raw_text else None

    excerpt_block = ""
    if excerpt_text:
        excerpt_block = (
            f'\nOriginal announcement excerpt (context only, for subject matter — '
            f'do not render any of this text in the image): "{excerpt_text}"'
        )

    return (
        f"Create a vivid, modern digital illustration for {subject}{context}.\n"
        f"Style: {style}. Mood: {mood}. Color palette: {palette}.\n"
        f"Scene: {scene}, rendered fully in the {style} style described above — do not "
        f"default to a dark navy or moody tech look unless that's what the style and "
        f"palette above actually call for.{excerpt_block}\n"
        "Composition: large smooth negative space across the left two-thirds for text "
        "overlay; concentrate visual interest on the right side and background.\n"
        "High resolution, 1200x628, professional poster-illustration quality."
    )


def _crop_resize_to_card(raw: bytes, width: int = TARGET_WIDTH, height: int = TARGET_HEIGHT) -> bytes:
    """Center-crop + resize to the card's exact target size, re-encoded as JPEG.

    Gemini doesn't accept explicit width/height, so whatever aspect ratio it
    returns gets normalized here before it's ever handed to the HTML template.
    """
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


def _compute_metrics(jpeg_bytes: bytes) -> tuple[float, float]:
    with Image.open(io.BytesIO(jpeg_bytes)) as img:
        gray = img.convert("L")
        stat = ImageStat.Stat(gray)
        brightness = round(stat.mean[0] / 255.0, 3)
        contrast = round(stat.stddev[0] / 255.0, 3)
    return brightness, contrast


def _model_chain(settings) -> list[str]:
    """Primary image model first, then configured siblings, de-duplicated.

    Order matters: the primary is the model whose look the channel is tuned to,
    so siblings are only ever reached when it is unreachable.
    """
    chain = [settings.GEMINI_IMAGE_MODEL]
    for name in settings.GEMINI_IMAGE_FALLBACK_MODELS.split(","):
        name = name.strip()
        if name and name not in chain:
            chain.append(name)
    return chain


async def _call_gemini(prompt: str, api_key: str, model: str) -> bytes:
    import httpx

    payload = {
        "contents": [{"parts": [{"text": f"{prompt}\n\nAvoid: {NEGATIVE_PROMPT}"}]}],
        "generationConfig": {"responseModalities": ["image", "text"]},
    }
    url = f"{_API_BASE}/{model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})

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


async def generate_live_background(opp: "Opportunity") -> LiveBackground:
    """Generate a fresh, opportunity-specific background.

    Raises after a few bounded retries on transient errors. The caller
    (``image_gen.generate_card``) decides what that means — it degrades to the
    procedural background so the post still ships.
    """
    import asyncio

    from src.core.config import Settings

    settings = Settings()
    if not settings.ENABLE_LIVE_BACKGROUND:
        raise RuntimeError("ENABLE_LIVE_BACKGROUND is off")
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    prompt = _compose_prompt(opp)
    models = _model_chain(settings)
    opp_id = getattr(opp, "id", None)

    last_error: Exception | None = None
    attempt = 0
    for attempt, delay in enumerate(_RETRY_SCHEDULE, start=1):
        model = models[(attempt - 1) % len(models)]
        if delay:
            # Jitter so several posts in one batch don't retry in lockstep and
            # hammer the same model at the same instant.
            await asyncio.sleep(delay + random.uniform(0, 2))
        try:
            raw = await _call_gemini(prompt, api_key, model)
            jpeg_bytes = _crop_resize_to_card(raw)
            brightness, contrast = _compute_metrics(jpeg_bytes)
            logger.info(
                "live_background_generated", opp_id=opp_id, attempt=attempt, model=model
            )
            return LiveBackground(data=jpeg_bytes, brightness=brightness, contrast=contrast)
        except Exception as e:  # noqa: BLE001
            last_error = e
            logger.warning(
                "live_background_attempt_failed",
                opp_id=opp_id,
                attempt=attempt,
                model=model,
                error=str(e),
            )
            msg = str(e).lower()
            if not any(s in msg for s in _TRANSIENT_MARKERS):
                break  # a bad key or blocked prompt won't fix itself on retry

    raise RuntimeError(
        f"Live background generation failed after {attempt} attempt(s): {last_error}"
    ) from last_error
