import json
from typing import Any

import redis.asyncio as aioredis

from src.core.config import Settings

_redis_pool: aioredis.Redis | None = None

QUEUE_KEY = "simurg:queue"
DEDUP_PREFIX = "simurg:dedup:"
EMBED_VECTORS_KEY = "simurg:embed_vectors"


async def init_redis(settings: Settings) -> aioredis.Redis:
    global _redis_pool
    if settings.LOCAL_DEV:
        import fakeredis.aioredis as fakeredis
        _redis_pool = fakeredis.FakeRedis(decode_responses=True)
    else:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await _redis_pool.ping()
    return _redis_pool


def get_redis() -> aioredis.Redis:
    if _redis_pool is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis_pool


async def enqueue_message(redis: aioredis.Redis, payload: dict[str, Any]) -> None:
    await redis.rpush(QUEUE_KEY, json.dumps(payload))


async def dequeue_batch(redis: aioredis.Redis, n: int = 10) -> list[dict[str, Any]]:
    items = await redis.lpop(QUEUE_KEY, n)
    if not items:
        return []
    return [json.loads(item) for item in items]


async def is_duplicate(redis: aioredis.Redis, hash_key: str, ttl: int) -> bool:
    full_key = DEDUP_PREFIX + hash_key
    result = await redis.set(full_key, "1", nx=True, ex=ttl)
    return result is None  # None means key already existed


async def store_hash(redis: aioredis.Redis, hash_key: str, ttl: int) -> None:
    full_key = DEDUP_PREFIX + hash_key
    await redis.set(full_key, "1", ex=ttl)


async def store_embedding_vector(
    redis: aioredis.Redis, vector: list[float], max_vectors: int = 1000
) -> None:
    await redis.rpush(EMBED_VECTORS_KEY, json.dumps(vector))
    await redis.ltrim(EMBED_VECTORS_KEY, -max_vectors, -1)


async def get_embedding_vectors(redis: aioredis.Redis) -> list[list[float]]:
    items = await redis.lrange(EMBED_VECTORS_KEY, 0, -1)
    return [json.loads(item) for item in items]
