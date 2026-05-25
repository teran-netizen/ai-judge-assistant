import logging
from datetime import datetime, timedelta
from uuid import UUID as PyUUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Case, CaseFile, Transaction, ActivityLog, Feedback, InviteCode, InviteActivation, JudgeAssistant
from app.schemas import FeedbackResponse
from app.utils.deps import get_current_admin

from app.utils.datetime import utcnow_naive
router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


from pydantic import BaseModel, Field

class FeedbackAction(BaseModel):
    status: str = Field(pattern="^(in_review|accepted|rejected|rewarded)$")
    response_text: str = Field(default="", max_length=5000)
    reward: int = Field(default=0, ge=0, le=100_000)  # deprecated: kopecks, оставлено для обратной совместимости
    reward_tokens: int = Field(default=0, ge=0, le=10_000_000)  # токены (≈10 простых дел = 300K)


@router.get("/dashboard")
async def dashboard(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
):
    # Parse date filters
    dt_from = datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
    dt_to = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1) if date_to else None

    # Users
    users_q = select(func.count()).select_from(User)
    if dt_from: users_q = users_q.where(User.created_at >= dt_from)
    if dt_to: users_q = users_q.where(User.created_at < dt_to)
    total_users = (await db.execute(users_q)).scalar()

    month_ago = utcnow_naive() - timedelta(days=30)
    paying_users_30d = (await db.execute(
        select(func.count(func.distinct(Transaction.user_id))).where(
            Transaction.credited_at > month_ago,
            Transaction.amount_kopecks > 0,
        )
    )).scalar()

    # Cases
    cases_q = select(func.count()).select_from(Case)
    if dt_from: cases_q = cases_q.where(Case.created_at >= dt_from)
    if dt_to: cases_q = cases_q.where(Case.created_at < dt_to)
    total_cases = (await db.execute(cases_q)).scalar()

    # Revenue (credited payments only)
    rev_q = select(func.coalesce(func.sum(Transaction.amount_kopecks), 0)).where(
        Transaction.type == "purchase",
        Transaction.credited_at.is_not(None),
    )
    if dt_from: rev_q = rev_q.where(Transaction.credited_at >= dt_from)
    if dt_to: rev_q = rev_q.where(Transaction.credited_at < dt_to)
    total_rev = (await db.execute(rev_q)).scalar()

    pending_fb = (await db.execute(
        select(func.count()).where(Feedback.status == "new")
    )).scalar()

    # Инвайт-коды
    active_invites = (await db.execute(
        select(func.count()).where(InviteCode.is_active == True)
    )).scalar()
    total_activations = (await db.execute(
        select(func.count()).select_from(InviteActivation)
    )).scalar()
    total_gifted_tokens = (await db.execute(
        select(func.coalesce(func.sum(InviteActivation.bonus_tokens), 0))
    )).scalar()

    # UTM-статистика
    utm_stats = (await db.execute(
        select(User.utm_source, func.count())
        .where(User.utm_source.is_not(None))
        .group_by(User.utm_source)
        .order_by(func.count().desc())
    )).all()

    # Cost: from case.cost_kopecks, fallback to estimate ~17.3r/completed case
    cost_q = select(func.coalesce(func.sum(Case.cost_kopecks), 0)).select_from(Case)
    if dt_from: cost_q = cost_q.where(Case.created_at >= dt_from)
    if dt_to: cost_q = cost_q.where(Case.created_at < dt_to)
    total_cost = (await db.execute(cost_q)).scalar()

    completed_q = select(func.count()).select_from(Case).where(Case.status == "completed")
    if dt_from: completed_q = completed_q.where(Case.created_at >= dt_from)
    if dt_to: completed_q = completed_q.where(Case.created_at < dt_to)
    completed_count = (await db.execute(completed_q)).scalar() or 0

    # Fallback для безопасности (на случай partial data) — очень низкий порог,
    # обычно не срабатывает т.к. cost_kopecks точно считается в pipeline.
    if completed_count > 0 and total_cost < completed_count * 50:  # < 0.5 RUB/кейс = аномалия
        total_cost = int(completed_count * 12.0 * 100)

    # Экономика: налог + эквайринг = 10% от выручки
    TAX_ACQUIRING_PCT = 0.10
    tax_acquiring = round(int(total_rev) * TAX_ACQUIRING_PCT)
    net_revenue = int(total_rev) - tax_acquiring
    margin = net_revenue - total_cost

    # 24h metrics
    day_ago = utcnow_naive() - timedelta(hours=24)
    payments_24h = (await db.execute(
        select(func.count()).where(Transaction.credited_at >= day_ago, Transaction.credited_at.is_not(None))
    )).scalar() or 0
    revenue_24h = (await db.execute(
        select(func.coalesce(func.sum(Transaction.amount_kopecks), 0)).where(
            Transaction.credited_at >= day_ago, Transaction.credited_at.is_not(None)
        )
    )).scalar() or 0
    payment_attempts_24h = (await db.execute(
        select(func.count()).where(
            Transaction.type == "purchase", Transaction.created_at >= day_ago, Transaction.external_payment_id.is_not(None)
        )
    )).scalar() or 0
    completed_cases_24h = (await db.execute(
        select(func.count()).where(Case.status == "completed", Case.updated_at >= day_ago)
    )).scalar() or 0
    errors_24h = (await db.execute(
        select(func.count()).where(Case.status == "error", Case.updated_at >= day_ago)
    )).scalar() or 0
    stuck_cases = (await db.execute(
        select(func.count()).where(Case.status == "processing", Case.updated_at < utcnow_naive() - timedelta(minutes=30))
    )).scalar() or 0
    new_users_24h = (await db.execute(
        select(func.count()).where(User.created_at >= day_ago)
    )).scalar() or 0
    fast_cases_24h = (await db.execute(
        select(func.count()).where(
            Case.status == "completed", Case.updated_at >= day_ago,
            Case.updated_at - Case.created_at < timedelta(minutes=10)
        )
    )).scalar() or 0
    slow_cases_24h = (await db.execute(
        select(func.count()).where(
            Case.status == "completed", Case.updated_at >= day_ago,
            Case.updated_at - Case.created_at >= timedelta(minutes=10)
        )
    )).scalar() or 0

    return {
        "total_users": total_users,
        "paying_users_30d": paying_users_30d,
        "total_cases": total_cases,
        "total_revenue_kopecks": total_rev,
        "total_revenue_rub": total_rev / 100,
        "total_cost_kopecks": total_cost,
        "total_cost_rub": round(total_cost / 100, 2),
        "tax_acquiring_rub": round(tax_acquiring / 100, 2),
        "net_revenue_rub": round(net_revenue / 100, 2),
        "margin_rub": round(margin / 100, 2),
        "total_gifted_tokens": total_gifted_tokens,
        "pending_feedbacks": pending_fb,
        "active_invites": active_invites,
        "total_invite_activations": total_activations,
        "utm_sources": {src: cnt for src, cnt in utm_stats},
        "date_from": date_from,
        "date_to": date_to,
        "payments_24h": payments_24h,
        "revenue_24h_rub": int(revenue_24h) / 100,
        "payment_attempts_24h": payment_attempts_24h,
        "completed_cases_24h": completed_cases_24h,
        "errors_24h": errors_24h,
        "stuck_cases": stuck_cases,
        "new_users_24h": new_users_24h,
        "fast_cases_24h": fast_cases_24h,
        "slow_cases_24h": slow_cases_24h,
    }


