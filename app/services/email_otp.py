"""Email OTP service — send one-time codes via SMTP (Yandex) with Resend fallback."""
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
s = get_settings()

OTP_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 40px 20px;">
<div style="max-width: 420px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
  <div style="text-align: center; margin-bottom: 24px;">
    <span style="background: #1a55f5; color: #fff; padding: 4px 12px; border-radius: 8px; font-weight: 700; font-size: 16px;">AI</span>
    <span style="font-weight: 700; font-size: 18px; margin-left: 6px;">Помощник Судьи</span>
  </div>
  <h2 style="text-align: center; color: #1a1a2e; margin: 0 0 8px;">Код для входа</h2>
  <p style="text-align: center; color: #666; font-size: 15px; margin: 0 0 24px;">Введите этот код на сайте для входа в систему</p>
  <div style="background: #f0f4ff; border: 2px solid #1a55f5; border-radius: 12px; padding: 20px; text-align: center; margin-bottom: 24px;">
    <span style="font-size: 36px; font-weight: 700; letter-spacing: 8px; color: #1a55f5;">{code}</span>
  </div>
  <p style="text-align: center; color: #999; font-size: 13px; margin: 0;">Код действителен 10 минут.<br>Если вы не запрашивали код — проигнорируйте это письмо.</p>
</div>
</body>
</html>
"""


async def send_otp_email(email: str, code: str) -> bool:
    """Send OTP code via SMTP. Falls back to Resend API on failure."""
    html = OTP_EMAIL_TEMPLATE.replace("{code}", code)
    subject = f"Код для входа: {code} — Помощник Судьи"

    # Try SMTP first
    if s.smtp_host and s.smtp_user and s.smtp_password:
        try:
            ok = await _send_smtp(email, subject, html)
            if ok:
                return True
            logger.warning("[OTP] SMTP failed for %s, trying Resend", email)
        except Exception as e:
            logger.warning("[OTP] SMTP error: %s, trying Resend", e)

    # Fallback: Resend API
    if s.resend_api_key:
        try:
            return await _send_resend(email, subject, html)
        except Exception as e:
            logger.error("[OTP] Resend also failed: %s", e)

    logger.error("[OTP] All email methods failed for %s", email)
    return False


def _apply_common_headers(msg, to_email: str, subject: str) -> None:
    """Минимальные безопасные headers — не триггерят Yandex outbound spam filter.

    НЕ добавляем display name — Yandex outbound-фильтр отклоняет письма если
    отображаемое имя не совпадает с доменом авторизованного пользователя.
    """
    from email.utils import make_msgid, formatdate
    from email.header import Header
    msg["From"] = s.smtp_user  # plain email — как было до C-патча
    msg["To"] = to_email
    msg["Subject"] = str(Header(subject, "utf-8"))
    msg["Reply-To"] = s.smtp_user  # совпадает с From — безопасно
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=s.smtp_user.split("@", 1)[-1] or "localhost")
    msg["MIME-Version"] = "1.0"


async def _send_smtp(to_email: str, subject: str, html: str) -> bool:
    """Send email via SMTP SSL."""
    import asyncio

    def _blocking_send():
        msg = MIMEMultipart("alternative")
        _apply_common_headers(msg, to_email, subject)
        msg.attach(MIMEText(html, "html", "utf-8"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=15) as server:
            server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
        return True

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _blocking_send)


async def _send_resend(to_email: str, subject: str, html: str) -> bool:
    """Send email via Resend API (fallback)."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
            json={
                "from": "Помощник Судьи <onboarding@resend.dev>",
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
        )
        if r.status_code in (200, 201):
            logger.info("[OTP] Resend OK for %s: %s", to_email, r.json().get("id"))
            return True
        logger.warning("[OTP] Resend error %d: %s", r.status_code, r.text[:200])
        return False


async def _send_smtp_with_attachment(to_email: str, subject: str, html: str, attachment_name: str, attachment_bytes: bytes) -> bool:
    """Send email with attachment via SMTP SSL (Yandex)."""
    import asyncio
    from email.mime.base import MIMEBase
    from email import encoders

    def _blocking_send():
        msg = MIMEMultipart("mixed")
        _apply_common_headers(msg, to_email, subject)

        # HTML body
        msg.attach(MIMEText(html, "html", "utf-8"))

        # Attachment
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        from email.utils import encode_rfc2231
        encoded_name = encode_rfc2231(attachment_name, "utf-8")
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", attachment_name))
        msg.attach(part)

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=30) as server:
            server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
        return True

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _blocking_send)
    except Exception as e:
        logger.error("[EMAIL] SMTP attachment send failed: %s", e)
        return False
