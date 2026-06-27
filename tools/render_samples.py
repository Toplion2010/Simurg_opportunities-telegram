"""Diversity gallery renderer for opportunity cards.

Renders a large cross-section of cards (every category × every hook × multiple
backgrounds) and produces an HTML gallery for visual inspection and near-duplicate
clustering.

Usage:
    # Render all categories with procedural backgrounds
    python -m tools.render_samples

    # Render with real background images
    python -m tools.render_samples --with-backgrounds

    # Render only specific categories
    python -m tools.render_samples --categories Conference Job Grant

    # Custom output directory
    python -m tools.render_samples --output-gallery output/gallery

    # Skip rendering (use existing rendered images) and just build the gallery
    python -m tools.render_samples --build-only

Architecture:
    Category × Hook × Background matrix → Render → HTML gallery + clustering

The gallery shows thumbnails, category/hook metadata, and highlights near-duplicates
detected via perceptual hashing.
"""
from __future__ import annotations

import argparse
import asyncio
import colorsys
import hashlib
import html
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

# ------------------------------------------------------------------ Constants

# All categories from the Category enum
ALL_CATEGORIES = [
    "Internship", "Scholarship", "Fellowship", "Research",
    "Competition", "Olympiad", "Hackathon", "Startup",
    "Accelerator", "Incubator", "Grant", "Conference",
    "SummerProgram", "Exchange", "Volunteer", "Job",
]

# All hook value strings from HookLabel
ALL_HOOKS = [
    "\ud83d\udd25 #PremiumOpportunity",
    "\ud83d\ude80 #EarlyAccess",
    "\u2b50 #LimitedSpots",
    "\ud83d\udcb0 #PaidOpportunity",
    "\ud83e\uddea #BetaTesting",
    "\ud83c\udf81 #Exclusive",
    "\ud83c\udf0d #Worldwide",
    "\u26a1 #ClosingSoon",
    "\ud83c\udfc6 #HighlyRecommended",
]

# Background directories to sample from
THEME_DIRS = [
    "technology", "academic", "business", "nature", "design",
    "research", "conference", "exchange", "startup", "finance",
    "general", "hackathon", "medicine", "space", "volunteer",
]


# ------------------------------------------------------------------ Data classes

@dataclass
class SampleCard:
    """Metadata for one rendered sample card."""
    name: str
    category: str
    hook: str | None
    background: str | None
    image_path: Path
    title: str
    meta_fields: list[str]
    phash: int = 0
    is_duplicate_of: str | None = None


# ------------------------------------------------------------------ Title generators

_TITLE_TEMPLATES: dict[str, list[str]] = {
    "Internship": [
        "Summer Software Engineering Intern at Meta",
        "Research Intern at MIT CSAIL",
        "Product Internship at Stripe",
    ],
    "Scholarship": [
        "Fulbright Foreign Student Program 2026",
        "Chevening Scholarships UK 2026",
        "Rhodes Scholarship at Oxford",
    ],
    "Fellowship": [
        "MIT Fellowship in AI & ML",
        "Mo Ibrahim Leadership Fellowship",
        "NSF Graduate Research Fellowship",
    ],
    "Research": [
        "Particle Physics Research at CERN",
        "Climate Change Research Internship NASA",
        "Genomics Research at Broad Institute",
    ],
    "Competition": [
        "Google Code Jam 2026",
        "International Math Olympiad",
        "World Robotics Competition",
    ],
    "Olympiad": [
        "International Physics Olympiad 2026",
        "European Linguistics Olympiad",
        "USA Computing Olympiad",
    ],
    "Hackathon": [
        "HackMIT 2026",
        "ClimateHack Global",
        "DevPost AI Hackathon",
    ],
    "Startup": [
        "Y Combinator W2026 Batch",
        "Techstars Berlin Accelerator",
        "500 Global Startup Accelerator",
    ],
    "Accelerator": [
        "Andreessen Horowitz a16z 2026",
        "Plug and Play Tech Center",
        "Founder Institute SF",
    ],
    "Incubator": [
        "Stanford StartX 2026",
        "MassChallenge Global",
        "HAX Hardware Accelerator",
    ],
    "Grant": [
        "Gates Cambridge Scholarship Grant",
        "Ford Foundation Fellowship Grant",
        "Amazon Research Award",
    ],
    "Conference": [
        "NeurIPS 2026 Conference on Neural Information",
        "Google I/O Developer Conference",
        "TED Conference Fellows Program",
    ],
    "SummerProgram": [
        "Ross Summer Program for High School Students",
        "MITES Summer Program for Middle School Students",
        "Stanford Pre-Collegiate Programs",
    ],
    "Exchange": [
        "Erasmus+ Exchange in Germany",
        "Japan Exchange and Teaching Programme",
        "Study Abroad in Australia 2026",
    ],
    "Volunteer": [
        "Peace Corps Volunteer Program",
        "UN Volunteer Digital Response",
        "Doctors Without Borders",
    ],
    "Job": [
        "Senior Software Engineer at Google",
        "Machine Learning Engineer at OpenAI",
        "Product Manager at Apple",
    ],
}


