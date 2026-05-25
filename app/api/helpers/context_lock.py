"""Redis-based distributed lock for case context processing."""
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

_CONTEXT_LOCK_TTL = 60 * 10  # 10 minutes


def _context_lock_key(case_id: str) -> str:
    return f"lock:case:{case_id}:context"


async def acquire_context_lock(case_id: str) -> str | None:
    """Acquire distributed lock. Returns token on success, None if already locked."""
    from app.services.redis_stream import get_redis
    token = uuid4().hex
    try:
        r = await get_redis()
        ok = await r.set(_context_lock_key(case_id), token, ex=_CONTEXT_LOCK_TTL, nx=True)
        if ok:
            logger.info("[LOCK] ACQUIRED case=%s ttl=%ds", case_id[:8], _CONTEXT_LOCK_TTL)
        else:
            logger.warning("[LOCK] BLOCKED case=%s (already locked)", case_id[:8])
        return token if ok else None
    except Exception as e:
        logger.warning("context lock acquire failed case=%s: %s", case_id, e)
        return token  # fallback: allow if Redis is down


async def context_lock_exists(case_id: str) -> bool:
    """Check if lock exists (non-blocking)."""
    from app.services.redis_stream import get_redis
    try:
        r = await get_redis()
        return bool(await r.exists(_context_lock_key(case_id)))
    except Exception as e:
        logger.warning("context lock exists check failed case=%s: %s", case_id, e)
        return False


async def release_context_lock(case_id: str, token: str | None) -> None:
    """Release lock only if we own it (token matches)."""
    if not token:
        return
    from app.services.redis_stream import get_redis
    try:
        r = await get_redis()
        key = _context_lock_key(case_id)
        current = await r.get(key)
        if current == token:
            await r.delete(key)
            logger.info("[LOCK] RELEASED case=%s", case_id[:8])
        else:
            logger.warning("[LOCK] RELEASE FAILED case=%s (token mismatch)", case_id[:8])
    except Exception as e:
        logger.warning("context lock release failed case=%s: %s", case_id, e)
