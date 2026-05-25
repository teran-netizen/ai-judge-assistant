"""API для управления помощниками судьи."""
import logging
import secrets
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.models import User, JudgeAssistant, Case
from app.utils.deps import get_current_user
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assistants", tags=["assistants"])
s = get_settings()

INVITE_TTL = 86400  # 24 hours
INVITE_PREFIX = "assistant_invite:"


def _redis():
    return aioredis.from_url(s.redis_url)


class AddAssistantRequest(BaseModel):
    identifier: str


class AcceptInviteRequest(BaseModel):
    code: str


# ── Judge endpoints ──────────────────────────────────────────

@router.get("/")
async def list_my_assistants(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Judge: list my assistants."""
    rows = (await db.execute(
        select(JudgeAssistant, User)
        .join(User, User.id == JudgeAssistant.assistant_id)
        .where(JudgeAssistant.judge_id == user.id)
        .order_by(JudgeAssistant.created_at)
    )).all()
    return [
        {
            "id": str(ja.id),
            "assistant_id": str(ja.assistant_id),
            "name": u.name,
            "nickname": u.nickname,
            "display_id": u.display_id,
            "created_at": ja.created_at.isoformat() if ja.created_at else None,
        }
        for ja, u in rows
    ]


@router.post("/invite")
async def create_invite(user: User = Depends(get_current_user)):
    """Judge: generate invite code for assistant."""
    code = secrets.token_hex(6).upper()  # 12 hex chars, 48-bit entropy (281T variants)
    r = _redis()
    try:
        key = f"{INVITE_PREFIX}{code}"
        await r.set(key, str(user.id), ex=INVITE_TTL)
        logger.info("create_invite: judge=%s code=%s", user.id, code)
        return {"code": code, "expires_in": INVITE_TTL}
    finally:
        await r.aclose()


@router.post("/")
async def add_assistant(body: AddAssistantRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Judge: add assistant by display_id or nickname (legacy)."""
    identifier = body.identifier.strip()
    if not identifier:
        raise HTTPException(400, "Укажите ID или никнейм помощника")

    query = select(User)
    if identifier.isdigit():
        query = query.where(User.display_id == int(identifier))
    else:
        query = query.where(User.nickname == identifier)

    assistant = (await db.execute(query)).scalar_one_or_none()
    if not assistant:
        raise HTTPException(404, "Пользователь не найден")
    if str(assistant.id) == str(user.id):
        raise HTTPException(400, "Нельзя добавить себя как помощника")

    existing = (await db.execute(
        select(JudgeAssistant).where(
            JudgeAssistant.judge_id == user.id,
            JudgeAssistant.assistant_id == assistant.id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Этот помощник уже добавлен")

    ja = JudgeAssistant(judge_id=user.id, assistant_id=assistant.id)
    db.add(ja)
    await db.commit()
    logger.info("add_assistant: judge=%s assistant=%s (%s)", user.id, assistant.id, assistant.name)
    return {
        "id": str(ja.id),
        "assistant_id": str(assistant.id),
        "name": assistant.name,
        "nickname": assistant.nickname,
        "display_id": assistant.display_id,
    }


@router.delete("/{assistant_id}")
async def remove_assistant(assistant_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Judge: remove assistant."""
    ja = (await db.execute(
        select(JudgeAssistant).where(
            JudgeAssistant.judge_id == user.id,
            JudgeAssistant.assistant_id == assistant_id,
        )
    )).scalar_one_or_none()
    if not ja:
        raise HTTPException(404, "Помощник не найден")
    await db.delete(ja)
    await db.commit()
    logger.info("remove_assistant: judge=%s assistant=%s", user.id, assistant_id)
    return {"ok": True}


# ── Assistant endpoints ──────────────────────────────────────

@router.post("/accept")
async def accept_invite(body: AcceptInviteRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Assistant: accept invite code from judge."""
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(400, "Введите код приглашения")

    r = _redis()
    try:
        # Per-user brute-force limiter: 10 failed attempts / 1h = block further tries.
        fail_key = f"invite_fail:{user.id}"
        fail_count = int(await r.get(fail_key) or 0)
        if fail_count >= 10:
            raise HTTPException(429, "Слишком много неудачных попыток. Попробуйте через час.")

        key = f"{INVITE_PREFIX}{code}"
        judge_id = await r.get(key)
        if not judge_id:
            # Increment fail counter (TTL 1h, resets on success below)
            pipe = r.pipeline()
            pipe.incr(fail_key)
            pipe.expire(fail_key, 3600)
            await pipe.execute()
            raise HTTPException(404, "Код не найден или истёк")

        # Reset fail counter on successful code lookup
        await r.delete(fail_key)
        judge_id = judge_id.decode()

        if judge_id == str(user.id):
            raise HTTPException(400, "Нельзя принять собственное приглашение")

        # Check judge exists
        judge = (await db.execute(select(User).where(User.id == judge_id))).scalar_one_or_none()
        if not judge:
            raise HTTPException(404, "Судья не найден")

        # Check not already linked
        existing = (await db.execute(
            select(JudgeAssistant).where(
                JudgeAssistant.judge_id == judge_id,
                JudgeAssistant.assistant_id == user.id,
            )
        )).scalar_one_or_none()
        if existing:
            await r.delete(key)
            raise HTTPException(409, "Вы уже помощник этого судьи")

        ja = JudgeAssistant(judge_id=judge_id, assistant_id=user.id)
        db.add(ja)
        await db.commit()
        await r.delete(key)

        # Transfer all assistant's existing cases to judge's cabinet
        transferred = (await db.execute(
            update(Case)
            .where(Case.user_id == user.id)
            .values(user_id=judge_id, created_by=user.id)
        )).rowcount
        await db.commit()

        logger.info("accept_invite: assistant=%s judge=%s code=%s transferred_cases=%d",
                     user.id, judge_id, code, transferred)
        return {
            "ok": True,
            "judge_id": judge_id,
            "judge_name": judge.name,
            "transferred_cases": transferred,
        }
    finally:
        await r.aclose()


@router.get("/judges")
async def list_my_judges(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Assistant: list judges I'm bound to."""
    rows = (await db.execute(
        select(JudgeAssistant, User)
        .join(User, User.id == JudgeAssistant.judge_id)
        .where(JudgeAssistant.assistant_id == user.id)
        .order_by(JudgeAssistant.created_at)
    )).all()
    return [
        {
            "id": str(ja.id),
            "judge_id": str(u.id),
            "name": u.name,
            "nickname": u.nickname,
            "display_id": u.display_id,
            "free_cases_left": u.free_cases_left,
            "paid_cases_left": u.paid_cases_left,
            "is_vip": u.is_vip,
            "subscription_until": u.subscription_until.isoformat() if u.subscription_until else None,
            "token_balance": u.token_balance,
        }
        for ja, u in rows
    ]


@router.delete("/judges/{judge_id}")
async def detach_from_judge(judge_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Assistant: detach from judge."""
    ja = (await db.execute(
        select(JudgeAssistant).where(
            JudgeAssistant.judge_id == judge_id,
            JudgeAssistant.assistant_id == user.id,
        )
    )).scalar_one_or_none()
    if not ja:
        raise HTTPException(404, "Связка не найдена")
    await db.delete(ja)
    await db.commit()
    logger.info("detach_from_judge: assistant=%s judge=%s", user.id, judge_id)
    return {"ok": True}
