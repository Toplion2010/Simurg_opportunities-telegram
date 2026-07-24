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

    # Destination channels — audience-based routing (school vs university)
    DEST_CHANNEL_ID_SCHOOL: int
    DEST_CHANNEL_ID_UNIVERSITY: int

    # LLM — Groq (primary) or OpenAI-compatible
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # OpenAI — used only for embeddings when ENABLE_EMBEDDING_DEDUP=true
    OPENAI_API_KEY: str = ""
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"

    # Gemini — live per-post card background generation (image_gen.py)
    GEMINI_API_KEY: str = ""
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image"

    # Database
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 10

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    DEDUP_TTL_SECONDS: int = 2_592_000  # 30 days

    # Processing
    PROCESSOR_INTERVAL_SECONDS: int = 30
    PUBLISHER_POLL_SECONDS: int = 60

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
