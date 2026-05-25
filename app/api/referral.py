"""
Реферальная система: user-to-user рефералы.
- Track link copy
- User referral stats (для страницы /referral)
- Admin referral leaderboard
"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case as sa_case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, ReferralEvent, ReferralLinkClick, Transaction, ActivityLog
from app.utils.deps import get_current_user, get_current_admin

from app.utils.datetime import utcnow_naive
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/referral", tags=["referral"])

REFERRAL_BONUS_CASES = 3


# ── User endpoints ────────────────────────────────────────

@router.post("/track-copy")
async def track_copy(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Track when user copies their referral link."""
    db.add(ReferralLinkClick(user_id=user.id))
    await db.commit()
    return {"ok": True}


@router.get("/my-stats")
async def my_referral_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """User-facing referral stats for /referral page."""
    uid = user.id

    signups = (await db.execute(
        select(func.count()).select_from(ReferralEvent).where(ReferralEvent.referrer_id == uid)
    )).scalar() or 0

    conversions = (await db.execute(
        select(func.count()).select_from(ReferralEvent).where(
            ReferralEvent.referrer_id == uid,
            ReferralEvent.status == "bonus_paid",
        )
    )).scalar() or 0

    bonus_cases = (await db.execute(
        select(func.sum(ReferralEvent.referrer_bonus_cases)).where(ReferralEvent.referrer_id == uid)
    )).scalar() or 0

    copies = (await db.execute(
        select(func.count()).select_from(ReferralLinkClick).where(ReferralLinkClick.user_id == uid)
    )).scalar() or 0

    ref_code = str(uid).replace("-", "")[:8]

    return {
        "ref_code": ref_code,
        "ref_url": "https://\u043f\u043e\u043c\u043e\u0449\u043d\u0438\u043a-\u0441\u0443\u0434\u044c\u0438.\u0440\u0444/login?ref=" + ref_code,
        "signups": signups,
        "conversions": conversions,
        "bonus_cases_earned": bonus_cases,
        "link_copies": copies,
    }


# ── Admin endpoints ───────────────────────────────────────

