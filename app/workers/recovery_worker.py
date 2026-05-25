"""Recovery worker — periodic job that finds and rescues stuck cases.

Runs as cron job inside arq worker every 2 minutes.
Detects stuck cases by:
- Type A: CaseRun status=running + heartbeat stale (>5 min)
- Type B: Case status=draft + files + old (>5 min) + no active run
- Type C: Case has summary but no generated_text
"""
import asyncio
import os
import json
import logging
import sys
import html
from datetime import datetime, timedelta
from app.utils.datetime import utcnow_naive, utcnow, ensure_utc

sys.path.insert(0, "/app")

logger = logging.getLogger("recovery")

async def _alert(text):
    try:
        from app.services.telegram import send_admin
        await send_admin(text)
    except Exception as e:
        logger.warning("admin alert failed: %s", e)


async def recovery_sweep(ctx):
    """Periodic recovery sweep — finds and rescues stuck cases."""
    from app.database import async_session
    from app.models import Case, CaseRun, User
    from sqlalchemy import select, text, or_, and_
    from sqlalchemy.orm import selectinload

    found = 0
    rescued = 0
    rescued_details = []

    def _rescue_detail(case, user, recovery_type, extra=""):
        cid = str(case.id)[:8] if case else "unknown"
        email = getattr(user, "email", None) or "no-email"
        billing = getattr(case, "billing_method", None) or "-"
        title = (getattr(case, "title", None) or "").replace("\n", " ").strip()
        if len(title) > 70:
            title = title[:67] + "..."
        parts = [f"{recovery_type}", f"case={cid}", f"user={email}", f"billing={billing}"]
        if extra:
            parts.append(extra)
        if title:
            parts.append(f"title={title}")
        return html.escape(" | ".join(parts), quote=False)

    try:
        async with async_session() as db:
            now = utcnow_naive()
            stale_heartbeat = now - timedelta(minutes=5)
            stale_queued = now - timedelta(minutes=15)
            stale_draft = now - timedelta(minutes=10)  # Increased from 5→10; use updated_at below

            # Type A: Running CaseRun with stale heartbeat
            stale_runs = (await db.execute(
                select(CaseRun).where(
                    CaseRun.status == "running",
                    or_(
                        CaseRun.heartbeat_at < stale_heartbeat,
                        CaseRun.heartbeat_at.is_(None),
                    ),
                )
            )).scalars().all()

            for run in stale_runs:
                found += 1
                cid = str(run.case_id)
                logger.info("[RECOVERY] Type A: stale run=%s case=%s stage=%s", str(run.id)[:8], cid[:8], run.stage)
                # Mark run as stale
                run.status = "stale"
                if not run.started_at:
                    run.started_at = run.created_at or now
                if not run.finished_at:
                    run.finished_at = now
                run.error_code = "heartbeat_timeout"
                run.error_message = f"No heartbeat since {run.heartbeat_at}"
                run_case = await db.get(Case, run.case_id)
                if run_case and str(run_case.active_run_id or "") == str(run.id):
                    run_case.active_run_id = None
                await db.commit()

                # Enqueue rescue
                try:
                    from app.services.job_queue import enqueue_rescue
                    await enqueue_rescue(cid)
                    rescued += 1
                    run_user = None
                    if run_case:
                        run_user = await db.get(User, run_case.user_id)
                    rescued_details.append(_rescue_detail(run_case, run_user, "Type A"))
                    logger.info("[RECOVERY] Rescue enqueued for case=%s", cid[:8])
                except Exception as e:
                    logger.error("[RECOVERY] Failed to enqueue rescue case=%s: %s", cid[:8], e)

            # Type A2: queued CaseRun that never started. This covers the
            # crash window after CaseRun commit but before ARQ enqueue/job start.
            stale_queued_runs = (await db.execute(
                select(CaseRun).where(
                    CaseRun.status == "queued",
                    CaseRun.heartbeat_at.is_(None),
                    CaseRun.created_at < stale_queued,
                )
            )).scalars().all()

            for run in stale_queued_runs:
                found += 1
                cid = str(run.case_id)
                logger.info("[RECOVERY] Type A2: stale queued run=%s case=%s", str(run.id)[:8], cid[:8])
                run.status = "stale"
                if not run.started_at:
                    run.started_at = run.created_at or now
                if not run.finished_at:
                    run.finished_at = now
                run.error_code = "queue_timeout"
                run.error_message = "Queued CaseRun never started"
                run_case = await db.get(Case, run.case_id)
                if run_case and str(run_case.active_run_id or "") == str(run.id):
                    run_case.active_run_id = None
                await db.commit()

                try:
                    from app.services.job_queue import enqueue_rescue
                    await enqueue_rescue(cid)
                    rescued += 1
                    run_user = None
                    if run_case:
                        run_user = await db.get(User, run_case.user_id)
                    rescued_details.append(_rescue_detail(run_case, run_user, "Type A2"))
                    logger.info("[RECOVERY] Rescue enqueued for queued case=%s", cid[:8])
                except Exception as e:
                    logger.error("[RECOVERY] Failed to enqueue queued case=%s: %s", cid[:8], e)

            # Type B: Stuck processing cases — but NOT awaiting_generate (user hasn't clicked Generate yet)
            draft_cases = (await db.execute(
                select(Case).options(selectinload(Case.files)).where(
                    Case.status.in_(["processing"]),
                    or_(Case.stage.is_(None), Case.stage != "awaiting_generate"),  # waiting for user is not stuck
                    Case.updated_at < stale_draft,
                )
            )).scalars().all()

            for case in draft_cases:
                cid = str(case.id)
                _u = None
                files = case.files or []
                # Skip cases with no files AND no context - rescue cannot do anything
                has_ctx = bool((case.case_context or {}).get("doc_count", 0))
                if not files and not has_ctx:
                    logger.debug("[RECOVERY] Skip case=%s: no files, no context", cid[:8])
                    continue
                has_gen = case.generated_text and len(case.generated_text or "") > 100
                if has_gen:
                    continue
                # Skip test cases
                if case.title and case.title.startswith("["):
                    continue

                # ─── DO NOT REVERT: billing guard (ported from 47792a0) ─────
                # Skip cases where user has no balance. If we enqueue rescue,
                # Y.1 pre-bill will find nothing, Y.2 will halt the worker,
                # case stays "summary+no text" → next cycle detects same case
                # → infinite loop of pointless rescue jobs + free generation
                # risk if Y.1/Y.2 regress. 26 freebies history (2026-03-23).
                # ────────────────────────────────────────────────────────────
                try:
                    _u = (await db.execute(
                        select(User).where(User.id == case.user_id)
                    )).scalar_one_or_none()
                    if _u and _u.billing_model == "cases" and not _u.is_vip:
                        _has_sub = _u.subscription_until and ensure_utc(_u.subscription_until) > utcnow()
                        _has_credits = (_u.free_cases_left or 0) > 0 or (_u.paid_cases_left or 0) > 0
                        _already_billed = case.billing_method and case.billing_method not in ("free_case", "")
                        if not _has_sub and not _has_credits and not _already_billed:
                            logger.info("[RECOVERY] Skip case=%s: user has no balance", cid[:8])
                            continue
                except Exception as _e:
                    logger.warning("[RECOVERY] balance check failed for case=%s: %s", cid[:8], _e)

                # Check no active run
                active_run = (await db.execute(
                    select(CaseRun).where(
                        CaseRun.case_id == cid,
                        CaseRun.status.in_(["queued", "running"]),
                    )
                )).scalar_one_or_none()

                if active_run:
                    continue  # Has active run, skip

                found += 1
                has_summary = bool((case.case_context or {}).get("summary"))

                if has_summary:
                    logger.info("[RECOVERY] Type C: summary ready, no text case=%s", cid[:8])
                    recovery_type = "Type C"
                else:
                    logger.info("[RECOVERY] Type B: draft+files case=%s files=%d", cid[:8], len(files))
                    recovery_type = "Type B"

                try:
                    from app.services.job_queue import enqueue_rescue
                    await enqueue_rescue(cid)
                    rescued += 1
                    if _u is None:
                        _u = await db.get(User, case.user_id)
                    extra = f"files={len(files)}" if files else ""
                    rescued_details.append(_rescue_detail(case, _u, recovery_type, extra))
                    logger.info("[RECOVERY] Rescue enqueued case=%s", cid[:8])
                except Exception as e:
                    logger.error("[RECOVERY] Failed to enqueue case=%s: %s", cid[:8], e)

            # Type D: cases with generated_text in context_ready/awaiting_generate
            # but stuck in processing. Worker stopped (no billing), case never finalized.
            stuck_ready = (await db.execute(
                select(Case).where(
                    Case.status == "processing",
                    Case.stage.in_(["context_ready", "awaiting_generate"]),
                    Case.generated_text.is_not(None),
                )
            )).scalars().all()
            for sc in stuck_ready:
                scid = str(sc.id)[:8]
                gen_len = len(sc.generated_text or "")
                if gen_len < 100:
                    continue
                # Check no active run
                active = (await db.execute(
                    select(CaseRun).where(
                        CaseRun.case_id == sc.id,
                        CaseRun.status.in_(["queued", "running"]),
                    )
                )).scalar_one_or_none()
                if active:
                    continue
                # Finalize: text exists, no active job — case can be marked completed
                sc.status = "completed"
                sc.stage = "ready"
                sc.active_run_id = None
                logger.info("[RECOVERY] Type D: finalized stuck context_ready case=%s gen_len=%d", scid, gen_len)
                # Close last completed run for consistency
                last_run = (await db.execute(
                    select(CaseRun).where(
                        CaseRun.case_id == sc.id,
                        CaseRun.status == "completed",
                    ).order_by(CaseRun.created_at.desc()).limit(1)
                )).scalar_one_or_none()
                if last_run:
                    sc.active_run_id = last_run.id
                    if not last_run.finished_at:
                        last_run.finished_at = utcnow_naive()
                await db.commit()

        if found > 0:
            logger.info("[RECOVERY] Sweep done: found=%d rescued=%d", found, rescued)
        if rescued > 0:
            if rescued_details:
                rescued_info = "\n".join(f"• {detail}" for detail in rescued_details[:5])
                if len(rescued_details) > 5:
                    rescued_info += f"\n• ...и еще {len(rescued_details) - 5}"
            else:
                rescued_info = "• details missing; see recovery logs"
            await _alert(f"🔧 Перезапущено {rescued} зависших дел:\n{rescued_info}")

        # ── Alert: cases idle in awaiting_generate > 10 min ──────────────
        # These are context-ready, frontend should have called /generate.
        # If they linger, the handoff likely broke — needs investigation.
        idle_awaiting = (await db.execute(
            select(Case).where(
                Case.status == "processing",
                Case.stage == "awaiting_generate",
                Case.updated_at < now - timedelta(minutes=10),
            )
        )).scalars().all()
        for ac in idle_awaiting:
            acid = str(ac.id)[:8]
            idle_min = int((utcnow_naive() - (ac.updated_at or ac.created_at)).total_seconds() / 60)
            logger.warning("[RECOVERY] AWAITING_GENERATE idle case=%s for %d min", acid, idle_min)
            if idle_min >= 10:
                try:
                    from app.config import get_settings as _ags
                    import redis.asyncio as _aredis
                    _as = _ags()
                    _ar = _aredis.from_url(_as.redis_url)
                    _akey = f"recovery:awaiting_alert:{acid}"
                    _aexists = await _ar.get(_akey)
                    if not _aexists:
                        await _ar.set(_akey, "1", ex=3600)
                        await _ar.aclose()
                        await _alert(f"⏳ Дело {acid} ждёт генерацию {idle_min} мин — фронт не вызвал /generate!")
                    else:
                        await _ar.aclose()
                except Exception:
                    await _alert(f"⏳ Дело {acid} ждёт генерацию {idle_min} мин — фронт не вызвал /generate!")

        # Alert on cases stuck in processing > 15 min (possible deadlock).
        # Exclude cases legitimately waiting for user (awaiting_generate or
        # paywalled context_ready) — those are idle, not stuck.
        stuck_cases = (await db.execute(
            select(Case).where(
                Case.status == "processing",
                Case.updated_at < now - timedelta(minutes=15),
            )
        )).scalars().all()
        for sc in stuck_cases:
            scid = str(sc.id)[:8]
            stuck_min = int((utcnow_naive() - (sc.updated_at or sc.created_at)).total_seconds() / 60)

            # Skip cases awaiting user action — not stuck
            if (sc.stage or "") in ("context_ready", "awaiting_generate"):
                _u = (await db.execute(select(User).where(User.id == sc.user_id))).scalar_one_or_none()
                if _u:
                    has_sub = _u.subscription_until and ensure_utc(_u.subscription_until) > utcnow()
                    has_credits = (_u.free_cases_left or 0) > 0 or (_u.paid_cases_left or 0) > 0
                    if not has_sub and not has_credits and not _u.is_vip:
                        # Paywall case — not a real stuck, user is waiting to pay.
                        # Log at debug to avoid log noise, no Telegram alert.
                        logger.debug("[RECOVERY] Paywall-waiting case=%s for %d min (no alert)", scid, stuck_min)
                        continue

            logger.warning("[RECOVERY] STUCK case=%s for %d min", scid, stuck_min)
            if stuck_min >= 15:
                # Anti-spam: only alert once per case per 60 minutes via Redis TTL
                try:
                    from app.config import get_settings as _gs
                    import redis.asyncio as aioredis
                    _s = _gs()
                    _r = aioredis.from_url(_s.redis_url)
                    _key = f"recovery:stuck_alert:{scid}"
                    _alerted = await _r.get(_key)
                    if not _alerted:
                        await _r.set(_key, "1", ex=3600)
                        await _r.aclose()
                        await _alert(f"🚨 Дело {scid} зависло {stuck_min} мин в processing!")
                    else:
                        await _r.aclose()
                except Exception:
                    await _alert(f"🚨 Дело {scid} зависло {stuck_min} мин в processing!")

        # Close transaction explicitly to avoid idle-in-transaction
        await db.commit()

    except Exception as e:
        logger.error("[RECOVERY] Sweep error: %s", e)


