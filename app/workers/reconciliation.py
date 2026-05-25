"""
reconciliation.py — периодическая проверка что балансы дел совпадают.
Запускается как arq cron job каждые 6 часов.
"""
import logging
from datetime import datetime

logger = logging.getLogger("reconciliation")


async def reconciliation_check(ctx):
    """Сравнивает paid_cases_left с (зачислено - использовано) для платящих юзеров."""
    from app.database import async_session
    from sqlalchemy import text

    logger.info("[RECONCILIATION] Проверка балансов")

    async with async_session() as db:
        rows = await db.execute(text("""
            WITH credited_paid AS (
                -- Купленные кейсы идут в paid_cases_left
                SELECT user_id,
                    SUM(CASE
                        WHEN purchase_type = 'first_case' THEN 1
                        WHEN purchase_type = 'single_case' THEN 1
                        WHEN purchase_type = 'case_pack_5' THEN 5
                        WHEN purchase_type = 'case_pack_10' THEN 10
                        ELSE 0
                    END) as total
                FROM transactions
                WHERE credited_at IS NOT NULL
                    AND type = 'purchase'
                    AND purchase_type IN ('first_case', 'single_case', 'case_pack_5', 'case_pack_10')
                GROUP BY user_id
            ),
            bonuses_free AS (
                -- Бонусы и подарки идут в free_cases_left, НЕ в paid
                SELECT user_id,
                    SUM(CASE
                        WHEN type = 'referral_bonus' THEN 3
                        WHEN type = 'gift' THEN COALESCE(
                            (SELECT bonus_free_cases FROM invite_activations ia WHERE ia.user_id = transactions.user_id LIMIT 1), 0
                        )
                        ELSE 0
                    END) as total
                FROM transactions
                WHERE type IN ('referral_bonus', 'gift')
                GROUP BY user_id
            ),
            used_paid AS (
                -- Гибридный подсчёт: case считается как "paid use" если выполняется ЛЮБОЕ:
                --   (a) cases.billing_method='paid_case' — обычный путь (/generate, rescue-billed)
                --   (b) activity_log.action='generate' + details LIKE '%billing=paid_case%'
                --       И cases.billing_method='retry' — оплата была, но retry переписал поле.
                -- Этим покрываются три сценария:
                --   1. Обычная оплата → billing='paid_case' → (a)
                --   2. Оплата + retry → billing='retry' + history в activity_log → (b)
                --   3. Pre-Apr-logging-era / rescue-billed: billing='paid_case' без generate-log → (a)
                -- DISTINCT case_id предотвращает двойной счёт если case попадает в обе ветки.
                --
                -- DO NOT REVERT to pure cases.billing_method (scenario 2 даёт ложные "-N")
                -- и DO NOT REVERT to pure activity_log (scenario 3 даёт ложные "-N").
                -- История: коммит 0d0ca0f (activity_log-only) → 0d0ca0f+1 (hybrid).
                SELECT user_id, COUNT(*) as cnt
                FROM (
                    SELECT DISTINCT c.user_id, c.id as case_id
                    FROM cases c
                    WHERE c.billing_method = 'paid_case'
                      AND c.status IN ('completed', 'processing', 'error')
                    UNION
                    SELECT DISTINCT al.user_id, al.case_id
                    FROM activity_log al
                    JOIN cases c ON c.id = al.case_id
                    WHERE al.action = 'generate'
                      AND al.details LIKE '%billing=paid_case%'
                      AND c.billing_method = 'retry'
                      AND c.status IN ('completed', 'processing', 'error')
                ) combined
                GROUP BY user_id
            ),
            used_free AS (
                -- Гибридный подсчёт free_case по той же схеме что и used_paid (см. выше).
                SELECT user_id, COUNT(*) as cnt
                FROM (
                    SELECT DISTINCT c.user_id, c.id as case_id
                    FROM cases c
                    WHERE c.billing_method = 'free_case'
                      AND c.status IN ('completed', 'processing', 'error')
                    UNION
                    SELECT DISTINCT al.user_id, al.case_id
                    FROM activity_log al
                    JOIN cases c ON c.id = al.case_id
                    WHERE al.action = 'generate'
                      AND al.details LIKE '%billing=free_case%'
                      AND c.billing_method = 'retry'
                      AND c.status IN ('completed', 'processing', 'error')
                ) combined
                GROUP BY user_id
            )
            SELECT
                u.id, u.name,
                COALESCE(cp.total, 0) as credited_paid,
                COALESCE(up.cnt, 0) as used_paid,
                u.paid_cases_left as balance_paid,
                COALESCE(cp.total, 0) - COALESCE(up.cnt, 0) as expected_paid,

                COALESCE(bf.total, 0) as bonus_free,
                COALESCE(uf.cnt, 0) as used_free,
                u.free_cases_left as balance_free,
                COALESCE(bf.total, 0) - COALESCE(uf.cnt, 0) as expected_free
            FROM users u
            LEFT JOIN credited_paid cp ON cp.user_id = u.id
            LEFT JOIN bonuses_free bf ON bf.user_id = u.id
            LEFT JOIN used_paid up ON up.user_id = u.id
            LEFT JOIN used_free uf ON uf.user_id = u.id
            WHERE u.subscription_until IS NULL  -- пропускаем подписчиков
              AND (
                  -- показываем только реально расходящихся (в одном из балансов)
                  u.paid_cases_left != (COALESCE(cp.total, 0) - COALESCE(up.cnt, 0))
                  OR u.free_cases_left != (COALESCE(bf.total, 0) - COALESCE(uf.cnt, 0))
              )
              AND (
                  -- Алертим только тех, у кого были ЯВНЫЕ credit-записи (покупка или записанный бонус).
                  -- Юзеры с usage без credit'ов — это обычно registration_bonus установленный напрямую
                  -- в users.free_cases_left без transaction. Не алертим, учёт корректен по дизайну.
                  cp.total > 0 OR bf.total > 0
              )
        """))

        discrepancies = rows.fetchall()

        if not discrepancies:
            logger.info("[RECONCILIATION] Балансы в порядке")
            return

        logger.warning("[RECONCILIATION] Расхождения: %d", len(discrepancies))

        # Строим snapshot для дедупликации и готовим строки для алерта.
        alert_lines = []
        current_state = {}  # {user_id_short: (paid_delta, free_delta)}

        for row in discrepancies:
            uid_full = str(row[0])
            uid = uid_full[:8]
            name = row[1] or "\u2014"
            b_paid = row[4]
            e_paid = row[5]
            d_paid = b_paid - e_paid
            b_free = row[8]
            e_free = row[9]
            d_free = b_free - e_free

            parts = []
            if d_paid != 0:
                dir_p = "+" if d_paid > 0 else ""
                parts.append(f"paid {b_paid}!={e_paid} ({dir_p}{d_paid})")
            if d_free != 0:
                dir_f = "+" if d_free > 0 else ""
                parts.append(f"free {b_free}!={e_free} ({dir_f}{d_free})")
            if not parts:
                continue

            current_state[uid] = [d_paid, d_free]
            line = f"  {uid} ({name}): " + ", ".join(parts)
            logger.warning("[RECONCILIATION] %s", line)
            alert_lines.append(line)

        # Dedup: сравним с последним snapshot в Redis.
        # Алертим ТОЛЬКО если состояние изменилось (появились новые расхождения
        # или изменились deltas / часть исправлена).
        should_alert = True
        diff_info = ""
        try:
            import json
            from app.services.redis_stream import get_redis
            r = await get_redis()
            prev_raw = await r.get("reconciliation:last_state")
            prev_state = {}
            if prev_raw:
                try:
                    prev_state = json.loads(prev_raw.decode() if isinstance(prev_raw, bytes) else prev_raw)
                except Exception:
                    prev_state = {}

            # Сравним
            curr_keys = set(current_state.keys())
            prev_keys = set(prev_state.keys())
            new_keys = curr_keys - prev_keys
            fixed_keys = prev_keys - curr_keys
            changed_keys = {k for k in (curr_keys & prev_keys) if prev_state[k] != current_state[k]}

            if not (new_keys or fixed_keys or changed_keys):
                should_alert = False
                logger.info("[RECONCILIATION] state unchanged (%d discrepancies), silent", len(current_state))
            else:
                diffs = []
                if new_keys:
                    diffs.append(f"🆕 новых: {len(new_keys)}")
                if fixed_keys:
                    diffs.append(f"✅ исправлено: {len(fixed_keys)}")
                if changed_keys:
                    diffs.append(f"🔄 изменилось: {len(changed_keys)}")
                diff_info = " (" + ", ".join(diffs) + ")" if diffs else ""

            # Сохраним текущее для следующего раза (24h TTL — state пересоздастся если долго нет кейсов)
            await r.set("reconciliation:last_state", json.dumps(current_state), ex=86400 * 7)
        except Exception as e:
            logger.warning("[RECONCILIATION] dedup state IO failed: %s", e)
            # fall-through — alert отправится всё равно

        # Telegram
        if should_alert:
            try:
                from app.services.telegram import send_admin
                msg = f"\u26a0\ufe0f <b>Сверка балансов:</b> {len(discrepancies)} расхождений{diff_info}\n" + "\n".join(alert_lines[:10])
                await send_admin(msg)
            except Exception:
                pass
