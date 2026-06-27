"""Procedurally generate category-themed background images for the library.

Fills ``backgrounds/<theme>/`` with unique, dark, premium-looking abstract backgrounds
(gradient / mesh / geometric / textured) that read well under the card's scrim + white text.
Free, instant, no API key, and safe to re-run (adds more images, never clobbers by default).

Usage
-----
    python -m scripts.generate_backgrounds                       # ~10 per theme
    python -m scripts.generate_backgrounds --themes academic,conference --count 3 --seed 1
    python -m scripts.generate_backgrounds --force               # regenerate from _01
    python -m scripts.generate_backgrounds --include-collections # also fill google/, nasa/, ...
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageStat

# Allow running as a plain script too.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.publisher.background_map import GENERAL_THEME, KNOWN_THEMES  # noqa: E402

# Theme → (base dark hex, [accent hexes], named accent for tags). Seeded from the per-category
# palette in src/publisher/image_gen.py so generated art matches the card accent colours.
THEME_PALETTES: dict[str, tuple[str, list[str], str]] = {
    "academic":   ("#0A0800", ["#FFD700", "#FFE082", "#FFB300"], "gold"),
    "business":   ("#050D1A", ["#90CAF9", "#4FC3F7", "#5C6BC0"], "blue"),
    "technology": ("#050D1A", ["#00D4FF", "#18FFFF", "#2979FF"], "cyan"),
    "nature":     ("#021208", ["#69F0AE", "#00E676", "#A5D6A7"], "green"),
    "space":      ("#080618", ["#B388FF", "#7C4DFF", "#536DFE"], "violet"),
    "finance":    ("#021208", ["#69F0AE", "#00C853", "#1DE9B6"], "green"),
    "medicine":   ("#021510", ["#80DEEA", "#4DD0E1", "#26C6DA"], "teal"),
    "design":     ("#150010", ["#E040FB", "#FF4081", "#7C4DFF"], "magenta"),
    "startup":    ("#100800", ["#FF6B35", "#FFA000", "#FF8A65"], "orange"),
    "hackathon":  ("#050D1A", ["#00D4FF", "#18FFFF", "#00B0FF"], "cyan"),
    "research":   ("#050D1A", ["#80DEEA", "#4DD0E1", "#64B5F6"], "teal"),
    "conference": ("#050D1A", ["#4FC3F7", "#29B6F6", "#5C6BC0"], "blue"),
    "exchange":   ("#001010", ["#80CBC4", "#26A69A", "#4DB6AC"], "teal"),
    "volunteer":  ("#100505", ["#EF9A9A", "#FF8A80", "#FFAB91"], "coral"),
    "general":    ("#050D1A", ["#00D4FF", "#7C4DFF", "#4FC3F7"], "cyan"),
}
_FALLBACK_PALETTE = ("#050D1A", ["#00D4FF", "#7C4DFF", "#4FC3F7"], "cyan")

STYLES = ("gradient", "mesh", "geometric", "textured")


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _add_grain(arr: np.ndarray, rng: np.random.Generator, amount: float = 7.0) -> np.ndarray:
    noise = rng.normal(0.0, amount, arr.shape[:2])[:, :, None]
    return np.clip(arr + noise, 0, 255)


def _gen_gradient(size, base, accents, rng, np_rng) -> Image.Image:
    w, h = size
    base_c = np.array(_hex_to_rgb(base), dtype=np.float32)
    accent_c = np.array(_hex_to_rgb(rng.choice(accents)), dtype=np.float32)

    angle = rng.uniform(0, np.pi)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    proj = xx * np.cos(angle) + yy * np.sin(angle)
    t = (proj - proj.min()) / (np.ptp(proj) + 1e-6)
    # base -> accent -> base, accent muted so text stays readable
    tri = 1.0 - np.abs(1.0 - 2.0 * t)
    tri = (tri ** 1.4) * rng.uniform(0.35, 0.6)
    arr = base_c[None, None, :] + (accent_c - base_c)[None, None, :] * tri[:, :, None]
    arr = _add_grain(arr, np_rng)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _gen_mesh(size, base, accents, rng, np_rng) -> Image.Image:
    w, h = size
    arr = np.tile(np.array(_hex_to_rgb(base), dtype=np.float32), (h, w, 1))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for _ in range(rng.randint(3, 5)):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        radius = rng.uniform(0.25, 0.6) * max(w, h)
        color = np.array(_hex_to_rgb(rng.choice(accents)), dtype=np.float32)
        dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
        falloff = np.exp(-dist2 / (2 * radius ** 2)) * rng.uniform(0.30, 0.55)
        arr += color[None, None, :] * falloff[:, :, None]
    arr = np.clip(arr, 0, 255)
    # tone down so it never washes out the white card text
    arr *= 0.85
    arr = _add_grain(arr, np_rng)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _gen_geometric(size, base, accents, rng, np_rng) -> Image.Image:
    img = _gen_gradient(size, base, accents, rng, np_rng).convert("RGB")
    w, h = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(rng.randint(2, 4)):
        color = _hex_to_rgb(rng.choice(accents)) + (rng.randint(22, 55),)
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(0.18, 0.45) * max(w, h)
        if rng.random() < 0.5:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        else:
            pts = [(cx + rng.uniform(-r, r), cy + rng.uniform(-r, r)) for _ in range(3)]
            draw.polygon(pts, fill=color)
    overlay = overlay.filter(ImageFilter.GaussianBlur(rng.uniform(20, 60)))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img


def _gen_textured(size, base, accents, rng, np_rng) -> Image.Image:
    img = _gen_gradient(size, base, accents, rng, np_rng).convert("RGBA")
    w, h = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    accent = _hex_to_rgb(rng.choice(accents))
    if rng.random() < 0.5:
        step = rng.randint(40, 70)
        for x in range(0, w, step):
            draw.line([(x, 0), (x, h)], fill=accent + (12,), width=1)
        for y in range(0, h, step):
            draw.line([(0, y), (w, y)], fill=accent + (12,), width=1)
    else:
        step = rng.randint(34, 60)
        for x in range(0, w, step):
            for y in range(0, h, step):
                rr = rng.randint(1, 3)
                draw.ellipse([x - rr, y - rr, x + rr, y + rr], fill=accent + (rng.randint(15, 40),))
    img = Image.alpha_composite(img, overlay).convert("RGB")
    return img


_GENERATORS = {
    "gradient": _gen_gradient,
    "mesh": _gen_mesh,
    "geometric": _gen_geometric,
    "textured": _gen_textured,
}


def _compute_meta(img: Image.Image) -> tuple[str, float]:
    rgb = img.convert("RGB")
    r, g, b = rgb.resize((1, 1)).getpixel((0, 0))
    brightness = round(ImageStat.Stat(rgb.convert("L")).mean[0] / 255.0, 3)
    return f"#{r:02X}{g:02X}{b:02X}", brightness


def _load_metadata(folder: Path) -> dict[str, dict]:
    p = folder / "metadata.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_metadata(folder: Path, meta: dict[str, dict]) -> None:
    (folder / "metadata.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _next_index(folder: Path, theme: str) -> int:
    existing = list(folder.glob(f"{theme}_*.jpg"))
    nums = []
    for f in existing:
        stem = f.stem.rsplit("_", 1)[-1]
        if stem.isdigit():
            nums.append(int(stem))
    return (max(nums) + 1) if nums else 1


def generate_for_theme(
    root: Path, theme: str, count: int, size: tuple[int, int], quality: int,
    force: bool, rng: random.Random, np_rng: np.random.Generator,
) -> int:
    folder = root / theme
    folder.mkdir(parents=True, exist_ok=True)
    palette = THEME_PALETTES.get(theme, _FALLBACK_PALETTE)
    base, accents, color_name = palette

    meta = _load_metadata(folder)
    start = 1 if force else _next_index(folder, theme)

    written = 0
    for i in range(start, start + count):
        style = rng.choice(STYLES)
        img = _GENERATORS[style](size, base, accents, rng, np_rng)
        name = f"{theme}_{i:02d}.jpg"
        img.save(folder / name, "JPEG", quality=quality)

        dominant_color, brightness = _compute_meta(img)
        meta[name] = {
            "weight": 1,
            "quality": 3,
            "tags": [theme, color_name, style],
            "dominant_color": dominant_color,
            "brightness": brightness,
            "generated": True,
        }
        written += 1

    _write_metadata(folder, meta)
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate themed background images for the library.")
    p.add_argument("--count", type=int, default=10, help="images per theme (default 10)")
    p.add_argument("--themes", type=str, default="", help="comma-separated subset of themes")
    p.add_argument("--size", type=str, default="1280x720", help="WxH (default 1280x720)")
    p.add_argument("--quality", type=int, default=88, help="JPEG quality (default 88)")
    p.add_argument("--force", action="store_true", help="regenerate from _01 (overwrites)")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible output")
    p.add_argument("--include-collections", action="store_true",
                   help="also fill brand-collection folders with neutral backgrounds")
    p.add_argument("--root", type=str, default="backgrounds", help="library root (default backgrounds)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    w, h = (int(x) for x in args.size.lower().split("x"))
    size = (w, h)
    rng = random.Random(args.seed)
    np_rng = np.random.default_rng(args.seed)
    root = Path(args.root)

    if args.themes:
        themes = [t.strip() for t in args.themes.split(",") if t.strip()]
    else:
        themes = sorted(KNOWN_THEMES)

    if args.include_collections:
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if d.is_dir() and d.name not in KNOWN_THEMES and not d.name.startswith("."):
                themes.append(d.name)

    total = 0
    for theme in themes:
        n = generate_for_theme(root, theme, args.count, size, args.quality,
                               args.force, rng, np_rng)
        total += n
        print(f"  {theme:<12} +{n} images")

    print(f"\nDone: {total} images across {len(themes)} folder(s) under '{root}/'.")
    print("Restart the bot (or wait for the next library refresh) to pick them up.")


if __name__ == "__main__":
    main()
