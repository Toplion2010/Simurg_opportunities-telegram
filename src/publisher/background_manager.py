"""BackgroundManager — scans a curated image library and selects a fitting background.

Responsibilities:
  * scan ``backgrounds/<theme>/`` for theme images + per-folder ``metadata.json``
  * scan ``backgrounds/brands/<name>/`` for brand collections
  * auto-generate metadata (dominant color, brightness, contrast, visual complexity,
    content density, primary safe area) for new images
  * cache the scan and refresh lazily every few minutes (never per request)
  * pick a background using folder-first → tag-rank selection, avoiding recent repeats

State that is *learned* (usage counts) lives in Redis so rotation stays even across restarts.
Static curated fields live in each folder's ``metadata.json``.

Selection order (ADR-002):
  1. Brand collection (``backgrounds/brands/<name>/``) if organizer/title matches
  2. Mapped theme pool (``backgrounds/<theme>/`` + variants)
  3. ``general`` fallback

Within each pool images are ranked by tag overlap + weight + least-used count.
"""
from __future__ import annotations

import json
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.logging import get_logger
from src.publisher.background_map import (
    BRANDS_DIR,
    GENERAL_THEME,
    StyleDescriptor,
    is_theme_folder,
    resolve_collection,
)

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_METADATA_FILE = "metadata.json"

USAGE_KEY = "simurg:bg:usage"
LASTUSED_KEY = "simurg:bg:lastused"

_DEFAULT_WEIGHT = 1.0
_DEFAULT_QUALITY = 3.0


@dataclass
class SafeArea:
    """Rectangle expressed as normalised fractions of image dimensions.

    Stored in metadata.json as ``{"x": 0.08, "y": 0.12, "w": 0.46, "h": 0.72}``.
    Named *primary* so a secondary / L-shaped region can be added later without
    breaking the schema.
    """

    x: float = 0.08
    y: float = 0.12
    w: float = 0.46
    h: float = 0.72

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, data: dict) -> "SafeArea":
        return cls(
            x=float(data.get("x", 0.08)),
            y=float(data.get("y", 0.12)),
            w=float(data.get("w", 0.46)),
            h=float(data.get("h", 0.72)),
        )


@dataclass
class ImageEntry:
    path: Path
    rel_key: str  # path relative to backgrounds root, used as the Redis field / history key
    weight: float = _DEFAULT_WEIGHT
    quality: float = _DEFAULT_QUALITY
    tags: frozenset[str] = field(default_factory=frozenset)
    dominant_color: str | None = None
    brightness: float | None = None
    # Precomputed metrics (ADR-004) — never calculated at render time.
    contrast: float | None = None
    visual_complexity: float | None = None
    content_density: float | None = None
    primary_safe_area: SafeArea = field(default_factory=SafeArea)


