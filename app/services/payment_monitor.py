"""Payment & balance monitoring — запускается внутри cron-контейнера.

Делает три проверки и шлёт Telegram-алерт при проблемах:

1. **Tochka sweep** (B2): для каждой `Transaction` где
   `credited_at IS NULL` И `external_payment_id IS NOT NULL`
   И `created_at < now()-15min` — запрашивает статус у Точки.
   Если `paid` — зачисляем через `_apply_case_purchase` (тот же путь что
   webhook и /confirm-payment, с тем же row lock).

2. **Stuck-payments alert** (B3): если после sweep всё ещё есть
   `credited_at IS NULL` старше 2ч **и** Точка уже вернула `paid`
   — срочный Telegram-алерт. Потому что юзер заплатил, но денег не видит.

3. **Canary: negative balance** (M4): проверяем что нет юзеров с
   `paid_cases_left < 0` или `free_cases_left < 0`. Это не должно
   случиться (БД CHECK + `max(0, ...)` в коде), но если появится —
   значит защита сломалась, шлём критический алерт.

4. **Cleanup old uncredited** (M2): транзакции «Попытка покупки»
   старше 30 дней с `credited_at IS NULL` удаляются (засоряют БД).

Запуск: `python -m app.services.payment_monitor` из cron раз в 15-20 мин.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, text
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import User, Transaction
from app.services.telegram import send_admin, _esc
from app.services.tochka_payment import check_payment_status

from app.utils.datetime import utcnow_naive
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("payment_monitor")


# Адаптивный sweep:
#   * свежие (younger than FRESH_AGE) — проверяем на каждом тике (30 сек)
#   * средние (FRESH_AGE..OLD_AGE) — проверяем если tick % 4 == 0 (раз в 2 мин)
#   * старые (older than OLD_AGE) — проверяем если tick % 20 == 0 (раз в 10 мин)
# Защищает Tochka API от rate-limit при большом количестве «передумавших» попыток,
# но новым платежам даёт мгновенную реакцию.
FRESH_AGE = timedelta(minutes=10)
OLD_AGE = timedelta(hours=2)
STUCK_ALERT_AGE = timedelta(hours=2)
CLEANUP_AGE = timedelta(days=30)


async def _send_alert(text: str) -> None:
    try:
        await send_admin(text)
    except Exception as e:
        log.warning("send_admin failed: %s", e)


async def tochka_sweep(db, tick: int = 0) -> dict:
    """B2: проверить uncredited транзакции в Точке и зачислить paid.

    `tick` — номер запуска в минутах от старта (для адаптивного расписания):
      * свежие (<10 мин) — каждый тик
      * средние (10 мин..2 ч) — каждые 4 тика (~ раз в 2 мин при 30-сек цикле)
      * старые (>2 ч) — каждые 20 тиков (~ раз в 10 мин)
    """
    now = utcnow_naive()
    fresh_cutoff = now - FRESH_AGE
    old_cutoff = now - OLD_AGE

    # Всегда проверяем свежие.
    conds = [Transaction.credited_at.is_(None),
             Transaction.external_payment_id.is_not(None),
             Transaction.type == "purchase"]

    # Адаптивно добавляем средние/старые
    from sqlalchemy import and_, or_
    include_mid = (tick % 4 == 0)
    include_old = (tick % 20 == 0)

    if include_old:
        # все uncredited
        pass
    elif include_mid:
        conds.append(Transaction.created_at >= old_cutoff)
    else:
        conds.append(Transaction.created_at >= fresh_cutoff)

    stmt = select(Transaction).where(*conds).order_by(Transaction.created_at.desc()).limit(100)
    txs = (await db.execute(stmt)).scalars().all()
    stats = {"checked": 0, "paid": 0, "credited": 0, "still_pending": 0, "errors": 0}

    for tx in txs:
        stats["checked"] += 1
        op_id = tx.external_payment_id
        try:
            status = await check_payment_status(op_id)
        except Exception as e:
            log.warning("tochka check failed op=%s: %s", op_id[:16], e)
            stats["errors"] += 1
            continue

        if status.get("status") != "paid":
            stats["still_pending"] += 1
            continue

        stats["paid"] += 1

        # Лочим tx и user — тот же паттерн что webhook/confirm-payment.
        locked_tx = (await db.execute(
            select(Transaction).where(Transaction.id == tx.id).with_for_update()
        )).scalar_one_or_none()
        if not locked_tx or locked_tx.credited_at is not None:
            continue  # кто-то уже закредитил (race с webhook)

        locked_user = (await db.execute(
            select(User).where(User.id == locked_tx.user_id).with_for_update()
        )).scalar_one_or_none()
        if not locked_user:
            log.warning("tochka_sweep: user not found for tx=%s", str(locked_tx.id)[:8])
            continue

        from app.config import get_settings
        _s = get_settings()
        packages = _s.promo_packages if getattr(locked_user, "promo_price", False) else _s.case_packages

        try:
            from app.api.billing import _apply_case_purchase
            _apply_case_purchase(locked_user, locked_tx, packages)
        except Exception as e:
            log.error("tochka_sweep apply failed tx=%s: %s", str(locked_tx.id)[:8], e)
            try:
                await db.rollback()
            except Exception as re:
                log.warning("rollback after apply failure also failed: %s", re)
            stats["errors"] += 1
            continue

        locked_tx.credited_at = utcnow_naive()

        try:
            from app.api.referral import maybe_award_referral_bonus
            await maybe_award_referral_bonus(db, locked_user, locked_tx)
        except Exception as e:
            log.warning("referral bonus failed: %s", e)

        await db.commit()
        stats["credited"] += 1

        await _send_alert(
            f"💳 <b>Новая оплата</b>\n"
            f"Пользователь: {_esc(locked_user.real_name or locked_user.name or '—')}"
            f"{' (display: ' + str(locked_user.display_id) + ')' if locked_user.display_id else ''}\n"
            f"Email: {_esc(locked_user.email or '—')}\n"
            f"Тариф: {_esc(packages.get(locked_tx.purchase_type, {}).get('label', locked_tx.purchase_type))}"
            f" ({locked_tx.amount_kopecks / 100:.0f}₽)\n"
            f"Время: {_esc(locked_tx.created_at.strftime('%d.%m.%Y %H:%M') if locked_tx.created_at else '—')} MSK\n"
            f"Город: {_esc(locked_user.city or '—')}\n"
            f"Промо-цена: {'да' if getattr(locked_user, 'promo_price', False) else 'нет'}\n"
            f"Баланс дел: {(locked_user.paid_cases_left or 0) + (locked_user.free_cases_left or 0)}\n"
            f"Регистрация: {_esc(locked_user.created_at.strftime('%d.%m.%Y') if locked_user.created_at else '—')}\n"
            f"UTM: {_esc(locked_user.utm_source or '—')}\n"
            f"op: {op_id[:16]}"
        )
        log.info("tochka_sweep credited tx=%s user=%s", str(locked_tx.id)[:8], str(locked_user.id)[:8])

    return stats


async def stuck_payments_alert(db) -> int:
    """B3: алерт если Точка сказала paid, но credited_at всё ещё NULL >2ч.

    ВАЖНО: DB-сессия освобождается ДО HTTP-запросов к Tochka, потому что
    проверка каждого tx может быть медленной (таймауты), а PostgreSQL
    закрывает idle connection после ~5 минут, что приводило к crash в
    `async with async_session()` exit (InterfaceError on rollback).
    """
    cutoff = utcnow_naive() - STUCK_ALERT_AGE
    # Читаем только нужные поля, сразу detach'им от сессии.
    stmt = select(
        Transaction.id,
        Transaction.external_payment_id,
        Transaction.user_id,
        Transaction.purchase_type,
        Transaction.amount_kopecks,
    ).where(
        Transaction.credited_at.is_(None),
        Transaction.external_payment_id.is_not(None),
        Transaction.created_at < cutoff,
        Transaction.type == "purchase",
    ).limit(20)
    candidates = (await db.execute(stmt)).all()

    # Коммитим session SELECT (no-op если read-only) чтобы освободить connection.
    await db.commit()

    # HTTP-запросы к Tochka идут БЕЗ DB-lock.
    stuck_paid = []
    for cand in candidates:
        try:
            status = await check_payment_status(cand.external_payment_id)
        except Exception:
            continue
        if status.get("status") == "paid":
            stuck_paid.append(cand)

    if stuck_paid:
        lines = "\n".join(
            f"  • tx={str(c.id)[:8]} user={str(c.user_id)[:8]} {c.purchase_type} {c.amount_kopecks/100:.0f}₽ op={c.external_payment_id[:16]}"
            for c in stuck_paid[:10]
        )
        await _send_alert(
            f"🚨 <b>Платежи зависли: Точка PAID, но не зачислено</b>\n"
            f"Найдено {len(stuck_paid)} tx старше 2ч:\n{lines}\n\n"
            f"Нужно разобраться: webhook не пришёл И /confirm-payment не сработал. "
            f"Проверь <code>docker logs ai-judge-app-1</code> на ошибки billing."
        )
    return len(stuck_paid)


async def canary_negative_balance(db) -> int:
    """M4: алерт если появились юзеры с отрицательным балансом."""
    stmt = select(User.id, User.email, User.paid_cases_left, User.free_cases_left, User.token_balance).where(
        (User.paid_cases_left < 0) | (User.free_cases_left < 0) | (User.token_balance < 0)
    ).limit(20)
    rows = (await db.execute(stmt)).all()
    if rows:
        lines = "\n".join(
            f"  • {str(r.id)[:8]} ({r.email or '—'}) paid={r.paid_cases_left} free={r.free_cases_left} tok={r.token_balance}"
            for r in rows[:10]
        )
        await _send_alert(
            f"🚨 <b>CANARY: user с отрицательным балансом</b>\n"
            f"Найдено {len(rows)}:\n{lines}\n\n"
            f"Это не должно случаться (DB CHECK + max(0, ...) в коде). "
            f"Если сработало — regression, немедленно исследовать."
        )
    return len(rows)


async def cleanup_old_uncredited(db) -> int:
    """M2: DELETE «Попытка покупки» старше 30 дней без credited_at."""
    cutoff = utcnow_naive() - CLEANUP_AGE
    result = await db.execute(
        text("""
            DELETE FROM transactions
            WHERE type = 'purchase'
              AND credited_at IS NULL
              AND created_at < :cutoff
              AND description LIKE 'Попытка покупки%'
            RETURNING id
        """),
        {"cutoff": cutoff},
    )
    deleted = result.rowcount or 0
    if deleted:
        await db.commit()
        log.info("cleanup_old_uncredited: deleted %d rows older than 30 days", deleted)
    return deleted


async def main(tick: int = 0):
    log.info("=" * 60)
    log.info("PAYMENT MONITOR starting (tick=%d)", tick)
    log.info("=" * 60)

    async def _safe_phase(name: str, coro_fn):
        """Выполнить фазу в отдельной сессии, подавить close-errors.

        tochka_sweep + stuck_payments_alert делают долгие HTTP к Tochka внутри
        сессии. PostgreSQL закрывает idle connection >5 min — при exit async
        with SQLAlchemy пытается rollback на мёртвом conn → InterfaceError,
        который обходит внутренний try/except.

        Все реальные commit'ы происходят внутри функций (после каждого
        credit), так что ошибка в cleanup — безвредна.
        """
        db = async_session()
        try:
            result = await coro_fn(db)
            log.info("%s: %s", name, result)
        except Exception as e:
            log.error("%s crashed: %s", name, e)
            if name == "tochka_sweep":
                try:
                    await _send_alert(f"payment_monitor: tochka_sweep crashed — {e}")
                except Exception:
                    pass
        finally:
            try:
                await db.close()
            except Exception as close_err:
                # Соединение уже закрыто PostgreSQL (idle timeout) —
                # commit'ы уже сделаны внутри функций, ничего не теряем.
                log.warning("%s: session close failed (connection dropped, benign): %s", name, close_err)

    await _safe_phase("tochka_sweep", lambda db: tochka_sweep(db, tick=tick))
    await _safe_phase("stuck_payments_alert", stuck_payments_alert)
    await _safe_phase("canary_negative_balance", canary_negative_balance)
    await _safe_phase("cleanup_old_uncredited", cleanup_old_uncredited)

    log.info("PAYMENT MONITOR done")


if __name__ == "__main__":
    import sys
    tick_arg = 0
    if len(sys.argv) > 1:
        try:
            tick_arg = int(sys.argv[1])
        except ValueError:
            pass
    asyncio.run(main(tick_arg))