@router.get("/users")
async def list_users(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Список всех пользователей с количеством дел."""
    from sqlalchemy.orm import selectinload
    users = (await db.execute(
        select(User).order_by(User.created_at.desc())
    )).scalars().all()

    # Количество дел по пользователям
    case_counts = dict((await db.execute(
        select(Case.user_id, func.count()).group_by(Case.user_id)
    )).all())

    result = []
    for u in users:
        result.append({
            "id": str(u.id),
                "display_id": u.display_id,
            "email": u.email,
            "name": u.name,
            "nickname": u.nickname,
            "yandex_id": u.yandex_id,
            "vk_id": u.vk_id,
            "is_admin": u.is_admin,
            "token_balance": u.token_balance or 0,
            "free_cases_left": u.free_cases_left or 0,
            "billing_model": getattr(u, "billing_model", "tokens"),
            "paid_cases_left": getattr(u, "paid_cases_left", 0),
            "subscription_until": u.subscription_until.isoformat() if getattr(u, "subscription_until", None) else None,
            "cases_count": case_counts.get(u.id, 0),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return result


@router.get("/feedbacks", response_model=list[FeedbackResponse])
async def list_feedbacks(
    status: Literal["new", "in_review", "accepted", "rejected", "rewarded"] = "new",
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Feedback).where(Feedback.status == status).order_by(Feedback.created_at)
    )
    return result.scalars().all()


@router.put("/feedbacks/{fb_id}")
async def process_feedback(
    fb_id: PyUUID,
    body: FeedbackAction,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    fb = (await db.execute(select(Feedback).where(Feedback.id == fb_id).with_for_update())).scalar_one_or_none()
    if not fb:
        raise HTTPException(404)
    # Защита от повторного начисления: проверяем ОБА типа наград
    already_rewarded = (fb.reward_kopecks and fb.reward_kopecks > 0) or fb.status == "rewarded"
    wants_reward = body.reward > 0 or body.reward_tokens > 0
    if already_rewarded and wants_reward:
        raise HTTPException(409, "Награда уже начислена")

    # State machine: допустимые переходы статусов
    ALLOWED_TRANSITIONS = {
        "new": {"in_review", "accepted", "rejected", "rewarded"},
        "in_review": {"accepted", "rejected", "rewarded"},
        "accepted": {"rewarded"},  # можно только наградить
        # rejected и rewarded — финальные статусы
    }
    allowed = ALLOWED_TRANSITIONS.get(fb.status, set())
    if body.status not in allowed:
        raise HTTPException(409, f"Нельзя сменить статус с '{fb.status}' на '{body.status}'")

    fb.status = body.status
    fb.admin_response = body.response_text
    # Награда за фидбек — в токенах (предпочтительно) или в копейках (обратная совместимость)
    actual_reward_tokens = body.reward_tokens or 0
    actual_reward_kopecks = body.reward or 0
    if actual_reward_tokens > 0 or actual_reward_kopecks > 0:
        fb.reward_kopecks = actual_reward_kopecks  # обратная совместимость
        fb.status = "rewarded"
        user = (await db.execute(select(User).where(User.id == fb.user_id).with_for_update())).scalar_one_or_none()
        if not user:
            raise HTTPException(404, "Пользователь не найден")
        if actual_reward_tokens > 0:
            user.token_balance = (user.token_balance or 0) + actual_reward_tokens
            db.add(Transaction(
                user_id=user.id,
                type="rating_bonus",
                amount_tokens=actual_reward_tokens,
                description=f"Награда за обратную связь: {actual_reward_tokens:,} токенов",
            ))
            logger.info("Feedback %s rewarded: %d tokens to user %s, admin=%s",
                        fb_id, actual_reward_tokens, str(user.id)[:8], str(admin.id)[:8])
        elif actual_reward_kopecks > 0:
            user.balance_kopecks = (user.balance_kopecks or 0) + actual_reward_kopecks
            db.add(Transaction(
                user_id=user.id,
                type="rating_bonus",
                amount_kopecks=actual_reward_kopecks,
                description=f"Награда за обратную связь",
            ))
            logger.info("Feedback %s rewarded: %d kopecks to user %s, admin=%s",
                        fb_id, actual_reward_kopecks, str(user.id)[:8], str(admin.id)[:8])
    await db.commit()
    return {"ok": True}


@router.get("/clients")
async def list_clients(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Подробная таблица клиентов: источник, выручка, статистика генераций."""
    from sqlalchemy import case as sql_case, literal_column

    # Выручка по пользователям (только подтверждённые оплаты)
    rev_q = (await db.execute(
        select(
            Transaction.user_id,
            func.coalesce(func.sum(Transaction.amount_kopecks), 0).label('revenue')
        )
        .where(
            Transaction.type == 'purchase',
            Transaction.external_payment_id.is_not(None),
            Transaction.credited_at.is_not(None),
        )
        .group_by(Transaction.user_id)
    )).all()
    rev_map = {r[0]: r[1] for r in rev_q}

    # Статистика дел по пользователям (owner)
    case_q = (await db.execute(
        select(
            Case.user_id,
            func.count().label('total'),
            func.count().filter(Case.status == 'completed').label('completed'),
            func.count().filter(Case.status == 'error').label('errors'),
            func.max(Case.updated_at).filter(Case.status == 'completed').label('last_completed_at'),
        )
        .group_by(Case.user_id)
    )).all()
    case_map = {r[0]: {'total': r[1], 'completed': r[2], 'errors': r[3], 'last_completed_at': r[4]} for r in case_q}

    # Статистика дел по created_by (для помощников)
    created_by_q = (await db.execute(
        select(
            Case.created_by,
            func.count().label('total'),
            func.count().filter(Case.status == 'completed').label('completed'),
            func.count().filter(Case.status == 'error').label('errors'),
        )
        .where(Case.created_by.is_not(None))
        .group_by(Case.created_by)
    )).all()
    created_by_case_map = {r[0]: {'total': r[1], 'completed': r[2], 'errors': r[3]} for r in created_by_q}

    # Подробный список дел с файлами и содержимым
    all_cases = (await db.execute(
        select(Case).order_by(Case.created_at.desc())
    )).scalars().all()

    # Файлы по делам
    all_files = (await db.execute(
        select(CaseFile).order_by(CaseFile.uploaded_at)
    )).scalars().all()
    files_by_case = {}
    for cf in all_files:
        files_by_case.setdefault(cf.case_id, []).append({
            "name": cf.filename,
            "type": cf.file_type,
            "uploaded_at": cf.uploaded_at.strftime("%d.%m %H:%M") if cf.uploaded_at else None,
        })

    cases_map = {}
    for c in all_cases:
        duration = None
        if c.status != "draft" and c.updated_at and c.created_at:
            duration = int((c.updated_at - c.created_at).total_seconds())

        gen_text = c.final_text or c.generated_text or ""
        summary = ""
        if gen_text:
            # Берём первые 200 символов, убираем заголовки типа "ВВОДНАЯ ЧАСТЬ"
            clean = gen_text.replace("ВВОДНАЯ ЧАСТЬ", "").replace("ОПИСАТЕЛЬНАЯ ЧАСТЬ", "").strip()
            lines = [l.strip() for l in clean.split(chr(10)) if l.strip() and len(l.strip()) > 10]
            summary = " ".join(lines[:3])[:200]
            if len(summary) >= 200:
                summary = summary[:197] + "..."

        tokens = None
        if c.tokens_used:
            try:
                tokens = {
                    "prompt": c.tokens_used.get("prompt_tokens", 0),
                    "completion": c.tokens_used.get("completion_tokens", 0),
                }
            except Exception:
                tokens = None

        case_files = files_by_case.get(c.id, [])
        case_entry = {
            "id": str(c.id)[:8],
            "title": c.title or c.user_instructions or "Без названия",
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "created_time": c.created_at.strftime("%d.%m %H:%M") if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "updated_time": c.updated_at.strftime("%d.%m %H:%M") if c.updated_at else None,
            "user_instructions": c.user_instructions or None,
            "files": case_files,
            "files_count": len(case_files),
            "has_generated_text": bool(gen_text),
            "generated_length": len(gen_text) if gen_text else 0,
            "duration_sec": duration,
            "tokens": tokens,
            "summary": summary or None,
            "billing_method": getattr(c, 'billing_method', None),
            "cost_kopecks": getattr(c, 'cost_kopecks', 0) or 0,
            "cost_rub": round((getattr(c, 'cost_kopecks', 0) or 0) / 100, 2),
        }
        cases_map.setdefault(c.user_id, []).append(case_entry)
        # Also index by created_by so assistants see their cases
        if c.created_by and c.created_by != c.user_id:
            cases_map.setdefault(c.created_by, []).append(case_entry)

    # Попытки покупки по пользователям
    purchase_txs = (await db.execute(
        select(Transaction)
        .where(Transaction.purchase_type.is_not(None))
        .order_by(Transaction.created_at.desc())
    )).scalars().all()
    purchases_map = {}
    for pt in purchase_txs:
        purchases_map.setdefault(pt.user_id, []).append({
            "type": pt.purchase_type,
            "amount_rub": (pt.amount_kopecks or 0) / 100,
            "description": pt.description,
            "has_payment_link": bool(pt.external_payment_id),
            "created_at": pt.created_at.isoformat() if pt.created_at else None,
            "created_time": pt.created_at.strftime("%d.%m %H:%M") if pt.created_at else None,
        })

    # Activity log по пользователям
    all_activities = (await db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc())
    )).scalars().all()
    activity_map = {}
    # Count logins per user
    visit_count_map = {}
    for a in all_activities:
        if a.action == "login":
            visit_count_map[a.user_id] = visit_count_map.get(a.user_id, 0) + 1
    for a in all_activities:
        activity_map.setdefault(a.user_id, []).append({
            "action": a.action,
            "details": a.details,
            "utm_source": a.utm_source,
            "ip_address": a.ip_address,
            "case_id": str(a.case_id)[:8] if a.case_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "created_time": a.created_at.strftime("%d.%m %H:%M") if a.created_at else None,
        })

    # Referral counts from referral_events
    from app.models import ReferralEvent
    ref_counts_q = await db.execute(
        select(ReferralEvent.referrer_id, func.count()).group_by(ReferralEvent.referrer_id)
    )
    referral_counts = {r[0]: r[1] for r in ref_counts_q.fetchall()}
    # Referred-by map: who invited whom
    referred_by_map = {}
    for u_ref in (await db.execute(select(User).where(User.referred_by.is_not(None)))).scalars().all():
        referred_by_map[u_ref.id] = u_ref.referred_by

    # Cost per user: from actual case.cost_kopecks in DB
    cost_map = {}
    for c in all_cases:
        if c.status == 'completed' and getattr(c, 'cost_kopecks', 0):
            cost_map[c.user_id] = cost_map.get(c.user_id, 0) + (c.cost_kopecks or 0)

    # Judge-assistant relationships
    all_ja = (await db.execute(select(JudgeAssistant))).scalars().all()
    # Build user lookup for names
    user_lookup = {}  # filled after users query

    # Все пользователи
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    for u in users:
        user_lookup[u.id] = {"name": u.name, "email": u.email, "display_id": u.display_id,
                             "free_cases_left": u.free_cases_left or 0, "paid_cases_left": u.paid_cases_left or 0,
                             "subscription_until": u.subscription_until.isoformat() if getattr(u, 'subscription_until', None) else None}

    # Maps: who is assistant of whom, who has which assistants
    judges_of_map = {}   # assistant_id → [{ judge info }]
    assistants_of_map = {}  # judge_id → [{ assistant info }]
    for ja in all_ja:
        j_info = user_lookup.get(ja.judge_id, {})
        a_info = user_lookup.get(ja.assistant_id, {})
        judges_of_map.setdefault(ja.assistant_id, []).append({
            "id": str(ja.judge_id)[:8],
            "full_id": str(ja.judge_id),
            "display_id": j_info.get("display_id"),
            "name": j_info.get("name") or j_info.get("email") or "?",
            "free_cases_left": j_info.get("free_cases_left", 0),
            "paid_cases_left": j_info.get("paid_cases_left", 0),
            "subscription_until": j_info.get("subscription_until"),
        })
        assistants_of_map.setdefault(ja.judge_id, []).append({
            "id": str(ja.assistant_id)[:8],
            "full_id": str(ja.assistant_id),
            "display_id": a_info.get("display_id"),
            "name": a_info.get("name") or a_info.get("email") or "?",
        })

    result = []
    for u in users:
        cs = case_map.get(u.id, {'total': 0, 'completed': 0, 'errors': 0})
        # For assistants: use created_by stats (their actual work)
        cb_cs = created_by_case_map.get(u.id, None)
        if cb_cs and cs['total'] == 0:
            cs = cb_cs
        result.append({
            "id": str(u.id),
                "display_id": u.display_id,
            "full_id": str(u.id),
            "email": u.email,
            "name": u.name,
            "source": getattr(u, 'utm_source', None) or None,
            "yandex_id": bool(u.yandex_id),
            "vk_id": bool(u.vk_id),
            "is_admin": getattr(u, 'is_admin', False),
            "billing_model": getattr(u, 'billing_model', 'tokens'),
            "free_cases_left": getattr(u, 'free_cases_left', 0) or 0,
            "paid_cases_left": getattr(u, 'paid_cases_left', 0) or 0,
            "subscription_until": u.subscription_until.isoformat() if getattr(u, 'subscription_until', None) else None,
            "ab_group": getattr(u, 'ab_group', None),
            "promo_price": getattr(u, 'promo_price', None),
            "revenue_kopecks": rev_map.get(u.id, 0),
            "revenue_rub": rev_map.get(u.id, 0) / 100,
            "total_cases": cs['total'],
            "completed_cases": cs['completed'],
            "error_cases": cs['errors'],
            "token_balance": u.token_balance or 0,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_activity": u.last_activity.isoformat() if getattr(u, 'last_activity', None) else None,
            "last_completed_at": cs['last_completed_at'].isoformat() if cs.get('last_completed_at') else None,
            "city": getattr(u, 'city', None),
            "timezone": getattr(u, 'timezone', None),
            "cases": cases_map.get(u.id, []),
            "purchase_attempts": purchases_map.get(u.id, []),
            "activity_log": activity_map.get(u.id, []),
            "visit_count": visit_count_map.get(u.id, 0),
            "available_cases": (u.free_cases_left or 0) + (u.paid_cases_left or 0),
            "referral_count": referral_counts.get(u.id, 0),
            "referred_by_id": str(referred_by_map[u.id])[:8] if u.id in referred_by_map else None,
            "cost_kopecks": cost_map.get(u.id, 0),
            "cost_rub": round(cost_map.get(u.id, 0) / 100, 2),
            "margin_rub": round((int(rev_map.get(u.id, 0)) * 0.9 - cost_map.get(u.id, 0)) / 100, 2),
            "judge_of": judges_of_map.get(u.id, []),
            "assistants": assistants_of_map.get(u.id, []),
        })
    return result



