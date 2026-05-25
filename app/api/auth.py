import re
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
import httpx
import uuid as _uuid

from app.database import get_db
from app.models import User
from pydantic import BaseModel, Field
from app.schemas import UserProfile, SetNickname, OAuthCallback
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.auth import create_access_token, decode_access_token_full, revoke_user_tokens

_logout_bearer = HTTPBearer(auto_error=False)
from app.utils.deps import get_current_user
from app.config import get_settings
from app.api.helpers.activity import log_activity

from app.utils.datetime import utcnow_naive
logger = logging.getLogger(__name__)

def _validate_redirect_uri(redirect_uri: str | None, provider: str) -> str:
    """Валидирует redirect_uri — только наш домен."""
    settings = get_settings()
    allowed = {
        f"{settings.domain}/auth/callback?provider=yandex",
        f"{settings.domain}/auth/vk-callback",
    }
    if settings.debug:
        allowed |= {
            "http://localhost:3000/auth/callback?provider=yandex",
            "http://localhost:3000/auth/vk-callback",
            "http://localhost:5173/auth/callback?provider=yandex",
            "http://localhost:5173/auth/vk-callback",
        }
    default_uris = {
        "yandex": f"{settings.domain}/auth/callback?provider=yandex",
        "vk": f"{settings.domain}/auth/vk-callback",
    }
    default = default_uris.get(provider, f"{settings.domain}/auth/callback?provider={provider}")
    if not redirect_uri:
        return default
    if redirect_uri not in allowed:
        return default  # игнорируем невалидный, используем дефолтный
    return redirect_uri


# Shared httpx client — reuses TCP+TLS connections (saves ~150ms per auth)
_http_client: httpx.AsyncClient | None = None

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
    return _http_client

router = APIRouter(prefix="/api/auth", tags=["auth"])
s = get_settings()


async def _set_auth_cookie_with_refresh(response: JSONResponse, token: str, user_id: str) -> str:
    """Set HttpOnly auth cookie + generate refresh token stored in Redis (90 days)."""
    response.set_cookie(
        key="access_token", value=token, httponly=True,
        secure=not s.debug, samesite="lax",
        max_age=s.jwt_expire_minutes * 60, path="/",
    )
    refresh = _uuid.uuid4().hex + _uuid.uuid4().hex
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(s.redis_url, decode_responses=True)
        await r.set(f"refresh:{refresh}", user_id, ex=90 * 86400)
        await r.aclose()
    except Exception:
        pass
    return refresh


def _set_auth_cookie(response: JSONResponse, token: str) -> None:
    """Set HttpOnly auth cookie on the response."""
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=not s.debug,  # HTTPS only in production
        samesite="lax",
        max_age=s.jwt_expire_minutes * 60,
        path="/",
    )


def _parse_source_from_state(state: str | None) -> str | None:
    """Extract UTM/referral source from state.
    Frontend AuthCallback already extracts ref from 'nonce:source' and sends just the source value.
    Fallback: if state still contains ':', take the part after it (legacy format)."""
    if not state:
        return None
    s = state.strip()
    if not s:
        return None
    if ":" in s:
        return s.split(":", 1)[1][:500] or None
    return s[:500]


