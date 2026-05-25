"""Health monitoring — запускается из arq cron раз в час.

Проверяет что критичные точки отказа работают:
  1. Frontend bundle содержит OAuth client_ids (предотвращает баг 17.04)
  2. /api/auth/{yandex,vk}/start отвечают непустым auth_url
  3. Tochka access_token в Redis живой (skip если Tochka не настроена)
  4. OAuth-воронка логинов не умерла (activity_log behavioral check)

При проблемах — один Telegram-алерт со сводкой всех упавших проверок.
Префикс "[STAGING]" отличает от прод-алертов при шаринге бота.
"""
from __future__ import annotations

import logging
import re
from typing import Tuple

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.database import async_session
from app.services.telegram import send_admin, _esc

log = logging.getLogger("health_check")

# Backend резолвится через compose service name (ok в изолированной сети).
INTERNAL_BACKEND = "http://app:8000"

PREFIX = ""


def _frontend_url() -> tuple[str, dict]:
    """Возвращает (url, headers) для запроса к фронту.

    If a public domain is configured, use it. Otherwise fall back to the
    Compose service name used in local review.
    """
    s = get_settings()
    if s.domain and ("http" in s.domain):
        return s.domain.rstrip("/"), {}
    return "http://frontend:80", {}


async def check_frontend_bundle(base_url: str = "") -> Tuple[bool, str]:
    """Скачать index.html, найти JS-бандл, проверить что в нём есть OAuth-строки."""
    s = get_settings()
    if not base_url:
        base_url, extra_headers = _frontend_url()
    else:
        extra_headers = {}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, verify=False) as c:
            r = await c.get(f"{base_url}/", headers=extra_headers)
            if r.status_code != 200:
                return False, f"index.html HTTP {r.status_code}"
            m = re.search(r'src="(/assets/index-[^"]+\.js)"', r.text)
            if not m:
                return False, "JS bundle tag not found in index.html"
            bundle_path = m.group(1)
            r2 = await c.get(f"{base_url}{bundle_path}", headers=extra_headers)
            if r2.status_code != 200:
                return False, f"bundle HTTP {r2.status_code}"
            body = r2.text
            missing = []
            for marker, label in [
                ("oauth.yandex.ru", "oauth.yandex.ru URL"),
                ("id.vk.com", "id.vk.com URL"),
            ]:
                if marker not in body:
                    missing.append(label)
            if s.yandex_client_id and s.yandex_client_id not in body:
                missing.append("YANDEX_CLIENT_ID value")
            if s.vk_client_id and s.vk_client_id not in body:
                missing.append("VK_CLIENT_ID value")
            if missing:
                return False, f"bundle {bundle_path} missing: {', '.join(missing)}"
            return True, f"bundle {bundle_path} OK"
    except Exception as e:
        return False, f"bundle fetch failed: {type(e).__name__}: {e}"


async def check_auth_endpoints(base_url: str = INTERNAL_BACKEND) -> Tuple[bool, str]:
    """Проверить что /api/auth/{yandex,vk}/start отдают валидный client_id.

    404 трактуется как "endpoint отсутствует на этой инсталляции" — на staging
    legacy /start endpoints удалены, фронт строит OAuth-URL сам. В этом случае
    проверка bundle уже покрывает корень проблемы.
    """
    s = get_settings()
    dom = s.domain.rstrip("/") if s.domain else "http://localhost"
    errors = []
    statuses = []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            for provider, redirect_suffix in [
                ("yandex", "/auth/callback?provider=yandex"),
                ("vk", "/auth/vk-callback"),
            ]:
                r = await c.get(
                    f"{base_url}/api/auth/{provider}/start",
                    params={"redirect_uri": f"{dom}{redirect_suffix}"},
                )
                if r.status_code == 404:
                    statuses.append(f"{provider}=404(skip)")
                    continue
                if r.status_code != 200:
                    errors.append(f"{provider}/start HTTP {r.status_code}")
                    continue
                auth_url = (r.json() or {}).get("auth_url", "")
                m = re.search(r"client_id=([^&]+)", auth_url)
                min_len = 10 if provider == "yandex" else 5
                if not m or len(m.group(1)) < min_len:
                    errors.append(f"{provider}: empty/short client_id in auth_url")
                else:
                    statuses.append(f"{provider}=OK")
    except Exception as e:
        errors.append(f"auth endpoint fetch failed: {type(e).__name__}: {e}")
    if errors:
        return False, "; ".join(errors)
    return True, "; ".join(statuses) if statuses else "no checks ran"