@router.get("/admin/stats")
async def admin_referral_stats(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Admin referral leaderboard and totals."""
    now = utcnow_naive()
    day_ago = now - timedelta(hours=24)

    total_signups = (await db.execute(
        select(func.count()).select_from(ReferralEvent)
    )).scalar() or 0

    total_conversions = (await db.execute(
        select(func.count()).select_from(ReferralEvent).where(ReferralEvent.status == "bonus_paid")
    )).scalar() or 0

    total_link_copies = (await db.execute(
        select(func.count()).select_from(ReferralLinkClick)
    )).scalar() or 0

    signups_24h = (await db.execute(
        select(func.count()).select_from(ReferralEvent).where(ReferralEvent.registered_at >= day_ago)
    )).scalar() or 0

    conversions_24h = (await db.execute(
        select(func.count()).select_from(ReferralEvent).where(
            ReferralEvent.status == "bonus_paid",
            ReferralEvent.bonus_paid_at >= day_ago,
        )
    )).scalar() or 0

    stmt = (
        select(
            ReferralEvent.referrer_id,
            func.count().label("signups"),
            func.sum(sa_case((ReferralEvent.status == "bonus_paid", 1), else_=0)).label("conversions"),
            func.sum(ReferralEvent.referrer_bonus_cases).label("bonus_cases"),
        )
        .group_by(ReferralEvent.referrer_id)
        .order_by(func.count().desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).all()

    referrer_ids = [r.referrer_id for r in rows]
    users_map = {}
    if referrer_ids:
        users_list = (await db.execute(
            select(User).where(User.id.in_(referrer_ids))
        )).scalars().all()
        users_map = {u.id: u for u in users_list}

    copies_map = {}
    if referrer_ids:
        copies_rows = (await db.execute(
            select(ReferralLinkClick.user_id, func.count().label("copies"))
            .where(ReferralLinkClick.user_id.in_(referrer_ids))
            .group_by(ReferralLinkClick.user_id)
        )).all()
        copies_map = {r.user_id: r.copies for r in copies_rows}

    leaderboard = []
    for r in rows:
        u = users_map.get(r.referrer_id)
        sc = r.signups or 0
        cc = r.conversions or 0
        leaderboard.append({
            "referrer_id": str(r.referrer_id),
            "display_id": u.display_id if u else None,
            "name": (u.name if u else None) or "?",
            "email": (u.email if u else None) or "",
            "signups": sc,
            "conversions": cc,
            "bonus_cases": r.bonus_cases or 0,
            "link_copies": copies_map.get(r.referrer_id, 0),
            "conversion_rate": round(cc / sc * 100, 1) if sc > 0 else 0,
        })

    return {
        "totals": {
            "total_signups": total_signups,
            "total_conversions": total_conversions,
            "total_link_copies": total_link_copies,
            "conversion_rate": round(total_conversions / total_signups * 100, 1) if total_signups > 0 else 0,
            "signups_24h": signups_24h,
            "conversions_24h": conversions_24h,
        },
        "leaderboard": leaderboard,
    }


@router.get("/admin/referred/{referrer_id}")
async def admin_referred_users(referrer_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    referred_rows = (await db.execute(
        select(ReferralEvent, User).join(User, ReferralEvent.referred_id == User.id)
        .where(ReferralEvent.referrer_id == referrer_id)
        .order_by(ReferralEvent.registered_at.desc())
        .limit(200)
    )).all()

    return {
        "referrer_id": referrer_id,
        "total": len(referred_rows),
        "referred": [
            {
                "user_id": str(u.id),
                "display_id": u.display_id,
                "name": u.name,
                "email": u.email,
                "status": e.status,
                "registered_at": e.registered_at.isoformat() if e.registered_at else None,
                "converted_at": e.converted_at.isoformat() if e.converted_at else None,
                "bonus_paid_at": e.bonus_paid_at.isoformat() if e.bonus_paid_at else None,
            }
            for e, u in referred_rows
        ],
    }


# ── Bonus award function (called from billing.py) ────────

async def maybe_award_referral_bonus(db: AsyncSession, user: User, trigger_tx: Transaction):
    """
    Award referral bonus (3 cases each) when a referred user makes their first payment.
    Called from billing.py confirm_payment and main.py payment_checker.
    """
    if not user.referred_by:
        return

    prev_payments = (await db.execute(
        select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.credited_at.is_not(None),
            Transaction.id != trigger_tx.id,
        )
    )).scalar() or 0

    if prev_payments > 0:
        return

    event = (await db.execute(
        select(ReferralEvent).where(ReferralEvent.referred_id == user.id).with_for_update()
    )).scalar_one_or_none()

    if not event or event.status == "bonus_paid":
        return

    event.status = "converted"
    event.converted_at = utcnow_naive()
    await db.flush()

    user.free_cases_left = (user.free_cases_left or 0) + REFERRAL_BONUS_CASES
    event.referred_bonus_cases = REFERRAL_BONUS_CASES
    db.add(Transaction(
        user_id=user.id,
        type="referral_bonus",
        amount_tokens=0,
        description=f"Реферальный бонус: +{REFERRAL_BONUS_CASES} бесплатных дел",
    ))

    referrer = (await db.execute(
        select(User).where(User.id == user.referred_by).with_for_update()
    )).scalar_one_or_none()

    if referrer and referrer.is_active:
        referrer.free_cases_left = (referrer.free_cases_left or 0) + REFERRAL_BONUS_CASES
        event.referrer_bonus_cases = REFERRAL_BONUS_CASES
        db.add(Transaction(
            user_id=referrer.id,
            type="referral_bonus",
            amount_tokens=0,
            description=f"Реферальный бонус: +{REFERRAL_BONUS_CASES} дел (пригласил {user.name or str(user.id)[:8]})",
        ))
        logger.info("[REFERRAL-BONUS] referrer=%s +%d cases (invited %s)", str(referrer.id)[:8], REFERRAL_BONUS_CASES, str(user.id)[:8])
        db.add(ActivityLog(
            user_id=referrer.id,
            action="referral_bonus",
            details=f"Реферальный бонус +{REFERRAL_BONUS_CASES} дел — пригласил {user.name or str(user.id)[:8]}",
        ))
    else:
        logger.warning("[REFERRAL-BONUS] referrer=%s inactive, skipping", str(user.referred_by)[:8])

    event.status = "bonus_paid"
    event.bonus_paid_at = utcnow_naive()
    logger.info("[REFERRAL-BONUS] referred=%s +%d cases", str(user.id)[:8], REFERRAL_BONUS_CASES)
    db.add(ActivityLog(
        user_id=user.id,
        action="referral_bonus",
        details=f"Реферальный бонус +{REFERRAL_BONUS_CASES} дел за первую оплату",
    ))

    try:
        from app.services.telegram import send_admin, _esc
        ref_name = _esc(referrer.name or str(referrer.id)[:8]) if referrer else "?"
        new_name = _esc(user.name or str(user.id)[:8])
        await send_admin(
            f"\U0001f389 <b>Реферальный бонус!</b>\n"
            f"Реферер: {ref_name} \u2192 +{REFERRAL_BONUS_CASES} дел\n"
            f"Приглашённый: {new_name} \u2192 +{REFERRAL_BONUS_CASES} дел\n"
            f"Оплата: {trigger_tx.amount_kopecks // 100 if trigger_tx.amount_kopecks else 0}\u20bd"
        )
    except Exception:
        pass
