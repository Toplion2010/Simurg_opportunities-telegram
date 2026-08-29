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
    "ethglobal": {"module": "sources.ethglobal", "priority": 6, "enabled": True},
    "hackathoncom": {"module": "sources.hackathoncom", "priority": 7, "enabled": True},
    "allhackathons": {"module": "sources.allhackathons", "priority": 8, "enabled": True},
    "hackclub": {"module": "sources.hackclub", "priority": 9, "enabled": True},
    "lablab": {"module": "sources.lablab", "priority": 10, "enabled": True},
    "mlcontests": {"module": "sources.mlcontests", "priority": 11, "enabled": True},
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
# allhackathons.com has ~60 pages (mixed past/upcoming, sorted newest-added
# first, not by date) — capped low since we only care about recently added
# items; the still_open filter drops anything past regardless of page.
ALLHACKATHONS_PAGE_CAP: int = 3
# lablab.ai's listing page body is client-rendered, but the page embeds a
# real schema.org ItemList (title+url, ~24 items, first-page order) and
# each detail page embeds a real schema.org Event (dates, attendance mode,
# prize-pool text) — both server-side JSON-LD, no browser needed. Detail
# fetches are capped since each hackathon needs its own request.
LABLAB_DETAIL_CAP: int = 15

# --- State ---
SEEN_PRUNE_DAYS: int = 60

# --- Enrichment (pipeline/enrich.py) ---
ENRICH_ENABLED: bool = True
ENRICH_TIMEOUT_TOTAL: float = 120.0  # wall-clock budget per run, seconds
ENRICH_DETAIL_TIMEOUT: int = 15  # per detail-page request
ENRICH_DETAIL_RETRIES: int = 1
ENRICH_SLEEP_SECONDS: float = 1.0  # between detail fetches

# --- Image generation (pipeline/image_gen.py) ---
# Fallback cover image via Gemini when a source gives no real photo (a
# filtered generic placeholder, or a source that never provides one). Same
# GEMINI_API_KEY secret and model family as Simurg's own opportunity-card
# generator (src/publisher/live_background.py) — read from the environment
# in main.py, not stored here, matching TELEGRAM_BOT_TOKEN's convention.
IMAGE_GEN_ENABLED: bool = True
GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image"
GEMINI_IMAGE_FALLBACK_MODELS: list[str] = [
    "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-3-pro-image",
]
IMAGE_GEN_TIMEOUT: int = 30
# Lighter than Simurg's card generator (0,4,10,25,45s) — this bot posts up
# to MAX_POSTS_PER_RUN items per cron run and needs to stay well inside a
# GitHub Actions job's time budget, not just eventually succeed.
IMAGE_GEN_RETRY_SCHEDULE: tuple[float, ...] = (0, 3, 8)

# --- Generic AI-assisted enrichment (pipeline/generic_enrich.py) ---
# Fallback for any source that hasn't defined its own enrich() (reskilll,
# devevents, mlh, hackclub today). Tier 1 (free) sniffs schema.org JSON-LD
# on the item's own url; Tier 2 (Gemini text model) only runs when Tier 1
# finds nothing and GEMINI_API_KEY is set. Same key/model family as
# image_gen.py, but a text model, not the image one.
AI_ENRICH_ENABLED: bool = True
GEMINI_TEXT_MODEL: str = "gemini-3.6-flash"
AI_ENRICH_PAGE_CHARS: int = 6000  # page text truncation before sending to Gemini
# 20s proved too tight in production — the model reliably answers, but read
# timeouts were the single largest cause of items posting without any
# description (2 of 3 enrichment failures in an all-source audit run).
AI_ENRICH_TIMEOUT: int = 45
# Below this many visible characters, a raw fetch is treated as a JS-only
# shell (confirmed live on ethglobal.com and kaggle.com: ~15-20 chars, just
# the title) not worth sending to Gemini — Firecrawl (if configured) renders
# the page with real JS execution instead.
AI_ENRICH_MIN_PAGE_CHARS: int = 200
FIRECRAWL_TIMEOUT: int = 30

# --- HTTP ---
REQUEST_TIMEOUT_SECONDS: int = 20
REQUEST_RETRIES: int = 2
REQUEST_BACKOFF_SECONDS: float = 1.0
USER_AGENT: str = (
    "Mozilla/5.0 (compatible; HackathonWatcherBot/1.0; "
    "+https://github.com/) hackathon-watcher"
)
