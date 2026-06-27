"""Visual regression testing for opportunity cards.

Renders fixture opportunities and compares against committed baselines
to detect unintended visual changes.  Works entirely offline — no
database or Redis required.

Usage:
    # Compare against existing baselines
    python -m tools.visual_regression

    # Generate fresh baselines (first run, or to approve changes)
    python -m tools.visual_regression --generate-baselines

    # Show diff images for failures
    python -m tools.visual_regression --show-diffs

    # Custom baseline directory
    python -m tools.visual_regression --baseline-dir baselines/custom/

Architecture:
    Fixtures (test data) → _build_html() → Playwright render → Pixel compare
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

# ------------------------------------------------------------------ Fixtures

# Representative test opportunities covering the key combinations of
# category, hooks, field population, and edge cases.  Each fixture is
# a dict that maps to Opportunity fields.

FIXTURES: list[dict[str, Any]] = [
    # 1 — Standard conference, no hooks, all common fields
    {
        "title": "AI & Machine Learning Conference 2026",
        "category": "Conference",
        "deadline": "2026-08-15",
        "location": "San Francisco, CA",
        "organizer": "Stanford University",
        "duration": "3 days",
        "hooks": [],
    },
    # 2 — Job with premium hook, prize field
    {
        "title": "Senior Software Engineer at Google",
        "category": "Job",
        "deadline": "2026-07-01",
        "location": "Mountain View, CA",
        "rewards": "$180K - $250K",
        "organizer": "Google",
        "hooks": ["\ud83d\udd25 #PremiumOpportunity"],
    },
    # 3 — Hackathon with multiple hooks, short title
    {
        "title": "ClimateHack",
        "category": "Hackathon",
        "deadline": "2026-09-20",
        "location": "Online",
        "rewards": "$50K in prizes",
        "duration": "48 hours",
        "hooks": ["\ud83d\ude80 #EarlyAccess", "\ud83c\udf0d #Worldwide"],
    },
    # 4 — Exchange program, long title, minimal fields
    {
        "title": "Erasmus+ Student Exchange Program for Undergraduate Students in European Universities",
        "category": "Exchange",
        "deadline": "2027-01-15",
        "location": "Europe",
        "hooks": [],
    },
    # 5 — Grant with closing-soon hook, long values
    {
        "title": "NSF Graduate Research Fellowship",
        "category": "Grant",
        "deadline": "Closing July 2026",
        "location": "United States (remote eligible)",
        "rewards": "$120,000 over two years",
        "organizer": "National Science Foundation",
        "duration": "24 months",
        "hooks": ["\u26a1 #ClosingSoon"],
    },
    # 6 — Internship, worldwide hook, moderate fields
    {
        "title": "Summer Research Internship at CERN",
        "category": "Internship",
        "deadline": "2026-06-30",
        "location": "Geneva, Switzerland",
        "organizer": "CERN",
        "duration": "6-12 weeks",
        "hooks": ["\ud83c\udf0d #Worldwide"],
    },
    # 7 — Scholarship, no deadline, many fields
    {
        "title": "Rhodes Scholarship at Oxford University",
        "category": "Scholarship",
        "location": "Oxford, UK",
        "organizer": "Rhodes Trust",
        "eligibility": "Ages 17-25, outstanding academic record",
        "duration": "1-2 years",
        "hooks": ["\ud83c\udfc6 #HighlyRecommended"],
    },
    # 8 — Startup program, exclusive hook, short values
    {
        "title": "Y Combinator W2026",
        "category": "Startup",
        "deadline": "2026-09-01",
        "location": "SF",
        "rewards": "$500K",
        "duration": "3mo",
        "hooks": ["\ud83c\udf81 #Exclusive"],
    },
    # 9 — Competition, limited-spots hook
    {
        "title": "International Mathematical Olympiad 2026",
        "category": "Competition",
        "deadline": "2026-07-15",
        "location": "Brazil",
        "organizer": "IMO Committee",
        "duration": "2 days",
        "hooks": ["\u2b50 #LimitedSpots"],
    },
    # 10 — Volunteer, no hooks, minimal fields (edge: fewest meta rows)
    {
        "title": "UN Volunteer — Digital Response",
        "category": "Volunteer",
        "location": "Remote",
        "hooks": [],
    },
]


# ------------------------------------------------------------------ Fixture model

@dataclass
class FixtureOpportunity:
    """Lightweight Opportunity for rendering — no database required."""
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


def _dict_to_fixture(d: dict[str, Any]) -> FixtureOpportunity:
    """Convert a fixture dict to FixtureOpportunity."""
    kw = {k: v for k, v in d.items() if k in (
        "title", "category", "deadline", "eligibility", "location",
        "cost", "organizer", "duration", "rewards", "apply_link",
        "description", "rewritten_text", "hooks", "media_path",
        "similarity_hash", "id",
    )}
    category_val = kw.get("category", "")
    if isinstance(category_val, str):
        # _build_html accesses opp.category.value — so it must be an enum-like
        # object with a .value attribute.  Use a simple wrapper.
        kw["category"] = _EnumProxy(category_val)
    return FixtureOpportunity(**kw)


@dataclass
class _EnumProxy:
    """Minimal enum-like wrapper for category strings in fixtures."""
    value: str


# ------------------------------------------------------------------ Render

async def _render_fixture(fixture: FixtureOpportunity, bg_path: Path | None = None) -> bytes:
    """Render a fixture opportunity to a JPEG card image.

    Uses the same HTML builder and Playwright renderer as the production
    pipeline, but bypasses the database and background selection.
    """
    from src.publisher.image_gen import _build_html, _render_html

    # Load a specific background if provided
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


# ------------------------------------------------------------------ Compare

@dataclass
class DiffResult:
    """Result of comparing one rendered card against its baseline."""
    name: str
    passed: bool
    rmse: float | None = None
    baseline_size: tuple[int, int] | None = None
    rendered_size: tuple[int, int] | None = None
    error_msg: str = ""


def compare_images(baseline_path: Path, rendered_bytes: bytes, threshold: float = 2.0) -> DiffResult:
    """Compare a rendered image against a baseline.

    Uses RMSE (root mean square error) as the difference metric.
    Threshold of 2.0 is a reasonable cutoff for visually indistinguishable.

    Returns a DiffResult with comparison metrics.
    """
    from io import BytesIO

    name = baseline_path.stem

    if not baseline_path.exists():
        return DiffResult(
            name=name,
            passed=False,
            error_msg=f"baseline missing: {baseline_path}",
        )

    baseline = Image.open(baseline_path).convert("RGB")
    rendered = Image.open(BytesIO(rendered_bytes)).convert("RGB")

    if baseline.size != rendered.size:
        return DiffResult(
            name=name,
            passed=False,
            baseline_size=baseline.size,
            rendered_size=rendered.size,
            error_msg=f"size mismatch: baseline={baseline.size}, rendered={rendered.size}",
        )

    # Compute RMSE using numpy for reliability across PIL versions
    import math
    import numpy as np

    b_arr = np.array(baseline, dtype=np.int16)
    r_arr = np.array(rendered, dtype=np.int16)
    diff = b_arr - r_arr
    rmse = float(np.sqrt(np.mean(diff ** 2)))

    passed = rmse <= threshold
    return DiffResult(
        name=name,
        passed=passed,
        rmse=round(rmse, 4),
        baseline_size=baseline.size,
        rendered_size=rendered.size,
        error_msg=f"RMSE {rmse:.4f} exceeds threshold {threshold}" if not passed else "",
    )


def generate_diff_image(baseline_path: Path, rendered_bytes: bytes, output_dir: Path) -> Path | None:
    """Generate a visual diff image highlighting pixel differences.

    Returns the path to the diff image, or None if images are identical.
    """
    from io import BytesIO

    baseline = Image.open(baseline_path).convert("RGB")
    rendered = Image.open(BytesIO(rendered_bytes)).convert("RGB")

    if baseline.size != rendered.size:
        rendered = rendered.resize(baseline.size)

    diff = ImageChops.difference(baseline, rendered)

    # Check if there are any actual differences
    stat = ImageStat.Stat(diff)
    if all(m == 0.0 for m in stat.mean):
        return None

    # Amplify differences for visibility (multiply by 10)
    diff = diff.point(lambda v: min(255, v * 10))

    out = output_dir / f"{baseline_path.stem}_diff.png"
    diff.save(out, "PNG")
    return out


# ------------------------------------------------------------------ Pipeline

async def run_regression(
    baseline_dir: Path,
    output_dir: Path,
    generate_baselines: bool = False,
    show_diffs: bool = False,
    bg_path: Path | None = None,
    threshold: float = 2.0,
) -> list[DiffResult]:
    """Run the full visual regression suite.

    Args:
        baseline_dir: Directory containing committed baseline images.
        output_dir: Directory for rendered images and diffs.
        generate_baselines: If True, save rendered images as new baselines.
        show_diffs: If True, generate diff images for failures.
        bg_path: Optional specific background image to use for all fixtures.
        threshold: RMSE threshold for passing (default 2.0).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if generate_baselines:
        baseline_dir.mkdir(parents=True, exist_ok=True)

    if show_diffs:
        (output_dir / "diffs").mkdir(parents=True, exist_ok=True)

    results: list[DiffResult] = []
    total = len(FIXTURES)

    for i, fixture_dict in enumerate(FIXTURES, 1):
        fixture = _dict_to_fixture(fixture_dict)
        fixture.id = i
        name = f"fixture_{i:02d}_{fixture.category.value.replace(' ', '_')}"

        try:
            rendered = await _render_fixture(fixture, bg_path)

            baseline_path = baseline_dir / f"{name}.jpg"

            if generate_baselines:
                baseline_path.write_bytes(rendered)
                results.append(DiffResult(name=name, passed=True, error_msg="baseline created"))
                print(f"  [CREATE] {name}.jpg")
            else:
                result = compare_images(baseline_path, rendered, threshold)
                result.name = name  # ensure consistent naming

                if result.passed:
                    print(f"  \u2713 {name} (RMSE: {result.rmse})")
                else:
                    print(f"  \u2717 {name} — {result.error_msg}")
                    if show_diffs and isinstance(rendered, bytes):
                        diff_path = generate_diff_image(
                            baseline_path, rendered, output_dir / "diffs"
                        )
                        if diff_path:
                            print(f"      diff: {diff_path}")

                # Save rendered for inspection
                (output_dir / f"{name}_rendered.jpg").write_bytes(rendered)
                results.append(result)

        except Exception as e:
            print(f"  ! {name} — RENDER ERROR: {e}", file=sys.stderr)
            results.append(DiffResult(name=name, passed=False, error_msg=f"render error: {e}"))

    return results


