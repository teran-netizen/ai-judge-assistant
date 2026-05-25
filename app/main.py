from fastapi import Request,  FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
import re
import logging

# ── Logging configuration ──
import json as _json
import os

class _JSONFormatter(logging.Formatter):
    """Structured JSON logging for production. Plain text in DEBUG mode."""
    def format(self, record):
        log = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log["exc"] = self.formatException(record.exc_info)
        # Дополнительные поля (user_id, case_id и т.д.)
        for key in ("user_id", "case_id", "tokens", "amount", "order_id", "duration_sec"):
            val = getattr(record, key, None)
            if val is not None:
                log[key] = val
        return _json.dumps(log, ensure_ascii=False)

_log_handler = logging.StreamHandler()
if os.environ.get("DEBUG", "false").lower() == "true":
    _log_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
else:
    _log_handler.setFormatter(_JSONFormatter())

logging.root.handlers.clear()
logging.root.addHandler(_log_handler)
logging.root.setLevel(logging.INFO)

# Reduce noise from third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)

# Prevent duplicate log lines from uvicorn
for _uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _uv_logger = logging.getLogger(_uv_name)
    _uv_logger.handlers.clear()
    _uv_logger.propagate = True

from app.api import auth, cases, billing, admin, norms, invites, email, upload_sessions
from app.api import referral
from app.api import assistants
from app.api import internal_widget

from app.config import get_settings
from app.utils.datetime import ensure_utc, utcnow, utcnow_naive

s = get_settings()

# ── Sentry error monitoring ──
import sentry_sdk

_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,      # 10% запросов для performance monitoring
        profiles_sample_rate=0.1,    # 10% профилирование
        send_default_pii=False,      # НЕ отправляем персональные данные
        environment="production" if not s.debug else "development",
        release="ai-judge@3.18.2",
    )

app = FastAPI(
    title="ИИ Помощник Судьи",
    version="3.11.0",
    description="API для генерации проектов судебных решений с помощью DeepSeek",
    docs_url="/docs" if s.debug else None,       # Swagger UI только в debug
    redoc_url="/redoc" if s.debug else None,      # ReDoc только в debug
    openapi_url="/openapi.json" if s.debug else None,  # OpenAPI schema только в debug
)

# ── Security Middleware (первый слой — до CORS и роутинга) ──
from app.middleware.security import SecurityMiddleware
app.add_middleware(SecurityMiddleware)

# CORS: с credentials нельзя использовать "*" — браузер заблокирует
# В продакшене: domain. В debug: + localhost из cors_origins.
allowed_origins = [s.domain]
if s.debug:
    allowed_origins.extend([o.strip() for o in s.cors_origins.split(",") if o.strip()])
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,  # Required for HttpOnly cookie auth
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # Явный whitelist вместо "*"
    allow_headers=["Authorization", "Content-Type"],  # Явный whitelist вместо "*"
    expose_headers=["Content-Disposition"],  # Для скачивания .docx с именем файла
)

from app.api import activity
app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(billing.router)
app.include_router(admin.router)
app.include_router(norms.router)
app.include_router(invites.router)
app.include_router(activity.router)
app.include_router(email.router)
app.include_router(upload_sessions.router)
app.include_router(referral.router)
app.include_router(assistants.router)
app.include_router(internal_widget.router)



# ── Startup: recover stuck cases after restart ──
@app.on_event("startup")
async def _recover_stuck_cases():
    """Reset cases stuck in 'processing'/'generating' after container restart."""
    from app.database import async_session
    from sqlalchemy import text
    logger = logging.getLogger("app.startup")
    try:
        async with async_session() as db:
            r = await db.execute(text(
                "UPDATE cases SET status='draft', updated_at = NOW() "
                "WHERE status = 'processing' "
                "RETURNING id"
            ))
            stuck = r.fetchall()
            if stuck:
                await db.commit()
                ids = [str(row[0]) for row in stuck]
                logger.warning(f"Recovered {len(stuck)} stuck cases → draft: {ids}")
            else:
                logger.info("No stuck cases found on startup")
    except Exception as e:
        logger.error(f"Failed to recover stuck cases: {e}")