async def _get_or_create(db: AsyncSession, provider: str, pid: str, email: str | None, name: str | None, source: str | None = None, phone: str | None = None, sex: str | None = None, real_name: str | None = None) -> User:
    if provider == "email":
        user = (await db.execute(select(User).where(User.email == pid))).scalar_one_or_none()
    else:
        col = User.yandex_id if provider == "yandex" else User.vk_id
        user = (await db.execute(select(User).where(col == pid))).scalar_one_or_none()
    if user:
        # Обновляем email/name если раньше не были получены
        if email and not user.email:
            user.email = email
        if name:
            user.name = _to_cyrillic(name) if name else name
        # Обновляем UTM если ранее не был установлен
        if source and not getattr(user, 'utm_source', None):
            user.utm_source = source
        # Обновляем phone, sex, real_name если не были заполнены
        if phone and not user.phone:
            user.phone = phone
        if sex and not user.sex:
            user.sex = sex
        if real_name and not user.real_name:
            user.real_name = real_name
        return user
    user = User(email=email, name=_to_cyrillic(name) if name else name, free_cases_left=0, billing_model="cases", utm_source=source, promo_price=True)
    if provider == "yandex":
        user.yandex_id = pid
    else:
        user.vk_id = pid
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Параллельный OAuth-коллбэк уже создал юзера — откатываем и достаём его
        await db.rollback()
        user = (await db.execute(select(User).where(col == pid))).scalar_one_or_none()
        if user:
            return user
        raise  # что-то другое — пробрасываем

    # Auto-activate invite code if ref matches an invite
    if source:
        ref_code = source.split("&")[0] if "&" in source else source
        try:
            from app.models import InviteCode, InviteActivation
            invite = (await db.execute(
                select(InviteCode).where(InviteCode.code == ref_code, InviteCode.is_active == True)
            )).scalar_one_or_none()
            if invite and invite.activated_count < invite.max_activations:
                user.free_cases_left = (user.free_cases_left or 0) + invite.bonus_free_cases
                user.invite_code_used = invite.code
                invite.activated_count += 1
                db.add(InviteActivation(invite_id=invite.id, user_id=user.id, bonus_tokens=invite.bonus_tokens, bonus_free_cases=invite.bonus_free_cases))
                # Subscription bonus for referral codes
                if invite.label and "7 дней" in invite.label:
                    from datetime import datetime, timezone, timedelta
                    user.subscription_until = datetime.now(timezone.utc) + timedelta(days=7)
                    logger.info("[REFERRAL] user=%s code=%s sub_until=%s", str(user.id)[:8], invite.code, user.subscription_until)
                else:
                    logger.info("[REFERRAL] user=%s code=%s bonus_cases=%d bonus_tokens=%d", str(user.id)[:8], invite.code, invite.bonus_free_cases, invite.bonus_tokens)
                await db.flush()
        except Exception as e:
            logger.warning("Invite auto-activation failed: %s", e)

    # User-to-user referral: if ref looks like user ID prefix and no InviteCode matched
    if source and not user.invite_code_used and not user.referred_by:
        ref_code = source.split("&")[0] if "&" in source else source
        if re.match(r"^[a-f0-9]{8}$", ref_code, re.IGNORECASE):
            try:
                from sqlalchemy import cast, String as SAString
                from app.models import ReferralEvent
                potential = (await db.execute(
                    select(User).where(cast(User.id, SAString).like(ref_code + "%"), User.is_active == True)
                )).scalars().all()
                if len(potential) == 1 and potential[0].id != user.id:
                    referrer = potential[0]
                    user.referred_by = referrer.id
                    db.add(ReferralEvent(referrer_id=referrer.id, referred_id=user.id, status="registered"))
                    logger.info("[REFERRAL-USER] new_user=%s referred_by=%s (%s)", str(user.id)[:8], str(referrer.id)[:8], referrer.name or referrer.email or "?")
                    from app.models import ActivityLog
                    db.add(ActivityLog(
                        user_id=referrer.id,
                        action="referral_signup",
                        details=f"Зарегистрировался по вашей ссылке: {user.name or user.email or str(user.id)[:8]}",
                    ))
                    await db.flush()
                elif len(potential) > 1:
                    logger.warning("[REFERRAL-USER] Multiple users match ref=%s, skipping", ref_code)
            except Exception as e:
                logger.warning("[REFERRAL-USER] Failed: %s", e)

    return user


