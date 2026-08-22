"""All tunables for the hackathon watcher, independent of the cron schedule."""

from __future__ import annotations

# --- Source registry ---
# Adding a source = write sources/<name>.py + add one entry here. Never edit
# main.py to add a source: it resolves `module` dynamically and looks up
# the Source subclass defined in it. `priority` doubles as the dedup
# tie-breaker (lower wins). `enabled: False` drops a source from every run
# without deleting its code.
SOURCES: dict[str, dict] = {
    "devpost": {"module": "sources.devpost", "priority": 1, "enabled": True},
    "devevents": {"module": "sources.devevents", "priority": 2, "enabled": True},
    "mlh": {"module": "sources.mlh", "priority": 3, "enabled": True},
    "devfolio": {"module": "sources.devfolio", "priority": 4, "enabled": True},
    "reskilll": {"module": "sources.reskilll", "priority": 5, "enabled": True},
}

# --- Filters (pipeline/filters.py reads these) ---
ONLINE_ONLY: bool = True
STILL_OPEN: bool = True
MIN_PRIZE: float | None = None
EXCLUDE_THEMES: list[str] = []
INCLUDE_THEMES: list[str] = []

# --- Posting ---
MAX_POSTS_PER_RUN: int = 15
POST_SLEEP_SECONDS: float = 1.5

# --- Source-specific ---
DEVPOST_PAGE_CAP: int = 5

# --- State ---
SEEN_PRUNE_DAYS: int = 60

# --- HTTP ---
REQUEST_TIMEOUT_SECONDS: int = 20
REQUEST_RETRIES: int = 2
REQUEST_BACKOFF_SECONDS: float = 1.0
USER_AGENT: str = (
    "Mozilla/5.0 (compatible; HackathonWatcherBot/1.0; "
    "+https://github.com/) hackathon-watcher"
)