@app.on_event("startup")
async def _start_payment_checker():
    """Background task: check pending payments every 15 minutes (webhook is primary)."""
    import asyncio

    async def send_bot_alert(text):
        """Send alert via configured Telegram admin bot."""
        try:
            from app.services.telegram import send_admin
            await send_admin(text)
        except Exception:
            pass

    async def check_pending_payments():
        from app.database import async_session
        from app.models import User, Transaction
        from app.services.tochka_payment import check_payment_status
        from sqlalchemy import select
        from datetime import timedelta
        import redis.asyncio as aioredis
        log = logging.getLogger("app.payment_checker")

        while True:
            await asyncio.sleep(900)  # 15 minutes fallback scan (webhook is primary)
            # Redis lock to prevent double-run
            try:
                from app.config import get_settings
                _s = get_settings()
                _redis = aioredis.from_url(_s.redis_url)
                lock_acquired = await _redis.set("payment_checker_lock", "1", ex=840, nx=True)
                await _redis.aclose()
                if not lock_acquired:
                    log.debug("[PAYMENT_CHECK] Another instance running, skip")
                    continue
            except Exception:
                pass  # proceed without lock if Redis unavailable
            try:
                async with async_session() as db:
                    from datetime import datetime
                    cutoff = utcnow_naive() - timedelta(hours=24)  # naive — matches DB column type
                    txs = (await db.execute(
                        select(Transaction).where(
                            Transaction.purchase_type.is_not(None),
                            Transaction.external_payment_id.is_not(None),
                            Transaction.created_at >= cutoff,
                            Transaction.credited_at.is_(None),
                        ).order_by(Transaction.created_at.desc())
                    )).scalars().all()

                    if not txs:
                        continue

                    # Convert to plain dicts — protects against MissingGreenlet
                    # if a rollback occurs mid-loop and invalidates ORM objects.
                    pending = [
                        {
                            "id": tx.id,
                            "user_id": tx.user_id,
                            "external_payment_id": tx.external_payment_id,
                            "purchase_type": tx.purchase_type,
                            "amount_kopecks": tx.amount_kopecks or 0,
                        }
                        for tx in txs
                    ]

                    log.info(f"[PAYMENT_CHECK] Checking {len(pending)} pending transactions")

                    for p in pending:
                        op_id = p["external_payment_id"]
                        op_short = op_id[:12] if op_id else "?"
                        user_short = str(p["user_id"])[:8]
                        try:
                            status = await check_payment_status(op_id)
                            raw = status.get("raw_status", "?")

                            if status["status"] == "paid":
                                # Re-read transaction with lock to prevent double-credit race
                                locked_tx = (await db.execute(
                                    select(Transaction).where(Transaction.id == p["id"]).with_for_update()
                                )).scalar_one_or_none()
                                if not locked_tx or locked_tx.credited_at is not None:
                                    log.info(f"[PAYMENT_CHECK] user={user_short} op={op_short} already credited, skip")
                                    continue
                                tx = locked_tx  # full ORM object for mutation
                                tx_id = tx.id
                                tx_user_id = tx.user_id

                                locked_user = (await db.execute(
                                    select(User).where(User.id == tx_user_id).with_for_update()
                                )).scalar_one()

                                before_cases = locked_user.paid_cases_left or 0
                                before_sub = locked_user.subscription_until

                                from app.config import get_settings
                                s = get_settings()
                                # Use promo packages if user has promo_price
                                pkg_source = s.promo_packages if getattr(locked_user, "promo_price", False) else s.case_packages
                                pkg = pkg_source.get(tx.purchase_type, {})

                                if tx.purchase_type == "single_case":
                                    locked_user.paid_cases_left = before_cases + 1
                                    tx.description = f"Оплачено: {pkg.get('label', '1 дело')} ({tx.amount_kopecks / 100:.0f}\u20bd)"
                                elif tx.purchase_type in ("case_pack_5", "case_pack_10"):
                                    cases_to_add = 5 if tx.purchase_type == "case_pack_5" else 10
                                    locked_user.paid_cases_left = before_cases + cases_to_add
                                    tx.description = f"Оплачено: {pkg.get('label', f'{cases_to_add} дел')} ({tx.amount_kopecks / 100:.0f}\u20bd)"
                                elif tx.purchase_type in ("subscription_weekly", "subscription_monthly"):
                                    current_until = ensure_utc(locked_user.subscription_until)
                                    base_until = current_until if current_until and current_until > utcnow() else utcnow()
                                    sub_days = 30 if tx.purchase_type == "subscription_monthly" else 7
                                    locked_user.subscription_until = base_until + timedelta(days=sub_days)
                                    tx.description = f"Оплачено: {pkg.get('label', 'Подписка')} ({tx.amount_kopecks / 100:.0f}\u20bd)"

                                tx.credited_at = utcnow_naive()

                                # Referral bonus
                                from app.api.referral import maybe_award_referral_bonus
                                await maybe_award_referral_bonus(db, locked_user, tx)

                                await db.commit()

                                after_cases = locked_user.paid_cases_left or 0
                                after_sub = locked_user.subscription_until

                                log.info(
                                    f"[PAYMENT_CHECK] APPROVED user={user_short} type={tx.purchase_type} "
                                    f"amount={tx.amount_kopecks/100:.0f}r op={op_short} "
                                    f"paid_cases: {before_cases}->{after_cases}"
                                )

                                # Activity log for auto-confirmed payment
                                try:
                                    from app.models import ActivityLog
                                    db.add(ActivityLog(
                                        user_id=tx_user_id,
                                        action="payment_checker_found",
                                        details=f"auto-confirm {tx.purchase_type} {tx.amount_kopecks/100:.0f}r op={op_short} cases:{before_cases}->{after_cases}",
                                    ))
                                    if tx.purchase_type in ("subscription_weekly", "subscription_monthly"):
                                        db.add(ActivityLog(
                                            user_id=tx_user_id,
                                            action="subscription_renewed",
                                            details=f"auto until={locked_user.subscription_until}",
                                        ))
                                    await db.commit()
                                except Exception:
                                    pass

                                # Verify credit
                                verify_user = (await db.execute(
                                    select(User).where(User.id == tx_user_id)
                                )).scalar_one()

                                if tx.purchase_type in ("single_case", "case_pack_5", "case_pack_10"):
                                    if verify_user.paid_cases_left == after_cases:
                                        log.info(f"[PAYMENT_CHECK] VERIFY OK: user={user_short} paid_cases={after_cases}")
                                    else:
                                        log.error(f"[PAYMENT_CHECK] VERIFY FAILED! user={user_short} expected={after_cases} got={verify_user.paid_cases_left}")
                                        await send_bot_alert(
                                            f"\U0001f534 <b>Зачисление не прошло!</b>\n"
                                            f"Юзер: {user_short}\n"
                                            f"Тариф: {tx.purchase_type}\n"
                                            f"Ожидалось: {after_cases}, факт: {verify_user.paid_cases_left}"
                                        )
                                elif tx.purchase_type in ("subscription_weekly", "subscription_monthly"):
                                    if verify_user.subscription_until:
                                        log.info(f"[PAYMENT_CHECK] VERIFY OK: user={user_short} sub_until={verify_user.subscription_until}")
                                    else:
                                        log.error(f"[PAYMENT_CHECK] VERIFY FAILED! user={user_short} subscription_until=None")
                                        await send_bot_alert(
                                            f"\U0001f534 <b>Подписка не зачислена!</b>\n"
                                            f"Юзер: {user_short}"
                                        )

                                # Success notification
                                await send_bot_alert(
                                    f"\U0001f4b3 <b>Оплата зачислена!</b>\n"
                                    f"Юзер: {locked_user.name or user_short}\n"
                                    f"Тариф: {pkg.get('label', tx.purchase_type)}\n"
                                    f"Сумма: {tx.amount_kopecks/100:.0f}\u20bd\n"
                                    f"Баланс: {before_cases}\u2192{after_cases} дел"
                                )
                            else:
                                log.info(f"[PAYMENT_CHECK] user={user_short} op={op_short} type={p['purchase_type']} -> {raw}")

                        except Exception as e:
                            await db.rollback()
                            err_msg = f"{type(e).__name__}"
                            err_repr = repr(e)
                            if str(e):
                                err_msg += f": {str(e)[:100]}"
                            log.error(f"[PAYMENT_CHECK] Error op={op_short} user={user_short}: {err_msg}")
                            await send_bot_alert(
                                f"\U0001f534 <b>Ошибка проверки оплаты!</b>\n"
                                f"Operation: {op_short}\n"
                                f"Тип: {type(e).__name__}\n"
                                f"{repr(e)[:150] if repr(e) else 'нет деталей'}"
                            )

            except Exception as e:
                log.error(f"[PAYMENT_CHECK] Cycle error: {e}")
                await send_bot_alert(f"\U0001f534 <b>Payment checker error!</b>\n{str(e)[:200]}")

    asyncio.create_task(check_pending_payments())