@router.get("/analytics")
async def analytics(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db),
                     days: int = Query(default=14, ge=1, le=90)):
    """Аналитика: воронка по дням, retention, запросы, часы активности."""
    from sqlalchemy import cast, Date, Integer, extract, case as sql_case, text

    days_back = days

    # 1. Воронка по дням
    start_date = utcnow_naive() - timedelta(days=days_back)

    # Регистрации по дням
    reg_q = (await db.execute(
        select(cast(User.created_at, Date).label("day"), func.count().label("cnt"))
        .where(User.created_at >= start_date)
        .group_by(cast(User.created_at, Date))
        .order_by(cast(User.created_at, Date))
    )).all()
    reg_map = {str(r[0]): r[1] for r in reg_q}

    # Дела по дням и статусу
    cases_q = (await db.execute(
        select(
            cast(Case.created_at, Date).label("day"),
            func.count().label("total"),
            func.count().filter(Case.status == "completed").label("completed"),
            func.count().filter(Case.status == "error").label("errors"),
        )
        .where(Case.created_at >= start_date)
        .group_by(cast(Case.created_at, Date))
        .order_by(cast(Case.created_at, Date))
    )).all()
    cases_map = {str(r[0]): {"total": r[1], "completed": r[2], "errors": r[3]} for r in cases_q}

    # Загрузки файлов по дням (уникальные дела с файлами)
    uploads_q = (await db.execute(
        select(cast(CaseFile.uploaded_at, Date).label("day"), func.count(func.distinct(CaseFile.case_id)).label("cnt"))
        .where(CaseFile.uploaded_at >= start_date)
        .group_by(cast(CaseFile.uploaded_at, Date))
        .order_by(cast(CaseFile.uploaded_at, Date))
    )).all()
    uploads_map = {str(r[0]): r[1] for r in uploads_q}

    # Оплаты по дням
    payments_q = (await db.execute(
        select(
            cast(Transaction.created_at, Date).label("day"),
            func.count().label("cnt"),
            func.coalesce(func.sum(Transaction.amount_kopecks), 0).label("total")
        )
        .where(
            Transaction.type == "purchase",
            Transaction.external_payment_id.is_not(None),
            Transaction.credited_at.is_not(None),
            Transaction.created_at >= start_date,
        )
        .group_by(cast(Transaction.created_at, Date))
        .order_by(cast(Transaction.created_at, Date))
    )).all()
    payments_map = {str(r[0]): {"count": r[1], "revenue": r[2] / 100} for r in payments_q}

    # Себестоимость по дням (completed cases cost_kopecks)
    cost_q = (await db.execute(
        select(
            cast(Case.created_at, Date).label("day"),
            func.coalesce(func.sum(Case.cost_kopecks), 0).label("total")
        )
        .where(Case.created_at >= start_date, Case.status == "completed")
        .group_by(cast(Case.created_at, Date))
        .order_by(cast(Case.created_at, Date))
    )).all()
    cost_map = {str(r[0]): r[1] / 100 for r in cost_q}

    # Собираем воронку
    funnel_days = []
    for i in range(days_back + 1):
        d = (utcnow_naive() - timedelta(days=days_back - i)).strftime("%Y-%m-%d")
        cs = cases_map.get(d, {"total": 0, "completed": 0, "errors": 0})
        pm = payments_map.get(d, {"count": 0, "revenue": 0})
        funnel_days.append({
            "date": d,
            "registrations": reg_map.get(d, 0),
            "uploads": uploads_map.get(d, 0),
            "cases": cs["total"],
            "completed": cs["completed"],
            "errors": cs["errors"],
            "payments": pm["count"],
            "revenue": pm["revenue"],
            "cost": round(cost_map.get(d, 0), 2),
            "profit": round(pm["revenue"] - cost_map.get(d, 0), 2),
        })

    # 2. Retention (когорты последних 7 дней)
    retention = []
    for cohort_offset in range(7):
        cohort_date = (utcnow_naive() - timedelta(days=6 - cohort_offset)).date()
        cohort_start = datetime.combine(cohort_date, datetime.min.time())
        cohort_end = cohort_start + timedelta(days=1)

        # Юзеры зарегистрированные в этот день
        cohort_users = (await db.execute(
            select(User.id).where(User.created_at >= cohort_start, User.created_at < cohort_end)
        )).scalars().all()

        if not cohort_users:
            retention.append({"date": str(cohort_date), "size": 0, "d1": 0, "d2": 0, "d3": 0})
            continue

        # Кто создавал дела в следующие дни
        days_ret = {}
        for dn in [1, 2, 3]:
            ret_start = cohort_start + timedelta(days=dn)
            ret_end = ret_start + timedelta(days=1)
            ret_count = (await db.execute(
                select(func.count(func.distinct(Case.user_id)))
                .where(
                    Case.user_id.in_(cohort_users),
                    Case.created_at >= ret_start,
                    Case.created_at < ret_end,
                )
            )).scalar()
            days_ret[f"d{dn}"] = ret_count or 0

        retention.append({
            "date": str(cohort_date),
            "size": len(cohort_users),
            **days_ret,
        })

    # 3. Топ поисковых запросов с конверсией и выручкой
    users_with_utm = (await db.execute(
        select(User.id, User.utm_source).where(User.utm_source.is_not(None), User.utm_source != "", User.created_at >= start_date)
    )).all()

    term_stats = {}
    for uid, utm in users_with_utm:
        term = ""
        for part in (utm or "").split("&"):
            if part.startswith("term="):
                term = part[5:]
                break
        if not term:
            term = "(без запроса)"

        if term not in term_stats:
            term_stats[term] = {"registrations": 0, "completed": 0, "payments": 0, "revenue": 0}
        term_stats[term]["registrations"] += 1

    # Get completed + payments per user (pre-fetched in period)
    if users_with_utm:
        uid_list = [uid for uid, _ in users_with_utm]
        comp_q = (await db.execute(
            select(Case.user_id, func.count()).where(
                Case.user_id.in_(uid_list), Case.status == "completed", Case.created_at >= start_date
            ).group_by(Case.user_id)
        )).all()
        comp_map = {r[0]: r[1] for r in comp_q}
        pay_q = (await db.execute(
            select(Transaction.user_id, func.count(), func.coalesce(func.sum(Transaction.amount_kopecks), 0)).where(
                Transaction.user_id.in_(uid_list),
                Transaction.type == "purchase", Transaction.external_payment_id.is_not(None),
                Transaction.credited_at.is_not(None), Transaction.created_at >= start_date,
            ).group_by(Transaction.user_id)
        )).all()
        pay_map = {r[0]: (r[1], r[2] / 100) for r in pay_q}

        for uid, utm in users_with_utm:
            term = ""
            for part in (utm or "").split("&"):
                if part.startswith("term="):
                    term = part[5:]
                    break
            if not term:
                term = "(без запроса)"
            if comp_map.get(uid):
                term_stats[term]["completed"] += 1
            if pay_map.get(uid):
                term_stats[term]["payments"] += pay_map[uid][0]
                term_stats[term]["revenue"] += pay_map[uid][1]

    top_terms = sorted(term_stats.items(), key=lambda x: x[1]["revenue"], reverse=True)[:20]

    # 3b. Channel breakdown: source × medium groups
    all_users = (await db.execute(
        select(User.id, User.utm_source).where(User.created_at >= start_date)
    )).all()
    channel_map = {}
    for uid, utm in all_users:
        src = "organic"
        med = "seo"
        if utm:
            parts = dict(p.split("=", 1) for p in utm.split("&") if "=" in p)
            src = parts.get("utm_source", parts.get("source", "organic"))
            med = parts.get("utm_medium", parts.get("medium", "seo"))
        channel = f"{src}/{med}"
        channel_map.setdefault(channel, {"registrations": 0, "completed": 0, "payments": 0, "revenue": 0, "uids": []})
        channel_map[channel]["registrations"] += 1
        channel_map[channel]["uids"].append(uid)

    if all_users:
        all_uids = [uid for uid, _ in all_users]
        ch_comp = (await db.execute(
            select(Case.user_id, func.count()).where(
                Case.user_id.in_(all_uids), Case.status == "completed", Case.created_at >= start_date
            ).group_by(Case.user_id)
        )).all()
        ch_comp_map = {r[0]: r[1] for r in ch_comp}
        ch_pay = (await db.execute(
            select(Transaction.user_id, func.count(), func.coalesce(func.sum(Transaction.amount_kopecks), 0)).where(
                Transaction.user_id.in_(all_uids),
                Transaction.type == "purchase", Transaction.external_payment_id.is_not(None),
                Transaction.credited_at.is_not(None), Transaction.created_at >= start_date,
            ).group_by(Transaction.user_id)
        )).all()
        ch_pay_map = {r[0]: (r[1], r[2] / 100) for r in ch_pay}
        for ch, data in channel_map.items():
            for uid in data.pop("uids", []):
                if ch_comp_map.get(uid):
                    data["completed"] += 1
                if ch_pay_map.get(uid):
                    data["payments"] += ch_pay_map[uid][0]
                    data["revenue"] += ch_pay_map[uid][1]

    channels = sorted(channel_map.items(), key=lambda x: x[1]["revenue"], reverse=True)

    # 4. Активность по часам
    hours_q = (await db.execute(
        select(
            extract("hour", Case.created_at).label("hour"),
            func.count().label("cnt")
        )
        .where(Case.created_at >= start_date)
        .group_by(extract("hour", Case.created_at))
        .order_by(extract("hour", Case.created_at))
    )).all()
    hours = {int(r[0]): r[1] for r in hours_q}
    hourly = [{"hour": h, "cases": hours.get(h, 0)} for h in range(24)]

    # 5. Юнит-экономика
    total_reg = (await db.execute(select(func.count()).select_from(User))).scalar()
    total_completed = (await db.execute(select(func.count()).where(Case.status == "completed"))).scalar()
    total_revenue = (await db.execute(
        select(func.coalesce(func.sum(Transaction.amount_kopecks), 0))
        .where(Transaction.type == "purchase", Transaction.external_payment_id.is_not(None), Transaction.credited_at.is_not(None))
    )).scalar() / 100
    total_payments = (await db.execute(
        select(func.count())
        .where(Transaction.type == "purchase", Transaction.external_payment_id.is_not(None), Transaction.credited_at.is_not(None))
    )).scalar()
    total_cost = (await db.execute(
        select(func.coalesce(func.sum(Case.cost_kopecks), 0)).where(Case.status == "completed")
    )).scalar() / 100

    # Топ по доработкам (refine_start за период)
    refine_q = (await db.execute(
        select(ActivityLog.user_id, func.count().label("cnt"))
        .where(ActivityLog.action == "refine_start", ActivityLog.created_at >= start_date)
        .group_by(ActivityLog.user_id)
        .order_by(func.count().desc())
        .limit(10)
    )).all()
    top_refiners = []
    if refine_q:
        uid_list = [r[0] for r in refine_q]
        users = (await db.execute(select(User).where(User.id.in_(uid_list)))).scalars().all()
        user_map = {u.id: u for u in users}
        top_refiners = [
            {"name": (user_map.get(uid) and (user_map[uid].name or user_map[uid].email or str(uid)[:8])) or str(uid)[:8],
             "refine_count": cnt}
            for uid, cnt in refine_q
        ]

    return {
        "funnel": funnel_days,
        "retention": retention,
        "top_terms": [{"term": t, **s} for t, s in top_terms],
        "hourly": hourly,
        "unit_economics": {
            "total_users": total_reg,
            "total_completed": total_completed,
            "total_revenue": total_revenue,
            "total_payments": total_payments,
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_revenue - total_cost, 2),
            "margin_pct": round((total_revenue - total_cost) / total_revenue * 100, 1) if total_revenue > 0 else 0,
            "avg_revenue_per_payment": round(total_revenue / total_payments, 2) if total_payments else 0,
            "conversion_to_completed": round(total_completed / total_reg * 100, 1) if total_reg else 0,
            "conversion_to_payment": round(total_payments / total_reg * 100, 2) if total_reg else 0,
        },
        "top_refiners": top_refiners,
        "channels": [{"channel": ch, **data} for ch, data in channels],
    }




