from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
import logging
import uuid as _uuid
import re
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from datetime import timedelta

from app.database import get_db
from app.models import User, Transaction
from app.schemas import SbpPaymentResponse
from app.services.tochka_payment import create_payment_link, check_payment_status as tochka_check_status
from app.services.telegram import send_admin
from app.utils.deps import get_current_user
from app.utils.datetime import ensure_utc, utcnow, utcnow_naive
from app.config import get_settings
from app.api.helpers.activity import log_activity

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Track failed purchases
async def _alert_purchase_error(user_name, purchase_type, error_msg):
    try:
        from app.services.telegram import send_admin
        text = "<b>Purchase error</b> " + str(user_name) + " " + str(purchase_type) + " " + str(error_msg)[:150]
        await send_admin(text)
    except Exception:
        pass

s = get_settings()
logger = logging.getLogger(__name__)


def _append_query_params(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None:
            query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _subscription_expires_from(current_until):
    base = ensure_utc(current_until)
    now = utcnow()
    if not base or base < now:
        base = now
    return base + timedelta(days=7)


def _apply_case_purchase(user: User, tx: Transaction, packages: dict) -> None:
    package_type = tx.purchase_type
    pkg = packages.get(package_type) or {}
    if package_type in ("single_case",):
        user.paid_cases_left = (user.paid_cases_left or 0) + 1
        tx.description = f"Оплачено: {pkg.get("label", "1 дело")} ({tx.amount_kopecks / 100:.0f}₽)"
    elif package_type in ("case_pack_5", "case_pack_10"):
        cases_to_add = 5 if package_type == "case_pack_5" else 10
        user.paid_cases_left = (user.paid_cases_left or 0) + cases_to_add
        tx.description = f"Оплачено: {pkg.get("label", f"{cases_to_add} дел")} ({tx.amount_kopecks / 100:.0f}₽)"
    elif package_type == "trial_3d":
        base = ensure_utc(user.subscription_until)
        now = utcnow()
        if not base or base < now:
            base = now
        user.subscription_until = base + timedelta(days=3)
        tx.description = f"Оплачено: {pkg.get('label', 'Безлимит 3 дня')} ({tx.amount_kopecks / 100:.0f}\u20bd)"
    elif package_type == "subscription_monthly":
        base = ensure_utc(user.subscription_until)
        now = utcnow()
        if not base or base < now:
            base = now
        user.subscription_until = base + timedelta(days=30)
        tx.description = f"Оплачено: {pkg.get('label', 'Подписка на месяц')} ({tx.amount_kopecks / 100:.0f}\u20bd)"
    elif package_type == "subscription_weekly":
        user.subscription_until = _subscription_expires_from(user.subscription_until)
        tx.description = f"Оплачено: {pkg.get('label', 'Безлимит неделя')} ({tx.amount_kopecks / 100:.0f}\u20bd)"
    elif package_type in ("case_simple", "case_medium", "case_large"):
        user.paid_cases_left = (user.paid_cases_left or 0) + 1
        tx.description = f"Оплачено: {pkg.get("label", "1 дело")} ({tx.amount_kopecks / 100:.0f}₽)"
    else:
        raise HTTPException(400, "Неизвестный тип пакета")


@router.get("/packages")
async def list_packages(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    packages = s.case_packages
    return {
        "billing_model": "cases",
        "case_packages": [
            {
                "type": k,
                "cases": v["cases"],
                "price_kopecks": v["price_kopecks"],
                "price_rub": v["price_kopecks"] / 100,
                "label": v["label"],
                "duration_days": v.get("duration_days"),
            }
            for k, v in packages.items()
            if k != "first_case"
        ],
    }


@router.get("/balance")
async def get_balance(user: User = Depends(get_current_user)):
    return {
        "balance_kopecks": user.balance_kopecks,
        "free_cases_left": user.free_cases_left,
        "paid_cases_left": user.paid_cases_left,
    }





# Allowed hosts for post-payment redirects. Any return_url outside this list
# is silently ignored and the default /billing?payment=success is used.
# See also app/api/auth.py _validate_redirect_uri for OAuth-side equivalent.
_RETURN_URL_ALLOWED_HOSTS = (
    "example.com",
    "www.example.com",
)


def _allowed_return_hosts() -> set[str]:
    hosts = set(_RETURN_URL_ALLOWED_HOSTS)
    if s.domain:
        parsed = urlparse(s.domain if "://" in s.domain else f"https://{s.domain}")
        host = (parsed.netloc or "").lower().split(":")[0]
        if host:
            hosts.add(host)
    return hosts


def _validate_return_url(return_url: str | None) -> str:
    """Return the provided return_url only if it's safe (our domain, https).
    Otherwise return empty string so caller falls back to default success URL.
    """
    if not return_url:
        return ""
    ru = return_url.strip()
    if not ru:
        return ""
    # Relative URL ("/cases/abc") — safe, lives on our domain.
    if ru.startswith("/") and not ru.startswith("//"):
        return ru
    # Absolute URL — require https + allowlisted host.
    from urllib.parse import urlparse
    try:
        parsed = urlparse(ru)
    except Exception:
        return ""
    if parsed.scheme not in ("https", "http"):
        return ""
    host = (parsed.netloc or "").lower().split(":")[0]
    if not host:
        return ""
    if any(host == h or host.endswith("." + h) for h in _allowed_return_hosts()):
        return ru
    return ""



@router.post("/purchase-attempt")
async def purchase_attempt(body: dict, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    package_type = body.get("package_type")
    return_url = body.get("return_url", "")  # optional: return to case page after payment
    if package_type not in ("single_case", "case_pack_5", "case_pack_10", "trial_3d", "subscription_weekly", "subscription_monthly", "case_simple", "case_medium", "case_large"):
        raise HTTPException(400, "Неизвестный тип пакета")

    # Rate limit: max 1 payment attempt per 10 seconds per user
    cutoff_10s = utcnow_naive() - timedelta(seconds=10)
    recent_tx = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.created_at >= cutoff_10s,
            Transaction.description.like("Попытка%"),
        )
    )).scalar_one_or_none()
    if recent_tx:
        raise HTTPException(429, "Подождите немного перед повторной попыткой")

    is_promo = getattr(user, "promo_price", False)
    packages = s.promo_packages if is_promo else s.case_packages


    pkg = packages[package_type]

    tx = Transaction(
        user_id=user.id,
        type="purchase",
        amount_tokens=0,
        amount_kopecks=pkg["price_kopecks"],
        description=f"Попытка покупки: {pkg['label']}",
        purchase_type=package_type,
    )
    db.add(tx)
    await db.commit()

    logger.info(f"[AB] Purchase attempt: user={user.id} package={package_type} price={pkg['price_kopecks']/100}r promo={is_promo} ab={getattr(user, 'ab_group', '?')}")

    # Create real payment link via Tochka
    amount_rub = pkg["price_kopecks"] / 100
    purpose = f"{pkg['label']} - AI Judge Assistant"
    domain = s.domain or "https://example.com"

    _safe_return = _validate_return_url(return_url)
    success_url = _safe_return if _safe_return else f"{domain}/billing?payment=success&type={package_type}"
    # If return_url was rejected, log it (possible reconnaissance / bad-client)
    if return_url and not _safe_return:
        logger.warning("[SECURITY] rejected return_url=%r (not in allowlist) user=%s", return_url[:200], user.id)
    success_url = _append_query_params(success_url, tx=str(tx.id))
    fail_url = _append_query_params(f"{domain}/billing?payment=fail", tx=str(tx.id))

    try:
        result = await create_payment_link(
            amount_rub=amount_rub,
            purpose=purpose,
            redirect_url=success_url,
            fail_redirect_url=fail_url,
        )
        op_id = result["operationId"]
        tx.external_payment_id = op_id
        await db.commit()
        logger.info(f"[PAYMENT] Link created: op={op_id} tx={tx.id} amount={amount_rub}r")

        await log_activity(db, user.id, "purchase_attempt", details=f"{package_type} {amount_rub}r op={op_id[:12]}", ip_address=request.client.host if request.client else None)
        await log_activity(db, user.id, "payment_started", details=f"{package_type} {amount_rub}r op={op_id[:12]} tx={str(tx.id)[:8]}")
        return {
            "status": "payment_link",
            "payment_url": result["paymentLink"],
            "operation_id": op_id,
        }
    except Exception as e:
        logger.error(f"Tochka payment error: {e}", exc_info=True)
        await log_activity(db, user.id, "payment_error", details=f"{package_type} {amount_rub}r err={str(e)[:120]}", ip_address=request.client.host if request.client else None)
        await db.commit()
        return {"status": "error", "message": "Оплата временно недоступна. Попробуйте позже."}


