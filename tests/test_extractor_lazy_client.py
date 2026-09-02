"""FieldExtractor must be constructible without an LLM key.

PipelineFactory builds a FieldExtractor unconditionally, and
openai.AsyncOpenAI() raises at construction when no api_key is set. That made a
Groq key mandatory for every caller that merely *constructs* the pipeline —
including the web collector, which supplies already structured DTOs and never
calls extract(). Caught by a live webscan run failing with
"openai.OpenAIError: Missing credentials" after the scrape had already
succeeded.
"""
import pytest

from src.core.config import Settings
from src.processor.extractor import FieldExtractor

BASE_ENV = dict(
    BOT_TOKEN="x",
    TELETHON_API_ID=1,
    TELETHON_API_HASH="x",
    DEST_CHANNEL_ID_SCHOOL=-100,
    DEST_CHANNEL_ID_UNIVERSITY=-101,
    DATABASE_URL="postgresql+asyncpg://u:p@h/db",
)


def test_constructs_with_no_groq_key():
    extractor = FieldExtractor(Settings(GROQ_API_KEY="", **BASE_ENV))
    assert extractor._llm_client_instance is None


def test_client_is_built_on_first_access_and_reused():
    extractor = FieldExtractor(Settings(GROQ_API_KEY="test-key", **BASE_ENV))
    assert extractor._llm_client_instance is None
    client = extractor._llm_client
    assert extractor._llm_client_instance is client
    assert extractor._llm_client is client


def test_missing_key_still_raises_when_the_llm_is_actually_used():
    # The key is a requirement of USING the LLM, not of importing it. It must
    # not silently degrade into a broken client.
    extractor = FieldExtractor(Settings(GROQ_API_KEY="", **BASE_ENV))
    with pytest.raises(Exception):
        _ = extractor._llm_client


def test_pipeline_factory_builds_without_any_llm_key():
    """The web collector's exact path: build the whole factory, no Groq key,
    no Redis."""
    from src.processor.worker import build_pipeline

    factory = build_pipeline(Settings(GROQ_API_KEY="", **BASE_ENV), None, None)
    assert factory._extractor is not None
