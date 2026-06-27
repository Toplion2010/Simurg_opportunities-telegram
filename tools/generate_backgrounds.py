"""Procedural background generator — creates varied gradient/texture backgrounds.

Library + Procedural = unlimited variety (ARCHITECTURE.md §6).
This tool generates backgrounds without any AI — pure Pillow math.

Each background is designed with negative space on the left for text overlay,
matching the composition bias of the prompt composer.

Usage:
    python -m tools.generate_backgrounds --theme technology --n 10
    python -m tools.generate_backgrounds --all --n 50
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageStat

# ------------------------------------------------------------------ Config

TARGET_WIDTH = 1200
TARGET_HEIGHT = 628

# Theme → palette mapping (dark backgrounds for text readability).
THEME_PALETTES: dict[str, list[tuple[int, int, int]]] = {
    "academic": [
        (15, 20, 50), (25, 35, 80), (40, 60, 120), (20, 40, 90),
        (30, 50, 100), (10, 15, 40), (35, 45, 95), (45, 70, 130),
    ],
    "business": [
        (15, 25, 35), (25, 40, 55), (30, 50, 65), (20, 35, 50),
        (35, 55, 70), (10, 20, 30), (40, 60, 75), (25, 45, 60),
    ],
    "technology": [
        (5, 15, 35), (10, 25, 60), (15, 35, 80), (8, 20, 50),
        (20, 40, 90), (3, 12, 28), (25, 45, 100), (12, 28, 65),
    ],
    "nature": [
        (10, 25, 15), (15, 35, 20), (20, 45, 25), (12, 30, 18),
        (25, 50, 30), (8, 20, 12), (30, 55, 35), (18, 40, 22),
    ],
    "design": [
        (35, 10, 40), (50, 15, 55), (65, 20, 70), (40, 12, 48),
        (75, 25, 80), (28, 8, 32), (85, 30, 90), (55, 18, 62),
    ],
    "research": [
        (5, 20, 35), (10, 30, 50), (15, 40, 65), (8, 25, 45),
        (20, 50, 75), (3, 15, 30), (25, 55, 85), (12, 35, 55),
    ],
    "conference": [
        (8, 15, 35), (15, 25, 55), (20, 35, 70), (10, 20, 50),
        (25, 40, 80), (5, 12, 28), (30, 45, 90), (18, 28, 62),
    ],
    "exchange": [
        (5, 25, 30), (10, 35, 40), (15, 45, 50), (8, 30, 38),
        (20, 55, 60), (3, 20, 25), (25, 60, 68), (12, 40, 48),
    ],
    "startup": [
        (35, 15, 5), (55, 20, 8), (70, 25, 10), (45, 18, 6),
        (80, 30, 12), (28, 12, 3), (90, 35, 15), (60, 22, 9),
    ],
    "finance": [
        (5, 25, 15), (10, 35, 22), (15, 45, 30), (8, 30, 18),
        (20, 55, 38), (3, 20, 12), (25, 60, 42), (12, 40, 25),
    ],
    "general": [
        (15, 15, 30), (20, 20, 40), (25, 25, 50), (18, 18, 35),
        (30, 30, 55), (12, 12, 25), (35, 35, 60), (22, 22, 45),
    ],
}

# Default palette if theme not found.
DEFAULT_PALETTE = THEME_PALETTES["general"]

# All themes that have palettes.
ALL_THEMES = sorted(THEME_PALETTES.keys())

# Background generation styles.
STYLES = ["gradient", "mesh", "geometric", "textured"]


# ------------------------------------------------------------------ Generators


def _lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Linear interpolation between two colours."""
    return tuple(max(0, min(255, int(a + (b - a) * t))) for a, b in zip(c1, c2))


def gen_gradient(palette: list, style_variant: int = 0) -> Image.Image:
    """Generate a gradient background with left-side negative space."""
    img = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT))
    draw = ImageDraw.Draw(img)

    c1 = palette[style_variant % len(palette)]
    c2 = palette[(style_variant + 1) % len(palette)]
    c3 = palette[(style_variant + 2) % len(palette)]

    if style_variant < 3:
        # Horizontal gradient — dark left, slightly lighter right
        for x in range(TARGET_WIDTH):
            t = x / TARGET_WIDTH
            t = t * t  # quadratic — keep left darker
            color = _lerp_color(c1, c2, t * 0.6)
            draw.line([(x, 0), (x, TARGET_HEIGHT - 1)], fill=color)
    elif style_variant < 6:
        # Diagonal gradient
        for x in range(TARGET_WIDTH):
            for y in range(TARGET_HEIGHT):
                t = (x / TARGET_WIDTH + y / TARGET_HEIGHT) / 2
                t = min(1.0, t * 0.7)  # keep mostly dark
                color = _lerp_color(c1, c3, t)
                img.putpixel((x, y), color)
    else:
        # Radial gradient — glow from right side
        cx, cy = TARGET_WIDTH * 0.8, TARGET_HEIGHT * 0.4
        max_r = math.sqrt(cx ** 2 + cy ** 2)
        for x in range(TARGET_WIDTH):
            for y in range(TARGET_HEIGHT):
                r = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                t = min(1.0, r / max_r)
                t = 1.0 - t  # center is lighter
                t = t * 0.4  # keep overall dark
                color = _lerp_color(c1, c2, t)
                img.putpixel((x, y), color)

    return img


