"""
Инвайт-коды (подарочные коды).
Админ создаёт код → отправляет судье → судья вводит → получает токены/бесплатные дела.

Защита от перебора:
- 5 попыток за 15 минут на IP
- 10 попыток за 15 минут на юзера
- После превышения — блокировка на 30 минут
- Коды 12 символов для дорогих подарков (>1M токенов)
- Все попытки логируются
"""

import secrets
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import User, InviteCode, InviteActivation, Transaction
from app.services.telegram import send_admin
from app.utils.deps import get_current_user, get_current_admin
from app.utils.rate_limit import check_rate_limit, get_client_ip
from app.utils.datetime import ensure_utc, utcnow
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/invites", tags=["invites"])
s = get_settings()

# Rate limit параметры
ACTIVATE_MAX_PER_IP = 5         # попыток на IP за окно
ACTIVATE_MAX_PER_USER = 10      # попыток на юзера за окно
ACTIVATE_WINDOW = 15 * 60       # 15 минут
ACTIVATE_BLOCK = 30 * 60        # блокировка на 30 минут

# Порог для длинных кодов
HIGH_VALUE_TOKEN_THRESHOLD = 1_000_000


def _generate_code(high_value: bool = False) -> str:
    """
    Генерирует читаемый код.
    Обычный: XXXX-XXXX (30^8 = 656 млрд комбинаций)
    Дорогой: XXXX-XXXX-XXXX (30^12 = 531 трлн комбинаций)
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    if high_value:
        raw = "".join(secrets.choice(alphabet) for _ in range(12))
        return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
    else:
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        return f"{raw[:4]}-{raw[4:]}"


def _gift_description(tokens: int, free_cases: int) -> str:
    parts = []
    if tokens > 0:
        parts.append(f"{tokens:,} токенов")
    if free_cases > 0:
        parts.append(f"{free_cases} бесплатных дел")
    return " + ".join(parts) or "Пустой подарок"


# --- Schemas ---

class InviteCreate(BaseModel):
    gift_type: str = "trial"
    label: str | None = None
    max_activations: int = Field(default=1, ge=1, le=1000)
    expires_days: int | None = None

class InviteCreateCustom(BaseModel):
    label: str | None = None
    bonus_tokens: int = Field(default=0, ge=0)
    bonus_free_cases: int = Field(default=0, ge=0)
    max_activations: int = Field(default=1, ge=1, le=1000)
    expires_days: int | None = None

class InviteResponse(BaseModel):
    id: str
    code: str
    label: str | None
    gift_type: str
    gift_description: str
    bonus_tokens: int
    bonus_free_cases: int
    max_activations: int
    activated_count: int
    is_active: bool
    expires_at: datetime | None
    created_at: datetime

class ActivateRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9А-яЁё\-\s]+$")  # только буквы, цифры, дефисы, пробелы

class ActivateResponse(BaseModel):
    bonus_tokens: int
    bonus_free_cases: int
    message: str


def _to_response(inv: InviteCode) -> InviteResponse:
    gift_type = "custom"
    for key, preset in s.gift_presets.items():
        if inv.bonus_tokens == preset["bonus_tokens"] and inv.bonus_free_cases == preset["bonus_free_cases"]:
            gift_type = key
            break
    return InviteResponse(
        id=str(inv.id), code=inv.code, label=inv.label,
        gift_type=gift_type,
        gift_description=_gift_description(inv.bonus_tokens, inv.bonus_free_cases),
        bonus_tokens=inv.bonus_tokens, bonus_free_cases=inv.bonus_free_cases,
        max_activations=inv.max_activations, activated_count=inv.activated_count,
        is_active=inv.is_active, expires_at=inv.expires_at, created_at=inv.created_at,
    )


# --- Admin: пресеты ---

@router.get("/admin/presets")
async def list_presets(admin: User = Depends(get_current_admin)):
    return [
        {
            "key": key,
            "label": p["label"],
            "bonus_tokens": p["bonus_tokens"],
            "bonus_free_cases": p["bonus_free_cases"],
            "description": _gift_description(p["bonus_tokens"], p["bonus_free_cases"]),
        }
        for key, p in s.gift_presets.items()
    ]


# --- Admin: создание ---

@router.post("/admin/create", response_model=InviteResponse)
async def create_invite(
    body: InviteCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    preset = s.gift_presets.get(body.gift_type)
    if not preset:
        raise HTTPException(400, f"Неизвестный тип подарка. Доступные: {list(s.gift_presets.keys())}")
    return await _create_invite(
        bonus_tokens=preset["bonus_tokens"],
        bonus_free_cases=preset["bonus_free_cases"],
        label=body.label,
        max_activations=body.max_activations,
        expires_days=body.expires_days,
        admin=admin, db=db,
    )


@router.post("/admin/create-custom", response_model=InviteResponse)
async def create_custom_invite(
    body: InviteCreateCustom,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _create_invite(
        bonus_tokens=body.bonus_tokens,
        bonus_free_cases=body.bonus_free_cases,
        label=body.label,
        max_activations=body.max_activations,
        expires_days=body.expires_days,
        admin=admin, db=db,
    )


async def _create_invite(
    *, bonus_tokens, bonus_free_cases, label, max_activations, expires_days, admin, db
) -> InviteResponse:
    high_value = bonus_tokens >= HIGH_VALUE_TOKEN_THRESHOLD
    code = _generate_code(high_value=high_value)
    for _ in range(10):
        exists = (await db.execute(
            select(InviteCode).where(InviteCode.code == code)
        )).scalar_one_or_none()
        if not exists:
            break
        code = _generate_code(high_value=high_value)

    expires_at = None
    if expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    invite = InviteCode(
        code=code, label=label,
        bonus_tokens=bonus_tokens, bonus_free_cases=bonus_free_cases,
        max_activations=max_activations, expires_at=expires_at,
        created_by=admin.id,
    )
    db.add(invite)
    await db.flush()

    logger.info(f"Invite created: {code} ({_gift_description(bonus_tokens, bonus_free_cases)}) by admin {admin.id}")
    return _to_response(invite)


# --- Admin: список и управление ---

@router.get("/admin/list", response_model=list[InviteResponse])
async def list_invites(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(InviteCode).order_by(InviteCode.created_at.desc()).limit(100)
    )).scalars().all()
    return [_to_response(r) for r in rows]


@router.get("/admin/stats")
async def invite_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Detailed stats per promo code: who activated, when."""
    codes = (await db.execute(
        select(InviteCode).order_by(InviteCode.created_at.desc()).limit(50)
    )).scalars().all()

    result = []
    for inv in codes:
        activations = (await db.execute(
            select(InviteActivation, User)
            .join(User, InviteActivation.user_id == User.id)
            .where(InviteActivation.invite_id == inv.id)
            .order_by(InviteActivation.activated_at.desc())
        )).all()

        result.append({
            "code": inv.code,
            "label": inv.label,
            "bonus_free_cases": inv.bonus_free_cases,
            "bonus_tokens": inv.bonus_tokens,
            "max_activations": inv.max_activations,
            "activated_count": inv.activated_count,
            "is_active": inv.is_active,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "activations": [
                {
                    "user_display_id": u.display_id,
                    "user_name": u.name or u.email or str(u.id)[:8],
                    "bonus_free_cases": a.bonus_free_cases,
                    "activated_at": a.activated_at.isoformat() if a.activated_at else None,
                }
                for a, u in activations
            ],
        })

    return result