@router.post("/confirm-payment")
async def confirm_payment(body: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Подтверждение оплаты после возврата с Точки.
    Фронт вызывает при возврате на /billing?payment=success&op=xxx
    """
    operation_id = (body.get("operation_id") or "").strip()
    transaction_id = (body.get("transaction_id") or "").strip()
    logger.info(
        "[CONFIRM] START user=%s tx=%s op_id=%s",
        user.id,
        transaction_id[:12] if transaction_id else "EMPTY",
        operation_id[:16] if operation_id else "EMPTY",
    )

    tx = None
    # 1. Search by transaction_id (most reliable)
    if transaction_id:
        try:
            tx_uuid = _uuid.UUID(transaction_id)
        except (ValueError, AttributeError):
            raise HTTPException(400, "Невалидный transaction_id")
        tx = (await db.execute(
            select(Transaction).where(
                Transaction.id == tx_uuid,
                Transaction.user_id == user.id,
                Transaction.purchase_type.is_not(None),
            ).with_for_update()
        )).scalar_one_or_none()
        if tx and tx.external_payment_id:
            operation_id = tx.external_payment_id

    # 2. Fallback: search by operation_id
    if tx is None and operation_id and operation_id != "PLACEHOLDER" and re.match(r'^[a-zA-Z0-9\-]{1,64}$', operation_id):
        logger.info("[CONFIRM] Searching by operation_id=%s", operation_id[:16])
        tx = (await db.execute(
            select(Transaction).where(
                Transaction.external_payment_id == operation_id,
                Transaction.user_id == user.id,
            ).with_for_update()
        )).scalar_one_or_none()

    if not tx:
        logger.warning("[CONFIRM] No transaction found for user=%s", user.id)
        raise HTTPException(404, "Транзакция не найдена")

    if not operation_id:
        logger.warning("[CONFIRM] Transaction has no external operation id: user=%s tx=%s", user.id, getattr(tx, "id", None))
        raise HTTPException(409, "Платёж ещё не инициализирован")

    # Проверяем что ещё не зачислено
    await log_activity(db, user.id, "payment_callback", details=f"op={operation_id[:12]} tx={str(tx.id)[:8]} type={tx.purchase_type}")

    if tx.credited_at is not None:
        logger.info("[CONFIRM] Already confirmed: user=%s op=%s", user.id, operation_id[:16])
        await log_activity(db, user.id, "payment_duplicate", details=f"op={operation_id[:12]} already credited")
        return {"status": "already_confirmed", "message": "Оплата уже зачислена"}

    # Проверяем статус в Точке
    logger.info("[CONFIRM] Checking Tochka status for op=%s", operation_id[:16])
    try:
        status = await tochka_check_status(operation_id)
        logger.info("[CONFIRM] Tochka status: %s (raw: %s)", status["status"], status.get("raw_status"))
    except Exception as e:
        logger.error("[CONFIRM] Tochka status check failed: %s", e)
        raise HTTPException(502, "Ошибка проверки статуса")

    if status["status"] != "paid":
        logger.info("[CONFIRM] Not paid yet: user=%s status=%s", user.id, status.get("raw_status"))
        return {"status": "not_paid", "raw_status": status.get("raw_status")}

    # Зачисляем!
    from sqlalchemy import select as sa_select
    locked_user = (await db.execute(
        sa_select(User).where(User.id == user.id).with_for_update()
    )).scalar_one()

    packages = s.promo_packages if getattr(locked_user, "promo_price", False) else s.case_packages
    _apply_case_purchase(locked_user, tx, packages)
    from datetime import datetime
    from sqlalchemy import text as sa_text
    tx.credited_at = utcnow_naive()
    # Explicit SQL UPDATE as safety net (ORM may not flush credited_at)
    await db.execute(sa_text("UPDATE transactions SET credited_at = NOW() WHERE id = cast(:tid as uuid)"), {"tid": str(tx.id)})

    # Referral bonus: award 3+3 cases on first payment
    from app.api.referral import maybe_award_referral_bonus
    await maybe_award_referral_bonus(db, locked_user, tx)

    await db.commit()

    pkg = packages.get(tx.purchase_type, {})

    sub_detail = ""
    if tx.purchase_type == "subscription_weekly":
        sub_detail = f" sub_until={locked_user.subscription_until}"
    await log_activity(db, user.id, "payment_confirmed",
        details=f"{tx.purchase_type} {tx.amount_kopecks/100:.0f}r paid_cases={locked_user.paid_cases_left or 0}{sub_detail}")
    if tx.purchase_type == "subscription_weekly":
        await log_activity(db, user.id, "subscription_renewed", details=f"until={locked_user.subscription_until}")

    logger.info(
        "[CONFIRM] SUCCESS! payment_confirmed user=%s package=%s amount=%d op=%s paid_cases=%d sub=%s",
        user.id, tx.purchase_type, tx.amount_kopecks, operation_id,
        locked_user.paid_cases_left or 0,
        locked_user.subscription_until,
        extra={"user_id": str(user.id), "amount": tx.amount_kopecks},
    )

    # Telegram notification
    try:
        from app.services.telegram import send_admin, _esc
        await send_admin(
            f"💳 <b>Оплата подтверждена!</b>\n"
            f"Юзер: {_esc(locked_user.name or str(locked_user.id)[:8])}\n"
            f"Email: {_esc(locked_user.email or '—')}\n"
            f"Тариф: {pkg.get('label', tx.purchase_type)}\n"
            f"Сумма: {tx.amount_kopecks / 100:.0f}₽"
        )
    except Exception:
        pass

    # Alert if user has a stuck draft case with uploaded files.
    # Порог 10 мин: если draft свежее — юзер ещё может возвращаться с СБП,
    # не триггерим ложный алерт.
    try:
        from app.models import Case
        from sqlalchemy import select as _sel
        from sqlalchemy.orm import selectinload
        from datetime import timedelta
        _draft_cutoff = utcnow_naive() - timedelta(minutes=10)
        stuck = (await db.execute(
            _sel(Case).options(selectinload(Case.files)).where(
                Case.user_id == str(user.id),
                Case.status == "draft",
                Case.created_at < _draft_cutoff,
            )
        )).scalars().all()
        stuck_with_files = [c for c in stuck if c.files and len(c.files) > 0]
        if stuck_with_files:
            c = stuck_with_files[0]
            await send_admin(
                f"⚠️ <b>Оплата прошла, но дело в draft!</b>\n"
                f"Юзер: {_esc(locked_user.name or str(locked_user.id)[:8])}\n"
                f"Дело: {_esc(str(c.id)[:8])} ({len(c.files)} файлов)\n"
                f"Возможно СБП не сделал redirect"
            )
    except Exception:
        pass


    return {
        "status": "confirmed",
        "package_type": tx.purchase_type,
        "paid_cases_left": locked_user.paid_cases_left,
        "subscription_until": locked_user.subscription_until.isoformat() if locked_user.subscription_until else None,
    }


@router.get("/watch/{tx_id}")
async def watch_payment(tx_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Live SSE-стрим состояния оплаты.

    Клиент подключается сразу после редиректа на /billing?payment=success
    (или из модалки оплаты) и видит `credited` как только Tochka вернёт paid.

    Политика polling'а Tochka API (одна подписка):
       первые 10 сек → каждая 1 сек  (fast path, ловим мгновенно)
       10-60 сек     → каждые 3 сек
       60-600 сек    → каждые 10 сек (deadline 10 мин)

    Как только Tochka вернула paid → мы здесь же зачисляем через
    `_apply_case_purchase` (тот же путь что webhook/confirm-payment,
    с tx/user row lock) и шлём клиенту `credited`. Закрываемся.

    Защита от параллельной работы с /confirm-payment: оба пути лочат tx
    с `FOR UPDATE` и проверяют `credited_at is not None` до credit —
    если кто-то уже зачислил, second path просто вернёт `credited`.
    """
    import asyncio
    import json
    import time
    from fastapi.responses import StreamingResponse

    try:
        tx_uuid = _uuid.UUID(tx_id)
    except ValueError:
        raise HTTPException(400, "Невалидный tx_id")

    # Проверяем что tx принадлежит этому юзеру (иначе watch — утечка данных)
    tx = (await db.execute(
        select(Transaction).where(
            Transaction.id == tx_uuid,
            Transaction.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not tx:
        raise HTTPException(404, "Транзакция не найдена")

    operation_id = tx.external_payment_id
    if not operation_id:
        raise HTTPException(409, "Платёж ещё не инициализирован")

    async def _encode(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def stream():
        # 0. Уже зачислено — сразу отдаём credited.
        if tx.credited_at is not None:
            yield await _encode({"status": "credited", "already": True})
            yield await _encode({"status": "done"})
            return

        start = time.time()
        deadline = start + 600  # 10 минут максимум
        last_keepalive = start

        while time.time() < deadline:
            # Проверяем disconnect клиента (SSE generator cancellation).
            elapsed = time.time() - start

            # Адаптивный интервал polling Tochka.
            if elapsed < 10:
                interval = 1.0
            elif elapsed < 60:
                interval = 3.0
            else:
                interval = 10.0

            # Дёргаем Tochka API.
            try:
                status_resp = await tochka_check_status(operation_id)
            except Exception as e:
                logger.warning("[WATCH] tochka check failed op=%s: %s", operation_id[:16], e)
                yield await _encode({"status": "pending", "error": "tochka_check_failed"})
                await asyncio.sleep(interval)
                continue

            raw = status_resp.get("status")
            if raw == "paid":
                # PAID → зачисляем под row lock (идентично webhook/confirm-payment).
                from sqlalchemy import select as sa_select
                locked_tx = (await db.execute(
                    sa_select(Transaction).where(Transaction.id == tx.id).with_for_update()
                )).scalar_one_or_none()

                if not locked_tx:
                    yield await _encode({"status": "error", "message": "tx vanished"})
                    return

                if locked_tx.credited_at is not None:
                    # Успели другим путём (webhook/confirm/monitor). Это ок.
                    yield await _encode({"status": "credited", "raced": True})
                    yield await _encode({"status": "done"})
                    return

                locked_user = (await db.execute(
                    sa_select(User).where(User.id == locked_tx.user_id).with_for_update()
                )).scalar_one_or_none()
                if not locked_user:
                    yield await _encode({"status": "error", "message": "user vanished"})
                    return

                packages = s.promo_packages if getattr(locked_user, "promo_price", False) else s.case_packages

                try:
                    _apply_case_purchase(locked_user, locked_tx, packages)
                except HTTPException as he:
                    yield await _encode({"status": "error", "message": he.detail})
                    return

                locked_tx.credited_at = utcnow_naive()

                try:
                    from app.api.referral import maybe_award_referral_bonus
                    await maybe_award_referral_bonus(db, locked_user, locked_tx)
                except Exception as e:
                    logger.warning("[WATCH] referral bonus failed: %s", e)

                await db.commit()

                await log_activity(
                    db, user.id, "payment_watched",
                    details=f"{locked_tx.purchase_type} {locked_tx.amount_kopecks/100:.0f}r elapsed={elapsed:.1f}s",
                )

                # Telegram alert
                try:
                    from app.services.telegram import _esc as _we
                    label = packages.get(locked_tx.purchase_type, {}).get('label', locked_tx.purchase_type)
                    await send_admin(
                        f"💳 <b>Новая оплата</b>\n"
                        f"Пользователь: {_we(locked_user.real_name or locked_user.name or '—')}"
                        f"{' (display: ' + str(locked_user.display_id) + ')' if locked_user.display_id else ''}\n"
                        f"Email: {_we(locked_user.email or '—')}\n"
                        f"Тариф: {_we(label)} ({locked_tx.amount_kopecks / 100:.0f}₽)\n"
                        f"Время: {_we(locked_tx.created_at.strftime('%d.%m.%Y %H:%M') if locked_tx.created_at else '—')} MSK\n"
                        f"Город: {_we(locked_user.city or '—')}\n"
                        f"Промо-цена: {'да' if getattr(locked_user, 'promo_price', False) else 'нет'}\n"
                        f"Баланс дел: {(locked_user.paid_cases_left or 0) + (locked_user.free_cases_left or 0)}\n"
                        f"Регистрация: {_we(locked_user.created_at.strftime('%d.%m.%Y') if locked_user.created_at else '—')}\n"
                        f"UTM: {_we(locked_user.utm_source or '—')}\n"
                        f"op: {operation_id[:16]}"
                    )
                except Exception:
                    pass

                yield await _encode({
                    "status": "credited",
                    "elapsed_seconds": round(elapsed, 1),
                    "paid_cases_left": locked_user.paid_cases_left,
                    "subscription_until": locked_user.subscription_until.isoformat() if locked_user.subscription_until else None,
                })
                yield await _encode({"status": "done"})
                return

            if raw in ("cancelled", "declined", "expired", "rejected", "failed"):
                yield await _encode({"status": "cancelled", "raw": raw})
                yield await _encode({"status": "done"})
                return

            # Всё ещё pending — шлём heartbeat раз в 15 сек чтобы клиент знал что живы.
            now = time.time()
            if now - last_keepalive >= 15:
                yield await _encode({"status": "pending", "elapsed_seconds": round(elapsed, 1)})
                last_keepalive = now

            await asyncio.sleep(interval)

        # Deadline 10 мин — передаём управление payment_monitor.
        yield await _encode({"status": "timeout", "elapsed_seconds": round(time.time() - start, 1)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # отключаем nginx-буферизацию для SSE
        },
    )