class BackgroundManager:
    def __init__(
        self,
        root: Path | str,
        redis: "aioredis.Redis | None" = None,
        refresh_interval: int = 300,
        history_size: int = 20,
    ) -> None:
        self._root = Path(root)
        self._redis = redis
        self._refresh_interval = refresh_interval
        # ``_folders`` maps collection names to image entries.
        # Theme folders use the theme name as key (e.g. "general").
        # Brand folders use the brand name as key (e.g. "apple").
        self._folders: dict[str, list[ImageEntry]] = {}
        self._last_scan: float = 0.0
        self._scanning = False
        self._history: deque[str] = deque(maxlen=max(1, history_size))

    # ------------------------------------------------------------------ scanning

    def scan(self) -> None:
        """(Re)scan the library from disk. Cheap, off the hot path; tolerant of bad input."""
        if self._scanning:
            return
        self._scanning = True
        try:
            folders: dict[str, list[ImageEntry]] = {}
            if not self._root.is_dir():
                logger.warning("backgrounds_dir_missing", path=str(self._root))
                self._folders = folders
                self._last_scan = time.monotonic()
                return

            # 1. Scan theme folders (direct children of backgrounds/)
            for folder_path in sorted(self._root.iterdir()):
                if not folder_path.is_dir():
                    continue
                # Skip hidden directories and the brands sub-directory
                if folder_path.name.startswith(".") or folder_path.name == BRANDS_DIR:
                    continue
                entries = self._scan_folder(folder_path)
                if entries:
                    folders[folder_path.name] = entries

            # 2. Scan brand collections (backgrounds/brands/<name>/)
            brands_dir = self._root / BRANDS_DIR
            if brands_dir.is_dir():
                for brand_path in sorted(brands_dir.iterdir()):
                    if not brand_path.is_dir() or brand_path.name.startswith("."):
                        continue
                    entries = self._scan_folder(brand_path, rel_prefix=BRANDS_DIR)
                    if entries:
                        folders[brand_path.name] = entries

            self._folders = folders
            self._last_scan = time.monotonic()
            logger.info(
                "backgrounds_scanned",
                folders=len(folders),
                images=sum(len(v) for v in folders.values()),
            )
        finally:
            self._scanning = False

    def _scan_folder(
        self, folder_path: Path, rel_prefix: str | None = None
    ) -> list[ImageEntry]:
        images = [
            p
            for p in sorted(folder_path.iterdir())
            if p.is_file()
            and not p.name.startswith(".")
            and p.suffix.lower() in _IMAGE_EXTS
        ]
        if not images:
            return []

        metadata = self._load_metadata(folder_path)
        generated = False
        entries: list[ImageEntry] = []

        for img in images:
            meta = metadata.get(img.name)
            needs_compute = (
                meta is None
                or "dominant_color" not in meta
                or "brightness" not in meta
                or "contrast" not in meta
                or "visual_complexity" not in meta
                or "content_density" not in meta
                or "primary_safe_area" not in meta
            )
            if needs_compute:
                computed = _auto_metadata(img)
                # Existing user fields win; only fill what's missing.
                merged = {**computed, **(meta or {})}
                metadata[img.name] = merged
                meta = merged
                generated = True
            entries.append(self._build_entry(img, meta, folder_path.name, rel_prefix))

        if generated:
            self._write_metadata(folder_path, metadata)

        return entries

    @staticmethod
    def _build_entry(
        img: Path, meta: dict, folder_name: str, rel_prefix: str | None
    ) -> ImageEntry:
        if rel_prefix:
            rel_key = f"{rel_prefix}/{folder_name}/{img.name}"
        else:
            rel_key = f"{folder_name}/{img.name}"

        tags = meta.get("tags") or []
        safe_area_dict = meta.get("primary_safe_area")
        if isinstance(safe_area_dict, dict):
            safe_area = SafeArea.from_dict(safe_area_dict)
        else:
            safe_area = SafeArea()

        return ImageEntry(
            path=img,
            rel_key=rel_key,
            weight=_coerce_float(meta.get("weight"), _DEFAULT_WEIGHT),
            quality=_coerce_float(meta.get("quality"), _DEFAULT_QUALITY),
            tags=frozenset(str(t).lower() for t in tags if isinstance(t, str)),
            dominant_color=meta.get("dominant_color"),
            brightness=_coerce_float(meta.get("brightness"), None),
            contrast=_coerce_float(meta.get("contrast"), None),
            visual_complexity=_coerce_float(meta.get("visual_complexity"), None),
            content_density=_coerce_float(meta.get("content_density"), None),
            primary_safe_area=safe_area,
        )

    def _load_metadata(self, folder_path: Path) -> dict[str, dict]:
        meta_path = folder_path / _METADATA_FILE
        if not meta_path.is_file():
            return {}
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, dict)}
            logger.warning("metadata_not_object", path=str(meta_path))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("metadata_load_failed", path=str(meta_path), error=str(e))
        return {}

    def _write_metadata(self, folder_path: Path, metadata: dict[str, dict]) -> None:
        meta_path = folder_path / _METADATA_FILE
        try:
            meta_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            # Read-only mount etc. — keep in-memory values, don't fail rendering.
            logger.warning("metadata_write_failed", path=str(meta_path), error=str(e))

    # ----------------------------------------------------------------- selection

    def _maybe_refresh(self) -> None:
        if not self._folders or (time.monotonic() - self._last_scan) > self._refresh_interval:
            self.scan()

    def _resolve_pool(self, descriptor: StyleDescriptor) -> list[ImageEntry]:
        """Fallback chain: brand collection → mapped theme (+ variants) → general.

        Brand collections live under ``backgrounds/brands/`` and are keyed by brand name.
        Theme folders are keyed by their folder name.
        """
        all_folders = set(self._folders)

        # 1. Brand collection (folder-first, ADR-002)
        collection = resolve_collection(all_folders, descriptor.organizer, descriptor.title)
        if collection and self._folders.get(collection):
            return list(self._folders[collection])

        # 2. Mapped theme pool (theme + variants)
        for theme in (descriptor.theme, GENERAL_THEME):
            pool: list[ImageEntry] = []
            for folder, entries in self._folders.items():
                if is_theme_folder(folder, theme):
                    pool.extend(entries)
            if pool:
                return pool
        return []

    async def get_background(self, descriptor: StyleDescriptor) -> ImageEntry | None:
        self._maybe_refresh()

        pool = self._resolve_pool(descriptor)
        if not pool:
            return None

        # Avoid recent repeats, but never exclude more than half the pool — otherwise a small
        # folder degrades into pure round-robin and weight/quality stop mattering. Excluding at
        # least the most recent pick (for any pool of 2+) still prevents immediate repeats.
        n_exclude = min(len(self._history), len(pool) // 2)
        recent = set(list(self._history)[-n_exclude:]) if n_exclude > 0 else set()
        candidates = [e for e in pool if e.rel_key not in recent] or pool

        usage = await self._load_usage([e.rel_key for e in candidates])
        weights = [self._score(e, descriptor, usage.get(e.rel_key, 0)) for e in candidates]

        chosen = random.choices(candidates, weights=weights, k=1)[0]
        self._history.append(chosen.rel_key)
        await self._record_usage(chosen.rel_key)
        return chosen

    @staticmethod
    def _score(entry: ImageEntry, descriptor: StyleDescriptor, usage_count: int) -> float:
        """Folder-first → tag-rank scoring.

        Rank within the selected pool by:
          * tag overlap with descriptor tags
          * palette match bonus
          * image weight and quality
          * inverse usage count (least-used preference)
        """
        quality_factor = max(0.1, entry.quality / _DEFAULT_QUALITY)

        overlap = entry.tags & descriptor.tags
        tag_bonus = 0.5 * len(overlap)
        if descriptor.palette and descriptor.palette in entry.tags:
            tag_bonus += 0.5

        base = max(0.0, entry.weight) * quality_factor * (1.0 + tag_bonus)
        score = base / (1.0 + usage_count)
        # Guard against all-zero weights (random.choices would raise).
        return max(score, 1e-6)

    # --------------------------------------------------------------- redis stats

    async def _load_usage(self, keys: list[str]) -> dict[str, int]:
        if self._redis is None or not keys:
            return {}
        try:
            values = await self._redis.hmget(USAGE_KEY, keys)
        except Exception as e:  # noqa: BLE001
            logger.warning("bg_usage_load_failed", error=str(e))
            return {}
        return {k: int(v) for k, v in zip(keys, values) if v is not None}

    async def _record_usage(self, rel_key: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.hincrby(USAGE_KEY, rel_key, 1)
            await self._redis.hset(LASTUSED_KEY, rel_key, str(int(time.time())))
        except Exception as e:  # noqa: BLE001
            logger.warning("bg_usage_record_failed", key=rel_key, error=str(e))


# ------------------------------------------------------------------- metadata

def _auto_metadata(img: Path) -> dict:
    """Compute precomputed metrics for a background image (ADR-004).

    Metrics are calculated **once** during scanning and persisted into ``metadata.json``.
    The render path never calls this — it reads metadata as O(1) lookups.

    Returns a dict with:
      * ``dominant_color`` — hex string of average colour
      * ``brightness`` — normalised mean luminance [0, 1]
      * ``contrast`` — standard deviation of luminance normalised to [0, 1]
      * ``visual_complexity`` — edge density via Sobel filter [0, 1]
      * ``content_density`` — fraction of non-empty (non-uniform) regions [0, 1]
      * ``primary_safe_area`` — rectangle dict best suited for text overlay
      * ``weight``, ``quality``, ``tags`` — defaults
    """
    result: dict = {
        "weight": _DEFAULT_WEIGHT,
        "quality": _DEFAULT_QUALITY,
        "tags": [],
    }
    try:
        from PIL import Image, ImageStat


        with Image.open(img) as im:
            rgb = im.convert("RGB")
            gray = rgb.convert("L")

            # --- Dominant colour (average) ---
            small = rgb.resize((1, 1))
            r, g, b = small.getpixel((0, 0))
            result["dominant_color"] = f"#{r:02X}{g:02X}{b:02X}"

            # --- Brightness ---
            stat = ImageStat.Stat(gray)
            result["brightness"] = round(stat.mean[0] / 255.0, 3)

            # --- Contrast (std dev of luminance, normalised) ---
            result["contrast"] = round(stat.stddev[0] / 255.0, 3)

            # --- Visual complexity (edge density via Sobel) ---
            result["visual_complexity"] = _compute_visual_complexity(gray)

            # --- Content density (fraction of non-uniform 16×16 blocks) ---
            result["content_density"] = _compute_content_density(gray)

            # --- Primary safe area (heuristic from complexity map) ---
            result["primary_safe_area"] = _compute_safe_area(gray).to_dict()

    except Exception as e:  # noqa: BLE001 — never let metadata gen break a scan
        logger.warning("auto_metadata_failed", path=str(img), error=str(e))
    return result


def _compute_visual_complexity(gray: "Image.Image") -> float:
    """Edge density via Sobel filter, normalised to [0, 1].

    Resizes to a small thumbnail first so this runs fast even on large images.
    """
    try:
        from PIL import ImageFilter, ImageStat

        thumb = gray.resize((128, 72))
        edged = thumb.filter(ImageFilter.FIND_EDGES)
        edge_gray = edged.convert("L")
        stats = ImageStat.Stat(edge_gray)
        # Mean edge intensity as a proxy for complexity
        complexity = stats.mean[0] / 255.0
        return round(min(1.0, max(0.0, complexity)), 3)
    except Exception:
        return 0.5  # sensible default


def _compute_content_density(gray: "Image.Image") -> float:
    """Fraction of 16×16 blocks that have non-trivial variance.

    Blocks with low variance are "empty" (uniform / smooth); blocks with
    higher variance contain visual content.  Returns [0, 1].
    """
    try:
        thumb = gray.resize((128, 72))
        width, height = thumb.size
        pixels = thumb.load()
        block_size = 16
        total_blocks = 0
        content_blocks = 0

        for by in range(0, height - block_size + 1, block_size):
            for bx in range(0, width - block_size + 1, block_size):
                total_blocks += 1
                values = [
                    pixels[x + bx, y + by]
                    for x in range(block_size)
                    for y in range(block_size)
                    if x + bx < width and y + by < height
                ]
                if not values:
                    continue
                mean = sum(values) / len(values)
                variance = sum((v - mean) ** 2 for v in values) / len(values)
                # Threshold: blocks with stddev > 15 are "content"
                if math.sqrt(variance) > 15:
                    content_blocks += 1

        if total_blocks == 0:
            return 0.5
        return round(content_blocks / total_blocks, 3)
    except Exception:
        return 0.5  # sensible default


def _compute_safe_area(gray: "Image.Image") -> SafeArea:
    """Determine the best rectangular region for text overlay.

    Heuristic: split the image into four quadrants (left/top, right/top,
    left/bottom, right/bottom) and pick the least-complex one as the
    text anchor side.  Returns a rectangle biased to the left (where
    content currently sits) but adapted to the image's content density.

    This runs on a small thumbnail so it's fast.
    """
    try:
        thumb = gray.resize((128, 72))
        width, height = thumb.size
        pixels = thumb.load()

        def quadrant_complexity(x0: int, y0: int, x1: int, y1: int) -> float:
            values = [
                pixels[x, y]
                for x in range(x0, x1)
                for y in range(y0, y1)
            ]
            if not values:
                return 1.0
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            return math.sqrt(variance) / 255.0

        mid_x = width // 2
        mid_y = height // 2

        left = quadrant_complexity(0, 0, mid_x, height)
        right = quadrant_complexity(mid_x, 0, width, height)

        # Prefer the left side for text (architecture invariant).
        # If the left is significantly busier (>30% more complex), shrink
        # the text area to stay in the calmest region.
        if left > right * 1.3:
            # Left is busier — constrain text area to the left side but
            # shifted toward the right (calmer) part of it.
            return SafeArea(x=0.18, y=0.10, w=0.38, h=0.75)

        # Left is calmer or comparable — use the standard left-anchored area.
        # Adjust width based on overall complexity: busier images get narrower columns.
        overall = (left + right) / 2
        if overall > 0.2:
            return SafeArea(x=0.06, y=0.10, w=0.40, h=0.75)

        return SafeArea(x=0.08, y=0.12, w=0.46, h=0.72)

    except Exception:
        return SafeArea()


def _coerce_float(value: object, default: float | None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