@router.post("/yandex/callback")
async def yandex_cb(body: OAuthCallback, request: Request, db: AsyncSession = Depends(get_db)):
    from app.utils.rate_limit import check_rate_limit, get_client_ip
    ip = get_client_ip(request)
    await check_rate_limit(f"auth:ip:{ip}", max_attempts=10, window_seconds=300, block_seconds=600)

    code = body.code
    actual_redirect = _validate_redirect_uri(body.redirect_uri, "yandex")
    try:
        c = _get_http_client()
        req_data = {
            "grant_type": "authorization_code", "code": code,
            "client_id": s.yandex_client_id, "client_secret": s.yandex_client_secret,
            "redirect_uri": actual_redirect,
        }
        # PKCE: добавляем verifier если фронт прислал (новые сессии).
        # Старые сессии без verifier продолжают работать через client_secret.
        if body.code_verifier:
            req_data["code_verifier"] = body.code_verifier
        tr = await c.post("https://oauth.yandex.ru/token", data=req_data)
        if tr.status_code != 200:
            raise HTTPException(400, "Ошибка Яндекс OAuth: не удалось получить токен")
        token_data = tr.json()
        if "access_token" not in token_data:
            raise HTTPException(400, "Яндекс не вернул access_token")
        pr = await c.get("https://login.yandex.ru/info", headers={"Authorization": f"OAuth {token_data['access_token']}"})
        p = pr.json()
        if "id" not in p:
            raise HTTPException(400, "Яндекс не вернул профиль пользователя")
    except httpx.HTTPError:
        raise HTTPException(502, "Яндекс OAuth недоступен")
    except (KeyError, ValueError):
        raise HTTPException(502, "Яндекс вернул некорректный ответ")
    logger.info("yandex_callback: raw body.state=%r", body.state)
    _source = _parse_source_from_state(body.state)
    logger.info("yandex_callback: parsed source=%r", _source)
    _yphone = p.get("default_phone", {}).get("number") if isinstance(p.get("default_phone"), dict) else None
    _ysex = p.get("sex")
    _yrname = (p.get("real_name") or (((p.get("first_name") or "") + " " + (p.get("last_name") or "")).strip())) or None
    user = await _get_or_create(db, "yandex", str(p["id"]), p.get("default_email"), p.get("display_name"), source=_source, phone=_yphone, sex=_ysex, real_name=_yrname)
    ip = request.headers.get("x-real-ip", request.client.host if request.client else "")
    await log_activity(db, user.id, "login", details="Yandex OAuth", utm_source=_source, ip_address=ip)
    # GeoIP: determine city and timezone
    await db.commit()
    # GeoIP in background — don't block auth response
    if not user.city:
        _uid = user.id
        async def _bg_geoip():
            try:
                from app.services.geoip import lookup_ip
                from app.database import async_session
                geo = await lookup_ip(ip)
                if geo.get("city"):
                    async with async_session() as s2:
                        u = (await s2.execute(select(User).where(User.id == _uid))).scalar_one_or_none()
                        if u and not u.city:
                            u.city = geo["city"]
                            u.timezone = geo.get("timezone", "")
                            await s2.commit()
                            logger.info("GeoIP bg: user=%s city=%s", str(_uid)[:8], geo["city"])
            except Exception as e:
                logger.warning("GeoIP bg failed: %s", e)
        asyncio.create_task(_bg_geoip())
    _token = create_access_token(str(user.id))
    response = JSONResponse(content={"user_id": str(user.id)})
    _set_auth_cookie(response, _token)
    # Generate refresh_token for localStorage fallback
    _refresh = await _set_auth_cookie_with_refresh(response, _token, str(user.id))
    import json as _j
    response.body = _j.dumps({"user_id": str(user.id), "refresh_token": _refresh}).encode()
    response.headers["content-length"] = str(len(response.body))
    return response


@router.post("/vk/callback")
async def vk_cb(body: OAuthCallback, request: Request, db: AsyncSession = Depends(get_db)):
    from app.utils.rate_limit import check_rate_limit, get_client_ip
    ip = get_client_ip(request)
    await check_rate_limit(f"auth:ip:{ip}", max_attempts=10, window_seconds=300, block_seconds=600)

    code = body.code
    actual_redirect = _validate_redirect_uri(body.redirect_uri, "vk")
    try:
        c = _get_http_client()
        token_data = {
            "grant_type": "authorization_code", "code": code,
            "client_id": s.vk_client_id, "client_secret": s.vk_client_secret,
                "redirect_uri": actual_redirect,
            }
        # PKCE: передаём code_verifier если есть
        if body.code_verifier:
            token_data["code_verifier"] = body.code_verifier
        if body.device_id:
            token_data["device_id"] = body.device_id
        tr = await c.post("https://id.vk.com/oauth2/auth", data=token_data)
        if tr.status_code != 200:
            logger.error("VK token exchange failed: %s %s", tr.status_code, tr.text[:500])
            raise HTTPException(400, "Ошибка VK ID: не удалось получить токен")
        d = tr.json()
        if "access_token" not in d:
            raise HTTPException(400, "VK не вернул access_token")
        user_id_vk = d.get("user_id")
        if not user_id_vk:
            raise HTTPException(400, "VK не вернул user_id")
        ir = await c.post("https://id.vk.com/oauth2/user_info", data={"access_token": d["access_token"], "client_id": s.vk_client_id, "lang": "ru"})
        info = ir.json().get("user", {})
    except httpx.HTTPError:
        raise HTTPException(502, "VK ID недоступен")
    except (KeyError, ValueError):
        raise HTTPException(502, "VK вернул некорректный ответ")
    name = f"{info.get('first_name','')} {info.get('last_name','')}".strip() or None
    logger.info("vk_callback: raw body.state=%r", body.state)
    _source = _parse_source_from_state(body.state)
    logger.info("vk_callback: parsed source=%r", _source)
    user = await _get_or_create(db, "vk", str(user_id_vk), d.get("email"), name, source=_source)
    ip = request.headers.get("x-real-ip", request.client.host if request.client else "")
    await log_activity(db, user.id, "login", details="VK OAuth", utm_source=_source, ip_address=ip)
    await db.commit()
    # GeoIP in background — don't block auth response
    if not user.city:
        _uid = user.id
        async def _bg_geoip():
            try:
                from app.services.geoip import lookup_ip
                from app.database import async_session
                geo = await lookup_ip(ip)
                if geo.get("city"):
                    async with async_session() as s2:
                        u = (await s2.execute(select(User).where(User.id == _uid))).scalar_one_or_none()
                        if u and not u.city:
                            u.city = geo["city"]
                            u.timezone = geo.get("timezone", "")
                            await s2.commit()
                            logger.info("GeoIP bg: user=%s city=%s", str(_uid)[:8], geo["city"])
            except Exception as e:
                logger.warning("GeoIP bg failed: %s", e)
        asyncio.create_task(_bg_geoip())
    _token = create_access_token(str(user.id))
    response = JSONResponse(content={"user_id": str(user.id)})
    _set_auth_cookie(response, _token)
    # Generate refresh_token for localStorage fallback
    _refresh = await _set_auth_cookie_with_refresh(response, _token, str(user.id))
    import json as _j
    response.body = _j.dumps({"user_id": str(user.id), "refresh_token": _refresh}).encode()
    response.headers["content-length"] = str(len(response.body))
    return response


