import html as html_lib
import httpx
from app.config import get_settings

settings = get_settings()


def _esc(text: str) -> str:
    """Экранирует HTML-спецсимволы для безопасной отправки в Telegram (parse_mode=HTML)."""
    return html_lib.escape(str(text)) if text else ""


async def send_admin(text: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": settings.telegram_admin_chat_id, "text": text, "parse_mode": "HTML"},
            )
            return r.status_code == 200
    except Exception:
        return False


async def notify_withdrawal(nickname: str, amount_rub: float, phone: str):
    await send_admin(f"💰 <b>Заявка на выплату</b>\n{_esc(nickname)}: {amount_rub:.0f}₽\nТел: {_esc(phone)}")


async def notify_feedback(nickname: str, category: str, preview: str):
    await send_admin(f"📝 <b>Feedback</b>\n{_esc(nickname)} [{_esc(category)}]\n{_esc(preview[:200])}")