async def cleanup_abandoned_sessions(ctx):
    """Clean up upload sessions abandoned for >24 hours.
    Delete associated files from disk and mark session as failed."""
    import logging
    from datetime import datetime, timedelta
    from sqlalchemy import select, update, text
    from app.database import async_session
    from app.models import CaseUploadSession

    logger = logging.getLogger('recovery')

    try:
        async with async_session() as db:
            cutoff = utcnow_naive() - timedelta(hours=24)
            stale = (await db.execute(
                select(CaseUploadSession).where(
                    CaseUploadSession.status.in_(['pending', 'uploading']),
                    CaseUploadSession.last_activity_at < cutoff,
                )
            )).scalars().all()

            for sess in stale:
                logger.warning(f'[CLEANUP] Abandoning upload session {sess.id} case={sess.case_id} files={sess.uploaded_files_count} last_activity={sess.last_activity_at}')
                sess.status = 'failed'
                sess.failed_at = utcnow_naive()
                sess.notes = 'Auto-abandoned: no activity for 24h'

            if stale:
                await db.commit()
                logger.info(f'[CLEANUP] Abandoned {len(stale)} upload sessions')

    except Exception as e:
        logger.error(f'[CLEANUP] Error: {e}')


async def cleanup_old_data(ctx):
    """
    Unified cleanup:
    1. Drafts older than 24h — delete files from disk + DB records
    2. Completed/error older than 30 days — delete files from disk + DB records
    3. Orphaned upload dirs older than 48h — delete from disk
    """
    import os
    import shutil
    from datetime import datetime, timedelta
    from pathlib import Path
    from sqlalchemy import text
    from app.database import async_session

    uploads_dir = "/app/uploads"
    total_files_deleted = 0
    total_bytes_freed = 0

    try:
        async with async_session() as db:
            # ── 1a. Drafts from unpaid users older than 30 min ──
            unpaid_cutoff = utcnow_naive() - timedelta(minutes=30)
            # Unpaid = no subscription, no paid cases, no free cases
            unpaid_draft_files = await db.execute(text(
                "SELECT cf.file_path FROM case_files cf "
                "JOIN cases c ON cf.case_id = c.id "
                "JOIN users u ON c.user_id = u.id "
                "WHERE c.status = 'draft' AND c.created_at < :cutoff "
                "AND (u.subscription_until IS NULL OR u.subscription_until < NOW()) "
                "AND COALESCE(u.free_cases_left, 0) + COALESCE(u.paid_cases_left, 0) = 0"
            ), {"cutoff": unpaid_cutoff})
            unpaid_paths = [r[0] for r in unpaid_draft_files.fetchall() if r[0]]

            for p in unpaid_paths:
                try:
                    if os.path.exists(p):
                        sz = os.path.getsize(p)
                        os.remove(p)
                        total_files_deleted += 1
                        total_bytes_freed += sz
                except Exception:
                    pass

            # Delete DB records for unpaid drafts (FK safe order)
            unpaid_filter = (
                "case_id IN (SELECT c.id FROM cases c JOIN users u ON c.user_id = u.id "
                "WHERE c.status = 'draft' AND c.created_at < :cutoff "
                "AND (u.subscription_until IS NULL OR u.subscription_until < NOW()) "
                "AND COALESCE(u.free_cases_left, 0) + COALESCE(u.paid_cases_left, 0) = 0)"
            )
            await db.execute(text(f"DELETE FROM case_files WHERE {unpaid_filter}"), {"cutoff": unpaid_cutoff})
            await db.execute(text(f"DELETE FROM case_upload_sessions WHERE {unpaid_filter}"), {"cutoff": unpaid_cutoff})
            await db.execute(text(f"DELETE FROM case_runs WHERE {unpaid_filter}"), {"cutoff": unpaid_cutoff})
            r_unpaid = await db.execute(text(
                "DELETE FROM cases c USING users u WHERE c.user_id = u.id "
                "AND c.status = 'draft' AND c.created_at < :cutoff "
                "AND (u.subscription_until IS NULL OR u.subscription_until < NOW()) "
                "AND COALESCE(u.free_cases_left, 0) + COALESCE(u.paid_cases_left, 0) = 0"
            ), {"cutoff": unpaid_cutoff})
            unpaid_draft_count = r_unpaid.rowcount

            # ── 1b. Drafts from paid users older than 24h ──
            draft_cutoff = utcnow_naive() - timedelta(hours=24)

            draft_files_result = await db.execute(text(
                "SELECT cf.file_path FROM case_files cf "
                "JOIN cases c ON cf.case_id = c.id "
                "WHERE c.status = 'draft' AND c.created_at < :cutoff"
            ), {"cutoff": draft_cutoff})
            draft_paths = [r[0] for r in draft_files_result.fetchall() if r[0]]

            for p in draft_paths:
                try:
                    if os.path.exists(p):
                        sz = os.path.getsize(p)
                        os.remove(p)
                        total_files_deleted += 1
                        total_bytes_freed += sz
                except Exception:
                    pass

            # Delete DB records (order: files → sessions → runs → cases, FK safe)
            await db.execute(text(
                "DELETE FROM case_files WHERE case_id IN "
                "(SELECT id FROM cases WHERE status = 'draft' AND created_at < :cutoff)"
            ), {"cutoff": draft_cutoff})
            await db.execute(text(
                "DELETE FROM case_upload_sessions WHERE case_id IN "
                "(SELECT id FROM cases WHERE status = 'draft' AND created_at < :cutoff)"
            ), {"cutoff": draft_cutoff})
            await db.execute(text(
                "DELETE FROM case_runs WHERE case_id IN "
                "(SELECT id FROM cases WHERE status = 'draft' AND created_at < :cutoff)"
            ), {"cutoff": draft_cutoff})
            r_drafts = await db.execute(text(
                "DELETE FROM cases WHERE status = 'draft' AND created_at < :cutoff"
            ), {"cutoff": draft_cutoff})
            draft_count = r_drafts.rowcount

            # ── 2. Completed/error older than 30 days ──
            completed_cutoff = utcnow_naive() - timedelta(days=30)

            # Get file paths
            old_files_result = await db.execute(text(
                "SELECT cf.file_path FROM case_files cf "
                "JOIN cases c ON cf.case_id = c.id "
                "WHERE c.status IN ('completed', 'error') AND c.created_at < :cutoff"
            ), {"cutoff": completed_cutoff})
            old_paths = [r[0] for r in old_files_result.fetchall() if r[0]]

            for p in old_paths:
                try:
                    if os.path.exists(p):
                        sz = os.path.getsize(p)
                        os.remove(p)
                        total_files_deleted += 1
                        total_bytes_freed += sz
                except Exception:
                    pass

            # Delete DB records (order: files -> sessions -> runs -> cases, FK safe)
            await db.execute(text(
                "DELETE FROM case_files WHERE case_id IN "
                "(SELECT id FROM cases WHERE status IN ('completed', 'error') AND created_at < :cutoff)"
            ), {"cutoff": completed_cutoff})
            await db.execute(text(
                "DELETE FROM case_upload_sessions WHERE case_id IN "
                "(SELECT id FROM cases WHERE status IN ('completed', 'error') AND created_at < :cutoff)"
            ), {"cutoff": completed_cutoff})
            await db.execute(text(
                "DELETE FROM case_runs WHERE case_id IN "
                "(SELECT id FROM cases WHERE status IN ('completed', 'error') AND created_at < :cutoff)"
            ), {"cutoff": completed_cutoff})
            r_old = await db.execute(text(
                "DELETE FROM cases WHERE status IN ('completed', 'error') AND created_at < :cutoff"
            ), {"cutoff": completed_cutoff})
            old_count = r_old.rowcount

            await db.commit()

            # ── 3. Orphaned upload dirs (no matching case in DB) ──
            orphan_cutoff = utcnow_naive() - timedelta(hours=48)
            orphan_count = 0
            if os.path.isdir(uploads_dir):
                case_ids_result = await db.execute(text("SELECT id::text FROM cases"))
                known_ids = {r[0] for r in case_ids_result.fetchall()}

                for entry in os.listdir(uploads_dir):
                    dir_path = os.path.join(uploads_dir, entry)
                    if not os.path.isdir(dir_path):
                        continue
                    # Check if dir name looks like UUID and is not in DB
                    if len(entry) == 36 and entry.count('-') == 4 and entry not in known_ids:
                        try:
                            mtime = datetime.utcfromtimestamp(os.path.getmtime(dir_path))
                            if mtime < orphan_cutoff:
                                dir_size = sum(
                                    os.path.getsize(os.path.join(r, f))
                                    for r, _, files in os.walk(dir_path) for f in files
                                )
                                shutil.rmtree(dir_path)
                                orphan_count += 1
                                total_bytes_freed += dir_size
                        except Exception:
                            pass

            # ── Log results ──
            mb_freed = total_bytes_freed / (1024 * 1024)
            if unpaid_draft_count > 0 or draft_count > 0 or old_count > 0 or orphan_count > 0:
                logger.info(
                    "[CLEANUP] unpaid_drafts=%d drafts=%d completed=%d orphans=%d files=%d freed=%.1fMB",
                    unpaid_draft_count, draft_count, old_count, orphan_count, total_files_deleted, mb_freed,
                )
                # Telegram notification
                try:
                    from app.services.telegram import send_admin
                    await send_admin(
                        f"\U0001f9f9 <b>Очистка хранилища</b>\n"
                        f"Черновики неоплаченных (30м): {unpaid_draft_count} дел\n"
                        f"Черновики оплаченных (24ч): {draft_count} дел\n"
                        f"Старые дела (30д): {old_count} дел\n"
                        f"Осиротевшие: {orphan_count} папок\n"
                        f"Освобождено: {mb_freed:.1f} МБ"
                    )
                except Exception:
                    pass

    except Exception as e:
        logger.error("[CLEANUP] Error: %s", e)


