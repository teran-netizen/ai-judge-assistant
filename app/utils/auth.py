from datetime import datetime, timedelta, timezone
import logging

from jose import jwt, JWTError

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

JWT_ISSUER = "ai-judge"
JWT_AUDIENCE = "ai-judge-api"


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {
            "sub": user_id,
            "iat": int(now.timestamp()),
            "exp": expire,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> str | None:
    """Returns user_id (sub) or None if invalid/expired. Kept for callers that
    only need the user id; new callers should prefer decode_access_token_full."""
    payload = decode_access_token_full(token)
    return payload.get("sub") if payload else None


def decode_access_token_full(token: str) -> dict | None:
    """Returns full decoded payload or None if invalid/expired."""
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
    except JWTError:
        return None


async def is_token_revoked(user_id: str, iat: int) -> bool:
    """True if token was issued before user's most recent logout (revocation).

    Fail-open on Redis errors: auth must keep working during Redis outages.
    Tradeoff: logout has a window equal to outage duration during which
    revoked tokens still pass. Acceptable given Redis has its own HA."""
    try:
        from app.services.redis_stream import get_redis
        r = await get_redis()
        val = await r.get(f"jwt:revoke:{user_id}")
        if val is None:
            return False
        revoke_ts = int(val)
        return iat < revoke_ts
    except Exception as e:
        logger.warning("jwt revoke check failed (fail-open): %s", e)
        return False


def decode_internal_jwt(token: str) -> dict | None:
    """Decode a service-to-service JWT issued by widget-backend for ai-judge.

    Uses INTERNAL_API_SECRET if configured, falls back to main secret_key.
    Verifies iss='widget-backend', aud='ai-judge'.
    """
    secret = settings.internal_api_secret or settings.secret_key
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            audience="ai-judge",
            issuer="widget-backend",
        )
    except JWTError as e:
        logger.warning("internal JWT decode failed: %s", e)
        return None


async def revoke_user_tokens(user_id: str) -> None:
    """Marks all current user tokens as revoked (typically called on logout).

    Stores current UTC timestamp at jwt:revoke:{user_id} with TTL slightly
    longer than max JWT lifetime so the marker outlasts any issued token."""
    try:
        from app.services.redis_stream import get_redis
        r = await get_redis()
        now_ts = int(datetime.now(timezone.utc).timestamp()) + 1  # +1: any token with iat <= wall-clock-now is considered issued before logout
        ttl = (settings.jwt_expire_minutes + 1440) * 60  # jwt expire + 1 day
        await r.set(f"jwt:revoke:{user_id}", now_ts, ex=ttl)
    except Exception as e:
        logger.error("jwt revoke set failed: %s", e)
        # swallow — logout cookie clear must still succeed
