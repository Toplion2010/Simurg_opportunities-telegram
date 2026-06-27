import hashlib
import re

import redis.asyncio as aioredis

from src.core.config import Settings
from src.core.exceptions import DuplicateError
from src.core.logging import get_logger
from src.core.redis_client import (
    get_embedding_vectors,
    is_duplicate,
    store_embedding_vector,
    store_hash,
)
from src.processor.extractor import FieldExtractor, OpportunityDTO

logger = get_logger(__name__)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", "", text.lower().strip())


class Deduplicator:
    def __init__(
        self,
        redis: aioredis.Redis,
        settings: Settings,
        extractor: FieldExtractor,
    ) -> None:
        self._redis = redis
        self._settings = settings
        self._extractor = extractor

    def make_hash(self, dto: OpportunityDTO) -> str:
        raw = (_normalize(dto.title) + _normalize(dto.apply_link)).encode()
        return hashlib.sha256(raw).hexdigest()

    async def check(self, dto: OpportunityDTO) -> bool:
        """Returns True if this is a duplicate."""
        hash_key = self.make_hash(dto)
        if await is_duplicate(self._redis, hash_key, self._settings.DEDUP_TTL_SECONDS):
            logger.info("duplicate_detected_hash", title=dto.title)
            return True

        if self._settings.ENABLE_EMBEDDING_DEDUP and dto.rewritten_text:
            try:
                if await self._embedding_check(dto.rewritten_text):
                    logger.info("duplicate_detected_embedding", title=dto.title)
                    return True
            except Exception:
                logger.exception("embedding_dedup_error")

        return False

    async def store(self, dto: OpportunityDTO) -> None:
        hash_key = self.make_hash(dto)
        await store_hash(self._redis, hash_key, self._settings.DEDUP_TTL_SECONDS)

        if self._settings.ENABLE_EMBEDDING_DEDUP and dto.rewritten_text:
            try:
                vector = await self._extractor.get_embedding(
                    dto.rewritten_text, self._settings.OPENAI_EMBED_MODEL
                )
                await store_embedding_vector(self._redis, vector)
            except Exception:
                logger.exception("embedding_store_error")

    async def _embedding_check(self, text: str) -> bool:
        import numpy as np

        vector = await self._extractor.get_embedding(
            text, self._settings.OPENAI_EMBED_MODEL
        )
        stored_vectors = await get_embedding_vectors(self._redis)

        if not stored_vectors:
            return False

        v = np.array(vector, dtype=np.float32)
        for stored in stored_vectors:
            s = np.array(stored, dtype=np.float32)
            cosine_sim = float(np.dot(v, s) / (np.linalg.norm(v) * np.linalg.norm(s) + 1e-9))
            if cosine_sim >= self._settings.SIMILARITY_THRESHOLD:
                return True
        return False