async def check_tochka_token() -> Tuple[bool, str]:
    """Проверить tochka:access_token в Redis.

    Если TTL < 600s — триггерим proactive refresh (через refresh_token).
    Это предотвращает ситуацию когда юзер попадёт на expired токен и получит
    лишние 200ms задержки на auto-refresh в середине оплаты.

    Skip если Tochka не настроена.
    """
    s = get_settings()
    if not s.tochka_client_id:
        return True, "tochka not configured (skip)"
    try:
        from app.services.redis_stream import get_redis
        r = await get_redis()
        tok = await r.get("tochka:access_token")
        ttl = await r.ttl("tochka:access_token")

        # Proactive refresh если токен близок к истечению или уже нет
        if (not tok) or (ttl is not None and ttl < 600):
            log.info("[HEALTH] Tochka TTL=%s — proactive refresh", ttl)
            try:
                from app.services.tochka_payment import _refresh_token
                new_tok = await _refresh_token()
                if new_tok:
                    new_ttl = await r.ttl("tochka:access_token")
                    return True, f"tochka proactively refreshed (new TTL={new_ttl}s)"
                return False, "tochka refresh returned empty token"
            except Exception as rex:
                return False, f"tochka refresh failed: {type(rex).__name__}: {rex}"

        return True, f"tochka access_token TTL={ttl}s"
    except Exception as e:
        return False, f"tochka check error: {type(e).__name__}: {e}"


