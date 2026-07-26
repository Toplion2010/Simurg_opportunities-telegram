"""Read the text/details out of a post's attached image via Gemini vision.

Many opportunity posters carry key facts (prize amount, deadline, eligibility)
only inside the image, with a thin or empty caption. This module transcribes
that image text so it reaches the field extractor alongside the caption.

Best-effort by design: any failure (disabled, no key, unreadable file, API
error) returns None and the pipeline simply falls back to caption-only
extraction — image analysis enriches extraction, it never blocks it.
"""
import base64
import mimetypes

import httpx

from src.core.config import Settings
from src.core.logging import get_logger

logger = get_logger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_VISION_PROMPT = (
    "This image is a poster or flyer advertising an opportunity (a competition, "
    "scholarship, internship, hackathon, conference, grant, etc.).\n"
    "Transcribe ALL text visible in the image exactly as written — in particular the "
    "title, any prize or money amount, dates and deadlines, eligibility, location, "
    "organizer name, and any URLs or @handles.\n"
    'Pay special attention to large numbers or amounts shown as a graphic (e.g. a big '
    '"$8500" prize) and state them explicitly.\n'
    "Output plain text only — just the information found in the image, with no "
    "commentary, headings, or markdown. If the image has no readable text, output nothing."
)


class ImageReader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def read(self, image_path: str) -> str | None:
        """Return the text/details found in the image, or None if unavailable."""
        if not self._settings.ENABLE_IMAGE_ANALYSIS:
            return None
        api_key = self._settings.GEMINI_API_KEY
        if not api_key:
            return None

        try:
            with open(image_path, "rb") as f:
                raw = f.read()
        except OSError as e:
            logger.warning("image_read_failed", path=image_path, error=str(e))
            return None

        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode("ascii")}},
                        {"text": _VISION_PROMPT},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1},
        }
        model = self._settings.GEMINI_VISION_MODEL
        url = f"{_API_BASE}/{model}:generateContent?key={api_key}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url, json=payload, headers={"Content-Type": "application/json"}
                )
            if resp.status_code != 200:
                logger.warning(
                    "image_analysis_http_error", status=resp.status_code, body=resp.text[:200]
                )
                return None
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return None
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            return text or None
        except Exception as e:  # noqa: BLE001 — best-effort; never block extraction
            logger.warning("image_analysis_failed", path=image_path, error=str(e))
            return None