def _generate_fixture(category: str, hook: str | None = None) -> dict[str, Any]:
    """Generate a representative fixture opportunity for a category/hook combination."""
    titles = _TITLE_TEMPLATES.get(category, ["Opportunity in " + category])
    title = random.choice(titles)

    fixture: dict[str, Any] = {
        "title": title,
        "category": category,
        "deadline": "2026-09-15",
        "location": "San Francisco, CA",
        "organizer": "Top Organization",
        "duration": "3 months",
        "hooks": [hook] if hook else [],
    }

    # Add category-specific variations
    if category in ("Conference", "Hackathon"):
        fixture["rewards"] = "$10K in prizes"
        fixture["duration"] = "3 days"
    elif category in ("Job", "Internship"):
        fixture["rewards"] = "$150K + equity"
        fixture.pop("duration", None)
    elif category in ("Scholarship", "Fellowship", "Grant"):
        fixture["eligibility"] = "Outstanding academic record required"
        fixture["rewards"] = "Full funding"

    return fixture


# ------------------------------------------------------------------ Background sampling

def _collect_backgrounds(bg_root: str = "backgrounds", max_per_theme: int = 2) -> list[Path]:
    """Collect background images from theme directories, sampling up to max_per_theme."""
    backgrounds: list[Path] = []
    root = Path(bg_root)
    if not root.exists():
        return backgrounds

    for theme in THEME_DIRS:
        theme_dir = root / theme
        if not theme_dir.is_dir():
            continue

        images = sorted(theme_dir.glob("*.jpg")) + sorted(theme_dir.glob("*.png"))
        # Skip metadata and other non-image files
        images = [img for img in images if img.suffix.lower() in (".jpg", ".jpeg", ".png")]
        if images:
            sampled = images[:max_per_theme]
            backgrounds.extend(sampled)

    return backgrounds


# ------------------------------------------------------------------ Rendering

@dataclass
class _EnumProxy:
    """Minimal enum-like wrapper for category strings in fixtures."""
    value: str


@dataclass
class _FixtureOpp:
    """Lightweight Opportunity for rendering."""
    title: str | None = None
    category: str = ""
    deadline: str | None = None
    eligibility: str | None = None
    location: str | None = None
    cost: str | None = None
    organizer: str | None = None
    duration: str | None = None
    rewards: str | None = None
    apply_link: str | None = None
    description: str | None = None
    rewritten_text: str | None = None
    hooks: list[str] | None = None
    media_path: str | None = None
    similarity_hash: str | None = None
    id: int = 0

    def __post_init__(self):
        if self.hooks is None:
            self.hooks = []
        if isinstance(self.category, str):
            self.category = _EnumProxy(self.category)


def _dict_to_fixture(d: dict[str, Any]) -> _FixtureOpp:
    kw = {k: v for k, v in d.items() if k in (
        "title", "category", "deadline", "eligibility", "location",
        "cost", "organizer", "duration", "rewards", "apply_link",
        "description", "rewritten_text", "hooks", "media_path",
        "similarity_hash", "id",
    )}
    return _FixtureOpp(**kw)