@router.post("/cases/{case_id}/rescue")
async def rescue_case(case_id: str, admin: User = Depends(get_current_admin)):
    """Admin rescue: enqueue stuck case for recovery."""
    from app.services.job_queue import enqueue_rescue
    try:
        job_id = await enqueue_rescue(case_id)
        return {"status": "enqueued", "job_id": job_id, "case_id": case_id}
    except Exception as e:
        raise HTTPException(500, f"Rescue failed: {e}")


@router.post("/cases/{case_id}/retry")
async def retry_case(case_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Admin retry: reset case and re-enqueue."""
    from app.models import Case, CaseRun
    from sqlalchemy import select
    case = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    # Cancel existing active runs
    active_runs = (await db.execute(
        select(CaseRun).where(CaseRun.case_id == case_id, CaseRun.status.in_(["queued", "running"]))
    )).scalars().all()
    for run in active_runs:
        run.status = "cancelled"
        if not run.started_at:
            run.started_at = run.created_at or utcnow_naive()
        if not run.finished_at:
            run.finished_at = utcnow_naive()
    case.status = "draft"
    case.stage = None
    await db.commit()
    # Enqueue fresh
    from app.services.job_queue import enqueue_full_pipeline
    job_id = await enqueue_full_pipeline(case_id, str(case.user_id), "free_case")
    return {"status": "retrying", "job_id": job_id, "case_id": case_id}


@router.get("/purchase-attempts")
async def list_purchase_attempts(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Purchase attempt transactions with user info."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.purchase_type.is_not(None))
        .order_by(Transaction.created_at.desc())
    )
    txs = result.scalars().all()

    # Get user info
    user_ids = list(set(t.user_id for t in txs))
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_map = {u.id: u for u in users_result.scalars().all()}
    else:
        users_map = {}

    items = []
    for t in txs:
        u = users_map.get(t.user_id)
        items.append({
            "id": str(t.id),
            "user_id": str(t.user_id),
            "user_email": u.email if u else None,
            "user_name": u.name if u else None,
            "purchase_type": t.purchase_type,
            "amount_kopecks": t.amount_kopecks,
            "description": t.description,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return items

@router.get("/ab-test")
async def ab_test_report(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Full AB test log: per-user timeline of what they saw, bought, and cost us."""

    users = (await db.execute(
        select(User).where(User.billing_model == "cases").order_by(User.created_at.desc())
    )).scalars().all()

    # All activities
    all_activities = (await db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.asc())
    )).scalars().all()
    acts_by_user = {}
    for a in all_activities:
        acts_by_user.setdefault(a.user_id, []).append(a)

    # All transactions (attempts + paid)
    all_txs = (await db.execute(
        select(Transaction).where(Transaction.type == "purchase").order_by(Transaction.created_at.asc())
    )).scalars().all()
    txs_by_user = {}
    for t in all_txs:
        txs_by_user.setdefault(t.user_id, []).append(t)

    # All cases with cost
    all_cases = (await db.execute(select(Case).order_by(Case.created_at.asc()))).scalars().all()
    cases_by_user = {}
    for c in all_cases:
        cases_by_user.setdefault(c.user_id, []).append(c)

    # Case files count
    from sqlalchemy import text as raw_text
    file_counts = dict((await db.execute(
        raw_text("SELECT case_id, count(*) FROM case_files GROUP BY case_id")
    )).fetchall())

    result = []
    funnel_a = {"users": 0, "created_case": 0, "completed": 0, "saw_prices": 0, "attempted": 0, "paid": 0, "revenue": 0, "cost": 0}
    funnel_b = {"users": 0, "created_case": 0, "completed": 0, "saw_prices": 0, "attempted": 0, "paid": 0, "revenue": 0, "cost": 0}

    for u in users:
        is_promo = getattr(u, "promo_price", False)
        group = "A" if is_promo else "B"
        funnel = funnel_a if is_promo else funnel_b
        funnel["users"] += 1

        # Build timeline
        timeline = []

        # Registration
        timeline.append({
            "ts": u.created_at.isoformat() if u.created_at else None,
            "event": "register",
            "group": group,
            "details": f"AB={group} promo={'yes' if is_promo else 'no'}",
        })

        # Activities
        for a in acts_by_user.get(u.id, []):
            entry = {
                "ts": a.created_at.isoformat() if a.created_at else None,
                "event": a.action,
                "details": a.details or "",
            }
            # Enrich specific events
            if a.action == "ab_prices_shown":
                entry["event"] = "saw_prices"
                entry["prices"] = a.details
            elif a.action == "paywall_shown":
                entry["event"] = "saw_paywall"
            elif a.action == "click_buy":
                entry["event"] = "click_buy"
                entry["package"] = a.details
            elif a.action == "purchase_attempt":
                entry["event"] = "purchase_attempt"
            elif a.action == "payment_redirect":
                entry["event"] = "payment_redirect"
                entry["package"] = a.details

            timeline.append(entry)

        # Transactions
        user_revenue = 0
        for t in txs_by_user.get(u.id, []):
            is_paid = t.credited_at is not None
            entry = {
                "ts": t.created_at.isoformat() if t.created_at else None,
                "event": "paid" if is_paid else "payment_pending",
                "package": t.purchase_type,
                "amount_rub": (t.amount_kopecks or 0) / 100,
                "details": t.description or "",
            }
            if is_paid:
                user_revenue += (t.amount_kopecks or 0) / 100
                funnel["paid"] += 1
            timeline.append(entry)

        # Cases with cost
        user_cost = 0
        user_cases = cases_by_user.get(u.id, [])
        for c in user_cases:
            files = file_counts.get(c.id, 0)
            cost_rub = round((c.cost_kopecks or 0) / 100, 2)
            ocr_est = round(files * 1.03, 2)
            ds_est = round(cost_rub - ocr_est, 2) if cost_rub > ocr_est else 0
            user_cost += ocr_est + ds_est if cost_rub == 0 else cost_rub

            timeline.append({
                "ts": c.created_at.isoformat() if c.created_at else None,
                "event": f"case_{c.status}",
                "details": f"{files} files",
                "cost_rub": cost_rub if cost_rub > 0 else ocr_est,
                "ocr_files": files,
                "title": (c.title or "")[:40],
            })

        # Update funnel
        if user_cases:
            funnel["created_case"] += 1
        if any(c.status == "completed" for c in user_cases):
            funnel["completed"] += 1
        saw = any(a.action in ("ab_prices_shown", "page_billing", "paywall_shown") for a in acts_by_user.get(u.id, []))
        if saw:
            funnel["saw_prices"] += 1
        attempted = any(a.action == "purchase_attempt" for a in acts_by_user.get(u.id, []))
        if attempted:
            funnel["attempted"] += 1
        funnel["revenue"] += user_revenue
        funnel["cost"] += user_cost

        # Sort timeline by ts
        timeline.sort(key=lambda x: x.get("ts") or "")

        result.append({
            "name": u.name or u.email or str(u.id)[:8],
            "user_id": str(u.id)[:8],
            "group": group,
            "is_promo": is_promo,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "revenue_rub": user_revenue,
            "cost_rub": round(user_cost, 2),
            "margin_rub": round(user_revenue - user_cost, 2),
            "cases_count": len(user_cases),
            "completed_count": sum(1 for c in user_cases if c.status == "completed"),
            "timeline": timeline,
        })

    # Add conversion rates to funnel
    for f in [funnel_a, funnel_b]:
        n = f["users"] or 1
        f["conv_case_pct"] = round(100 * f["created_case"] / n, 1)
        f["conv_paid_pct"] = round(100 * f["paid"] / n, 1)
        f["revenue"] = round(f["revenue"], 2)
        f["cost"] = round(f["cost"], 2)
        f["margin"] = round(f["revenue"] - f["cost"], 2)

    return {
        "funnel": {"A (promo)": funnel_a, "B (normal)": funnel_b},
        "users": result,
    }


