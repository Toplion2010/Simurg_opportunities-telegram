"""AI Background Generator — backend interface, not a vendor (ADR-005).

An interface for generating background images via FLUX-class models
(or any other image generation backend).  Reads its own local API token;
resumable; supports --dry-run cost estimation.

This is an **offline tool** — never imported by src/ at runtime.
Generated images go through QC before entering the library.

Usage:
    python -m tools.generate_ai_backgrounds --category Scholarship --n 10
    python -m tools.generate_ai_backgrounds --all --n 50
    python -m tools.generate_ai_backgrounds --dry-run --all --n 100
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageStat

# ------------------------------------------------------------------ Config

# The generator reads its own API token from a local file, never from
# the project's .env or code.  This keeps generation credentials separate
# from bot/deployment credentials.
DEFAULT_TOKEN_FILE = Path("tools/.gen_token")

# Output directory for new images. Must match what BackgroundManager.scan()
# actually reads: direct theme sub-folders of backgrounds/ (e.g. backgrounds/academic/),
# never a nested backgrounds/generated/<category>/ that the scanner never recurses into.
DEFAULT_OUTPUT_DIR = Path("backgrounds")

# Target image dimensions.
TARGET_WIDTH = 1200
TARGET_HEIGHT = 628

# All known categories for --all mode.
ALL_CATEGORIES = [
    "Scholarship", "Fellowship", "Research", "Conference",
    "Hackathon", "Competition", "Olympiad", "Internship",
    "Job", "Startup", "Accelerator", "Incubator", "Grant",
    "SummerProgram", "Exchange", "Volunteer",
]


# ------------------------------------------------------------------ Backend interface


class GenerationBackend:
    """Interface for image generation backends.

    Subclasses implement ``generate()``.  Today's reference
    implementation targets a FLUX-class model via an OpenAI-compatible API.
    """

    # Whether this backend needs a token from DEFAULT_TOKEN_FILE. Anonymous
    # no-signup backends (e.g. Pollinations) override this to False.
    requires_api_key: bool = True

    # Politeness delay between requests, in seconds. Backends with a known
    # anonymous rate limit (e.g. Pollinations' ~1 req/15s) override this.
    request_delay: float = 1.0

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.flux.ai/v1",
        model: str = "flux-1-schnell",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    async def generate(
        self,
        positive_prompt: str,
        negative_prompt: str,
        width: int = TARGET_WIDTH,
        height: int = TARGET_HEIGHT,
    ) -> bytes:
        """Generate a single image. Returns raw image bytes (JPEG).

        Raises RuntimeError on failure (rate limit, auth, etc.).
        """
        raise NotImplementedError

    @property
    def estimated_cost_per_image(self) -> float:
        """Estimated USD cost per image generation."""
        return 0.02  # typical FLUX-class price


# ------------------------------------------------------------------ OpenAI-compatible backend


class OpenAIBackend(GenerationBackend):
    """Backend for any OpenAI-compatible image generation API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "flux-1-schnell",
    ) -> None:
        super().__init__(api_key, base_url, model)

    async def generate(
        self,
        positive_prompt: str,
        negative_prompt: str,
        width: int = TARGET_WIDTH,
        height: int = TARGET_HEIGHT,
    ) -> bytes:
        import httpx

        # Combine prompts for backends that don't support negative prompts natively.
        combined = positive_prompt
        if negative_prompt:
            combined += f"\n\nNegative prompt: {negative_prompt}"

        payload = {
            "model": self.model,
            "prompt": combined,
            "width": width,
            "height": height,
            "n": 1,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/images/generations",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

        if response.status_code != 200:
            body = response.text[:200]
            raise RuntimeError(
                f"API error {response.status_code}: {body}"
            )

        data = response.json()

        # Handle both data:base64 and url formats
        result = data.get("data", [{}])[0]
        if "b64_json" in result:
            import base64
            return base64.b64decode(result["b64_json"])
        elif "url" in result:
            async with httpx.AsyncClient(timeout=30.0) as client:
                img_resp = await client.get(result["url"])
            return img_resp.content
        else:
            raise RuntimeError(f"Unexpected API response format: {data}")


# ------------------------------------------------------------------ Gemini backend


class GeminiBackend(GenerationBackend):
    """Backend for Google's Gemini image model (``gemini-2.5-flash-image``, "Nano Banana").

    Free tier, no credit card required. Unlike ``OpenAIBackend`` this is the default —
    it's the only backend that costs nothing to run.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str = "gemini-2.5-flash-image",
    ) -> None:
        super().__init__(api_key, base_url, model)

    async def generate(
        self,
        positive_prompt: str,
        negative_prompt: str,
        width: int = TARGET_WIDTH,
        height: int = TARGET_HEIGHT,
    ) -> bytes:
        import base64

        import httpx

        combined = positive_prompt
        if negative_prompt:
            combined += f"\n\nAvoid: {negative_prompt}"

        payload = {
            "contents": [{"parts": [{"text": combined}]}],
            "generationConfig": {"responseModalities": ["image", "text"]},
        }
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            )

        if response.status_code != 200:
            body = response.text[:300]
            raise RuntimeError(f"API error {response.status_code}: {body}")

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
            raise RuntimeError(f"Gemini returned no image: {reason}")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        for part in parts:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                raw = base64.b64decode(inline["data"])
                return _crop_resize_to_card(raw, width, height)

        finish_reason = candidates[0].get("finishReason", "unknown")
        raise RuntimeError(f"Gemini returned no image part (finishReason={finish_reason})")

    @property
    def estimated_cost_per_image(self) -> float:
        return 0.0


def _crop_resize_to_card(raw: bytes, width: int = TARGET_WIDTH, height: int = TARGET_HEIGHT) -> bytes:
    """Center-crop + resize arbitrary image bytes to the card's exact target size.

    Gemini doesn't accept explicit width/height like the OpenAI-compatible API does,
    so whatever aspect ratio it returns gets normalized here before it's ever written
    to disk or scored by QC.
    """
    import io

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
        cropped.save(out, format="JPEG", quality=90)
        return out.getvalue()


# ------------------------------------------------------------------ Pollinations backend


class PollinationsBackend(GenerationBackend):
    """Backend for Pollinations.ai — genuinely free: no API key, no signup, no billing.

    As of 2026, Google no longer grants any free-tier quota for Gemini's image-output
    models (confirmed live: every image-capable Gemini model returns a hard 0 free-tier
    request quota, even on established projects) — so this is the actual no-cost default,
    with Gemini kept available via ``--backend gemini`` for once billing is enabled.

    Anonymous requests are rate-limited to roughly one per 15s; ``request_delay`` reflects
    that so ``run_generation``'s politeness sleep doesn't hammer it into 429s.
    """

    requires_api_key = False
    request_delay = 16.0

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://image.pollinations.ai",
        model: str = "flux",
    ) -> None:
        super().__init__(api_key, base_url, model)

    async def generate(
        self,
        positive_prompt: str,
        negative_prompt: str,
        width: int = TARGET_WIDTH,
        height: int = TARGET_HEIGHT,
    ) -> bytes:
        import urllib.parse

        import httpx

        combined = positive_prompt
        if negative_prompt:
            combined += f"\n\nAvoid: {negative_prompt}"

        encoded = urllib.parse.quote(combined)
        url = (
            f"{self.base_url}/prompt/{encoded}"
            f"?width={width}&height={height}&nologo=true&model={self.model}"
        )

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(url)

        if response.status_code != 200:
            body = response.text[:200]
            raise RuntimeError(f"API error {response.status_code}: {body}")

        return _crop_resize_to_card(response.content, width, height)

    @property
    def estimated_cost_per_image(self) -> float:
        return 0.0


BACKENDS: dict[str, type[GenerationBackend]] = {
    "pollinations": PollinationsBackend,
    "gemini": GeminiBackend,
    "openai": OpenAIBackend,
}

DEFAULT_BACKEND = "pollinations"

# Used only for the --dry-run cost estimate (no backend is instantiated there).
_DRY_RUN_COST_PER_IMAGE: dict[str, float] = {"pollinations": 0.0, "gemini": 0.0, "openai": 0.02}


# ------------------------------------------------------------------ CLI


_THEME_INDEX_RE = re.compile(r"^(.+)_(\d+)$")


def _existing_theme_counts(output_dir: Path) -> dict[str, int]:
    """Highest existing per-theme image index, scanned from files already on disk.

    Several categories share one theme folder (e.g. Scholarship/Fellowship/SummerProgram/
    Competition/Olympiad -> academic), so the counter is per-theme, not per-category —
    otherwise two categories writing into the same folder would collide on filenames.
    """
    counts: dict[str, int] = {}
    if not output_dir.is_dir():
        return counts
    for theme_dir in output_dir.iterdir():
        if not theme_dir.is_dir():
            continue
        theme = theme_dir.name
        max_idx = 0
        for img in (
            list(theme_dir.glob("*.jpg"))
            + list(theme_dir.glob("*.jpeg"))
            + list(theme_dir.glob("*.png"))
        ):
            m = _THEME_INDEX_RE.match(img.stem)
            if m and m.group(1) == theme:
                max_idx = max(max_idx, int(m.group(2)))
        counts[theme] = max_idx
    return counts


async def run_generation(
    categories: list[str] | None,
    count: int,
    output_dir: Path,
    dry_run: bool = False,
    resume: bool = True,
    token_file: Path = DEFAULT_TOKEN_FILE,
    backend_name: str = DEFAULT_BACKEND,
    model: str | None = None,
) -> None:
    """Main generation loop."""
    from tools.prompt_composer import GeneratedPrompt, compose, load_negative_prompt
    from src.core.enums import Category
    from src.publisher.background_map import theme_for_category

    negative = load_negative_prompt()

    if not categories:
        categories = ALL_CATEGORIES

    per_category = max(1, count // len(categories))
    total = per_category * len(categories)

    if dry_run:
        # Generate prompts without calling the API
        for cat in categories:
            theme = theme_for_category(Category[cat])
            for i in range(per_category):
                prompt: GeneratedPrompt = compose(category=cat, negative_prompt=negative)
                print(f"[DRY-RUN] {cat} -> theme={theme} #{i+1} (intent={prompt.intent})")
                print(f"  Positive: {prompt.positive[:120]}...")
                print()
        cost_per_image = _DRY_RUN_COST_PER_IMAGE.get(backend_name, 0.02)
        cost_est = total * cost_per_image
        print(f"Total: {total} prompts, backend={backend_name}, estimated cost: ~${cost_est:.2f}")
        return

    backend_cls = BACKENDS.get(backend_name)
    if backend_cls is None:
        print(
            f"Error: unknown backend {backend_name!r}. Choices: {', '.join(sorted(BACKENDS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load API token (skipped for anonymous no-signup backends like Pollinations).
    api_key = ""
    if backend_cls.requires_api_key:
        if not token_file.is_file():
            print(
                f"Error: API token file not found at {token_file}\n"
                f"Create it with: echo 'YOUR_API_KEY' > {token_file}",
                file=sys.stderr,
            )
            sys.exit(1)
        api_key = token_file.read_text(encoding="utf-8").strip()

    backend_kwargs: dict = {"api_key": api_key}
    if model:
        backend_kwargs["model"] = model
    backend = backend_cls(**backend_kwargs)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Shared per-theme counter (for --resume) — advanced only after a successful save so
    # a failure never burns/skips a number.
    theme_counters = _existing_theme_counts(output_dir) if resume else {}

    generated_count = 0
    errors = 0

    for cat in categories:
        theme = theme_for_category(Category[cat])
        theme_dir = output_dir / theme
        theme_dir.mkdir(parents=True, exist_ok=True)

        for _ in range(per_category):
            idx = theme_counters.get(theme, 0) + 1
            filename = f"{theme}_{idx:03d}.jpg"
            filepath = theme_dir / filename

            # Skip if already exists (--resume)
            if resume and filepath.exists():
                theme_counters[theme] = idx
                continue

            prompt = compose(category=cat, negative_prompt=negative)

            try:
                print(f"Generating {cat} (theme={theme}) #{idx}... (intent={prompt.intent})")
                img_bytes = await backend.generate(
                    positive_prompt=prompt.positive,
                    negative_prompt=prompt.negative,
                )
                filepath.write_bytes(img_bytes)

                # Verify image is valid
                img = Image.open(filepath)
                img.verify()
                # Re-open after verify
                img = Image.open(filepath)
                rgb = img.convert("RGB")
                gray = rgb.convert("L")
                stat = ImageStat.Stat(gray)
                brightness = round(stat.mean[0] / 255.0, 3)

                # Write minimal metadata
                meta_file = theme_dir / "metadata.json"
                metadata = {}
                if meta_file.exists():
                    try:
                        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, ValueError):
                        metadata = {}

                img_name = filename
                if img_name not in metadata:
                    metadata[img_name] = {}
                metadata[img_name]["brightness"] = brightness
                metadata[img_name]["dominant_color"] = prompt.positive.split("palette: ")[-1].split(",")[0] if "palette: " in prompt.positive else "#000000"
                metadata[img_name]["tags"] = [theme, cat.lower(), prompt.intent]
                metadata[img_name]["weight"] = 1.0
                metadata[img_name]["quality"] = 3.0
                metadata[img_name]["generated"] = True
                metadata[img_name]["ai_generated"] = True

                meta_file.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

                theme_counters[theme] = idx
                generated_count += 1
                print(f"  Saved {filepath} (brightness={brightness})")

            except RuntimeError as e:
                errors += 1
                print(f"  ERROR: {e}", file=sys.stderr)
                # Rate limit — back off. Widened to also catch Gemini's wording.
                msg = str(e).lower()
                if any(s in msg for s in ("rate", "429", "resource_exhausted", "quota")):
                    wait = 30
                    print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                continue

            # Delay between requests — backend-specific (e.g. Pollinations' anonymous
            # rate limit needs ~16s; keyed backends only need a small politeness gap).
            await asyncio_sleep(backend.request_delay)

    print(f"\nDone. Generated {generated_count} images, {errors} errors.")


async def asyncio_sleep(seconds: float) -> None:
    """Async sleep (works with or without asyncio)."""
    import asyncio
    await asyncio.sleep(seconds)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate AI background images")
    parser.add_argument("--category", type=str, default=None, help="Single category")
    parser.add_argument("--all", action="store_true", help="Generate for all categories")
    parser.add_argument("--n", type=int, default=10, help="Total images to generate")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_DIR), help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Generate prompts without API calls")
    parser.add_argument("--no-resume", action="store_true", help="Skip existing files")
    parser.add_argument("--token-file", type=str, default=str(DEFAULT_TOKEN_FILE), help="API token file")
    parser.add_argument(
        "--backend", type=str, default=DEFAULT_BACKEND, choices=sorted(BACKENDS), help="Generation backend"
    )
    parser.add_argument("--model", type=str, default=None, help="Override the backend's default model")
    args = parser.parse_args()

    categories = None
    if args.category:
        categories = [args.category]
    elif args.all:
        categories = ALL_CATEGORIES

    if not categories:
        parser.error("Specify --category or --all")

    import asyncio
    asyncio.run(
        run_generation(
            categories=categories,
            count=args.n,
            output_dir=Path(args.output),
            dry_run=args.dry_run,
            resume=not args.no_resume,
            token_file=Path(args.token_file),
            backend_name=args.backend,
            model=args.model,
        )
    )


if __name__ == "__main__":
    main()