async def _render_card(fixture: _FixtureOpp, bg_path: Path | None = None) -> bytes:
    """Render a single card to JPEG bytes."""
    from src.publisher.image_gen import _build_html, _render_html

    bg_entry = None
    if bg_path and bg_path.exists():
        from src.publisher.background_manager import ImageEntry
        bg_entry = ImageEntry(
            path=bg_path,
            rel_key=bg_path.name,
            tags=frozenset(),
        )

    html_content = _build_html(fixture, bg_entry)
    return await _render_html(html_content)


def _compute_phash(img: Image.Image) -> int:
    """Compute perceptual hash (average hash)."""
    from PIL import Image as Img
    small = img.convert("L").resize((8, 8), Img.Resampling.LANCZOS)
    pixels = list(small.get_flattened_data())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


def _hamming_distance(a: int, b: int) -> int:
    """Count differing bits."""
    return bin(a ^ b).count("1")


# ------------------------------------------------------------------ Duplicate clustering

def _find_duplicates(cards: list[SampleCard], similarity_threshold: float = 0.90) -> None:
    """Mark near-duplicate cards based on perceptual hash similarity."""
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            if cards[i].is_duplicate_of or cards[j].is_duplicate_of:
                continue
            dist = _hamming_distance(cards[i].phash, cards[j].phash)
            similarity = 1.0 - (dist / 64)
            if similarity >= similarity_threshold:
                # Mark the later one as duplicate of the earlier one
                cards[j].is_duplicate_of = cards[i].name


# ------------------------------------------------------------------ Gallery HTML

