"""Generation worker — runs as separate process, survives web-app restarts.

Start: arq app.workers.generation_worker.WorkerSettings
Docker: separate service in docker-compose.yml

Lifecycle:
1. Claim job from queue
2. Mark CaseRun as running, set worker_id, started_at
3. Heartbeat every 30 sec + stage/progress updates
4. Process files (OCR + extract) if needed
5. Generate text from context
6. Atomic finalize: Case → completed, CaseRun → completed
7. On error: Case → error, CaseRun → failed with error details
"""
import asyncio
import json
import logging
import os
import uuid
import time
from app.services.telegram import send_admin
from app.services.redis_stream import publish_event
from datetime import datetime

from arq import cron
from arq.connections import RedisSettings

import json as _json

class _JSONFormatter(logging.Formatter):
    def format(self, record):
        d = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if hasattr(record, "case_id"): d["case_id"] = record.case_id
        if hasattr(record, "run_id"): d["run_id"] = record.run_id
        if hasattr(record, "worker_id"): d["worker_id"] = record.worker_id
        if hasattr(record, "stage"): d["stage"] = record.stage
        if hasattr(record, "latency_ms"): d["latency_ms"] = record.latency_ms
        if record.exc_info: d["exc"] = self.formatException(record.exc_info)
        return _json.dumps(d, ensure_ascii=False)

_handler = logging.StreamHandler()
_handler.setFormatter(_JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])
logger = logging.getLogger("worker")

WORKER_ID = f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
HEARTBEAT_INTERVAL = 30  # seconds


async def _update_run(case_id, stage=None, progress=None, status=None, error_code=None, error_msg=None, pipeline_type=None, run_id=None):
    """Update CaseRun with heartbeat, stage, progress.

    Prefer explicit run_id when available. Falls back to subquery on
    (case_id, pipeline_type) to avoid updating the wrong run when
    multiple pipeline types are active for the same case.
    """
    import sys
    sys.path.insert(0, "/app")
    try:
        from app.database import async_session
        from sqlalchemy import text
        async with async_session() as db:
            parts = ["heartbeat_at = NOW()"]
            params = {"cid": case_id, "wid": WORKER_ID}
            if stage:
                parts.append("stage = :stage")
                params["stage"] = stage
            if progress is not None:
                parts.append("progress_pct = :pct")
                params["pct"] = progress
            if status:
                parts.append("status = :st")
                params["st"] = status
                if status == "running":
                    parts.append("started_at = COALESCE(started_at, NOW())")
                elif status in ("completed", "failed", "stale", "cancelled"):
                    parts.append("finished_at = COALESCE(finished_at, NOW())")
            if error_code:
                parts.append("error_code = :ec")
                params["ec"] = error_code
            if error_msg:
                parts.append("error_message = :em")
                params["em"] = str(error_msg)[:500]
            if pipeline_type:
                parts.append("pipeline_type = :pt")
                params["pt"] = pipeline_type
            parts.append("worker_id = :wid")
            set_clause = ", ".join(parts)

            if run_id:
                where_clause = "id = cast(:rid as uuid)"
                params["rid"] = run_id
            else:
                where_clause = (
                    "id = (SELECT id FROM case_runs WHERE case_id = cast(:cid as uuid)"
                    " AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1)"
                )
            await db.execute(text(
                f"UPDATE case_runs SET {set_clause} WHERE {where_clause}"
            ), params)
            await db.commit()
    except Exception as e:
        logger.warning("[HEARTBEAT] Error: %s", e)


async def _log_activity(case_id, user_id, action, details=""):
    """Write to activity_log."""
    import sys
    sys.path.insert(0, "/app")
    try:
        from app.database import async_session
        from sqlalchemy import text
        async with async_session() as db:
            # Resolve user_id if system
            if user_id == "system":
                row = await db.execute(text("SELECT user_id FROM cases WHERE id = cast(:cid as uuid)"), {"cid": case_id})
                uid = str(row.scalar())
            else:
                uid = user_id
            await db.execute(text(
                "INSERT INTO activity_log (user_id, action, details, case_id) VALUES (cast(:uid as uuid), :action, :details, cast(:cid as uuid))"
            ), {"uid": uid, "action": action, "details": details, "cid": case_id})
            await db.commit()
    except Exception as e:
        logger.warning("[ACTIVITY] Log error: %s", e)