# Dev-login MUST NEVER expose on these hosts, regardless of env flags.
# Defense-in-depth: if DEV_ACCESS_ENABLED is accidentally set true on prod,
# the domain check below still refuses the request.
_DEV_LOGIN_BLOCKED_HOSTS = (
    "example.com",
    "www.example.com",
)


@router.post("/dev-login")
async def dev_login(request: Request, db: AsyncSession = Depends(get_db)):
    """Creates a test user and logs in when debug or explicit dev access is enabled.

    Two-layer gate:
      1. Host header MUST NOT be one of the production domains.
      2. DEBUG or DEV_ACCESS_ENABLED env flag MUST be truthy.
    Both must pass. Domain check is primary defense against an env flag misfire.
    """
    _host = (request.headers.get("host") or "").split(":")[0].lower()
    if any(blocked in _host for blocked in _DEV_LOGIN_BLOCKED_HOSTS):
        raise HTTPException(404, "Not found")
    if not (s.debug or s.dev_access_enabled):
        raise HTTPException(404, "Not found")
    dev_email = (s.dev_access_user_email or "dev@localhost").strip().lower()
    dev_name = (s.dev_access_user_name or "Dev User").strip() or "Dev User"
    user = (await db.execute(select(User).where(User.email == dev_email))).scalar_one_or_none()
    if not user:
        user = User(
            email=dev_email,
            name=dev_name,
            yandex_id="dev_local_001",
            free_cases_left=0, billing_model="cases", promo_price=True,
            
            is_admin=True,
        )
        db.add(user)
        await db.flush()
    try:
        ip = request.headers.get("x-real-ip", request.client.host if request.client else "")
        await log_activity(db, user.id, "login", details="Dev Access Login", ip_address=ip)
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
    _token = create_access_token(str(user.id))
    response = JSONResponse(content={"user_id": str(user.id)})
    _set_auth_cookie(response, _token)
    # Generate refresh_token for localStorage fallback
    _refresh = await _set_auth_cookie_with_refresh(response, _token, str(user.id))
    import json as _j
    response.body = _j.dumps({"user_id": str(user.id), "refresh_token": _refresh}).encode()
    response.headers["content-length"] = str(len(response.body))
    return response


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from datetime import datetime
    try:
        user.last_activity = utcnow_naive()
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
    return user


@router.post("/refresh")
async def refresh_token(request: Request):
    """Exchange refresh_token for new access_token cookie."""
    try:
        body = await request.json()
        refresh = body.get("refresh_token", "")
    except Exception:
        raise HTTPException(400, "Missing refresh_token")
    if not refresh or len(refresh) != 64:
        raise HTTPException(401, "Invalid refresh token")
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(s.redis_url, decode_responses=True)
        user_id = await r.get(f"refresh:{refresh}")
        await r.aclose()
    except Exception:
        raise HTTPException(500, "Redis error")
    if not user_id:
        raise HTTPException(401, "Refresh token expired")
    token = create_access_token(user_id)
    response = JSONResponse(content={"ok": True, "user_id": user_id})
    _set_auth_cookie(response, token)
    return response


