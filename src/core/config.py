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

    # Operator's profile for the extractor's relevance rating — tunable without
    # touching extractor.py. Kept short: it lands in every extraction prompt and
    # counts against the Groq free-tier token budget (see MAX_MESSAGES_PER_RUN).
    RELEVANCE_PROFILE: str = (
        "computer science, software engineering, AI/ML, data science, hackathons, "
        "competitive programming, math and logic olympiads, robotics, "
        "entrepreneurship, startups, business and product"
    )

    # Background library
    BACKGROUNDS_DIR: str = "backgrounds"
    BACKGROUND_REFRESH_SECONDS: int = 300
    BACKGROUND_HISTORY_SIZE: int = 20

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