def gen_mesh(palette: list, style_variant: int = 0) -> Image.Image:
    """Generate a mesh gradient background."""
    img = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT))

    # Create several radial gradients and blend them
    num_blobs = 3 + (style_variant % 3)
    base = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), palette[0])

    for i in range(num_blobs):
        cx = random.randint(TARGET_WIDTH // 2, TARGET_WIDTH - 100)
        cy = random.randint(50, TARGET_HEIGHT - 50)
        radius = random.randint(200, 500)
        color = palette[(i + 1) % len(palette)]

        blob = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(blob)
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=color,
        )
        blob = blob.filter(ImageFilter.GaussianBlur(radius // 3))
        base = Image.blend(base, blob, 0.3)

    return base


def gen_geometric(palette: list, style_variant: int = 0) -> Image.Image:
    """Generate a geometric background with subtle shapes."""
    img = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), palette[0])
    draw = ImageDraw.Draw(img)

    # Subtle geometric shapes on the right side
    num_shapes = 3 + (style_variant % 4)
    for i in range(num_shapes):
        x = random.randint(TARGET_WIDTH // 2, TARGET_WIDTH - 100)
        y = random.randint(20, TARGET_HEIGHT - 100)
        size = random.randint(50, 200)
        color = palette[(i + 1) % len(palette)]
        alpha = random.randint(15, 40)
        color = tuple(c + alpha for c in color)

        if style_variant % 3 == 0:
            draw.ellipse([x, y, x + size, y + size], outline=color, width=1)
        elif style_variant % 3 == 1:
            draw.rectangle([x, y, x + size, y + size], outline=color, width=1)
        else:
            points = [
                (x + size // 2, y),
                (x + size, y + size),
                (x, y + size),
            ]
            draw.polygon(points, outline=color, width=1)

    # Subtle grid lines
    for x in range(0, TARGET_WIDTH, 80):
        draw.line([(x, 0), (x, TARGET_HEIGHT)], fill=palette[1])
    for y in range(0, TARGET_HEIGHT, 80):
        draw.line([(0, y), (TARGET_WIDTH, y)], fill=palette[1])

    return img


def gen_textured(palette: list, style_variant: int = 0) -> Image.Image:
    """Generate a noise-textured gradient background."""
    # Start with gradient
    img = gen_gradient(palette, style_variant)

    # Add subtle noise
    pixels = img.load()
    for x in range(TARGET_WIDTH):
        for y in range(TARGET_HEIGHT):
            r, g, b = pixels[x, y]
            noise = random.randint(-8, 8)
            r = max(0, min(255, r + noise))
            g = max(0, min(255, g + noise))
            b = max(0, min(255, b + noise))
            pixels[x, y] = (r, g, b)

    return img


# Map style names to functions.
_STYLE_FUNCTIONS = {
    "gradient": gen_gradient,
    "mesh": gen_mesh,
    "geometric": gen_geometric,
    "textured": gen_textured,
}


# ------------------------------------------------------------------ Main


def generate_one(
    theme: str,
    index: int,
    style: str | None = None,
) -> tuple[Image.Image, dict]:
    """Generate a single background image.

    Returns (image, metadata_dict).
    """
    palette = THEME_PALETTES.get(theme, DEFAULT_PALETTE)

    if style is None:
        style = STYLES[index % len(STYLES)]

    variant = index % 8
    gen_func = _STYLE_FUNCTIONS[style]
    img = gen_func(palette, variant)

    # Compute metadata
    rgb = img.convert("RGB")
    small = rgb.resize((1, 1))
    r, g, b = small.getpixel((0, 0))
    dominant_color = f"#{r:02X}{g:02X}{b:02X}"

    gray = rgb.convert("L")
    stat = ImageStat.Stat(gray)
    brightness = round(stat.mean[0] / 255.0, 3)
    contrast = round(stat.stddev[0] / 255.0, 3)

    metadata = {
        "brightness": brightness,
        "contrast": contrast,
        "dominant_color": dominant_color,
        "generated": True,
        "procedural": True,
        "style": style,
        "theme": theme,
        "quality": 3,
        "weight": 1,
        "tags": [theme, style],
    }

    return img, metadata


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate procedural backgrounds")
    parser.add_argument("--theme", type=str, default=None, help="Theme name")
    parser.add_argument("--all", action="store_true", help="Generate for all themes")
    parser.add_argument("--n", type=int, default=10, help="Images per theme")
    parser.add_argument("--output", type=str, default="backgrounds", help="Output directory")
    parser.add_argument("--style", type=str, default=None, choices=STYLES, help="Generation style")
    args = parser.parse_args()

    if args.theme:
        themes = [args.theme]
    elif args.all:
        themes = ALL_THEMES
    else:
        themes = ["general"]

    output_base = Path(args.output)
    total = 0

    for theme in themes:
        theme_dir = output_base / theme
        theme_dir.mkdir(parents=True, exist_ok=True)

        meta_path = theme_dir / "metadata.json"
        metadata = {}
        if meta_path.exists():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                metadata = {}

        for i in range(args.n):
            # Find next available index
            idx = i + 1
            while f"{theme}_{idx:02d}.jpg" in metadata:
                idx += 1

            filename = f"{theme}_{idx:02d}.jpg"
            filepath = theme_dir / filename

            img, meta = generate_one(theme, idx, args.style)
            img.save(filepath, "JPEG", quality=95)

            metadata[filename] = meta
            total += 1
            print(f"Generated {filepath}")

        meta_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(f"\nDone. Generated {total} backgrounds across {len(themes)} themes.")


if __name__ == "__main__":
    main()