async def recover_stale_widget_payments(ctx):
    """Periodic recovery: find stale widget payments and confirm them.

    Runs as arq cron job every 2 minutes.
    Uses Redis lock (recover:widget_payments, 5 min TTL, non-blocking).
    Finds Transaction where type='widget_payment' OR purchase_type='widget_single_case',
    credited_at IS NULL, created_at > 5 min ago.

    For each stale transaction:
    - Checks payment status via Tochka
    - If APPROVED (paid): creates/finds User, creates Case, credits, enqueues generation
    - If rejected/failed: marks credited_at to prevent re-processing
    - Telegram alert on APPROVED-but-not-confirmed (possible bug)

    Batch limit: 50 transactions per run to avoid overload.
    """
    import json as _json_local
    from app.database import async_session
    from app.models import Transaction, User, Case, CaseRun, ActivityLog
    from app.services.tochka_payment import check_payment_status
    from app.services.job_queue import enqueue_full_pipeline
    from app.services.telegram import send_admin
    from app.config import get_settings
    from sqlalchemy import select, or_, exists

    log = logging.getLogger("recovery.widget")

    # ── Redis lock (non-blocking, 5 min TTL) ──
    try:
        import redis.asyncio as aioredis
        s = get_settings()
        redis = aioredis.from_url(s.redis_url)
        acquired = await redis.set("recover:widget_payments", "1", ex=300, nx=True)
        await redis.aclose()
        if not acquired:
            log.debug("[WIDGET-RECOVERY] Another instance running, skip")
            return
    except Exception as e:
        log.warning("[WIDGET-RECOVERY] Redis lock failed, proceeding anyway: %s", e)

    found = 0
    recovered = 0
    rejected = 0
    errors = 0

    try:
        async with async_session() as db:
            now = utcnow_naive()
            cutoff = now - timedelta(minutes=5)

            # Query stale widget transactions:
            # - type='widget_payment' (dedicated enum value)
            # - purchase_type='widget_single_case' (current create-payment path)
            stale_txs = (await db.execute(
                select(Transaction).where(
                    Transaction.credited_at.is_(None),
                    Transaction.external_payment_id.is_not(None),
                    Transaction.created_at < cutoff,
                    or_(
                        Transaction.type == "widget_payment",
                        Transaction.purchase_type == "widget_single_case",
                    ),
                ).order_by(Transaction.created_at.asc()).limit(50)
            )).scalars().all()

            orphaned_paid = (await db.execute(
                select(Transaction, Case, User)
                .join(Case, Transaction.case_id == Case.id)
                .join(User, Transaction.user_id == User.id)
                .where(
                    Transaction.credited_at.is_not(None),
                    Transaction.case_id.is_not(None),
                    Transaction.created_at < cutoff,
                    Case.generated_text.is_(None),
                    Case.status.in_(["draft", "processing"]),
                    or_(
                        Transaction.type == "widget_payment",
                        Transaction.purchase_type == "widget_single_case",
                    ),
                    ~exists().where(
                        CaseRun.case_id == Case.id,
                        CaseRun.status.in_(["queued", "running"]),
                    ),
                )
                .order_by(Transaction.created_at.asc())
                .limit(50)
            )).all()

            if not stale_txs and not orphaned_paid:
                log.debug("[WIDGET-RECOVERY] No stale or orphaned widget payments found")
                return

            log.info(
                "[WIDGET-RECOVERY] Found %d stale widget payments, %d orphaned paid cases",
                len(stale_txs),
                len(orphaned_paid),
            )
            found = len(stale_txs) + len(orphaned_paid)

            async def _enqueue_widget_case_with_run(case: Case, user: User, reason: str) -> str:
                active_run = (await db.execute(
                    select(CaseRun).where(
                        CaseRun.case_id == case.id,
                        CaseRun.status.in_(["queued", "running"]),
                    ).order_by(CaseRun.created_at.desc()).limit(1)
                )).scalar_one_or_none()
                if active_run:
                    log.info(
                        "[WIDGET-RECOVERY] Active run exists case=%s run=%s status=%s reason=%s",
                        str(case.id)[:8],
                        str(active_run.id)[:8],
                        active_run.status,
                        reason,
                    )
                    return active_run.job_id or str(active_run.id)

                run = CaseRun(
                    case_id=case.id,
                    pipeline_type="full",
                    status="queued",
                    stage="queued",
                )
                db.add(run)
                await db.flush()

                case.status = "processing"
                case.stage = "queued"
                case.active_run_id = run.id
                await db.commit()

                try:
                    job_id = await enqueue_full_pipeline(
                        case_id=str(case.id),
                        user_id=str(user.id),
                        billing_method="widget",
                    )
                except Exception:
                    log.exception(
                        "[WIDGET-RECOVERY] Queue enqueue failed case=%s run=%s reason=%s",
                        str(case.id)[:8],
                        str(run.id)[:8],
                        reason,
                    )
                    run.status = "failed"
                    run.error_code = "enqueue_failed"
                    run.error_message = "arq enqueue failed"
                    run.finished_at = utcnow_naive()
                    case.status = "draft"
                    case.stage = None
                    case.active_run_id = None
                    await db.commit()
                    raise

                run.job_id = job_id
                await db.commit()
                return job_id

            for locked_tx, case, user in orphaned_paid:
                tx_id = str(locked_tx.id)[:8]
                try:
                    job_id = await _enqueue_widget_case_with_run(case, user, "orphaned_paid")
                    recovered += 1
                    log.warning(
                        "[WIDGET-RECOVERY] Re-enqueued orphaned paid widget case=%s tx=%s job=%s",
                        str(case.id)[:8],
                        tx_id,
                        job_id,
                    )
                    try:
                        await send_admin(
                            "🔧 <b>Виджет: перезапущена оплаченная генерация</b>\n"
                            f"tx={tx_id}\n"
                            f"user={str(user.id)[:8]}\n"
                            f"case={str(case.id)[:8]}"
                        )
                    except Exception as alert_err:
                        log.warning("[WIDGET-RECOVERY] Orphan alert failed tx=%s: %s", tx_id, alert_err)
                except Exception as e:
                    errors += 1
                    await db.rollback()
                    log.error("[WIDGET-RECOVERY] Failed to re-enqueue orphaned tx=%s: %s", tx_id, e)

            for tx in stale_txs:
                tx_id = str(tx.id)[:8]
                op_id = (tx.external_payment_id or "")[:16]

                try:
                    # a) Check Tochka payment status
                    status_result = await check_payment_status(tx.external_payment_id)
                    payment_status = status_result.get("status", "pending")

                    if payment_status == "paid":
                        # ── APPROVED: confirm (create Case, credit, enqueue) ──

                        # Pessimistic lock to prevent race with webhook/confirm-payment
                        locked_tx = (await db.execute(
                            select(Transaction).where(Transaction.id == tx.id).with_for_update()
                        )).scalar_one_or_none()

                        if not locked_tx or locked_tx.credited_at is not None:
                            log.info("[WIDGET-RECOVERY] tx=%s already credited (race), skip", tx_id)
                            continue

                        # Extract email / title from metadata
                        email = None
                        session_title = None
                        partner_id = str(locked_tx.source_partner_id)[:8] if locked_tx.source_partner_id else None

                        # Prefer JSONB metadata column
                        meta = locked_tx.tx_metadata or {}
                        if isinstance(meta, dict):
                            email = (meta.get("email") or "").strip().lower() or None
                            session_title = meta.get("title")
                            if not partner_id:
                                partner_id = meta.get("source_partner_id")

                        # Fallback: parse description JSON (legacy storage)
                        if not email and locked_tx.description:
                            try:
                                desc_meta = _json_local.loads(locked_tx.description)
                                if isinstance(desc_meta, dict):
                                    email = (desc_meta.get("email") or "").strip().lower() or None
                                    if not session_title:
                                        session_title = desc_meta.get("title")
                            except (_json_local.JSONDecodeError, TypeError):
                                pass

                        # Find or create User by email
                        user = None
                        if email:
                            user_result = await db.execute(
                                select(User).where(User.email == email)
                            )
                            user = user_result.scalar_one_or_none()

                            if not user:
                                user = User(
                                    email=email,
                                    name=email.split("@")[0] if "@" in email else email,
                                    billing_model="cases",
                                    is_active=True,
                                )
                                db.add(user)
                                await db.flush()
                                log.info("[WIDGET-RECOVERY] Created user=%s email=%s", str(user.id)[:8], email)
                        else:
                            # No email — create anonymous user
                            user = User(
                                email=None,
                                name="Widget User (recovery)",
                                billing_model="cases",
                                is_active=True,
                            )
                            db.add(user)
                            await db.flush()
                            log.info("[WIDGET-RECOVERY] Created anonymous user=%s", str(user.id)[:8])

                        # Create Case (only if not already linked)
                        case = None
                        if locked_tx.case_id:
                            case_result = await db.execute(
                                select(Case).where(Case.id == locked_tx.case_id)
                            )
                            case = case_result.scalar_one_or_none()

                        if not case:
                            case = Case(
                                user_id=user.id,
                                title=session_title or "AI-документ виджета (recovery)",
                                status="draft",
                                billing_method="widget",
                            )
                            db.add(case)
                            await db.flush()
                            log.info("[WIDGET-RECOVERY] Created case=%s", str(case.id)[:8])

                        # Credit transaction
                        locked_tx.user_id = user.id
                        locked_tx.case_id = case.id
                        locked_tx.credited_at = utcnow_naive()

                        # Activity log
                        try:
                            db.add(ActivityLog(
                                user_id=user.id,
                                action="widget_payment_recovered",
                                details=(
                                    f"Recovered stale widget payment: tx={tx_id} "
                                    f"op={op_id} case={str(case.id)[:8]} "
                                    f"amount={locked_tx.amount_kopecks / 100:.0f}₽"
                                ),
                                case_id=case.id,
                            ))
                        except Exception as log_err:
                            log.warning("[WIDGET-RECOVERY] ActivityLog failed tx=%s: %s", tx_id, log_err)

                        await db.commit()
                        recovered += 1

                        try:
                            job_id = await _enqueue_widget_case_with_run(case, user, "stale_paid")
                            log.info(
                                "[WIDGET-RECOVERY] Enqueued generation case=%s job=%s",
                                str(case.id)[:8], job_id,
                            )
                        except Exception as gen_err:
                            log.error(
                                "[WIDGET-RECOVERY] Failed to enqueue generation case=%s: %s",
                                str(case.id)[:8], gen_err,
                            )
                            # Non-fatal: case is created, generation can be retried

                        # ── Telegram alert: payment was APPROVED but confirm not called ──
                        try:
                            alert_lines = [
                                f"⚠️ <b>Виджет-платёж APPROVED но confirm не вызван!</b>",
                                f"tx={tx_id}",
                                f"partner={partner_id or '—'}",
                                f"user={str(user.id)[:8]}",
                                f"case={str(case.id)[:8]}",
                                f"op={op_id}",
                            ]
                            if locked_tx.amount_kopecks:
                                alert_lines.append(f"amount={locked_tx.amount_kopecks / 100:.0f}₽")
                            if email:
                                alert_lines.append(f"email={email}")
                            await send_admin("\n".join(alert_lines))
                        except Exception as alert_err:
                            log.warning("[WIDGET-RECOVERY] Alert failed tx=%s: %s", tx_id, alert_err)

                    elif payment_status in ("failed", "rejected", "refunded"):
                        # Mark as processed (credited_at set, but no actual credit)
                        tx.credited_at = utcnow_naive()
                        if tx.user_id:
                            try:
                                db.add(ActivityLog(
                                    user_id=tx.user_id,
                                    action="widget_payment_rejected",
                                    details=(
                                        f"Stale widget payment rejected: tx={tx_id} "
                                        f"op={op_id} status={payment_status}"
                                    ),
                                ))
                            except Exception:
                                pass
                        await db.commit()
                        rejected += 1
                        log.info(
                            "[WIDGET-RECOVERY] tx=%s marked as rejected status=%s",
                            tx_id, payment_status,
                        )

                    else:
                        # Still pending (created, etc.) — leave for next cycle
                        log.debug(
                            "[WIDGET-RECOVERY] tx=%s still pending status=%s",
                            tx_id, payment_status,
                        )

                except Exception as tx_err:
                    log.error("[WIDGET-RECOVERY] Error processing tx=%s: %s", tx_id, tx_err)
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    errors += 1

        # Summary log
        if found > 0:
            log.info(
                "[WIDGET-RECOVERY] Done: found=%d recovered=%d rejected=%d errors=%d",
                found, recovered, rejected, errors,
            )

    except Exception as e:
        log.error("[WIDGET-RECOVERY] Fatal error: %s", e)
