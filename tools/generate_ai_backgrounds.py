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
import sys
import time
from pathlib import Path

from PIL import Image, ImageStat

# ------------------------------------------------------------------ Config

# The generator reads its own API token from a local file, never from
# the project's .env or code.  This keeps generation credentials separate
# from bot/deployment credentials.
DEFAULT_TOKEN_FILE = Path("tools/.gen_token")

# Output directory for new images (before QC).
DEFAULT_OUTPUT_DIR = Path("backgrounds/generated")

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


# ------------------------------------------------------------------ CLI


async def run_generation(
    categories: list[str] | None,
    count: int,
    output_dir: Path,
    dry_run: bool = False,
    resume: bool = True,
    token_file: Path = DEFAULT_TOKEN_FILE,
) -> None:
    """Main generation loop."""
    from tools.prompt_composer import GeneratedPrompt, compose, load_negative_prompt

    negative = load_negative_prompt()

    # Load existing images per category (for --resume).
    existing: dict[str, int] = {}
    if resume and output_dir.is_dir():
        for subdir in output_dir.iterdir():
            if subdir.is_dir():
                imgs = list(subdir.glob("*.jpg")) + list(subdir.glob("*.jpeg")) + list(subdir.glob("*.png"))
                existing[subdir.name] = len(imgs)

    if not categories:
        categories = ALL_CATEGORIES

    per_category = max(1, count // len(categories))
    total = per_category * len(categories)

    if dry_run:
        # Generate prompts without calling the API
        for cat in categories:
            for i in range(per_category):
                prompt: GeneratedPrompt = compose(category=cat, negative_prompt=negative)
                print(f"[DRY-RUN] {cat} #{i+1} (intent={prompt.intent})")
                print(f"  Positive: {prompt.positive[:120]}...")
                print()
        cost_est = total * 0.02  # rough estimate
        print(f"Total: {total} prompts, estimated cost: ~${cost_est:.2f}")
        return

    # Load API token
    if not token_file.is_file():
        print(
            f"Error: API token file not found at {token_file}\n"
            f"Create it with: echo 'YOUR_API_KEY' > {token_file}",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = token_file.read_text(encoding="utf-8").strip()
    backend = OpenAIBackend(api_key=api_key)

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_count = 0
    errors = 0

    for cat in categories:
        cat_dir = output_dir / cat.lower()
        cat_dir.mkdir(parents=True, exist_ok=True)

        existing_count = existing.get(cat.lower(), 0)

        for i in range(per_category):
            idx = existing_count + i + 1
            filename = f"{cat.lower()}_{idx:02d}.jpg"
            filepath = cat_dir / filename

            # Skip if already exists (--resume)
            if filepath.exists():
                continue

            prompt = compose(category=cat, negative_prompt=negative)

            try:
                print(f"Generating {cat} #{idx}... (intent={prompt.intent})")
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
                meta_file = cat_dir / "metadata.json"
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
                metadata[img_name]["tags"] = [cat.lower(), prompt.intent]
                metadata[img_name]["weight"] = 1.0
                metadata[img_name]["quality"] = 3.0
                metadata[img_name]["generated"] = True
                metadata[img_name]["ai_generated"] = True

                meta_file.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

                generated_count += 1
                print(f"  Saved {filepath} (brightness={brightness})")

            except RuntimeError as e:
                errors += 1
                print(f"  ERROR: {e}", file=sys.stderr)
                # Rate limit — back off
                if "rate" in str(e).lower() or "429" in str(e):
                    wait = 30
                    print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                continue

            # Small delay between requests to be polite
            await asyncio_sleep(1.0)

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
        )
    )


if __name__ == "__main__":
    main()
