"""
Unisender integration — email collection + sending docx via email.

API: https://www.unisender.com/ru/support/api/
"""

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger("app.services.unisender")

BASE_URL = "https://api.unisender.com/ru/api"


async def subscribe_email(email: str, name: str | None = None, tags: str | None = None) -> bool:
    """
    Add email to Unisender list.
    Returns True on success.
    """
    s = get_settings()
    if not s.unisender_api_key:
        logger.warning("[UNISENDER] No API key, skipping subscribe")
        return False

    fields = {"email": email}
    if name:
        fields["Name"] = name

    params = {
        "format": "json",
        "api_key": s.unisender_api_key,
        "list_ids": str(s.unisender_list_id),
        "fields[email]": email,
        "double_optin": "0",  # no confirmation email
        "overwrite": "2",  # update existing + skip confirmation
    }
    if name:
        params["fields[Name]"] = name
    if tags:
        params["tags"] = tags

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BASE_URL}/subscribe", data=params)
            data = resp.json()
            if "result" in data:
                logger.info(f"[UNISENDER] Subscribed: {email}")
                return True
            else:
                logger.error(f"[UNISENDER] Subscribe error: {data}")
                return False
    except Exception as e:
        logger.error(f"[UNISENDER] Subscribe failed: {e}")
        return False


async def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    sender_name: str = "ИИ Помощник Судьи",
    sender_email: str = "terekhov111@yandex.ru",
    attachments: dict | None = None,
) -> bool:
    """
    Send transactional email via Unisender.
    attachments: {"filename.docx": base64_content}
    """
    s = get_settings()
    if not s.unisender_api_key:
        logger.warning("[UNISENDER] No API key, skipping send")
        return False

    params = {
        "format": "json",
        "api_key": s.unisender_api_key,
        "email": to_email,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "subject": subject,
        "body": body_html,
        "list_id": str(s.unisender_list_id),
    }

    if attachments:
        for filename, content_b64 in attachments.items():
            params[f"attachments[{filename}]"] = content_b64

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{BASE_URL}/sendEmail", data=params)
            data = resp.json()
            if "result" in data:
                logger.info(f"[UNISENDER] Email sent to {to_email}: {subject}")
                return True
            else:
                logger.error(f"[UNISENDER] Send error: {data}")
                return False
    except Exception as e:
        logger.error(f"[UNISENDER] Send failed: {e}")
        return False
