"""
Tochka Bank Acquiring — Payment Link API.

API: https://enter.tochka.com/uapi/acquiring/v1.0
Docs: https://developers.tochka.com/docs/tochka-api/opisanie-metodov/platyozhnye-ssylki

Flow:
  1. create_payment_link(amount_rub, purpose) -> {operationId, paymentLink}
  2. User pays via paymentLink (card or SBP)
  3. check_payment_status(operationId) -> {status, amount}
  4. On APPROVED -> credit tokens/cases
"""

import logging
import httpx
import asyncio
from app.config import get_settings

logger = logging.getLogger("app.services.tochka")

BASE_URL = "https://enter.tochka.com/uapi/acquiring/v1.0"
TOKEN_URL = "https://enter.tochka.com/connect/token"

# ── Token Management ──────────────────────────────────────

_cached_token: str | None = None
_REDIS_KEY_ACCESS = "tochka:access_token"
_REDIS_KEY_REFRESH = "tochka:refresh_token"


async def _get_redis():
    from app.services.redis_stream import get_redis
    return await get_redis()


async def _refresh_token() -> str:
    """Refresh access_token using refresh_token via OAuth.
    Stores both tokens in Redis to survive app restarts."""
    s = get_settings()
    # Get refresh_token from Redis first, fallback to .env
    try:
        r = await _get_redis()
        stored_refresh = await r.get(_REDIS_KEY_REFRESH)
        if stored_refresh:
            refresh_tok = stored_refresh
            logger.info("[TOCHKA] Using refresh_token from Redis")
        else:
            refresh_tok = s.tochka_refresh_token
            logger.info("[TOCHKA] Using refresh_token from .env (first run)")
    except Exception:
        refresh_tok = s.tochka_refresh_token

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_URL, data={
            "client_id": s.tochka_client_id,
            "client_secret": s.tochka_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
        })
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        global _cached_token
        _cached_token = token

        # Save BOTH tokens to Redis (survives restart)
        new_refresh = data.get("refresh_token", refresh_tok)
        try:
            r = await _get_redis()
            await r.set(_REDIS_KEY_ACCESS, token, ex=86400)
            await r.set(_REDIS_KEY_REFRESH, new_refresh)
            logger.info("[TOCHKA] Tokens saved to Redis: access=%s refresh=%s", token[:8], new_refresh[:8])
        except Exception as re:
            logger.error("[TOCHKA] Failed to save to Redis: %s", re)

        # Also update in-memory settings
        s.tochka_access_token = token
        s.tochka_refresh_token = new_refresh
        logger.info("[TOCHKA] Access token refreshed OK")
        return token


def _update_env(key: str, value: str):
    """Update a key in .env file."""
    import os
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


async def get_token() -> str:
    """Get current access token, refresh if needed."""
    global _cached_token
    if _cached_token:
        return _cached_token
    # Check Redis for cached token
    try:
        r = await _get_redis()
        stored = await r.get(_REDIS_KEY_ACCESS)
        if stored:
            _cached_token = stored
            return stored
    except Exception:
        pass
    s = get_settings()
    if s.tochka_access_token:
        _cached_token = s.tochka_access_token
        return _cached_token
    return await _refresh_token()


async def _request(method: str, path: str, **kwargs) -> dict:
    """Make authenticated API request, auto-refresh on 401.
    Retries once on transient network errors (ConnectError, ReadTimeout, ConnectTimeout)."""
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{BASE_URL}{path}"

    last_err = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(method, url, headers=headers, **kwargs)

                if resp.status_code in (401, 403):
                    logger.info(f"[TOCHKA] {resp.status_code}, refreshing token...")
                    token = await _refresh_token()
                    headers["Authorization"] = f"Bearer {token}"
                    resp = await client.request(method, url, headers=headers, **kwargs)

                resp.raise_for_status()
                return resp.json()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_err = e
            if attempt == 0:
                wait = 1.0 + attempt * 1.0
                logger.warning(f"[TOCHKA] Network error on attempt {attempt+1}, retrying in {wait}s: {type(e).__name__} {e!r}")
                await asyncio.sleep(wait)
            else:
                logger.error(f"[TOCHKA] Network error after {attempt+1} attempts: {type(e).__name__} {e!r}")
        except httpx.HTTPStatusError as e:
            # 401/403 already handled above via token refresh, but if refresh
            # didn't help, re-raise with full context.
            raise
    raise last_err