async def _heartbeat_loop(case_id, stop_event):
    """Background heartbeat every 30 seconds."""
    while not stop_event.is_set():
        await _update_run(case_id)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def run_generation_job(ctx, *, case_id: str, user_id: str, pipeline_type: str, billing_method: str):
    """Main job: process files + generate text for a case."""
    import sys
    sys.path.insert(0, "/app")

    from app.database import async_session
    from app.models import Case
    from sqlalchemy import select, text
    from sqlalchemy.orm import selectinload

    start_time = time.time()
    logger.info("[JOB] START case=%s pipeline=%s worker=%s", case_id[:8], pipeline_type, WORKER_ID)

    # ── Distributed lock: prevent duplicate processing of same case ──
    import redis as _redis
    _redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    _rconn = _redis.from_url(_redis_url)
    _lock_key = f"job_lock:{case_id}"
    _lock = _rconn.lock(_lock_key, timeout=3600, blocking=False)
    if not _lock.acquire():
        logger.warning("[JOB] SKIP duplicate job for case=%s — already locked", case_id[:8])
        return {"status": "skipped", "reason": "duplicate"}
    logger.info("[JOB] Acquired lock for case=%s", case_id[:8])

    # Step 1: Claim — mark run as running
    # Ensure CaseRun exists (fallback if enqueued without API).
    # Capture run_id once — all subsequent _update_run calls must use this ID
    # to avoid updating a wrong run when multiple runs exist for the same case.
    worker_run_id = None
    try:
        from app.database import async_session as _as_init
        from sqlalchemy import text as _t_init
        async with _as_init() as db_init:
            existing = await db_init.execute(_t_init(
                "SELECT id FROM case_runs WHERE case_id = cast(:cid as uuid) AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
            ), {"cid": case_id})
            row = existing.scalar()
            if row:
                worker_run_id = str(row)
            else:
                import uuid as _uuid
                worker_run_id = str(_uuid.uuid4())
                await db_init.execute(_t_init(
                    "INSERT INTO case_runs (id, case_id, pipeline_type, status, stage, worker_id, created_at) "
                    "VALUES (cast(:rid as uuid), cast(:cid as uuid), :ptype, 'queued', 'starting', :wid, NOW())"
                ), {"rid": worker_run_id, "cid": case_id, "ptype": pipeline_type, "wid": WORKER_ID})
                await db_init.commit()
                logger.info("[JOB] Created missing CaseRun for case=%s run=%s", case_id[:8], worker_run_id[:8])
    except Exception as e:
        logger.warning("[JOB] CaseRun fallback creation error: %s", e)

    logger.info("[JOB] STEP 1: update_run starting case=%s run=%s", case_id[:8], worker_run_id[:8] if worker_run_id else "?")
    await _update_run(case_id, stage="starting", status="running", progress=0, run_id=worker_run_id)
    logger.info("[JOB] STEP 1: done")
    # Set active_run_id on case
    if worker_run_id:
        try:
            from app.database import async_session as _as2
            from sqlalchemy import text as _t2
            async with _as2() as db2:
                await db2.execute(_t2("UPDATE cases SET active_run_id = cast(:rid as uuid), updated_at = NOW() WHERE id = cast(:cid as uuid)"), {"rid": worker_run_id, "cid": case_id})
                await db2.commit()
        except Exception:
            pass
    await _log_activity(case_id, user_id, "worker_start", f"pipeline={pipeline_type} worker={WORKER_ID}")

    # Step 2: Start heartbeat loop
    logger.info("[JOB] STEP 2: heartbeat case=%s", case_id[:8])
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat_loop(case_id, stop_heartbeat))

    try:
        # Step 3: Load case
        logger.info("[JOB] STEP 3: loading case=%s from DB", case_id[:8])
        async with async_session() as db:
            case = (await db.execute(
                select(Case).options(selectinload(Case.files)).where(Case.id == case_id)
            )).scalar_one_or_none()

            if not case:
                logger.error("[JOB] Case not found: %s", case_id[:8])
                await _update_run(case_id, status="failed", error_code="not_found", error_msg="Case not found", run_id=worker_run_id)
                return {"status": "error", "error": "Case not found"}

            files = case.files or []
            case_ctx = case.case_context or {}
            has_summary = bool(case_ctx.get("summary"))
            logger.info("[JOB] STEP 3: loaded case=%s files=%d ctx_size=%d has_summary=%s", case_id[:8], len(files), len(str(case_ctx)), has_summary)

        # Step 4: Process files (OCR + extract) with checkpoint resumption
        if files:
            # Wait briefly for any in-flight chunk uploads to complete
            await asyncio.sleep(5)
            # Re-read files in case more arrived during wait
            async with async_session() as _wait_db:
                _fresh = (await _wait_db.execute(
                    select(Case).options(selectinload(Case.files)).where(Case.id == case_id)
                )).scalar_one()
                files = _fresh.files or []
            logger.info("[JOB] Files after wait: %d", len(files))

            await _update_run(case_id, stage="ocr_running", progress=10, run_id=worker_run_id)
            await _log_activity(case_id, user_id, "worker_process_start", f"files={len(files)}")
            logger.info("[JOB] Processing %d files", len(files))

            from app.services.ingest import process_batch_streaming, get_unprocessed_files
            from app.services.case_context import empty_context
            from app.models import CaseFile

            process_ctx = case_ctx if case_ctx.get("doc_count", 0) > 0 else empty_context()

            async with async_session() as db:
                case = (await db.execute(
                    select(Case).options(selectinload(Case.files)).where(Case.id == case_id)
                )).scalar_one()
                sorted_files = sorted(case.files, key=lambda x: (x.sort_order or 0))

                # --- Checkpoint OCR: check which files already have ocr_text ---
                files_needing_ocr = []
                files_with_cached_ocr = []
                for cf in sorted_files:
                    if cf.ocr_text and len(cf.ocr_text.strip()) > 0:
                        files_with_cached_ocr.append(cf)
                        logger.info("[CHECKPOINT] File %s already has OCR text (%d chars), skipping OCR",
                                    cf.filename, len(cf.ocr_text))
                    else:
                        files_needing_ocr.append(cf)

                if files_with_cached_ocr:
                    logger.info("[CHECKPOINT] Resuming: %d files cached, %d need OCR",
                                len(files_with_cached_ocr), len(files_needing_ocr))

            # Get unprocessed files (not yet in case_context)
            unprocessed = get_unprocessed_files(sorted_files, process_ctx)

            if unprocessed:
                logger.info("[JOB] OCR+extract %d unprocessed files", len(unprocessed))
                file_checkpoints = {}
                async for sse_event in process_batch_streaming(case_id, unprocessed, process_ctx, emit_checkpoints=True):
                    # Publish processing progress to Redis for SSE clients
                    if sse_event.startswith("data: "):
                        json_str = sse_event[6:].strip()
                        try:
                            payload = json.loads(json_str)
                        except json.JSONDecodeError:
                            logger.warning("[SSE] Invalid JSON progress payload case=%s payload=%s", case_id[:8], json_str[:160])
                            continue
                        if payload.get("type") == "doc_checkpoint":
                            filename = payload.get("filename")
                            if filename:
                                file_checkpoints[filename] = payload
                            continue
                        await publish_event(case_id, payload)

                # Re-read context from DB (compile_summary inside generator creates new dict)
                async with async_session() as _reread_db:
                    _reread_case = (await _reread_db.execute(
                        select(Case).where(Case.id == case_id)
                    )).scalar_one()
                    if _reread_case.case_context and _reread_case.case_context.get("summary"):
                        process_ctx = _reread_case.case_context
                        logger.info("[JOB] Re-read context from DB: summary=%s", bool(process_ctx.get("summary")))

                # --- After OCR batch: save ocr_text checkpoint + delete original file ---
                _cleanup_count = 0
                _cleanup_bytes = 0
                async with async_session() as db:
                    case = (await db.execute(
                        select(Case).options(selectinload(Case.files)).where(Case.id == case_id)
                    )).scalar_one()
                    for cf in case.files:
                        doc_match = None
                        for doc in process_ctx.get("documents", []):
                            if doc.get("filename") == cf.filename or doc.get("file_path") == cf.file_path:
                                doc_match = doc
                                break

                        if doc_match and cf.ocr_status != "completed":
                            ocr_chars = int(doc_match.get("ocr_chars", 0) or 0)
                            full_ocr = doc_match.get("ocr_text", "")  # may be absent (only hash stored)
                            if ocr_chars > 0:
                                cf.ocr_status = "completed"
                                cf.ocr_chars = ocr_chars
                                if full_ocr:
                                    cf.ocr_text = full_ocr
                                logger.info("[CHECKPOINT] Saved OCR for %s (%d chars)", cf.filename, ocr_chars)
                            else:
                                cf.ocr_status = "error"
                                logger.warning("[CHECKPOINT] OCR returned 0 chars for %s", cf.filename)
                            await db.flush()

                            # Delete original file from disk
                            try:
                                file_path = cf.file_path
                                if file_path and os.path.exists(file_path):
                                    fsize = os.path.getsize(file_path)
                                    os.remove(file_path)
                                    _cleanup_count += 1
                                    _cleanup_bytes += fsize
                                    logger.info("[CLEANUP-FILE] Deleted %s (%.2f MB)", cf.filename, fsize / 1048576)
                                else:
                                    logger.info("[CLEANUP-FILE] Already gone: %s", cf.filename)
                            except OSError as e:
                                logger.warning("[CLEANUP-FILE] FAILED %s: %s", cf.filename, e)
                        elif cf.filename in file_checkpoints and cf.ocr_status != "completed":
                            checkpoint = file_checkpoints[cf.filename]
                            cf.ocr_status = checkpoint.get("ocr_status") or "error"
                            cf.ocr_chars = int(checkpoint.get("ocr_chars") or 0)
                            full_ocr = checkpoint.get("ocr_text") or ""
                            if full_ocr:
                                cf.ocr_text = full_ocr
                            logger.warning(
                                "[CHECKPOINT] Saved failed OCR/extract checkpoint for %s status=%s code=%s chars=%d",
                                cf.filename,
                                cf.ocr_status,
                                checkpoint.get("error_code", "extract_error"),
                                cf.ocr_chars or 0,
                            )
                            await db.flush()

                    await db.commit()
                    logger.info("[CLEANUP-FILE] case=%s files_deleted=%d freed=%.2f MB", case_id[:8], _cleanup_count, _cleanup_bytes / 1048576)

            # Save context
            await _update_run(case_id, stage="context_building", progress=50, run_id=worker_run_id)
            ctx_json = json.dumps(process_ctx, ensure_ascii=False, default=str)
            async with async_session() as db:
                await db.execute(text(
                    "UPDATE cases SET case_context = cast(:ctx as jsonb), stage = 'context_ready', updated_at = NOW() WHERE id = cast(:cid as uuid)"
                ), {"ctx": ctx_json, "cid": case_id})
                await db.commit()

            doc_count = process_ctx.get("doc_count", 0)
            logger.info("[JOB] Context saved: docs=%d", doc_count)
            await _update_run(case_id, stage="context_ready", progress=60, run_id=worker_run_id)
            await _log_activity(case_id, user_id, "worker_process_complete", f"docs={doc_count}")
            case_ctx = process_ctx

        # Step 5: Generate (with generated_text checkpoint)
        #
        # ─── DO NOT REVERT WITHOUT READING docs/pipeline_handoff.md ─────────
        # Stop if pipeline is "full" (from /process, frontend must call /generate)
        # OR "rescue" without billing (recovery should not generate for free —
        # the whole bug of vlad_s-pb@mail.ru 2026-04-22 was exactly this:
        # rescue ran silently and gave away paid cases without deducting).
        # ────────────────────────────────────────────────────────────────────
        if pipeline_type in ("full", "rescue") and billing_method in ("preview", None, ""):
            doc_count = case_ctx.get("doc_count", 0)
            logger.info("[JOB] STOP after processing (%s pipeline, no billing). case=%s docs=%d",
                        pipeline_type, case_id[:8], doc_count)

            # Guard: if files were uploaded but OCR/extract produced nothing,
            # don't pretend context is ready — user would pay and get an error.
            if doc_count == 0 and len(files) > 0:
                # Distinguish: OCR ran (ocr_text exists) vs OCR failed entirely
                ocr_chars = sum(len(getattr(cf, 'ocr_text', '') or '') for cf in sorted_files)
                if ocr_chars > 0:
                    detail = f"OCR successful ({ocr_chars} chars) but text extraction produced 0 documents"
                    logger.warning("[JOB] docs=0 after OCR+extract (extract parse failed, %d chars ocr_text) — setting error", ocr_chars)
                else:
                    detail = "OCR produced no text from uploaded files"
                    logger.warning("[JOB] docs=0 after OCR (no text) — setting error")
                async with async_session() as edb:
                    await edb.execute(text(
                        "UPDATE cases SET status = 'error', stage = 'extract_failed',"
                        " error_message = :msg, updated_at = NOW() WHERE id = cast(:cid as uuid)"
                    ), {"cid": case_id, "msg": detail})
                    await edb.commit()
                await _update_run(case_id, stage="extract_failed", status="failed",
                                  error_code="empty_extract", error_msg=detail, run_id=worker_run_id)
                await _log_activity(case_id, user_id, "worker_extract_empty",
                                    f"files={len(files)} docs=0 ocr_chars={ocr_chars}")
                from app.services.redis_stream import set_stream_status
                await set_stream_status(case_id, status="error", error=detail)
                return {"status": "error", "reason": "empty_extract"}

            async with async_session() as db:
                await db.execute(text(
                    "UPDATE cases SET status = 'processing', stage = 'awaiting_generate', updated_at = NOW() WHERE id = cast(:cid as uuid)"
                ), {"cid": case_id})
                await db.commit()
            await _update_run(case_id, stage="ready", progress=60, status="completed", pipeline_type="process_only", run_id=worker_run_id)
            elapsed = int(time.time() - start_time)
            await _log_activity(case_id, user_id, "worker_process_only_complete",
                                f"docs={case_ctx.get('doc_count', 0)} elapsed={elapsed}s")
            # Emit batch_done so frontend knows processing is finished
            from app.services.redis_stream import set_stream_status
            await set_stream_status(case_id, status='batch_done')
            return {"status": "ready", "reason": "awaiting_generate"}

        logger.info("[JOB] STEP 5: generate case=%s has_summary=%s", case_id[:8], bool(case_ctx.get("summary")))
        if case_ctx.get("summary"):
            # --- Checkpoint: skip generation if already done ---
            async with async_session() as db:
                case = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one()
                if case.generated_text and len(case.generated_text.strip()) > 100:
                    logger.info("[CHECKPOINT] generated_text already exists (%d chars), skipping generation",
                                len(case.generated_text))
                    result = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}
                    tokens = 0
                    gen_len = len(case.generated_text)

                    await _update_run(case_id, stage="validating", progress=90, run_id=worker_run_id)
                    async with async_session() as db2:
                        await db2.execute(text(
                            "UPDATE cases SET stage = 'ready', status = 'completed', updated_at = NOW() WHERE id = cast(:cid as uuid)"
                        ), {"cid": case_id})
                        await db2.commit()

                    elapsed = int(time.time() - start_time)
                    await _update_run(case_id, stage="ready", progress=100, status="completed", run_id=worker_run_id)
                    try:
                        async with async_session() as fdb:
                            await fdb.execute(text(
                                "UPDATE cases SET active_run_id = NULL, last_successful_run_id = (SELECT id FROM case_runs WHERE case_id = cast(:cid as uuid) AND status = 'completed' ORDER BY created_at DESC LIMIT 1), updated_at = NOW() WHERE id = cast(:cid as uuid)"
                            ), {"cid": case_id})
                            await fdb.commit()
                    except Exception:
                        pass
                    await _log_activity(case_id, user_id, "worker_generate_complete",
                                        f"tokens=0 chars={gen_len} elapsed={elapsed}s (checkpoint)")
                    logger.info("[JOB] DONE (checkpoint) case=%s chars=%d elapsed=%ds", case_id[:8], gen_len, elapsed)
                    return {"status": "completed", "tokens": 0}

            await _update_run(case_id, stage="generating", progress=70, run_id=worker_run_id)
            # Reset stream status so reconnecting SSE clients don't see stale batch_done
            # and terminate the stream before generation chunks arrive.
            from app.services.redis_stream import set_stream_status
            await set_stream_status(case_id, "processing")
            await _log_activity(case_id, user_id, "worker_generate_start", f"pipeline={pipeline_type}")
            logger.info("[JOB] STEP 5b: calling DeepSeek generate case=%s", case_id[:8])

            from app.services.generate_from_context import generate_from_context

            async with async_session() as db:
                case = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one()
                case.status = "processing"
                case.stage = "generating"
                await db.commit()
                result = await generate_from_context(case_id, case, db)
                await db.commit()

            tokens = result.get("total_tokens", 0)
            # Save usage to CaseRun — full cost breakdown
            try:
                from app.config import get_settings as _get_settings
                _cfg = _get_settings()
                _prompt_tok = result.get("prompt_tokens", result.get("usage", {}).get("prompt_tokens", 0))
                _compl_tok = result.get("completion_tokens", result.get("usage", {}).get("completion_tokens", 0))
                # Count OCR files
                _ocr_files = 0
                try:
                    async with async_session() as _cdb:
                        _ocr_row = await _cdb.execute(text(
                            "SELECT count(*) FROM case_files WHERE case_id = cast(:cid as uuid) AND ocr_status = 'completed'"
                        ), {"cid": case_id})
                        _ocr_files = _ocr_row.scalar() or 0
                except Exception:
                    pass
                _ocr_cost_rub = _ocr_files * _cfg.ocr_cost_per_page_rub
                _ds_cost_rub = _prompt_tok * _cfg.ds_cost_per_input_token + _compl_tok * _cfg.ds_cost_per_output_token
                _total_cost_rub = _ocr_cost_rub + _ds_cost_rub
                usage = {
                    "prompt_tokens": _prompt_tok,
                    "completion_tokens": _compl_tok,
                    "total_tokens": tokens,
                    "ocr_files": _ocr_files,
                    "ocr_cost_rub": round(_ocr_cost_rub, 2),
                    "deepseek_cost_rub": round(_ds_cost_rub, 2),
                    "total_cost_rub": round(_total_cost_rub, 2),
                }
                logger.info("[JOB] Cost case=%s: ocr=%d files (%.1f rub) ds=%.1f rub total=%.1f rub",
                            case_id[:8], _ocr_files, _ocr_cost_rub, _ds_cost_rub, _total_cost_rub)
                async with async_session() as udb:
                    await udb.execute(text(
                        "UPDATE case_runs SET usage_json = cast(:usage as jsonb) WHERE id = (SELECT id FROM case_runs WHERE case_id = cast(:cid as uuid) AND status = 'running' ORDER BY created_at DESC LIMIT 1)"
                    ), {"usage": json.dumps(usage), "cid": case_id})
                    await udb.commit()
            except Exception:
                pass
            gen_len = len(case.generated_text or "") if hasattr(case, "generated_text") else 0

            # Step 6: Atomic finalize
            await _update_run(case_id, stage="validating", progress=90, run_id=worker_run_id)
            async with async_session() as db:
                await db.execute(text(
                    "UPDATE cases SET stage = 'ready', status = 'completed', updated_at = NOW() WHERE id = cast(:cid as uuid)"
                ), {"cid": case_id})
                await db.commit()

            elapsed = int(time.time() - start_time)
            await _update_run(case_id, stage="ready", progress=100, status="completed", run_id=worker_run_id)
            # Update case: clear active_run_id, set last_successful_run_id
            try:
                async with async_session() as fdb:
                    await fdb.execute(text(
                        "UPDATE cases SET active_run_id = NULL, last_successful_run_id = (SELECT id FROM case_runs WHERE case_id = cast(:cid as uuid) AND status = 'completed' ORDER BY created_at DESC LIMIT 1), updated_at = NOW() WHERE id = cast(:cid as uuid)"
                    ), {"cid": case_id})
                    await fdb.commit()
            except Exception:
                pass
            await _log_activity(case_id, user_id, "worker_generate_complete", f"tokens={tokens} chars={gen_len} elapsed={elapsed}s")
            logger.info("[JOB] DONE case=%s tokens=%d chars=%d elapsed=%ds", case_id[:8], tokens, gen_len, elapsed)
            return {"status": "completed", "tokens": tokens}
        else:
            # Summary missing — auto-rebuild instead of failing
            logger.warning("[JOB] No summary for case=%s, rebuilding...", case_id[:8])
            try:
                from app.services.ingest import compile_summary
                case_ctx = await compile_summary(case_ctx)
                # Save rebuilt context
                async with async_session() as rebuild_db:
                    import json as _json
                    from sqlalchemy import text as _rebuild_text
                    await rebuild_db.execute(
                        _rebuild_text("UPDATE cases SET case_context = cast(:ctx as jsonb), updated_at = NOW() WHERE id = cast(:cid as uuid)"),
                        {"ctx": _json.dumps(case_ctx, ensure_ascii=False, default=str), "cid": case_id}
                    )
                    await rebuild_db.commit()
                if case_ctx.get("summary"):
                    logger.info("[JOB] Summary rebuilt for case=%s, retrying generation", case_id[:8])
                    await _log_activity(case_id, user_id, "worker_summary_rebuilt", "auto-rebuild OK")
                    # Re-enqueue this job to retry with the rebuilt summary
                    from app.services.job_queue import enqueue_generate_only
                    await enqueue_generate_only(case_id, user_id, billing_method=billing_method)
                    return {"status": "requeued", "reason": "summary_rebuilt"}
                else:
                    error = "Summary rebuild failed — still empty"
                    logger.error("[JOB] %s case=%s", error, case_id[:8])
                    await _update_run(case_id, status="failed", error_code="no_summary", error_msg=error, run_id=worker_run_id)
                    await _log_activity(case_id, user_id, "worker_error", error)
                    try:
                        asyncio.ensure_future(send_admin("Worker error: " + case_id[:8] + " " + error))
                    except: pass
            except Exception as rebuild_err:
                error = f"Summary rebuild error: {rebuild_err}"
                logger.error("[JOB] %s case=%s", error, case_id[:8])
                await _update_run(case_id, status="failed", error_code="no_summary", error_msg=error, run_id=worker_run_id)
                await _log_activity(case_id, user_id, "worker_error", error)
                try:
                    asyncio.ensure_future(send_admin("Worker error: " + case_id[:8] + " " + str(rebuild_err)[:100]))
                except: pass
            try:
                async with async_session() as db:
                    await db.execute(text(
                        "UPDATE cases SET status = 'error', stage = 'failed', updated_at = NOW() WHERE id = cast(:cid as uuid)"
                    ), {"cid": case_id})
                    await db.commit()
            except: pass
            return {"status": "error", "error": error}

    except Exception as e:
        elapsed = int(time.time() - start_time)
        logger.error("[JOB] FAILED case=%s after %ds: %s", case_id[:8], elapsed, e, exc_info=True)
        await _update_run(case_id, status="failed", error_code="exception", error_msg=str(e), run_id=worker_run_id)
        try:
            async with async_session() as edb:
                await edb.execute(text("UPDATE cases SET active_run_id = NULL, updated_at = NOW() WHERE id = cast(:cid as uuid)"), {"cid": case_id})
                await edb.commit()
        except Exception:
            pass
        await _log_activity(case_id, user_id, "worker_error", f"{str(e)[:200]} elapsed={elapsed}s")
        try:
            asyncio.ensure_future(send_admin(f"Worker error: {case_id[:8]}"))
        except: pass
        try:
            from app.database import async_session
            from sqlalchemy import text
            async with async_session() as db:
                await db.execute(text(
                    "UPDATE cases SET status = 'error', stage = 'failed', updated_at = NOW() WHERE id = cast(:cid as uuid)"
                ), {"cid": case_id})
                await db.commit()
        except Exception:
            pass
        return {"status": "error", "error": str(e)}

    finally:
        # Stop heartbeat
        stop_heartbeat.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        # Release distributed lock
        try:
            _lock.release()
            logger.info("[JOB] Released lock for case=%s", case_id[:8])
        except Exception:
            pass


