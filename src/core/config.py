from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram Bot
    BOT_TOKEN: str
    ADMIN_IDS: list[int] = []

    # Telethon userbot
    TELETHON_API_ID: int
    TELETHON_API_HASH: str
    TELETHON_SESSION: str = "simurg"
    # Portable session for hosts with an ephemeral filesystem (Railway et al.), where
    # the .session file would be wiped on redeploy and startup would then block forever
    # waiting for a login code. Takes precedence over the file when set.
    # Generate with: python -m scripts.export_session_string
    TELETHON_SESSION_STRING: str = ""

    # Destination channels — audience-based routing (school vs university)
    DEST_CHANNEL_ID_SCHOOL: int
    DEST_CHANNEL_ID_UNIVERSITY: int
    # Category-based routing, layered ON TOP of the audience channels above: a
    # Kazakhstan hackathon also goes here (src/publisher/sender.py). 0 = off,
    # and a sentinel default rather than a bare int because botcheck.yml and
    # vercelcheck.yml boot Settings() with fake env that has no such variable.
    DEST_CHANNEL_ID_HACKATHON: int = 0

    # LLM — Groq (primary) or OpenAI-compatible
    GROQ_API_KEY: str = ""
    # Groq deprecated its Llama chat models outright (llama-3.3-70b-versatile
    # 404s as of 2026-08-17 -- "does not exist or you do not have access to
    # it"). openai/gpt-oss-120b is the closest available replacement: still
    # supports json_mode/structured_outputs like the extractor needs, similar
    # capability tier to a 70B model. Verified via GET /v1/models against the
    # live key -- see run 32148224763.
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # OpenAI — used only for embeddings when ENABLE_EMBEDDING_DEDUP=true
    OPENAI_API_KEY: str = ""
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"

    # Gemini — live per-post card background generation (image_gen.py)
    GEMINI_API_KEY: str = ""
    # Cheapest image model first ($0.0336/image vs $0.039 for 2.5-flash-image).
    GEMINI_IMAGE_MODEL: str = "gemini-3.1-flash-lite-image"
    # Tried in order when the primary returns 503/429. Congestion is per-model,
    # so a sibling usually answers instantly while the primary is saturated.
    # gemini-3-pro-image is deliberately absent: at $0.134-$0.24/image it costs
    # 3.4-6x the primary, and it was being reached on every 4th retry.
    GEMINI_IMAGE_FALLBACK_MODELS: str = (
        "gemini-2.5-flash-image,gemini-3.1-flash-image"
    )
    # Emergency brake for the per-post background generation. Separate from
    # GEMINI_API_KEY so image spend can be stopped without also disabling
    # ENABLE_IMAGE_ANALYSIS below, which reads the same key.
    ENABLE_LIVE_BACKGROUND: bool = True
    # Gemini vision — reads text/details out of a post's attached poster image so
    # facts shown only on the image (e.g. a prize amount) reach the extractor.
    GEMINI_VISION_MODEL: str = "gemini-flash-latest"
    ENABLE_IMAGE_ANALYSIS: bool = True

    # Database
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 10

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    DEDUP_TTL_SECONDS: int = 2_592_000  # 30 days

    # Processing — batch runs 5x/day. Value is UTC hours (comma-separated, apscheduler
    # cron field syntax). Default below = 6,10,14,18,22 Astana time (GMT+5) converted to UTC.
    PROCESSOR_CRON_HOURS: str = "1,5,9,13,17"
    # Pause between messages so a backlog doesn't exhaust the LLM provider's rate
    # limit — Groq's free tier 429s long before the extractor's own retry can help.
    # Groq free tier caps tokens-per-minute at 12k; one extraction costs ~2.5k, so
    # anything under ~13s/message starts hitting 429s mid-run.
    LLM_THROTTLE_SECONDS: float = 15.0
    # Messages processed per run. The real ceiling is Groq's free-tier 100k
    # tokens/day: at ~2.5k tokens per extraction that is only ~40 messages/day
    # across all 5 runs. Raise this if the Groq plan is upgraded.
    MAX_MESSAGES_PER_RUN: int = 7
    PUBLISHER_POLL_SECONDS: int = 60

    # Background library
    BACKGROUNDS_DIR: str = "backgrounds"
    BACKGROUND_REFRESH_SECONDS: int = 300
    BACKGROUND_HISTORY_SIZE: int = 20

    # Web collector — scraped opportunity catalogs (src/collector/web/).
    # A second collector KIND alongside Telegram; see src/collector/web/README
    # notes in base.py for the source contract.
    #
    # Items per run, per source. Deliberately small: ExtracurricularHub alone
    # has ~1,760 listings, and a full first pass at this rate takes ~48 days.
    # That is the point — it keeps the admin queue reviewable and means a bad
    # parse costs 40 junk rows, not 1,760. Raise it via the workflow's --limit
    # input for a one-off backfill once the parse looks right.
    WEB_MAX_ITEMS_PER_RUN: int = 40
    # Pause between detail-page fetches. These are small, volunteer-run sites.
    WEB_FETCH_SLEEP_SECONDS: float = 1.0
    WEB_REQUEST_TIMEOUT_SECONDS: float = 20.0
    WEB_REQUEST_RETRIES: int = 2
    # sirel.org returns 403 to a default library user-agent and 200 to a browser
    # one, so this has to look like a browser — but it still names the project
    # and a contact URL, because an aggregator that identifies itself is what
    # keeps this legible to the sites as traffic rather than as an attack.
    WEB_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
        "(+https://t.me/simurg_opportunities; student-opportunity aggregator)"
    )
    # A paid in-person program is admitted anyway when the fee is at or below
    # this (USD) — the "or a small fee" limb of the admission rule.
    WEB_SMALL_FEE_USD: float = 50.0
    # Above that fee, one extra request to the opportunity's OWN site decides
    # it, because the catalogs are prose-free and never mention aid: across 45
    # real listings ZERO contained funding language, while 6 of 6 of the items
    # this filter had rejected turned out to offer a scholarship or need-based
    # aid on their official page. Bounded per run — it is a request each.
    WEB_FUNDING_CHECK_MAX_PER_RUN: int = 15
    # OFF by default and it must stay that way without a token budget attached.
    # Groq's free tier is ~100k tokens/day and already near ~87k; routing even
    # the admitted subset of ~1,900 catalog items through extractor.py would
    # starve the Telegram pipeline, which is the core product. Web sources are
    # structured enough to build a DTO deterministically (see to_dto.py).
    WEB_INGEST_USE_LLM: bool = False

    # Daily digest (src/routines/daily_digest.py) — surfaces the best pending
    # opportunities once a day instead of leaving the whole queue to manual
    # browsing. Score is src/core/scoring.py's 0-100 (coolness + fit).
    DIGEST_MIN_SCORE: int = 90
    AUTO_APPROVE_SCORE: int = 95
    DAILY_DIGEST_SIZE: int = 5
    # Ceiling on actual channel posts per day, enforced in
    # publisher/scheduler.py regardless of whether a row was auto-approved
    # today or approved manually on an earlier day.
    DAILY_PUBLISH_CAP: int = 7

    # Feature flags
    ENABLE_EMBEDDING_DEDUP: bool = False
    SIMILARITY_THRESHOLD: float = 0.92

    # Environment
    ENVIRONMENT: str = "production"
    LOCAL_DEV: bool = False  # set to true to use fakeredis (no Redis server needed)

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list) -> list[int]:
        if isinstance(v, list):
            return v
        import json
        return json.loads(v)

    @field_validator("DEST_CHANNEL_ID_HACKATHON", mode="before")
    @classmethod
    def blank_channel_to_off(cls, v: str | int | None) -> str | int:
        # A missing ${{ secrets.X }} expands to the EMPTY STRING in GitHub
        # Actions and the env var is still set, so pydantic gets int("") and
        # Settings() raises at boot — killing every batch and drain run, not
        # just this feature. Coerce blank back to the "off" sentinel so the
        # workflow env lines can merge before the secret exists.
        if v is None or (isinstance(v, str) and not v.strip()):
            return 0
        return v

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def force_async_driver(cls, v: str) -> str:
        # Managed hosts (Neon, Supabase, Railway, Heroku) inject a plain
        # postgresql:// URL, which SQLAlchemy resolves to the sync psycopg2 driver
        # and then rejects under create_async_engine.
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)

        if "+asyncpg" not in v or "?" not in v:
            return v

        # asyncpg takes none of libpq's query params: sslmode=require (Neon's
        # default) raises TypeError at connect time. Translate it to the driver's
        # own `ssl` arg and drop the rest.
        base, _, query = v.partition("?")
        keep: list[str] = []
        for part in query.split("&"):
            if not part:
                continue
            key, _, value = part.partition("=")
            if key == "sslmode":
                if value not in ("disable", "allow"):
                    keep.append("ssl=require")
            elif key in ("channel_binding", "options", "target_session_attrs"):
                continue  # libpq-only, unsupported by asyncpg
            else:
                keep.append(part)

        return f"{base}?{'&'.join(keep)}" if keep else base