# ── Payment Operations ────────────────────────────────────

async def create_payment_link(
    amount_rub: float,
    purpose: str,
    redirect_url: str | None = None,
    fail_redirect_url: str | None = None,
    webhook_url: str | None = None,
) -> dict:
    """
    Create payment link (card + SBP).

    Returns: {"operationId": "...", "paymentLink": "https://merch.tochka.com/..."}
    """
    s = get_settings()
    # Staging-safe fallback: if Tochka credentials are not configured,
    # return a mock link instead of touching real merchant.
    if not all([
        (s.tochka_client_id or "").strip(),
        (s.tochka_client_secret or "").strip(),
        (s.tochka_customer_code or "").strip(),
        (s.tochka_merchant_id or "").strip(),
    ]):
        op = f"STAGING_MOCK_{int(amount_rub * 100)}"
        logger.warning("[TOCHKA] Missing credentials, returning mock payment link op=%s", op)
        return {
            "operationId": op,
            "paymentLink": "#",
            "status": "MOCK",
        }

    body = {
        "Data": {
            "amount": amount_rub,
            "customerCode": s.tochka_customer_code,
            "merchantId": s.tochka_merchant_id,
            "purpose": purpose,
            "paymentMode": ["sbp", "card"],
        }
    }
    if redirect_url:
        body["Data"]["redirectUrl"] = redirect_url
    if fail_redirect_url:
        body["Data"]["failRedirectUrl"] = fail_redirect_url
    if webhook_url:
        body["Data"]["webhookUrl"] = webhook_url

    try:
        data = await _request("POST", "/payments", json=body)
    except httpx.HTTPStatusError:
        # Backward-compatible fallback: if account rejects webhookUrl,
        # retry creating the payment link without webhook field.
        if webhook_url:
            body["Data"].pop("webhookUrl", None)
            logger.warning("[TOCHKA] create /payments rejected webhookUrl, retrying without webhookUrl")
            data = await _request("POST", "/payments", json=body)
        else:
            raise
    result = data.get("Data", {})

    logger.info(
        "[TOCHKA] Payment link created: op=%s amount=%.2f purpose=%s",
        result.get("operationId", "?")[:8], amount_rub, purpose[:50],
    )
    return {
        "operationId": result["operationId"],
        "paymentLink": result["paymentLink"],
        "status": result.get("status", "CREATED"),
    }


async def check_payment_status(operation_id: str) -> dict:
    """
    Check payment status.

    Returns: {"status": "APPROVED"|"CREATED"|"REJECTED"|..., "amount": 350.0}
    Status mapping:
      CREATED -> pending
      APPROVED -> paid
      REJECTED -> failed
      REFUNDED -> refunded
    """
    data = await _request("GET", f"/payments/{operation_id}")
    # Tochka returns Data.Operation[0], not Data directly
    operations = data.get("Data", {}).get("Operation", [])
    result = operations[0] if operations else data.get("Data", {})
    logger.info("[TOCHKA] Full payment response: %s", result)

    raw_status = result.get("status", "UNKNOWN")
    mapped = {
        "CREATED": "pending",
        "APPROVED": "paid",
        "REJECTED": "failed",
        "REFUNDED": "refunded",
        "REFUNDED_PARTIALLY": "refunded",
    }.get(raw_status, "pending")

    return {
        "status": mapped,
        "raw_status": raw_status,
        "amount": result.get("amount", 0),
        "operationId": operation_id,
    }


async def refund_payment(operation_id: str, amount_rub: float | None = None) -> dict:
    """Refund payment (full or partial)."""
    body = {"Data": {}}
    if amount_rub is not None:
        body["Data"]["amount"] = amount_rub

    data = await _request("POST", f"/payments/{operation_id}/refund", json=body)
    result = data.get("Data", {})
    logger.info("[TOCHKA] Refund: op=%s amount=%s", operation_id[:8], amount_rub)
    return result