@app.post("/api/client-log")
async def client_log(request: Request):
    """Receive client-side error logs from browser.

    Rate-limited and alert-sampled: a public endpoint needs both per-IP
    request throttling (to keep log storage honest) and global alert
    dedup (to keep admin Telegram inbox honest).
    """
    import logging
    import redis.asyncio as aioredis
    from fastapi.responses import JSONResponse
    from app.middleware.security import _get_ip
    clog = logging.getLogger("client")

    # Per-IP rate limit: 60 requests / 5 minutes.
    # Uses shared Redis (same instance as app) with a sliding key per 5-min bucket.
    try:
        ip = _get_ip(request)
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        rl_key = f"clog_rl:{ip}"
        pipe = r.pipeline()
        pipe.incr(rl_key)
        pipe.expire(rl_key, 300)
        count, _ = await pipe.execute()
        await r.aclose()
        if count > 60:
            return JSONResponse({"ok": False, "error": "rate_limit"}, status_code=429)
    except Exception:
        # Redis unavailable — fail open for logging (don't break the endpoint),
        # but alert-sampling below still provides defense against Telegram spam.
        pass

    try:
        body = await request.json()
        level = body.get("level", "info")
        tag = body.get("tag", "?")
        msg = body.get("message", "")
        ctx = body.get("context", {})
        ua = request.headers.get("user-agent", "")[:80]
        clog.warning("[CLIENT-%s] %s: %s | ctx=%s ua=%s", level.upper(), tag, msg[:200], ctx, ua)

        # Alert sampling: max 3 Telegram alerts / hour globally.
        _url = (ctx.get("url") or "") if isinstance(ctx, dict) else ""
        if level.upper() == "ERROR" and any(p in _url for p in ["/billing", "/referral", "/cases/"]):
            try:
                settings = get_settings()
                r = aioredis.from_url(settings.redis_url, decode_responses=True)
                pipe = r.pipeline()
                pipe.incr("clog_alert_budget")
                pipe.expire("clog_alert_budget", 3600)
                count, _ = await pipe.execute()
                await r.aclose()
                if count <= 3:
                    from app.services.telegram import send_admin
                    import asyncio
                    asyncio.ensure_future(send_admin(f"<b>JS error</b> ({count}/3) {_url} {msg[:150]}"))
            except Exception:
                pass
    except Exception:
        pass
    return {"ok": True}

