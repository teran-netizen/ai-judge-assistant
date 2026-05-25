"""
Email collection + send docx to user's email.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import base64

from app.database import get_db
from app.config import get_settings
from app.models import User, Case
from app.utils.deps import get_current_user
from app.services.unisender import subscribe_email
from app.services.docx_export import build_docx
from app.api.helpers.activity import log_activity

router = APIRouter(prefix="/api/email", tags=["email"])
logger = logging.getLogger(__name__)


@router.post("/collect")
async def collect_email(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить email юзера + подписать в Unisender."""
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Некорректный email")

    # Save to user record
    user.email = email
    await db.commit()

    # Subscribe to Unisender
    name = user.name or ""
    # await subscribe_email(email, name=name, tags="pomoshnik-sudji")  # disabled: using own SMTP

    logger.info(f"Email collected: user={user.id} email={email}")
    return {"status": "ok"}


@router.post("/send-docx/{case_id}")
async def send_docx_email(
    case_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить решение в .docx на email."""
    email = (body.get("email") or user.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Укажите email")

    case = (await db.execute(
        select(Case).where(Case.id == case_id, Case.user_id == user.id)
    )).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Дело не найдено")

    text = case.final_text or case.generated_text
    if not text:
        raise HTTPException(400, "Решение ещё не сгенерировано")

    # Save email if not saved
    if not user.email:
        user.email = email
        await db.commit()
        # await subscribe_email(...)  # disabled

    # Generate docx
    try:
        docx_buf = build_docx(case.title or "Документ", text)
        docx_bytes = docx_buf.getvalue()
    except Exception as e:
        logger.error(f"Docx generation failed: {e}")
        raise HTTPException(500, "Ошибка генерации документа")

    # Send email with attachment
    from app.services.docx_export import safe_filename
    filename = safe_filename(case.title or "", str(case.id))
    public_base_url = (get_settings().domain or "https://example.com").rstrip("/")

    html_body = f"""
    <div style="font-family: sans-serif; max-width: 600px;">
        <h2 style="color: #1a55f5;">ИИ Помощник Судьи</h2>
        <p>Здравствуйте!</p>
        <p>Ваш юридический документ готов и прикреплён к этому письму.</p>
        <p>Если нужна доработка — вернитесь в сервис: <a href="{public_base_url}/cases/{case_id}">открыть документ</a></p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
        <p style="color: #888; font-size: 12px;">
            AI Judge Assistant — автоматизация подготовки юридических документов
        </p>
    </div>
    """

    # Send via SMTP (our Yandex mail)
    from app.services.email_otp import _send_smtp_with_attachment
    ok = await _send_smtp_with_attachment(
        to_email=email,
        subject=f"Документ — {case.title or 'юридический документ'}",
        html=html_body,
        attachment_name=filename,
        attachment_bytes=docx_bytes,
    )

    if not ok:
        raise HTTPException(502, "Ошибка отправки email")

    logger.info(f"Docx sent: user={user.id} case={case_id[:8]} email={email}")
    await log_activity(db, user.id, "email_docx_sent", details=f"На {email}", case_id=case_id)
    return {"status": "sent", "email": email}