@router.get("/system-check")
async def system_check(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Run all system health checks and return results."""
    checks = []

    # 1. Database
    try:
        await db.execute(select(func.count()).select_from(User))
        checks.append({"name": "База данных", "status": "ok"})
    except Exception as e:
        checks.append({"name": "База данных", "status": "error", "detail": str(e)[:100]})

    # 2. Redis
    try:
        from app.services.redis_stream import get_redis
        r = await get_redis()
        await r.ping()
        checks.append({"name": "Redis", "status": "ok"})
    except Exception as e:
        checks.append({"name": "Redis", "status": "error", "detail": str(e)[:100]})

    # 3. DeepSeek API
    try:
        from app.services.deepseek import deepseek
        result = await deepseek.chat([{"role": "user", "content": "ok"}], max_tokens=5)
        if result.get("content"):
            checks.append({"name": "DeepSeek API", "status": "ok"})
        else:
            checks.append({"name": "DeepSeek API", "status": "error", "detail": "Empty response"})
    except Exception as e:
        checks.append({"name": "DeepSeek API", "status": "error", "detail": str(e)[:100]})

    # 4. Tochka payment token
    try:
        from app.services.tochka_payment import get_token
        tok = await get_token()
        if tok:
            checks.append({"name": "Точка Банк", "status": "ok"})
        else:
            checks.append({"name": "Точка Банк", "status": "error", "detail": "No token"})
    except Exception as e:
        checks.append({"name": "Точка Банк", "status": "error", "detail": str(e)[:100]})

    # 5. Telegram bot
    try:
        import httpx
        from app.config import get_settings
        s = get_settings()
        if s.telegram_bot_token:
            async with httpx.AsyncClient(timeout=15) as c:
                resp = await c.get(f"https://api.telegram.org/bot{s.telegram_bot_token}/getMe")
                if resp.status_code == 200:
                    data = resp.json()
                    bot_name = data.get("result", {}).get("username", "?")
                    checks.append({"name": "Telegram бот", "status": "ok", "detail": f"@{bot_name}"})
                else:
                    checks.append({"name": "Telegram бот", "status": "error", "detail": f"HTTP {resp.status_code}"})
        else:
            checks.append({"name": "Telegram бот", "status": "warning", "detail": "Token not set"})
    except Exception as e:
        checks.append({"name": "Telegram бот", "status": "warning", "detail": str(e)[:80]})

    # 6. Workers (check arq queue)
    try:
        from app.services.redis_stream import get_redis
        r = await get_redis()
        queue_len = await r.zcard("arq:queue")
        checks.append({"name": "Очередь задач", "status": "ok", "detail": f"{queue_len} в очереди"})
    except Exception as e:
        checks.append({"name": "Очередь задач", "status": "error", "detail": str(e)[:100]})

    # 7. Stuck cases
    stuck = (await db.execute(
        select(func.count()).where(Case.status == "processing", Case.updated_at < utcnow_naive() - timedelta(minutes=15))
    )).scalar() or 0
    if stuck == 0:
        checks.append({"name": "Зависшие дела", "status": "ok"})
    else:
        checks.append({"name": "Зависшие дела", "status": "error", "detail": f"{stuck} дел зависло"})

    # 8. Idle transactions
    idle = (await db.execute(select(func.count()).select_from(User))).scalar()  # dummy to keep session alive
    try:
        from sqlalchemy import text
        idle_r = await db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction' AND pid != pg_backend_pid()"))
        idle_count = idle_r.scalar() or 0
        await db.commit()
        if idle_count <= 2:
            checks.append({"name": "Транзакции БД", "status": "ok"})
        else:
            checks.append({"name": "Транзакции БД", "status": "warning", "detail": f"{idle_count} idle"})
    except Exception:
        checks.append({"name": "Транзакции БД", "status": "ok"})

    # 9. Disk space
    try:
        import shutil
        usage = shutil.disk_usage("/")
        pct = round(usage.used / usage.total * 100)
        free_gb = round(usage.free / (1024**3), 1)
        if pct < 80:
            checks.append({"name": "Диск", "status": "ok", "detail": f"{free_gb} ГБ свободно ({pct}%)"})
        else:
            checks.append({"name": "Диск", "status": "warning", "detail": f"{free_gb} ГБ свободно ({pct}%)"})
    except Exception:
        checks.append({"name": "Диск", "status": "ok"})

    # 10. OAuth (check config)
    try:
        from app.config import get_settings
        s = get_settings()
        ya = bool(s.yandex_client_id)
        vk = bool(s.vk_client_id)
        if ya and vk:
            checks.append({"name": "OAuth (Яндекс + VK)", "status": "ok"})
        else:
            missing = []
            if not ya: missing.append("Яндекс")
            if not vk: missing.append("VK")
            checks.append({"name": "OAuth", "status": "error", "detail": f"Нет: {', '.join(missing)}"})
    except Exception:
        checks.append({"name": "OAuth", "status": "ok"})

    all_ok = all(c["status"] == "ok" for c in checks)
    return {"status": "ok" if all_ok else "issues", "checks": checks}