def _generate_gallery_html(cards: list[SampleCard], output_path: Path) -> None:
    """Generate an interactive HTML gallery for visual inspection."""
    # Compute stats
    total = len(cards)
    duplicates = sum(1 for c in cards if c.is_duplicate_of)
    categories = sorted({c.category for c in cards})

    # Build card entries JSON for JS
    cards_json = json.dumps([
        {
            "name": c.name,
            "category": c.category,
            "hook": c.hook,
            "background": c.background,
            "title": c.title,
            "meta": c.meta_fields,
            "duplicate_of": c.is_duplicate_of,
        }
        for c in cards
    ], ensure_ascii=False, indent=2)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Simurg Diversity Gallery</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', system-ui, sans-serif;
    background: #0a0a0a;
    color: #e0e0e0;
    padding: 24px;
  }}
  h1 {{ font-size: 28px; margin-bottom: 8px; }}
  .stats {{
    display: flex; gap: 24px; margin-bottom: 24px; color: #888; font-size: 14px;
  }}
  .stats span strong {{ color: #fff; }}
  .filters {{
    display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px;
  }}
  .filter-btn {{
    padding: 6px 16px; border-radius: 20px; border: 1px solid #333;
    background: transparent; color: #ccc; cursor: pointer; font-size: 13px;
    transition: all 0.2s;
  }}
  .filter-btn:hover, .filter-btn.active {{
    background: #3b82f6; border-color: #3b82f6; color: #fff;
  }}
  .filter-btn.duplicates.active {{
    background: #ef4444; border-color: #ef4444;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 16px;
  }}
  .card {{
    background: #1a1a1a; border-radius: 12px; overflow: hidden;
    border: 2px solid transparent; transition: border-color 0.2s;
  }}
  .card.duplicate {{ border-color: #ef4444; }}
  .card:hover {{ border-color: #555; }}
  .card img {{
    width: 100%; display: block; cursor: pointer;
  }}
  .card-info {{ padding: 12px; }}
  .card-title {{ font-size: 14px; font-weight: 600; margin-bottom: 4px; }}
  .card-meta {{
    display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: #888;
  }}
  .badge {{
    padding: 2px 8px; border-radius: 10px; font-size: 11px;
    background: #333; color: #aaa;
  }}
  .badge.category {{ background: #1e3a5f; color: #60a5fa; }}
  .badge.hook {{ background: #3b1f5e; color: #c084fc; }}
  .badge.duplicate {{ background: #5e1f1f; color: #fca5a5; }}
  .modal {{
    display: none; position: fixed; inset: 0; z-index: 100;
    background: rgba(0,0,0,0.9); justify-content: center; align-items: center;
    cursor: pointer; padding: 20px;
  }}
  .modal.show {{ display: flex; }}
  .modal img {{ max-width: 90vw; max-height: 90vh; border-radius: 8px; }}
</style>
</head>
<body>
<h1>Diversity Gallery</h1>
<div class="stats">
  <span>Total: <strong>{total}</strong></span>
  <span>Categories: <strong>{len(categories)}</strong></span>
  <span>Duplicates: <strong>{duplicates}</strong></span>
</div>

<div class="filters">
  <button class="filter-btn active" data-filter="all">All</button>
  <button class="filter-btn duplicates" data-filter="duplicates">Duplicates only</button>
  {"".join(f'<button class="filter-btn" data-filter="cat-{cat}">{cat}</button>' for cat in categories)}
</div>

<div class="grid" id="gallery">
  {"".join(_card_html(c) for c in cards)}
</div>

<div class="modal" id="modal" onclick="this.classList.remove('show')">
  <img id="modal-img" src="" alt="">
</div>

<script>
const cards = {cards_json};
const grid = document.getElementById('gallery');
const modal = document.getElementById('modal');
const modalImg = document.getElementById('modal-img');

// Click card images to view full-size
document.querySelectorAll('.card img').forEach(img => {{
  img.addEventListener('click', e => {{
    e.stopPropagation();
    modalImg.src = img.src;
    modal.classList.add('show');
  }});
}});

// Filtering
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const filter = btn.dataset.filter;

    document.querySelectorAll('.card').forEach(card => {{
      if (filter === 'all') {{ card.style.display = ''; return; }}
      if (filter === 'duplicates') {{
        card.style.display = card.classList.contains('duplicate') ? '' : 'none';
        return;
      }}
      const cat = card.dataset.category;
      card.style.display = (filter === `cat-{{cat}}`) ? '' : 'none';
    }});
  }});
}});
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")


def _card_html(c: SampleCard) -> str:
    """Generate HTML for one card in the gallery grid."""
    dup_class = " duplicate" if c.is_duplicate_of else ""
    dup_badge = f'<span class="badge duplicate">dup of {html.escape(c.is_duplicate_of or "")}</span>' if c.is_duplicate_of else ""
    hook_badge = f'<span class="badge hook">{html.escape(c.hook)}</span>' if c.hook else ""

    meta_html = "".join(f'<span class="badge">{html.escape(m)}</span>' for m in c.meta_fields[:3])

    return f'''<div class="card{dup_class}" data-category="{html.escape(c.category)}">
  <img src="{c.image_path.name}" alt="{html.escape(c.title)}" loading="lazy">
  <div class="card-info">
    <div class="card-title">{html.escape(c.title)}</div>
    <div class="card-meta">
      <span class="badge category">{html.escape(c.category)}</span>
      {hook_badge}
      {meta_html}
      {dup_badge}
    </div>
  </div>
</div>'''


# ------------------------------------------------------------------ Pipeline

async def run_render(
    categories: list[str],
    include_hooks: bool = True,
    with_backgrounds: bool = False,
    output_dir: Path = Path("output/gallery"),
    build_only: bool = False,
) -> None:
    """Render the diversity gallery.

    Args:
        categories: Categories to render (empty = all).
        include_hooks: Whether to render with all hook variations.
        with_backgrounds: Whether to use real background images.
        output_dir: Output directory for images and gallery HTML.
        build_only: If True, skip rendering and just build gallery from existing images.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)

    if not categories:
        categories = ALL_CATEGORIES

    # Collect backgrounds
    backgrounds = _collect_backgrounds() if with_backgrounds else []
    print(f"Found {len(backgrounds)} background images to sample")

    # Build render matrix
    render_tasks: list[tuple[str, dict[str, Any], Path | None]] = []

    for cat in categories:
        # Always render one no-hook version
        fixture = _generate_fixture(cat)
        render_tasks.append((f"{cat}_none", fixture, None))

        # Render with each hook
        if include_hooks:
            for hook in ALL_HOOKS:
                fixture = _generate_fixture(cat, hook)
                render_tasks.append((f"{cat}_{hook[:3]}", fixture, None))

        # Render with backgrounds (if available)
        if backgrounds:
            # Sample 1-2 backgrounds per category
            sampled_bgs = backgrounds[:max(1, len(backgrounds) // len(categories))]
            for bg_path in sampled_bgs[:2]:
                fixture = _generate_fixture(cat)
                name = f"{cat}_bg_{bg_path.parent.name}"
                render_tasks.append((name, fixture, bg_path))

    # Render cards
    cards: list[SampleCard] = []
    total = len(render_tasks)
    print(f"Rendering {total} cards...")

    if not build_only:
        for i, (name, fixture_dict, bg_path) in enumerate(render_tasks, 1):
            try:
                fixture = _dict_to_fixture(fixture_dict)
                fixture.id = i
                rendered = await _render_card(fixture, bg_path)

                img_name = f"sample_{i:04d}.jpg"
                img_path = output_dir / "images" / img_name
                img_path.write_bytes(rendered)

                # Compute phash
                img = Image.open(img_path)
                phash = _compute_phash(img)

                meta = []
                if fixture_dict.get("deadline"):
                    meta.append("deadline")
                if fixture_dict.get("location"):
                    meta.append("location")
                if fixture_dict.get("rewards"):
                    meta.append("rewards")
                if fixture_dict.get("organizer"):
                    meta.append("organizer")
                if fixture_dict.get("duration"):
                    meta.append("duration")

                cards.append(SampleCard(
                    name=name,
                    category=fixture_dict["category"],
                    hook=fixture_dict.get("hooks", [None])[0] if fixture_dict.get("hooks") else None,
                    background=bg_path.parent.name if bg_path else None,
                    image_path=img_path,
                    title=fixture_dict.get("title", ""),
                    meta_fields=meta,
                    phash=phash,
                ))

                if i % 20 == 0:
                    print(f"  {i}/{total}...")

            except Exception as e:
                print(f"  ! {name}: {e}", file=sys.stderr)
    else:
        # Build from existing images
        existing = sorted((output_dir / "images").glob("*.jpg"))
        print(f"Found {len(existing)} existing rendered images")
        for i, img_path in enumerate(existing):
            try:
                img = Image.open(img_path)
                phash = _compute_phash(img)
                cards.append(SampleCard(
                    name=img_path.stem,
                    category="Unknown",
                    hook=None,
                    background=None,
                    image_path=img_path,
                    title=img_path.stem,
                    meta_fields=[],
                    phash=phash,
                ))
            except Exception:
                continue

    # Find duplicates
    _find_duplicates(cards)
    dup_count = sum(1 for c in cards if c.is_duplicate_of)
    print(f"\nDuplicate detection: {dup_count} near-duplicates found")

    # Generate gallery HTML
    gallery_path = output_dir / "gallery.html"
    _generate_gallery_html(cards, gallery_path)
    print(f"Gallery: {gallery_path}")

    # Save metadata JSON
    meta_path = output_dir / "metadata.json"
    meta_data = {
        "total": len(cards),
        "duplicates": dup_count,
        "categories": sorted({c.category for c in cards}),
        "with_backgrounds": with_backgrounds,
        "cards": [
            {
                "name": c.name,
                "category": c.category,
                "hook": c.hook,
                "background": c.background,
                "title": c.title,
                "duplicate_of": c.is_duplicate_of,
            }
            for c in cards
        ],
    }
    meta_path.write_text(
        json.dumps(meta_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"\nDone: {len(cards)} cards, {dup_count} duplicates → {gallery_path}")


# ------------------------------------------------------------------ CLI

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Diversity gallery renderer for opportunity cards",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--categories", nargs="*", type=str, default=[],
        help="Categories to render (default: all)",
    )
    parser.add_argument(
        "--no-hooks", action="store_true",
        help="Skip hook variations (render category only)",
    )
    parser.add_argument(
        "--with-backgrounds", action="store_true",
        help="Render with real background images from the library",
    )
    parser.add_argument(
        "--output-gallery", type=str, default="output/gallery",
        help="Output directory for gallery",
    )
    parser.add_argument(
        "--build-only", action="store_true",
        help="Skip rendering, just build gallery from existing images",
    )
    args = parser.parse_args()

    asyncio.run(
        run_render(
            categories=args.categories,
            include_hooks=not args.no_hooks,
            with_backgrounds=args.with_backgrounds,
            output_dir=Path(args.output_gallery),
            build_only=args.build_only,
        )
    )


if __name__ == "__main__":
    main()
