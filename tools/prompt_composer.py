"""Prompt composer — generates image-generation prompts for backgrounds.

Design DNA (ARCHITECTURE.md §6):
    Core (always): Style · Mood · Palette · Composition
    Advanced (sometimes): Lighting · Camera · Texture · Perspective · Geometry
    Visual Intent: Prestige · Innovation · Competition · Discovery · Achievement

Composition is biased to text-safe negative space so the rendered card has
a calm region for text overlay (the ``primary_safe_area`` computed at scan
time will reflect this).

Visual Intent maps to the opportunity category so backgrounds feel
semantically appropriate, not just visually random.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# ------------------------------------------------------------------ Core DNA

STYLES: list[str] = [
    "minimalist gradient",
    "abstract geometric",
    "soft mesh gradient",
    "clean corporate",
    "premium dark",
    "soft watercolor texture",
    "matte finish gradient",
    "subtle noise texture",
]

MOODS: list[str] = [
    "calm and professional",
    "innovative and modern",
    "prestigious and elegant",
    "clean and minimal",
    "dynamic and energetic",
    "serene and focused",
    "bold and confident",
    "sophisticated and refined",
]

PALETTES: list[str] = [
    "deep navy and cyan",
    "charcoal and gold",
    "forest green and emerald",
    "deep purple and violet",
    "dark slate and teal",
    "midnight blue and silver",
    "burgundy and warm cream",
    "obsidian and electric blue",
    "dark olive and sage",
    "deep indigo and lavender",
]

COMPOSITIONS: list[str] = [
    "large area of smooth negative space on the left side for text overlay",
    "clean open space on the left third, subtle texture on the right",
    "gradual transition from dark left to detailed right",
    "wide horizontal negative space on the left two-thirds",
    "minimal detail on the left, concentrated visual interest on the right",
    "left side smooth gradient, right side abstract pattern",
    "open dark space dominating the left, subtle glow on the right edge",
]


# ------------------------------------------------------------------ Advanced DNA

LIGHTING: list[str] = [
    "soft diffused lighting",
    "subtle rim light",
    "gentle volumetric glow",
    "even studio lighting",
    "low-key lighting with minimal highlights",
]

CAMERA: list[str] = [
    "macro abstract perspective",
    "extreme close-up of surface texture",
    "flat lay composition",
    "top-down abstract view",
]

TEXTURES: list[str] = [
    "subtle fabric weave",
    "smooth brushed metal",
    "fine paper grain",
    "matte ceramic surface",
    "soft frosted glass",
]

GEOMETRIES: list[str] = [
    "flowing organic curves",
    "clean diagonal lines",
    "concentric circles",
    "overlapping translucent planes",
    "gradient mesh pattern",
]


# ------------------------------------------------------------------ Visual Intent

# Category → preferred visual intents.
VISUAL_INTENTS: dict[str, list[str]] = {
    "Scholarship": ["prestige", "achievement", "discovery"],
    "Fellowship": ["prestige", "discovery", "innovation"],
    "Research": ["discovery", "innovation", "prestige"],
    "Conference": ["innovation", "prestige", "competition"],
    "Hackathon": ["innovation", "competition", "achievement"],
    "Competition": ["competition", "achievement", "innovation"],
    "Olympiad": ["competition", "achievement", "prestige"],
    "Internship": ["achievement", "innovation", "discovery"],
    "Job": ["prestige", "achievement"],
    "Startup": ["innovation", "achievement", "competition"],
    "Accelerator": ["innovation", "competition", "achievement"],
    "Incubator": ["innovation", "discovery", "achievement"],
    "Grant": ["prestige", "discovery", "achievement"],
    "SummerProgram": ["achievement", "discovery", "innovation"],
    "Exchange": ["discovery", "innovation"],
    "Volunteer": ["achievement", "discovery"],
    "default": ["innovation", "prestige", "achievement"],
}

# Visual intent → prompt modifier.
INTENT_MODIFIERS: dict[str, str] = {
    "prestige": "conveying prestige and exclusivity, luxurious feel, award ceremony atmosphere",
    "innovation": "conveying technological innovation, futuristic feel, cutting-edge design",
    "competition": "conveying competition and excellence, dynamic energy, trophy atmosphere",
    "discovery": "conveying exploration and discovery, scientific wonder, laboratory aesthetics",
    "achievement": "conveying accomplishment and success, celebratory mood, milestone atmosphere",
}


# ------------------------------------------------------------------ Prompt builder


@dataclass(frozen=True)
class GeneratedPrompt:
    """A completed prompt for image generation."""

    positive: str
    negative: str
    intent: str
    style: str
    category: str


def compose(
    category: str | None = None,
    *,
    include_advanced: bool = True,
    negative_prompt: str | None = None,
) -> GeneratedPrompt:
    """Compose a single image-generation prompt.

    Args:
        category: Opportunity category name (for Visual Intent).
        include_advanced: Whether to add Lighting/Camera/Texture/Perspective.
        negative_prompt: Custom negative prompt.  If None, uses the default.

    Returns:
        GeneratedPrompt with positive prompt, negative prompt, and metadata.
    """
    # Core (always)
    style = random.choice(STYLES)
    mood = random.choice(MOODS)
    palette = random.choice(PALETTES)
    composition = random.choice(COMPOSITIONS)

    # Visual Intent
    intent_key = (category or "default") if category in VISUAL_INTENTS else "default"
    intents = VISUAL_INTENTS.get(intent_key, VISUAL_INTENTS["default"])
    intent = random.choice(intents)
    intent_modifier = INTENT_MODIFIERS[intent]

    # Build positive prompt
    parts = [
        f"abstract background, {style}",
        f"{mood} mood",
        f"color palette: {palette}",
        composition,
        intent_modifier,
        "high resolution, 1200x628, professional design",
    ]

    # Advanced (sometimes)
    if include_advanced:
        advanced_parts = []
        if random.random() > 0.3:
            advanced_parts.append(random.choice(LIGHTING))
        if random.random() > 0.4:
            advanced_parts.append(random.choice(TEXTURES))
        if random.random() > 0.5:
            advanced_parts.append(random.choice(GEOMETRIES))
        if random.random() > 0.6:
            advanced_parts.append(random.choice(CAMERA))
        parts.extend(advanced_parts)

    positive = ", ".join(parts)

    if negative_prompt is None:
        negative_prompt = DEFAULT_NEGATIVE

    return GeneratedPrompt(
        positive=positive,
        negative=negative_prompt,
        intent=intent,
        style=style,
        category=category or "general",
    )


# ------------------------------------------------------------------ Default negative prompt

DEFAULT_NEGATIVE = (
    "text, words, letters, typography, logo, watermark, signature, "
    "people, faces, hands, body parts, "
    "low quality, blurry, noisy, grainy, pixelated, "
    "overexposed, underexposed, washed out, "
    "cluttered, busy, chaotic, distracting, "
    "bright neon colors, rainbow, garish, "
    "reflection, shadow, silhouette, "
    "frame, border, margin, white space, "
    "screenshot, UI, interface, button, icon"
)


def load_negative_prompt(path: str = "tools/prompts/negative.txt") -> str:
    """Load negative prompt from file. Falls back to DEFAULT_NEGATIVE."""
    from pathlib import Path

    p = Path(path)
    if p.is_file():
        content = p.read_text(encoding="utf-8").strip()
        if content:
            return content
    return DEFAULT_NEGATIVE


# ------------------------------------------------------------------ CLI


def main() -> None:
    """CLI entry point — generate N prompts and print them."""
    import argparse

    parser = argparse.ArgumentParser(description="Compose image-generation prompts")
    parser.add_argument("-c", "--count", type=int, default=1, help="Number of prompts")
    parser.add_argument("--category", type=str, default=None, help="Opportunity category")
    parser.add_argument("--negative", type=str, default=None, help="Path to negative prompt file")
    parser.add_argument(
        "--no-advanced", action="store_true", help="Skip advanced DNA elements"
    )
    args = parser.parse_args()

    negative = load_negative_prompt(args.negative) if args.negative else DEFAULT_NEGATIVE

    for i in range(args.count):
        prompt = compose(category=args.category, include_advanced=not args.no_advanced, negative_prompt=negative)
        print(f"--- Prompt {i + 1} (category={prompt.category}, intent={prompt.intent}) ---")
        print(f"Positive: {prompt.positive}")
        print(f"Negative: {prompt.negative}")
        print()


if __name__ == "__main__":
    main()