@router.post("/logout")
async def logout(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_logout_bearer)):
    """Invalidate session: JWT revoke (iat-cutoff) + refresh-token revoke + cookie clear.

    Three layers revoked:
      1. Access token (JWT cookie) — via revoke_user_tokens (iat-cutoff in Redis)
      2. Refresh token (localStorage + Redis) — DELETEd from Redis
      3. Cookie — cleared client-side

    Refresh token is optionally accepted in POST body {\"refresh_token\": \"...\"}
    so frontend can pass localStorage value when no cookie is present.
    """
    response = JSONResponse(content={"ok": True})
    token = request.cookies.get("access_token")
    if not token and cred:
        token = cred.credentials

    # Revoke access token (JWT iat-cutoff in Redis)
    if token:
        payload = decode_access_token_full(token)
        if payload and payload.get("sub"):
            await revoke_user_tokens(payload["sub"])

    # Revoke refresh token if passed in body
    refresh_token_to_revoke = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            refresh_token_to_revoke = body.get("refresh_token")
    except Exception:
        pass  # no body / not JSON — fine, cookie-only logout

    if refresh_token_to_revoke and isinstance(refresh_token_to_revoke, str) and len(refresh_token_to_revoke) == 64:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(s.redis_url, decode_responses=True)
            await r.delete(f"refresh:{refresh_token_to_revoke}")
            await r.aclose()
        except Exception as e:
            logger.warning("logout: failed to revoke refresh token: %s", e)

    response.delete_cookie("access_token", path="/")
    return response




# ═══════════════════════════════════════════════════════════
# Email OTP authentication
# ═══════════════════════════════════════════════════════════

class _OTPSendRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)

class _OTPVerifyRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    code: str = Field(min_length=4, max_length=8)
    state: str | None = None  # UTM source


@router.post("/otp/send")
async def otp_send(body: _OTPSendRequest, request: Request):
    """Send OTP code to email."""
    import random
    import redis.asyncio as aioredis

    email = body.email.strip().lower()
    if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
        raise HTTPException(400, "Некорректный email")

    # Rate limit: 3 sends per 10 min per email
    r = aioredis.from_url(s.redis_url, decode_responses=True)
    try:
        # Rate limit by IP: 5 sends per 10 min
        ip = request.headers.get("x-real-ip", request.client.host if request.client else "unknown")
        ip_key = f"otp_ip:{ip}"
        ip_attempts = int(await r.get(ip_key) or 0)
        if ip_attempts >= 5:
            raise HTTPException(429, "Слишком много запросов с вашего адреса.")
        await r.incr(ip_key)
        await r.expire(ip_key, 600)

        # Global limit: 100 sends per hour
        global_key = "otp_global_hour"
        global_count = int(await r.get(global_key) or 0)
        if global_count >= 100:
            raise HTTPException(429, "Сервис временно недоступен. Попробуйте позже.")
        await r.incr(global_key)
        await r.expire(global_key, 3600)

        # Rate limit by email: 3 sends per 10 min
        rate_key = f"otp_rate:{email}"
        attempts = int(await r.get(rate_key) or 0)
        if attempts >= 3:
            raise HTTPException(429, "Слишком много запросов. Попробуйте через 10 минут.")
        await r.incr(rate_key)
        await r.expire(rate_key, 600)

        # Generate 6-digit code
        code = str(random.randint(100000, 999999))
        await r.set(f"otp:{email}", code, ex=600)  # 10 min TTL
        await r.set(f"otp_attempts:{email}", "0", ex=600)
    finally:
        await r.aclose()

    # Send email (async, don't block response)
    from app.services.email_otp import send_otp_email
    import asyncio
    asyncio.ensure_future(send_otp_email(email, code))

    ip = request.headers.get("x-real-ip", request.client.host if request.client else "")
    logger.info("[OTP] Code sent to %s from IP %s", email[:20], ip)
    return {"ok": True, "message": "Код отправлен на email"}