# ------------------------------------------------------------------ CLI

def main() -> None:
    """CLI entry point."""
    import asyncio

    default_baseline_dir = Path("baselines")
    default_output_dir = Path("output/regression")

    parser = argparse.ArgumentParser(
        description="Visual regression testing for opportunity cards",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--generate-baselines", action="store_true",
        help="Generate fresh baseline images (overwrites existing)",
    )
    parser.add_argument(
        "--show-diffs", action="store_true",
        help="Generate diff images for failing tests",
    )
    parser.add_argument(
        "--baseline-dir", type=str, default=str(default_baseline_dir),
        help="Directory for committed baseline images",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(default_output_dir),
        help="Directory for rendered output and diffs",
    )
    parser.add_argument(
        "--bg", type=str, default=None,
        help="Path to a specific background image to use for all fixtures",
    )
    parser.add_argument(
        "--threshold", type=float, default=2.0,
        help="RMSE threshold for passing (lower = stricter)",
    )
    args = parser.parse_args()

    baseline_dir = Path(args.baseline_dir)
    output_dir = Path(args.output_dir)
    bg_path = Path(args.bg) if args.bg else None

    print(f"Visual Regression — {len(FIXTURES)} fixtures")
    print(f"Baselines: {baseline_dir}")
    print(f"Output:    {output_dir}")
    if args.generate_baselines:
        print("Mode:      GENERATE BASELINES")
    else:
        print("Mode:      COMPARE")
    print()

    results = asyncio.run(
        run_regression(
            baseline_dir=baseline_dir,
            output_dir=output_dir,
            generate_baselines=args.generate_baselines,
            show_diffs=args.show_diffs,
            bg_path=bg_path,
            threshold=args.threshold,
        )
    )

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    errors = sum(1 for r in results if "error" in r.error_msg.lower() or "missing" in r.error_msg.lower())

    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{len(results)} passed, {failed} failed, {errors} errors")

    if failed:
        print(f"\nFailures:")
        for r in results:
            if not r.passed:
                print(f"  \u2717 {r.name}: {r.error_msg}")

    # Save summary JSON
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "threshold": args.threshold,
        "results": [
            {
                "name": r.name,
                "passed": r.passed,
                "rmse": r.rmse,
                "error": r.error_msg,
            }
            for r in results
        ],
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nSummary saved to {summary_path}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