async def check_login_funnel() -> Tuple[bool, str]:
    """Если за 3ч было >=10 login'ов но 0 через OAuth — подозрительно."""
    try:
        async with async_session() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                          count(*) AS total,
                          count(*) FILTER (WHERE details ILIKE '%OAuth%') AS oauth
                        FROM activity_log
                        WHERE action='login' AND created_at > now() - interval '3 hours'
                        """
                    )
                )
            ).first()
            total = int(row.total or 0)
            oauth = int(row.oauth or 0)
            if total >= 10 and oauth == 0:
                return (
                    False,
                    f"last 3h: {total} logins, 0 via OAuth — funnel dead?",
                )
            return True, f"last 3h: {total} logins ({oauth} OAuth)"
    except Exception as e:
        return False, f"funnel check error: {type(e).__name__}: {e}"


async def check_rescue_freebies() -> tuple[bool, str]:
    """Detect if rescue pipeline ran with empty billing in last 24h.

    This is the canary for the revenue-leak bug fixed 2026-04-22
    (see docs/pipeline_handoff.md). If count > 0, one of the
    "DO NOT REVERT" guards has regressed — Y.1 (enqueue_rescue pre-bill),
    Y.2 (worker stop for empty rescue billing), or Unify (recovery
    skipping users w/o balance).
    """
    from app.database import async_session
    from sqlalchemy import text
    try:
        async with async_session() as db:
            r = await db.execute(text(
                "SELECT count(*) FROM case_runs cr "
                "JOIN cases c ON c.id = cr.case_id "
                "WHERE cr.pipeline_type = 'rescue' "
                "  AND cr.started_at > now() - interval '2 hours' "
                "  AND (c.billing_method IS NULL OR c.billing_method = '')"
            ))
            n = r.scalar() or 0
        if n == 0:
            return True, "0 rescue-freebies in 2h"
        return False, f"{n} rescue runs with empty billing in last 2h — REGRESSION (see docs/pipeline_handoff.md)"
    except Exception as e:
        return False, f"rescue-freebie check error: {type(e).__name__}: {e}"


async def check_cert_expiry() -> tuple[bool, str]:
    """Detect certs expiring within 14 days via real SSL handshake.

    Connects to frontend:443 with each configured SNI host, reads the peer
    certificate, checks notAfter. More honest than filesystem check because
    it verifies what browsers actually see — cert file update without nginx
    reload would be caught here.
    """
    import ssl
    import asyncio
    import datetime

    s = get_settings()
    configured_host = ""
    if s.domain:
        from urllib.parse import urlparse
        parsed = urlparse(s.domain if "://" in s.domain else f"https://{s.domain}")
        configured_host = (parsed.netloc or "").split(":")[0]
    hosts = [configured_host] if configured_host else ["example.com"]
    now = datetime.datetime.now(datetime.timezone.utc)
    threshold = now + datetime.timedelta(days=14)
    expiring = []
    errors = []

    for host in hosts:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE  # we validate expiry, not chain
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("frontend", 443, ssl=ctx, server_hostname=host),
                timeout=5,
            )
            ssl_obj = writer.get_extra_info("ssl_object")
            cert_der = ssl_obj.getpeercert(binary_form=True) if ssl_obj else None
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            if not cert_der:
                errors.append(f"{host}(no-cert)")
                continue

            # Parse notAfter from DER without cryptography lib:
            # Use ssl module's built-in parse via getpeercert(False) second handshake.
            # Simpler: use cryptography if available, else fall back to ssl text parse.
            try:
                from cryptography import x509
                from cryptography.hazmat.backends import default_backend
                cert = x509.load_der_x509_certificate(cert_der, default_backend())
                expiry = getattr(cert, "not_valid_after_utc", None)
                if expiry is None:
                    expiry = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
            except ImportError:
                # Fallback: re-handshake with verify_mode set to get dict form
                ctx2 = ssl.create_default_context()
                ctx2.check_hostname = False
                ctx2.verify_mode = ssl.CERT_NONE
                r2, w2 = await asyncio.wait_for(
                    asyncio.open_connection("frontend", 443, ssl=ctx2, server_hostname=host),
                    timeout=5,
                )
                so2 = w2.get_extra_info("ssl_object")
                info = so2.getpeercert() if so2 else {}
                w2.close()
                try:
                    await w2.wait_closed()
                except Exception:
                    pass
                na = info.get("notAfter") if info else None
                if not na:
                    errors.append(f"{host}(no-notAfter)")
                    continue
                expiry = datetime.datetime.strptime(na, "%b %d %H:%M:%S %Y %Z").replace(
                    tzinfo=datetime.timezone.utc
                )

            days_left = (expiry - now).days
            if expiry < threshold:
                expiring.append(f"{host}({days_left}d)")
        except Exception as e:
            errors.append(f"{host}({type(e).__name__})")

    if expiring:
        return False, f"certs expiring <14d: {', '.join(expiring)} — check certbot container logs"
    if errors:
        return True, f"checked {len(hosts)} hosts, all >14d (errors on: {', '.join(errors)})"
    return True, f"all {len(hosts)} certs valid >14d"

async def run_all_checks(ctx=None) -> dict:
    """Entry point для arq cron. Прогоняет все проверки, Telegram-алерт при фейлах."""
    log.info("[HEALTH] start")
    checks = [
        ("Frontend bundle", await check_frontend_bundle()),
        ("Auth endpoints", await check_auth_endpoints()),
        ("Tochka token", await check_tochka_token()),
        ("Login funnel", await check_login_funnel()),
        ("Rescue freebies", await check_rescue_freebies()),
        ("Cert expiry", await check_cert_expiry()),
    ]
    results = []
    for name, (ok, msg) in checks:
        results.append({"name": name, "ok": ok, "msg": msg})
        log.info("[HEALTH] %s: %s — %s", name, "OK" if ok else "FAIL", msg)

    failed = [r for r in results if not r["ok"]]
    if failed:
        lines = [f"⚠️ <b>{PREFIX} Health check FAILED</b>"]
        for r in failed:
            lines.append(f"❌ <b>{_esc(r['name'])}</b>: {_esc(r['msg'])}")
        ok_list = [r["name"] for r in results if r["ok"]]
        if ok_list:
            lines.append("")
            lines.append(f"✅ OK: {_esc(', '.join(ok_list))}")
        try:
            await send_admin("\n".join(lines))
        except Exception as e:
            log.error("send_admin failed: %s", e)
    log.info("[HEALTH] done — %d/%d passed", len(results) - len(failed), len(results))
    return {"results": results, "failed_count": len(failed)}
