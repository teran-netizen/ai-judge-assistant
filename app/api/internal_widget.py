"""
Internal API for widget partners — create-payment + confirm-payment + stream.

POST /api/internal/widget/create-payment   (PAY-006)
POST /api/internal/widget/confirm-payment  (PAY-007)
GET  /api/internal/widget/stream/{case_id} (PAY-010)

Auth: Service JWT via Authorization: Bearer <token>
- Issuer: widget-backend
- Audience: ai-judge
"""

import asyncio
import json as _json
import logging
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Transaction, User, Case, CaseRun
from app.schemas import WidgetPaymentRequest, WidgetPaymentResponse
from app.services.tochka_payment import create_payment_link, check_payment_status
from app.services.redis_stream import (
    get_stream_state,
    get_redis,
    CHANNEL_KEY,
    CHUNK_LIST_KEY,
    DONE_MARKER,
    ERROR_PREFIX,
)
from app.services.sse_contract import (
    try_decode_event_payload,
    is_event_like_payload,
)
from app.utils.deps import get_internal_service
from app.utils.rate_limit import check_rate_limit

router = APIRouter(prefix="/api/internal/widget", tags=["internal-widget"])
logger = logging.getLogger(__name__)
settings = get_settings()


def _transaction_metadata(tx: Transaction) -> dict:
    """Return widget metadata from JSONB, falling back to legacy description JSON."""
    metadata = tx.tx_metadata or {}
    if isinstance(metadata, dict) and metadata:
        return metadata
    if tx.description:
        try:
            parsed = _json.loads(tx.description)
            if isinstance(parsed, dict):
                return parsed
        except (_json.JSONDecodeError, TypeError):
            pass
    return {}


def _payment_payload(tx: Transaction, status: str, *, case_id=None, raw_status: str | None = None) -> dict:
    metadata = _transaction_metadata(tx)
    return {
        "status": status,
        "payment_status": status,
        "raw_status": raw_status,
        "transaction_id": str(tx.id),
        "case_id": str(case_id or tx.case_id) if (case_id or tx.case_id) else None,
        "amount_kopecks": tx.amount_kopecks,
        "source_partner_id": str(tx.source_partner_id) if tx.source_partner_id else metadata.get("source_partner_id"),
        "widget_session_id": metadata.get("widget_session_id"),
    }