@router.post("/otp/verify")
async def otp_verify(body: _OTPVerifyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Verify OTP code and login."""
    import redis.asyncio as aioredis

    email = body.email.strip().lower()
    code = body.code.strip()

    r = aioredis.from_url(s.redis_url, decode_responses=True)
    try:
        # Check attempts (brute-force protection)
        attempts = int(await r.get(f"otp_attempts:{email}") or 0)
        if attempts >= 5:
            await r.delete(f"otp:{email}", f"otp_attempts:{email}")
            raise HTTPException(429, "Слишком много попыток. Запросите новый код.")

        stored_code = await r.get(f"otp:{email}")
        if not stored_code:
            raise HTTPException(400, "Код истёк или не был запрошен")

        if stored_code != code:
            await r.incr(f"otp_attempts:{email}")
            remaining = 5 - attempts - 1
            raise HTTPException(400, f"Неверный код. Осталось попыток: {remaining}")

        # Success — delete OTP
        await r.delete(f"otp:{email}", f"otp_attempts:{email}", f"otp_rate:{email}")
    finally:
        await r.aclose()

    # Get or create user by email
    _source = _parse_source_from_state(body.state) if body.state else None
    user = await _get_or_create(db, "email", email, email, None, source=_source)

    ip = request.headers.get("x-real-ip", request.client.host if request.client else "")
    await log_activity(db, user.id, "login", details="Email OTP", utm_source=_source, ip_address=ip)
    await db.commit()

    _token = create_access_token(str(user.id))
    response = JSONResponse(content={"user_id": str(user.id)})
    _set_auth_cookie(response, _token)

    # Refresh token for localStorage fallback
    try:
        refresh = await _set_auth_cookie_with_refresh(response, _token, str(user.id))
        import json as _j
        response.body = _j.dumps({"user_id": str(user.id), "refresh_token": refresh}).encode()
        response.headers["content-length"] = str(len(response.body))
    except Exception:
        pass

    logger.info("[OTP] Login success: %s user=%s", email[:20], str(user.id)[:8])
    return response



class _UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: str | None = None


@router.put("/profile")
async def update_profile(body: _UpdateProfileRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Update user name and/or email."""
    if body.name is not None:
        name = body.name.strip()[:200]
        if name:
            user.name = name
    if body.email is not None:
        email = body.email.strip().lower()[:255]
        if email and "@" in email:
            user.email = email
        elif email == "":
            user.email = None
    await db.commit()
    return {"ok": True}

@router.put("/nickname")
async def set_nickname(body: SetNickname, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(User).where(User.nickname == body.nickname))).scalar_one_or_none()
    if existing and str(existing.id) != str(user.id):
        raise HTTPException(409, "Ник занят")
    user.nickname = body.nickname
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Ник занят")
    return {"ok": True}


# Transliteration fallback for VK names
_TRANSLIT = {
    'A':'А','B':'Б','V':'В','G':'Г','D':'Д','E':'Е','Ž':'Ж','Z':'З','I':'И',
    'J':'Й','K':'К','L':'Л','M':'М','N':'Н','O':'О','P':'П','R':'Р','S':'С',
    'T':'Т','U':'У','F':'Ф','H':'Х','C':'Ц','Č':'Ч','Š':'Ш','Ě':'Е','Ë':'Ё',
    'Y':'Ы','Ju':'Ю','Ja':'Я','Je':'Е','Jo':'Ё',
    'a':'а','b':'б','v':'в','g':'г','d':'д','e':'е','ž':'ж','z':'з','i':'и',
    'j':'й','k':'к','l':'л','m':'м','n':'н','o':'о','p':'п','r':'р','s':'с',
    't':'т','u':'у','f':'ф','h':'х','c':'ц','č':'ч','š':'ш','ě':'е','ë':'ё',
    'y':'ы','ju':'ю','ja':'я','je':'е','jo':'ё',
    'ch':'х','sh':'ш','shch':'щ','sch':'щ','zh':'ж','ts':'ц',
    'Ch':'Х','Sh':'Ш','Shch':'Щ','Sch':'Щ','Zh':'Ж','Ts':'Ц',
    'kh':'х','Kh':'Х','ij':'ий','iy':'ий','x':'кс','X':'Кс','ph':'ф','Ph':'Ф','w':'в','W':'В','ks':'кс',
}

def _to_cyrillic(name: str) -> str:
    """Convert transliterated name to Cyrillic if it looks like Latin."""
    if not name or any('\u0400' <= c <= '\u04ff' for c in name):
        return name  # already has Cyrillic
    result = name
    # Sort by length desc to match longer patterns first
    for lat, cyr in sorted(_TRANSLIT.items(), key=lambda x: -len(x[0])):
        result = result.replace(lat, cyr)
    # Check if conversion produced Cyrillic
    if any('\u0400' <= c <= '\u04ff' for c in result):
        return result
    return name  # couldn't convert, return original