async def startup(ctx):
    """Worker startup hook."""
    logger.info("[WORKER] Started: %s", WORKER_ID)
    await _validate_raw_sql()


async def on_job_error(ctx, job):
    """Called when job fails after all retries — dead-letter logging."""
    logger.error("[DEAD-LETTER] Job %s failed after all retries: %s", job.job_id, job.kwargs)
    # Alert admin
    try:
        from app.services.telegram import send_admin
        case_id = job.kwargs.get("case_id", "?")[:8]
        await send_admin(f"🚨 Dead-letter: case={case_id} failed after all retries")
    except Exception as e:
        logger.warning("admin alert failed: %s", e)


async def shutdown(ctx):
    """Worker shutdown hook."""
    logger.info("[WORKER] Stopping: %s", WORKER_ID)


def get_redis_settings():
    """Get Redis settings from env."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return RedisSettings.from_dsn(redis_url.replace("/0", "/1"))



async def _validate_raw_sql():
    """Validate all raw SQL queries at startup using EXPLAIN."""
    from app.database import async_session
    from sqlalchemy import text
    import logging
    log = logging.getLogger("worker.sql_check")

    test_queries = [
        "UPDATE case_runs SET heartbeat_at = NOW(), worker_id = 'test' WHERE id = (SELECT id FROM case_runs WHERE case_id = cast('00000000-0000-0000-0000-000000000000' as uuid) AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1)",
        "UPDATE case_runs SET usage_json = cast('{}' as jsonb) WHERE id = (SELECT id FROM case_runs WHERE case_id = cast('00000000-0000-0000-0000-000000000000' as uuid) AND status = 'running' ORDER BY created_at DESC LIMIT 1)",
        "UPDATE cases SET active_run_id = NULL, last_successful_run_id = (SELECT id FROM case_runs WHERE case_id = cast('00000000-0000-0000-0000-000000000000' as uuid) AND status = 'completed' ORDER BY created_at DESC LIMIT 1) WHERE id = cast('00000000-0000-0000-0000-000000000000' as uuid)",
        "SELECT id FROM case_runs WHERE case_id = cast('00000000-0000-0000-0000-000000000000' as uuid) AND status = 'running' ORDER BY created_at DESC LIMIT 1",
        "SELECT id, case_id, status, heartbeat_at FROM case_runs WHERE status = 'running' AND (heartbeat_at < NOW() - INTERVAL '5 minutes' OR heartbeat_at IS NULL)",
    ]

    errors = []
    async with async_session() as db:
        for i, sql in enumerate(test_queries):
            try:
                await db.execute(text(f"EXPLAIN {sql}"))
            except Exception as e:
                errors.append(f"Query #{i+1}: {str(e)[:200]}")
                log.error(f"[SQL_CHECK] INVALID query #{i+1}: {str(e)[:200]}")
        await db.rollback()

    if errors:
        log.error(f"[SQL_CHECK] {len(errors)} invalid SQL queries found!")
        try:
            await send_admin(f"[X] Worker SQL check: {len(errors)} invalid queries!")
        except Exception:
            pass
    else:
        log.info("[SQL_CHECK] All raw SQL queries validated OK")
    return len(errors) == 0


class WorkerSettings:
    """arq worker settings."""
    functions = [run_generation_job]
    on_startup = startup
    on_shutdown = shutdown
    on_job_error = on_job_error
    redis_settings = get_redis_settings()
    max_jobs = 5
    job_timeout = 3600  # 30 min
    retry_jobs = True
    max_tries = 1
    health_check_interval = 30
    # Recovery sweep every 2 minutes (even minutes)
    cron_jobs = [
            cron("app.workers.reconciliation.reconciliation_check", hour={0, 6, 12, 18}, minute={15}),
        cron("app.workers.recovery_worker.recovery_sweep", run_at_startup=True, second={0}, minute={0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58}),
        cron("app.workers.recovery_worker.cleanup_old_data", hour={3, 15}, minute={0}),  # Twice daily
            cron("app.workers.recovery_worker.cleanup_abandoned_sessions", hour={4}, minute={0}),  # Daily at 04:00
        cron("app.workers.recovery_worker.recover_stale_widget_payments", run_at_startup=True, second={0}, minute={0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58}),  # Every 2 min — same as recovery_sweep
        cron("app.services.health_check.run_all_checks", minute={7}),  # Hourly at :07
    ]