@app.get("/health")
async def health():
    """Health check: DB connectivity + schema consistency."""
    from app.database import async_session
    from sqlalchemy import text
    from app.models import Base
    from fastapi.responses import JSONResponse

    result = {"status": "ok", "db": "ok", "schema": "ok", "schema_errors": []}

    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        result["status"] = "degraded"
        result["db"] = f"error: {str(e)[:100]}"
        return JSONResponse(result, status_code=503)

    # Schema check: verify all model columns exist in DB
    try:
        async with async_session() as db:
            for mapper in Base.registry.mappers:
                cls = mapper.class_
                table_name = cls.__tablename__
                model_cols = {c.name for c in mapper.columns}

                rows = await db.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ), {"t": table_name})
                db_cols = {r[0] for r in rows}

                if not db_cols:
                    result["schema_errors"].append(f"table {table_name} not found in DB")
                    continue

                missing = model_cols - db_cols
                if missing:
                    result["schema_errors"].append(
                        f"{table_name}: missing columns {sorted(missing)}"
                    )

        if result["schema_errors"]:
            result["status"] = "degraded"
            result["schema"] = "mismatch"
    except Exception as e:
        result["schema"] = f"check_error: {str(e)[:100]}"

    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(result, status_code=status_code)


DOCS_DIR = Path(__file__).parent.parent / "docs"

@app.get("/docs/{doc_name}")
async def serve_doc(doc_name: str):
    """Отдаёт markdown-документы (оферта, политика) как HTML-страницы."""
    # Защита от path traversal: только буквы, цифры, дефис, подчёркивание
    if not re.match(r'^[a-zA-Z0-9_\-]+$', doc_name):
        return HTMLResponse("<h1>404 — Документ не найден</h1>", status_code=404)
    md_path = DOCS_DIR / f"{doc_name}.md"
    # Проверяем что resolved path всё ещё внутри DOCS_DIR
    try:
        md_path.resolve().relative_to(DOCS_DIR.resolve())
    except ValueError:
        return HTMLResponse("<h1>404 — Документ не найден</h1>", status_code=404)
    if not md_path.exists() or not md_path.is_file():
        return HTMLResponse("<h1>404 — Документ не найден</h1>", status_code=404)

    content = md_path.read_text(encoding="utf-8")
    # Простая конвертация MD → HTML (без внешних зависимостей)
    html_body = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Заголовки (ДО замены переносов, иначе MULTILINE ^ не сработает)
    html_body = re.sub(r"^#{3}(?!#)\s*(.+)", r"<h3>\1</h3>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"^#{2}(?!#)\s*(.+)", r"<h2>\1</h2>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"^#{1}(?!#)\s*(.+)", r"<h1>\1</h1>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_body)
    # Параграфы и переносы (ПОСЛЕ заголовков)
    html_body = html_body.replace("\n\n", "</p><p>").replace("\n", "<br>")

    import html as _html
    safe_title = _html.escape(doc_name)
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<title>{safe_title}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;line-height:1.7;color:#333}}
h1,h2,h3{{margin-top:1.5em}}a{{color:#1a55f5}}</style>
</head><body><p>{html_body}</p></body></html>"""
    return HTMLResponse(html)
