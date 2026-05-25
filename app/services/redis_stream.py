"""Redis-based streaming for case generation pipeline.

Uses Redis LIST + PUBSUB dual approach:
- LIST stores chunks durably for catch-up on reconnect
- PUBSUB provides real-time notification for SSE clients

P1: connection pool (max_connections=50) — previously one shared client
    bottlenecked under concurrent SSE load.
P9: STREAM_TTL bumped from 1h to 24h — user returning to a half-done case
    after a few hours still sees catch-up data instead of empty state.
"""
import logging
import redis.asyncio as aioredis
from app.config import get_settings
from app.services.sse_contract import (
    DONE_MARKER,
    ERROR_PREFIX,
    encode_event_payload,
)

logger = logging.getLogger(__name__)
_redis = None

CHUNK_LIST_KEY = "stream:chunks:{case_id}"
STATUS_KEY = "stream:status:{case_id}"
ERROR_KEY = "stream:error:{case_id}"
FULL_TEXT_KEY = "stream:full:{case_id}"
CHANNEL_KEY = "channel:case:{case_id}"
STREAM_TTL = 24 * 3600  # 24 hours (P9: survives long user sessions)
REDIS_POOL_SIZE = 50    # P1: upper bound on concurrent Redis ops


async def get_redis():
    """Return a shared Redis client backed by a connection pool."""
    global _redis
    if _redis is None:
        s = get_settings()
        _redis = aioredis.from_url(
            s.redis_url,
            decode_responses=True,
            max_connections=REDIS_POOL_SIZE,
            health_check_interval=30,
        )
    return _redis


async def get_stream_chunks_from(case_id: str, start: int = 0) -> list:
    """P2: read chunks from offset `start` only (default 0 = full list).

    Used by /stream on reconnect with last_event_id > 0 so we don't
    re-read the entire list on every catch-up.
    """
    try:
        r = await get_redis()
        items = await r.lrange(CHUNK_LIST_KEY.format(case_id=case_id), start, -1)
        return items or []
    except Exception as e:
        logger.warning(f"Redis get_stream_chunks_from failed for {case_id}: {e}")
        return []


async def publish_chunk(case_id: str, chunk: str):
    """Append chunk to Redis list + publish to pubsub channel."""
    try:
        r = await get_redis()
        list_key = CHUNK_LIST_KEY.format(case_id=case_id)
        channel = CHANNEL_KEY.format(case_id=case_id)
        pipe = r.pipeline()
        pipe.rpush(list_key, chunk)
        pipe.expire(list_key, STREAM_TTL)
        pipe.publish(channel, chunk)
        await pipe.execute()
    except Exception as e:
        logger.warning(f"Redis publish_chunk failed for {case_id}: {e}")


async def publish_event(case_id: str, event: dict):
    """Publish strictly validated SSE event payload."""
    try:
        payload = encode_event_payload(event)
    except Exception as e:
        logger.error("SSE contract violation case=%s event=%s err=%s", case_id[:8], event, e)
        return
    await publish_chunk(case_id, payload)


async def _set_stream_status_strict(case_id: str, status: str, error: str = None, full_text: str = None):
    """Strict status publisher used by SSE contract (v2)."""
    try:
        r = await get_redis()
        pipe = r.pipeline()
        status_key = STATUS_KEY.format(case_id=case_id)
        channel = CHANNEL_KEY.format(case_id=case_id)

        pipe.set(status_key, status)
        pipe.expire(status_key, STREAM_TTL)

        if status == "error" and error:
            error_key = ERROR_KEY.format(case_id=case_id)
            pipe.set(error_key, error[:500])
            pipe.expire(error_key, STREAM_TTL)
            pipe.publish(channel, f"{ERROR_PREFIX}{error[:500]}")
        elif status == "completed":
            pipe.publish(channel, DONE_MARKER)
        elif status == "batch_done":
            payload = encode_event_payload({"type": "batch_done", "stage_label": "\u0413\u043e\u0442\u043e\u0432\u043e"})
            # Make batch_done durable: rpush into the chunks list so
            # reconnecting SSE clients can replay it via catch-up.
            list_key = CHUNK_LIST_KEY.format(case_id=case_id)
            pipe.rpush(list_key, payload)
            pipe.expire(list_key, STREAM_TTL)
            pipe.publish(channel, payload)

        await pipe.execute()
    except Exception as e:
        logger.warning(f"Redis strict set_stream_status failed for {case_id}: {e}")


# Use strict variant everywhere without changing import paths.
set_stream_status = _set_stream_status_strict


async def get_stream_state(case_id: str, chunks_from: int = 0) -> dict:
    """Get current stream state for catch-up.

    P2: `chunks_from` lets the SSE /stream endpoint skip chunks the client
    already confirmed via last_event_id — on reconnects with seq=N, we only
    read chunks[N:] instead of the entire list.

    Returns a dict with keys status, chunks, error, total_chunks — the last
    one is the absolute list length so callers can track a global cursor.
    """
    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.get(STATUS_KEY.format(case_id=case_id))
        pipe.lrange(CHUNK_LIST_KEY.format(case_id=case_id), chunks_from, -1)
        pipe.get(ERROR_KEY.format(case_id=case_id))
        pipe.llen(CHUNK_LIST_KEY.format(case_id=case_id))
        status, chunks, error, total_chunks = await pipe.execute()
        return {
            "status": status,
            "chunks": chunks or [],
            "error": error,
            "total_chunks": total_chunks or 0,
        }
    except Exception as e:
        logger.warning(f"Redis get_stream_state failed for {case_id}: {e}")
        return {"status": None, "chunks": [], "error": None, "total_chunks": 0}


async def cleanup_stream(case_id: str):
    """Delete all stream keys for a case."""
    try:
        r = await get_redis()
        keys = [
            CHUNK_LIST_KEY.format(case_id=case_id),
            STATUS_KEY.format(case_id=case_id),
            ERROR_KEY.format(case_id=case_id),
            FULL_TEXT_KEY.format(case_id=case_id),
        ]
        await r.delete(*keys)
    except Exception as e:
        logger.warning(f"Redis cleanup_stream failed for {case_id}: {e}")
