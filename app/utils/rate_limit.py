"""
Rate limiter на Redis для защиты чувствительных эндпоинтов.
Используется для: активации инвайтов, логина, сброса пароля.

При недоступности Redis — используется in-memory fallback (per-worker).
"""

import logging
import time
from fastapi import Request, HTTPException
import redis.asyncio as aioredis
from app.config import get_settings

logger = logging.getLogger(__name__)

_redis = None

# In-memory fallback: {key: (count, window_start_time)}
_memory_limiter: dict[str, tuple[int, float]] = {}
_memory_blocks: dict[str, float] = {}  # key → unblock_time
_last_cleanup = 0.0
_CLEANUP_INTERVAL = 300  # 5 минут


def _memory_cleanup():
    """Удаляет просроченные записи из in-memory fallback, вызывается не чаще чем раз в 5 минут."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    # Чистим блокировки
    expired_blocks = [k for k, v in _memory_blocks.items() if now >= v]
    for k in expired_blocks:
        del _memory_blocks[k]
    # Чистим счётчики старше 1 часа (макс window в приложении)
    expired_limits = [k for k, (_, start) in _memory_limiter.items() if now - start > 3600]
    for k in expired_limits:
        del _memory_limiter[k]


async def get_redis():
    global _redis
    if _redis is None:
        s = get_settings()
        _redis = aioredis.from_url(s.redis_url, decode_responses=True)
    return _redis


def _check_memory_fallback(
    key: str,
    max_attempts: int,
    window_seconds: int,
    block_seconds: int,
) -> tuple[bool, int]:
    """In-memory rate limiter (per-worker fallback). Не точный, но лучше чем ничего."""
    _memory_cleanup()
    now = time.monotonic()

    # Проверяем блокировку
    if key in _memory_blocks:
        if now < _memory_blocks[key]:
            remaining_secs = int(_memory_blocks[key] - now)
            raise HTTPException(
                429,
                f"Слишком много попыток. Повторите через {remaining_secs // 60 + 1} мин."
            )
        else:
            del _memory_blocks[key]

    # Инкремент
    if key in _memory_limiter:
        count, window_start = _memory_limiter[key]
        if now - window_start > window_seconds:
            # Окно истекло — сброс
            _memory_limiter[key] = (1, now)
            return True, max_attempts - 1
        count += 1
        _memory_limiter[key] = (count, window_start)
    else:
        _memory_limiter[key] = (1, now)
        count = 1

    remaining = max(0, max_attempts - count)

    if count > max_attempts:
        if block_seconds > 0:
            _memory_blocks[key] = now + block_seconds
        raise HTTPException(
            429,
            f"Слишком много попыток. Повторите через {block_seconds // 60 + 1} мин."
        )

    return True, remaining


async def check_rate_limit(
    key: str,
    max_attempts: int,
    window_seconds: int,
    block_seconds: int = 0,
) -> tuple[bool, int]:
    """
    Проверяет и инкрементит счётчик попыток.

    Returns: (allowed: bool, remaining: int)

    Если block_seconds > 0 и лимит превышен — блокирует на block_seconds.
    Если Redis недоступен — используется in-memory fallback.
    """
    try:
        r = await get_redis()
    except Exception:
        logger.warning(f"Redis unavailable for rate limit check: {key}, using memory fallback")
        return _check_memory_fallback(key, max_attempts, window_seconds, block_seconds)

    try:
        # Проверяем блокировку
        block_key = f"blocked:{key}"
        if await r.exists(block_key):
            ttl = await r.ttl(block_key)
            raise HTTPException(
                429,
                f"Слишком много попыток. Повторите через {ttl // 60 + 1} мин."
            )

        # Инкрементим счётчик
        count_key = f"ratelimit:{key}"
        pipe = r.pipeline()
        pipe.incr(count_key)
        pipe.expire(count_key, window_seconds)
        results = await pipe.execute()
        count = results[0]

        remaining = max(0, max_attempts - count)

        if count > max_attempts:
            # Блокируем
            if block_seconds > 0:
                await r.setex(block_key, block_seconds, "1")
            raise HTTPException(
                429,
                f"Слишком много попыток. Повторите через {block_seconds // 60 + 1} мин."
            )

        return True, remaining

    except HTTPException:
        raise  # пробрасываем 429
    except Exception:
        logger.warning(f"Redis error during rate limit check: {key}, using memory fallback", exc_info=True)
        return _check_memory_fallback(key, max_attempts, window_seconds, block_seconds)


def get_client_ip(request: Request) -> str:
    """Извлекает IP клиента. Приоритет: X-Real-IP (от nginx) > X-Forwarded-For > connection IP."""
    # X-Real-IP устанавливается nginx и не может быть подделан клиентом
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    # Fallback на X-Forwarded-For (первый IP в цепочке)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