@router.delete("/admin/{code}")
async def deactivate_invite(
    code: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    invite = (await db.execute(
        select(InviteCode).where(InviteCode.code == code.upper().strip())
    )).scalar_one_or_none()
    if not invite:
        raise HTTPException(404, "Код не найден")
    invite.is_active = False
    logger.info(f"Invite deactivated: {invite.code} by admin {admin.id}")
    return {"ok": True}


# --- User: активация (с rate limiting) ---

@router.post("/activate", response_model=ActivateResponse)
async def activate_invite(
    body: ActivateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client_ip = get_client_ip(request)

    # Rate limit по IP и по юзеру (оба должны пройти)
    await check_rate_limit(
        f"invite:ip:{client_ip}",
        max_attempts=ACTIVATE_MAX_PER_IP,
        window_seconds=ACTIVATE_WINDOW,
        block_seconds=ACTIVATE_BLOCK,
    )
    await check_rate_limit(
        f"invite:user:{user.id}",
        max_attempts=ACTIVATE_MAX_PER_USER,
        window_seconds=ACTIVATE_WINDOW,
        block_seconds=ACTIVATE_BLOCK,
    )

    # Нормализуем код: убираем пробелы, дефисы → upper → восстанавливаем формат
    clean = body.code.upper().replace(" ", "").replace("-", "")
    if len(clean) == 12:
        lookup = f"{clean[:4]}-{clean[4:8]}-{clean[8:]}"
    elif len(clean) == 8:
        lookup = f"{clean[:4]}-{clean[4:]}"
    else:
        lookup = body.code.upper().strip()

    invite = (await db.execute(
        select(InviteCode).where(InviteCode.code == lookup).with_for_update()
    )).scalar_one_or_none()

    if not invite:
        logger.warning(f"Invite activation FAILED: code={lookup!r} user={user.id} ip={client_ip} reason=not_found")
        raise HTTPException(404, "Код не найден. Проверьте правильность ввода.")
    if not invite.is_active:
        logger.warning(f"Invite activation FAILED: code={lookup!r} user={user.id} ip={client_ip} reason=deactivated")
        raise HTTPException(410, "Этот код деактивирован.")
    if invite.expires_at and utcnow() > ensure_utc(invite.expires_at):
        logger.warning(f"Invite activation FAILED: code={lookup!r} user={user.id} ip={client_ip} reason=expired")
        raise HTTPException(410, "Срок действия кода истёк.")
    if invite.activated_count >= invite.max_activations:
        logger.warning(f"Invite activation FAILED: code={lookup!r} user={user.id} ip={client_ip} reason=exhausted")
        raise HTTPException(410, "Код уже использован максимальное количество раз.")

    already = (await db.execute(
        select(InviteActivation).where(
            InviteActivation.invite_id == invite.id,
            InviteActivation.user_id == user.id,
        )
    )).scalar_one_or_none()
    if already:
        raise HTTPException(409, "Вы уже активировали этот код.")

    # Block promo codes for users who already paid
    has_payments = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.type == "purchase",
            Transaction.credited_at.is_not(None),
        ).limit(1)
    )).scalar_one_or_none()
    if has_payments:
        raise HTTPException(409, "Промокод доступен только для новых пользователей.")

    # Начисляем
    locked_user = (await db.execute(
        select(User).where(User.id == user.id).with_for_update()
    )).scalar_one()

    locked_user.free_cases_left = (locked_user.free_cases_left or 0) + invite.bonus_free_cases
    locked_user.invite_code_used = locked_user.invite_code_used or invite.code  # запоминаем первый код

    # Special: referral codes with subscription bonus
    if invite.label and "7 дней" in invite.label:
        from datetime import datetime, timezone, timedelta
        current_sub = locked_user.subscription_until
        now = datetime.now(timezone.utc)
        base = max(current_sub, now) if current_sub and current_sub > now else now
        locked_user.subscription_until = base + timedelta(days=7)
        logger.info(f"Referral subscription: user={user.id} code={invite.code} sub_until={locked_user.subscription_until}")
    invite.activated_count += 1

    db.add(InviteActivation(
        invite_id=invite.id, user_id=user.id,
        bonus_tokens=invite.bonus_tokens, bonus_free_cases=invite.bonus_free_cases,
    ))

    # flush с защитой от race condition (unique constraint invite_id + user_id)
    from sqlalchemy.exc import IntegrityError
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Вы уже активировали этот код.")

    await db.commit()  # явный commit: финансовая операция (начисление токенов/бесплатных дел)

    desc = _gift_description(invite.bonus_tokens, invite.bonus_free_cases)
    logger.info(f"Invite activation OK: code={invite.code} user={user.id} bonus={desc}")

    try:
        from app.services.telegram import _esc
        await send_admin(
            f"🎁 <b>Инвайт активирован</b>\n"
            f"Код: {invite.code} ({_esc(invite.label or '—')})\n"
            f"Подарок: {desc}\n"
            f"Юзер: {_esc(user.nickname or user.name or str(user.id)[:8])}\n"
            f"Активаций: {invite.activated_count}/{invite.max_activations}"
        )
    except Exception:
        pass

    parts = []
    if invite.bonus_tokens > 0:
        parts.append(f"{invite.bonus_tokens:,} токенов")
    if invite.bonus_free_cases > 0:
        parts.append(f"{invite.bonus_free_cases} бесплатных дел")

    return ActivateResponse(
        bonus_tokens=invite.bonus_tokens,
        bonus_free_cases=invite.bonus_free_cases,
        message=f"Начислено: {' и '.join(parts)}!",
    )