async def _ensure_widget_generation_enqueued(db: AsyncSession, case: Case, user_id, *, reason: str) -> str | None:
    """Idempotently create an active run and enqueue widget generation."""
    if case.status == "completed" or (case.generated_text and len(case.generated_text.strip()) > 100):
        return None

    active_run = (await db.execute(
        select(CaseRun).where(
            CaseRun.case_id == case.id,
            CaseRun.status.in_(["queued", "running"]),
        ).order_by(CaseRun.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if active_run:
        logger.info(
            "[WIDGET-CONFIRM] Active run already exists: case=%s run=%s status=%s reason=%s",
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
        from app.services.job_queue import enqueue_full_pipeline
        job_id = await enqueue_full_pipeline(
            case_id=str(case.id),
            user_id=str(user_id),
            billing_method="widget",
        )
    except Exception:
        logger.exception("[WIDGET-CONFIRM] Failed to enqueue generation: case=%s", str(case.id)[:8])
        run.status = "failed"
        run.error_code = "enqueue_failed"
        run.error_message = "arq enqueue failed"
        run.finished_at = datetime.utcnow()
        case.status = "draft"
        case.stage = None
        case.active_run_id = None
        await db.commit()
        raise HTTPException(503, "Generation queue unavailable")

    run.job_id = job_id
    await db.commit()
    logger.info(
        "[WIDGET-CONFIRM] Enqueued generation: case=%s run=%s job=%s reason=%s",
        str(case.id)[:8],
        str(run.id)[:8],
        job_id,
        reason,
    )
    return job_id


# ── PAY-006: create-payment ──────────────────────────────────────────


@router.post("/create-payment", response_model=WidgetPaymentResponse)
async def create_payment(
    body: WidgetPaymentRequest,
    request: Request,
    claims: dict = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db),
):
    """Create a payment link for a widget end-user.

    Called by widget-backend with a service JWT.
    Rate limited to 10 requests per minute per partner_id via Redis.
    """
    partner_id = body.partner_id
    session_id = body.session_id
    email = body.email
    amount_kopecks = body.amount_kopecks

    # ── Rate limit: 10 req/min per partner_id ──
    rl_key = f"widget:payment:{partner_id}"
    await check_rate_limit(rl_key, max_attempts=10, window_seconds=60, block_seconds=60)

    # ── Validate amount (sanity bounds) ──
    if amount_kopecks < 100 or amount_kopecks > 10_000_00:  # 1 ₽ … 10 000 ₽
        raise HTTPException(400, "amount_kopecks должен быть от 100 до 1 000 000")

    amount_rub = amount_kopecks / 100

    # ── Build metadata for tracking ──
    metadata: dict = {
        "widget_session_id": str(session_id),
        "source_type": "widget",
        "source_partner_id": str(partner_id),
    }
    if email:
        metadata["email"] = email
    if body.origin_url:
        metadata["origin_url"] = body.origin_url
    if body.utm:
        metadata["utm"] = body.utm

    # ── Create Transaction ──
    # user_id is NULL — assigned later on confirm-payment when we resolve the end-user
    tx = Transaction(
        user_id=None,
        type="widget_payment",
        amount_kopecks=amount_kopecks,
        purchase_type="widget_single_case",
        source_partner_id=partner_id,
        tx_metadata=metadata,
        description=_json.dumps(metadata, ensure_ascii=False),
    )
    db.add(tx)
    await db.flush()  # populate tx.id

    # ── Create Tochka payment link ──
    purpose = "AI document - AI Judge Assistant"
    domain = settings.domain or "https://example.com"
    success_url = (
        f"{domain}/billing?payment=success&tx={tx.id}"
        f"&from=widget&partner={partner_id}"
    )
    fail_url = f"{domain}/billing?payment=fail&tx={tx.id}&from=widget"

    try:
        result = await create_payment_link(
            amount_rub=amount_rub,
            purpose=purpose,
            redirect_url=success_url,
            fail_redirect_url=fail_url,
        )
    except Exception as e:
        logger.error("[WIDGET] Tochka create_payment_link failed: %s", e, exc_info=True)
        raise HTTPException(502, "Платёжный шлюз временно недоступен")

    operation_id = result["operationId"]
    payment_url = result["paymentLink"]

    # ── Persist external_payment_id ──
    tx.external_payment_id = operation_id
    await db.commit()

    logger.info(
        "[WIDGET] Payment created: partner=%s session=%s tx=%s op=%s amount=%.2f",
        partner_id, session_id, tx.id, operation_id[:16], amount_rub,
    )

    return WidgetPaymentResponse(
        status="ok",
        payment_url=payment_url,
        transaction_id=tx.id,
        operation_id=operation_id,
    )


@router.get("/payment-status/{transaction_id}")
async def payment_status(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_internal_service),
):
    """Check widget payment status without crediting or creating a case."""
    try:
        tx_uuid = _uuid.UUID(transaction_id)
    except (ValueError, AttributeError) as e:
        raise HTTPException(400, f"Invalid UUID: {e}")

    tx = (await db.execute(
        select(Transaction).where(Transaction.id == tx_uuid)
    )).scalar_one_or_none()
    if not tx:
        raise HTTPException(404, "Transaction not found")

    if tx.credited_at is not None:
        return _payment_payload(tx, "paid", raw_status="credited")

    if not tx.external_payment_id:
        return _payment_payload(tx, "pending", raw_status="no_operation_id")

    try:
        status_result = await check_payment_status(tx.external_payment_id)
    except Exception as e:
        logger.error("[WIDGET-STATUS] Tochka check failed: tx=%s error=%s", transaction_id[:8], e)
        raise HTTPException(502, "Payment gateway unavailable")

    status = status_result.get("status", "pending")
    return _payment_payload(tx, status, raw_status=status_result.get("raw_status"))


# ── PAY-007: confirm-payment ─────────────────────────────────────────


class ConfirmPaymentRequest(BaseModel):
    transaction_id: str  # UUID
    session_id: str      # UUID
    partner_id: str      # UUID


class ConfirmPaymentResponse(BaseModel):
    status: str           # "paid" | "already_paid" | "pending" | "failed" | "refunded"
    payment_status: Optional[str] = None
    case_id: Optional[str] = None
    amount_kopecks: Optional[int] = None
    source_partner_id: Optional[str] = None
    widget_session_id: Optional[str] = None


@router.post("/confirm-payment", response_model=ConfirmPaymentResponse)
async def confirm_payment(
    body: ConfirmPaymentRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_internal_service),
):
    """
    Confirm widget payment and create a Case + enqueue generation.

    Flow:
    1. Find Transaction by transaction_id with row lock (FOR UPDATE)
    2. Validate credited_at IS NULL (idempotency)
    3. Validate source_partner_id matches body.partner_id (403 if not)
    4. Check payment status via Tochka
    5. If paid: create/find User, create Case, credit transaction, enqueue pipeline
    """

    # 1. Validate UUIDs
    try:
        tx_uuid = _uuid.UUID(body.transaction_id)
        _session_uuid = _uuid.UUID(body.session_id)
        partner_uuid = _uuid.UUID(body.partner_id)
    except (ValueError, AttributeError) as e:
        raise HTTPException(400, f"Invalid UUID: {e}")

    # 2. Find Transaction with pessimistic lock
    tx = (await db.execute(
        select(Transaction).where(
            Transaction.id == tx_uuid,
        ).with_for_update()
    )).scalar_one_or_none()

    if not tx:
        raise HTTPException(404, "Transaction not found")

    # 3. Validate partner ownership
    if tx.source_partner_id and str(tx.source_partner_id) != body.partner_id:
        raise HTTPException(403, "Partner mismatch: transaction belongs to different partner")

    # 4. Idempotency: already credited
    if tx.credited_at is not None:
        if tx.case_id and tx.user_id:
            existing_case = (await db.execute(
                select(Case).where(Case.id == tx.case_id)
            )).scalar_one_or_none()
            if existing_case:
                await _ensure_widget_generation_enqueued(
                    db,
                    existing_case,
                    tx.user_id,
                    reason="idempotent_confirm",
                )
        logger.info(
            "[WIDGET-CONFIRM] Already credited: tx=%s case=%s",
            body.transaction_id[:8],
            str(tx.case_id)[:8] if tx.case_id else "N/A",
        )
        return ConfirmPaymentResponse(**_payment_payload(tx, "paid"))

    # 5. Check payment status via Tochka
    operation_id = tx.external_payment_id
    if not operation_id:
        raise HTTPException(409, "Transaction has no payment operation_id")

    logger.info(
        "[WIDGET-CONFIRM] Checking Tochka status: tx=%s op=%s",
        body.transaction_id[:8],
        operation_id[:16],
    )

    try:
        status_result = await check_payment_status(operation_id)
    except Exception as e:
        logger.error("[WIDGET-CONFIRM] Tochka check failed: %s", e)
        raise HTTPException(502, "Payment gateway unavailable")

    payment_status = status_result.get("status", "pending")
    logger.info(
        "[WIDGET-CONFIRM] Tochka status=%s (raw=%s) tx=%s",
        payment_status,
        status_result.get("raw_status", "?"),
        body.transaction_id[:8],
    )

    if payment_status != "paid":
        return ConfirmPaymentResponse(status=payment_status)

    # 6. Payment is PAID — credit!

    # a) Resolve metadata (JSONB column primary, description fallback)
    tx_metadata = _transaction_metadata(tx)

    # b) Create or find User by email from metadata
    user_email = (tx_metadata.get("email") or "").strip().lower() if tx_metadata else ""

    user = None
    if user_email:
        user_result = await db.execute(
            select(User).where(User.email == user_email)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            user = User(
                email=user_email,
                name=tx_metadata.get("name") or (user_email.split("@")[0] if "@" in user_email else user_email),
                billing_model="cases",
                is_active=True,
            )
            db.add(user)
            await db.flush()
            logger.info(
                "[WIDGET-CONFIRM] Created new user: id=%s email=%s",
                str(user.id)[:8],
                user_email,
            )
    else:
        # No email — create anonymous user
        user = User(
            email=None,
            name="Widget User",
            billing_model="cases",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        logger.info("[WIDGET-CONFIRM] Created anonymous user: id=%s", str(user.id)[:8])

    # c) Link user to transaction
    tx.user_id = user.id

    # d) Create Case
    case_title = tx_metadata.get("title") if tx_metadata else None
    if not case_title:
        case_title = "AI-документ виджета"

    case = Case(
        user_id=user.id,
        title=case_title,
        status="draft",
        billing_method="widget",
    )
    db.add(case)
    await db.flush()
    logger.info(
        "[WIDGET-CONFIRM] Created case: id=%s title=%s",
        str(case.id)[:8],
        case_title[:50],
    )

    # e) Link case to transaction + mark credited
    tx.case_id = case.id
    tx.credited_at = datetime.utcnow()

    await db.commit()
    logger.info(
        "[WIDGET-CONFIRM] Transaction credited: tx=%s user=%s case=%s",
        body.transaction_id[:8],
        str(user.id)[:8],
        str(case.id)[:8],
    )

    # f) Enqueue full pipeline generation. If enqueue fails after payment is
    # credited, return 503 so the caller can safely retry confirm-payment.
    await _ensure_widget_generation_enqueued(db, case, user.id, reason="fresh_confirm")

    return ConfirmPaymentResponse(
        status="paid",
        payment_status="paid",
        case_id=str(case.id),
        amount_kopecks=tx.amount_kopecks,
        source_partner_id=str(tx.source_partner_id) if tx.source_partner_id else tx_metadata.get("source_partner_id"),
        widget_session_id=tx_metadata.get("widget_session_id"),
    )


# ── PAY-010: stream generation events ─────────────────────────────────


def _validate_case_uuid(case_id: str) -> str:
    """Validate and normalise case UUID; raise 400 on malformed input."""
    try:
        _uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid case_id UUID")
    return case_id


def _sse_frame(event_type: str | None, payload: dict | str) -> str:
    """Format a single SSE frame with optional event type."""
    lines = []
    if event_type:
        lines.append(f"event: {event_type}")
    if isinstance(payload, str):
        lines.append(f"data: {payload}")
    else:
        lines.append(f"data: {_json.dumps(payload, ensure_ascii=False)}")
    lines.append("")  # blank line terminates the frame
    return "\n".join(lines) + "\n"


@router.get("/stream/{case_id}")
async def widget_stream_case(
    case_id: str,
    request: Request,
    claims: dict = Depends(get_internal_service),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream of case generation events for widget back-end.

    Called by widget-backend with a service JWT.  Reads Redis LIST for catch-up,
    subscribes to PUBSUB for real-time events, and formats them as SSE frames.

    SSE events follow the contract from app.services.sse_contract:
      chunk, full, done, error, ocr_progress, processing, doc_done,
      batch_done, validation_complete, etc.
    """
    _validate_case_uuid(case_id)

    # Confirm the case exists (created by confirm-payment)
    case = (
        await db.execute(select(Case).where(Case.id == case_id))
    ).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")

    logger.info(
        "[WIDGET-STREAM] stream started case=%s status=%s stage=%s",
        case_id[:8], case.status, getattr(case, "stage", "?"),
    )

    async def event_generator():
        """Generate SSE events from Redis stream."""
        yield ":ok\n\n"

        # ── Catch-up: already-published chunks ──
        state = await get_stream_state(case_id)
        chunks_sent = 0

        if state["status"] == "completed":
            # Case already finished — send full text + done
            full_text = case.final_text or case.generated_text or ""
            if full_text:
                yield _sse_frame("full", {"type": "full", "text": full_text})
            yield _sse_frame("done", {"type": "done"})
            return

        if state["status"] == "error":
            yield _sse_frame("error", {
                "type": "error",
                "message": state.get("error") or "Generation failed",
            })
            return

        # Replay existing chunks from Redis LIST
        for chunk in state["chunks"]:
            chunks_sent += 1
            if chunk == DONE_MARKER:
                yield _sse_frame("done", {"type": "done"})
                return
            if isinstance(chunk, str) and chunk.startswith(ERROR_PREFIX):
                yield _sse_frame("error", {
                    "type": "error",
                    "message": chunk[len(ERROR_PREFIX):],
                })
                return

            payload = try_decode_event_payload(chunk)
            if payload is not None:
                event_type = payload.get("type")
                yield _sse_frame(event_type, payload)
            elif isinstance(chunk, str) and not is_event_like_payload(chunk):
                # Plain text chunk from legacy pipeline
                yield _sse_frame("chunk", {"type": "chunk", "text": chunk})

        # ── Real-time: PUBSUB subscription ──
        pubsub = None
        try:
            r = await get_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(CHANNEL_KEY.format(case_id=case_id))

            # Drain any chunks published between catch-up and subscribe
            new_chunks = await r.lrange(
                CHUNK_LIST_KEY.format(case_id=case_id), chunks_sent, -1
            )
            for chunk in new_chunks:
                chunks_sent += 1
                if chunk == DONE_MARKER:
                    yield _sse_frame("done", {"type": "done"})
                    return
                if isinstance(chunk, str) and chunk.startswith(ERROR_PREFIX):
                    yield _sse_frame("error", {
                        "type": "error",
                        "message": chunk[len(ERROR_PREFIX):],
                    })
                    return
                payload = try_decode_event_payload(chunk)
                if payload is not None:
                    event_type = payload.get("type")
                    yield _sse_frame(event_type, payload)
                elif isinstance(chunk, str) and not is_event_like_payload(chunk):
                    yield _sse_frame("chunk", {"type": "chunk", "text": chunk})

            # Listen for real-time messages
            timeout_counter = 0
            while True:
                if await request.is_disconnected():
                    break

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    timeout_counter += 1
                    if timeout_counter % 15 == 0:
                        yield ": keepalive\n\n"
                    if timeout_counter > 300:  # 5 minutes idle → timeout
                        yield _sse_frame("error", {
                            "type": "error",
                            "message": "Timeout waiting for stream",
                        })
                        break
                    continue

                timeout_counter = 0
                data = message.get("data", "")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                if data == DONE_MARKER:
                    yield _sse_frame("done", {"type": "done"})
                    break

                if isinstance(data, str) and data.startswith(ERROR_PREFIX):
                    yield _sse_frame("error", {
                        "type": "error",
                        "message": data[len(ERROR_PREFIX):],
                    })
                    break

                payload = try_decode_event_payload(data)
                if payload is not None:
                    event_type = payload.get("type")
                    yield _sse_frame(event_type, payload)
                elif isinstance(data, str) and not is_event_like_payload(data):
                    yield _sse_frame("chunk", {"type": "chunk", "text": data})

        except Exception as e:
            logger.error(
                "[WIDGET-STREAM] SSE stream error case=%s: %s", case_id[:8], e
            )
            yield _sse_frame("error", {
                "type": "error",
                "message": "Streaming error",
            })
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Retry-After": "3",
        },
    )
