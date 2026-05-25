"""Job queue interface — single point for enqueueing generation jobs.

Uses arq (async Redis queue) to decouple generation from web-app lifecycle.
Jobs survive web-app restarts.
"""
import logging
from arq import create_pool
from arq.connections import RedisSettings
from app.config import get_settings
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)


async def get_arq_pool():
    """Get arq Redis connection pool."""
    s = get_settings()
    redis_url = s.redis_url  # redis://:PASSWORD@redis:6379/0
    # Parse Redis URL for arq settings
    # arq uses db=1 to avoid conflicts with app Redis (db=0)
    return await create_pool(RedisSettings.from_dsn(redis_url.replace("/0", "/1")))


async def enqueue_full_pipeline(case_id: str, user_id: str, billing_method: str = ""):
    """Enqueue full pipeline: process files + generate text."""
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "run_generation_job",
        case_id=case_id,
        user_id=user_id,
        pipeline_type="full",
        billing_method=billing_method,
    )
    logger.info("[JOB] Enqueued full pipeline case=%s job=%s", case_id[:8], job.job_id)
    await pool.close()
    return job.job_id


async def enqueue_generate_only(case_id: str, user_id: str, billing_method: str = ""):
    """Enqueue generate-only (context already ready)."""
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "run_generation_job",
        case_id=case_id,
        user_id=user_id,
        pipeline_type="generate_only",
        billing_method=billing_method,
    )
    logger.info("[JOB] Enqueued generate_only case=%s job=%s", case_id[:8], job.job_id)
    await pool.close()
    return job.job_id


async def enqueue_rescue(case_id: str):
    """Enqueue rescue job for a stuck case, pre-billing if possible.

    ─── DO NOT REVERT WITHOUT READING docs/pipeline_handoff.md ─────────
    Reads billing_method from case. If unset AND user has balance,
    determines billing and deducts NOW (same logic /generate would use),
    then writes case.billing_method so the worker generates with proper
    billing. If user has no balance, leaves billing empty and the worker
    (Y.2 stop condition) halts at context_ready — paywall preserved.

    Before this fix, rescue ran without billing, silently gifting 10 paid
    cases to users in the week before 2026-04-22 (~1300 RUB revenue leak).
    Regression signal: rescue_count_with_empty_billing > 0 per 24h.
    ────────────────────────────────────────────────────────────────────
    """
    from app.database import async_session
    from sqlalchemy import text

    actual_billing = ""
    actual_user_id = "system"

    try:
        async with async_session() as db:
            # Postgres does not allow FOR UPDATE on the nullable side of an
            # outer join. Lock the case first, then lock the user row only if
            # a user exists. This keeps rescue billing deterministic.
            row = await db.execute(
                text(
                    "SELECT billing_method, user_id, status "
                    "FROM cases "
                    "WHERE id = cast(:cid as uuid) "
                    "FOR UPDATE"
                ),
                {"cid": case_id},
            )
            r = row.first()
            if r:
                billing_col, user_id_col, status_col = r
                is_vip = sub_until = free_left = paid_left = billing_model = ab_group = None
                user_found = False
                actual_billing = (billing_col or "")
                actual_user_id = str(user_id_col) if user_id_col else "system"

                if user_id_col:
                    user_row = await db.execute(
                        text(
                            "SELECT is_vip, subscription_until, free_cases_left, "
                            "paid_cases_left, billing_model, ab_group "
                            "FROM users "
                            "WHERE id = cast(:uid as uuid) "
                            "FOR UPDATE"
                        ),
                        {"uid": str(user_id_col)},
                    )
                    u = user_row.first()
                    if u:
                        user_found = True
                        (
                            is_vip, sub_until, free_left, paid_left,
                            billing_model, ab_group,
                        ) = u

                # Pre-bill if empty and user has balance — prevents rescue freebies.
                # Skip for completed cases (retry semantics handled elsewhere).
                if not actual_billing and user_id_col and status_col != "completed" and user_found:
                    now = utcnow()
                    resolved = None
                    if is_vip:
                        resolved = "vip"
                    elif billing_model == "cases":
                        if sub_until and sub_until > now:
                            resolved = "subscription"
                        elif (free_left or 0) > 0:
                            await db.execute(
                                text(
                                    "UPDATE users SET free_cases_left = "
                                    "GREATEST(0, COALESCE(free_cases_left, 0) - 1) "
                                    "WHERE id = cast(:uid as uuid)"
                                ),
                                {"uid": str(user_id_col)},
                            )
                            resolved = "free_case"
                        elif (paid_left or 0) > 0:
                            await db.execute(
                                text(
                                    "UPDATE users SET paid_cases_left = "
                                    "GREATEST(0, COALESCE(paid_cases_left, 0) - 1) "
                                    "WHERE id = cast(:uid as uuid)"
                                ),
                                {"uid": str(user_id_col)},
                            )
                            resolved = "paid_case"
                        elif ab_group == "paywall_preview":
                            resolved = "preview"
                        # else: no balance — leave empty, worker Y.2 will halt

                    if resolved:
                        await db.execute(
                            text(
                                "UPDATE cases SET billing_method = :bm, updated_at = NOW() "
                                "WHERE id = cast(:cid as uuid)"
                            ),
                            {"bm": resolved, "cid": case_id},
                        )
                        actual_billing = resolved
                        logger.info(
                            "[RESCUE] pre-billed case=%s user=%s billing=%s",
                            case_id[:8], actual_user_id[:8], resolved,
                        )
                    await db.commit()
                elif actual_billing:
                    # already-billed rescue (normal path): no DB writes here
                    pass
    except Exception as e:
        logger.warning("[JOB] Could not pre-bill rescue case=%s: %s", case_id[:8], e)

    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "run_generation_job",
        case_id=case_id,
        user_id=actual_user_id,
        pipeline_type="rescue",
        billing_method=actual_billing,
    )
    logger.info(
        "[JOB] Enqueued rescue case=%s billing=%s job=%s",
        case_id[:8],
        actual_billing or "none",
        job.job_id,
    )
    await pool.close()
    return job.job_id

async def enqueue_process_and_generate(case_id: str, user_id: str, billing_method: str = ""):
    "Backward-compatible alias for old API code after backup restore."
    return await enqueue_full_pipeline(case_id, user_id, billing_method)
