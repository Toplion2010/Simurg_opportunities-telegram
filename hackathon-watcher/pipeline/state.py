"""Thin interface over state/seen.json — the only module that touches the
file directly, so swapping to a database later means rewriting this file,
not the pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import config

logger = logging.getLogger(__name__)

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "seen.json"
ENRICHED_STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "enriched.json"


def load(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("state: failed to load %s, starting empty", path, exc_info=True)
        return {}


def save(seen: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def prune(seen: dict, cutoff_days: int = config.SEEN_PRUNE_DAYS) -> dict:
    """Drop entries whose ends_at passed more than cutoff_days ago. Entries
    without a stored end date are kept (nothing to safely prune on)."""
    cutoff = date.today() - timedelta(days=cutoff_days)
    result = {}
    for key, entry in seen.items():
        ends_at = entry.get("ends_at")
        if ends_at:
            try:
                if date.fromisoformat(ends_at) < cutoff:
                    continue
            except ValueError:
                pass
        result[key] = entry
    return result
