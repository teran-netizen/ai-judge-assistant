"""
Интеграционные тесты для платёжного flow и ключевых API.

Запуск:
    pytest tests/ -v

Требуется: pip install pytest pytest-asyncio httpx

Тесты используют TestClient (sync) и тестовую БД.
"""

import uuid
import hmac
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Transaction, InviteCode

from conftest import auth_headers


# ── Tests: Auth ──

class TestAuth:
    @pytest.mark.asyncio
    async def test_get_me(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/auth/me", headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert data["token_balance"] == 1_000_000

    @pytest.mark.asyncio
    async def test_get_me_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_invalid_token(self, client: AsyncClient):
        resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401



# ── Tests: Billing ──

class TestBilling:
    @pytest.mark.asyncio
    async def test_get_packages(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/billing/packages")
        assert resp.status_code == 200
        packages = resp.json()
        assert len(packages) > 0
        assert all("tokens" in p and "price_kopecks" in p for p in packages)

    @pytest.mark.asyncio
    async def test_get_balance(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/billing/balance", headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_balance"] == 1_000_000
        assert data["free_cases_left"] == 5

    @pytest.mark.asyncio
    async def test_purchase_invalid_package(self, client: AsyncClient, test_user: User):
        resp = await client.post("/api/billing/purchase", json={"tokens": 999}, headers=auth_headers(test_user))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("app.api.billing.create_sbp_payment")
    async def test_purchase_success(self, mock_payment, client: AsyncClient, test_user: User):
        mock_payment.return_value = {
            "order_id": "test-order-123",
            "order_number": "abc123",
            "type": "sbp_qr",
            "payment_url": "https://pay.test/form",
            "qr_payload": "https://qr.nspk.ru/test",
            "qr_image": "data:image/png;base64,iVBOR...",
        }
        resp = await client.post("/api/billing/purchase", json={"tokens": 500_000}, headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == "test-order-123"
        assert data["payment_type"] == "sbp_qr"

    @pytest.mark.asyncio
    async def test_payment_status_invalid_order(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/billing/payment-status/invalid!!!", headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["paid"] is False

    @pytest.mark.asyncio
    async def test_webhook_untrusted_ip(self, client: AsyncClient):
        """Webhook от неизвестного IP должен вернуть 403."""
        resp = await client.post(
            "/api/billing/webhook/alfa",
            json={"mdOrder": "test", "status": "1"},
            headers={"X-Real-IP": "1.2.3.4"},  # не Альфа
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_webhook_duplicate_order(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Повторный webhook с тем же order_id не должен дублировать начисление."""
        # Создаём существующую транзакцию
        tx = Transaction(
            user_id=test_user.id,
            type="purchase",
            amount_tokens=500_000,
            amount_kopecks=49_000,
            external_payment_id="dup-order-123",
        )
        db_session.add(tx)
        await db_session.commit()

        # Формируем подпись
        params = {"mdOrder": "dup-order-123", "orderNumber": "abc", "status": "1", "amount": "49000"}
        sign_string = ";".join(f"{k};{v}" for k, v in sorted(params.items())) + ";"
        checksum = hmac.new(b"test-callback-secret", sign_string.encode(), hashlib.sha256).hexdigest()
        params["checksum"] = checksum

        with patch("app.api.billing.check_order_status") as mock_status:
            mock_status.return_value = {
                "paid": True, "status": "paid",
                "user_id": str(test_user.id), "tokens": 500_000, "amount_kopecks": 49_000,
            }
            resp = await client.post(
                "/api/billing/webhook/alfa",
                json=params,
                headers={"X-Real-IP": "193.200.10.1"},
            )
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}


# ── Tests: Invite Codes ──

class TestInvites:
    @pytest.mark.asyncio
    async def test_activate_nonexistent(self, client: AsyncClient, test_user: User):
        resp = await client.post(
            "/api/invites/activate",
            json={"code": "XXXX-XXXX"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_activate_success(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        invite = InviteCode(
            code="TEST-1234",
            bonus_tokens=100_000,
            bonus_free_cases=3,
            max_activations=5,
            created_by=test_user.id,
        )
        db_session.add(invite)
        await db_session.commit()

        initial_balance = test_user.token_balance
        resp = await client.post(
            "/api/invites/activate",
            json={"code": "TEST-1234"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bonus_tokens"] == 100_000
        assert data["bonus_free_cases"] == 3

    @pytest.mark.asyncio
    async def test_activate_double(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Двойная активация должна быть заблокирована."""
        invite = InviteCode(
            code="DUPE-CODE",
            bonus_tokens=50_000,
            max_activations=10,
            created_by=test_user.id,
        )
        db_session.add(invite)
        await db_session.commit()

        # Первая активация
        resp1 = await client.post(
            "/api/invites/activate",
            json={"code": "DUPE-CODE"},
            headers=auth_headers(test_user),
        )
        assert resp1.status_code == 200

        # Вторая — должна быть 409
        resp2 = await client.post(
            "/api/invites/activate",
            json={"code": "DUPE-CODE"},
            headers=auth_headers(test_user),
        )
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_activate_expired(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        invite = InviteCode(
            code="EXP-CODE1",
            bonus_tokens=10_000,
            max_activations=1,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            created_by=test_user.id,
        )
        db_session.add(invite)
        await db_session.commit()

        resp = await client.post(
            "/api/invites/activate",
            json={"code": "EXP-CODE1"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 410


# ── Tests: Cases ──

class TestCases:
    @pytest.mark.asyncio
    async def test_create_case(self, client: AsyncClient, test_user: User):
        resp = await client.post("/api/cases/", json={"title": "Тест"}, headers=auth_headers(test_user))
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft"

    @pytest.mark.asyncio
    async def test_create_case_title_too_long(self, client: AsyncClient, test_user: User):
        resp = await client.post("/api/cases/", json={"title": "A" * 501}, headers=auth_headers(test_user))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_cases_empty(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/cases/", headers=auth_headers(test_user))
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_cases_pagination(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/cases/?offset=0&limit=10", headers=auth_headers(test_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_nonexistent_case(self, client: AsyncClient, test_user: User):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/cases/{fake_id}", headers=auth_headers(test_user))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_uuid(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/cases/not-a-uuid", headers=auth_headers(test_user))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_case(self, client: AsyncClient, test_user: User):
        """Создать дело, удалить его, затем GET должен вернуть 404."""
        # Создаём
        resp = await client.post("/api/cases/", json={"title": "Удаляемое дело"}, headers=auth_headers(test_user))
        assert resp.status_code == 200
        case_id = resp.json()["id"]

        # Удаляем
        resp = await client.delete(f"/api/cases/{case_id}", headers=auth_headers(test_user))
        assert resp.status_code == 200

        # Проверяем что удалено
        resp = await client.get(f"/api/cases/{case_id}", headers=auth_headers(test_user))
        assert resp.status_code == 404


# ── Tests: Chat ──

class TestChat:
    @pytest.mark.asyncio
    async def test_chat_history_empty(self, client: AsyncClient, test_user: User):
        """GET /api/chat/history для нового юзера возвращает пустой список."""
        resp = await client.get("/api/chat/history", headers=auth_headers(test_user))
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_chat_limits(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/chat/limits", headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_limit" in data
        assert "remaining_free" in data

    @pytest.mark.asyncio
    async def test_chat_message_too_long(self, client: AsyncClient, test_user: User):
        resp = await client.post(
            "/api/chat/message",
            json={"message": "x" * 10001},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_clear_history(self, client: AsyncClient, test_user: User):
        resp = await client.delete("/api/chat/history", headers=auth_headers(test_user))
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── Tests: Admin ──

class TestAdmin:
    @pytest.mark.asyncio
    async def test_dashboard_forbidden(self, client: AsyncClient, test_user: User):
        resp = await client.get("/api/admin/dashboard", headers=auth_headers(test_user))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_dashboard_admin(self, client: AsyncClient, admin_user: User):
        resp = await client.get("/api/admin/dashboard", headers=auth_headers(admin_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "total_users" in data

    @pytest.mark.asyncio
    async def test_payouts_invalid_status(self, client: AsyncClient, admin_user: User):
        resp = await client.get("/api/admin/payouts?status=hacked", headers=auth_headers(admin_user))
        assert resp.status_code == 422


# ── Tests: Feedback ──

class TestFeedback:
    @pytest.mark.asyncio
    @patch("app.api.feedback.check_rate_limit", new_callable=AsyncMock, return_value=(True, 4))
    @patch("app.api.feedback.notify_feedback", new_callable=AsyncMock)
    async def test_create_feedback(self, mock_notify, mock_rl, client: AsyncClient, test_user: User):
        resp = await client.post(
            "/api/feedback/",
            json={"category": "bug", "text": "Кнопка не работает, пожалуйста исправьте"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "bug"
        assert data["status"] == "new"

    @pytest.mark.asyncio
    @patch("app.api.feedback.check_rate_limit", new_callable=AsyncMock, return_value=(True, 4))
    @patch("app.api.feedback.notify_feedback", new_callable=AsyncMock)
    async def test_get_feedbacks(self, mock_notify, mock_rl, client: AsyncClient, test_user: User):
        """Создать фидбек, затем GET /api/feedback/ должен вернуть его в списке."""
        # Сначала создаём фидбек
        await client.post(
            "/api/feedback/",
            json={"category": "suggestion", "text": "Test feedback text here"},
            headers=auth_headers(test_user),
        )
        # Получаем список
        resp = await client.get("/api/feedback/", headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_feedback_invalid_category(self, client: AsyncClient, test_user: User):
        resp = await client.post(
            "/api/feedback/",
            json={"category": "invalid", "text": "Hello world test message"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 422


# ── Tests: Rating ──

class TestRating:
    @pytest.mark.asyncio
    async def test_get_rating(self, client: AsyncClient, test_user: User):
        """GET /api/rating/ возвращает 200 с полем top."""
        resp = await client.get("/api/rating/", headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "top" in data


# ── Tests: Nickname ──

class TestNickname:
    @pytest.mark.asyncio
    async def test_set_nickname(self, client: AsyncClient, test_user: User):
        """PUT /api/auth/nickname с валидным ником — 200."""
        resp = await client.put(
            "/api/auth/nickname",
            json={"nickname": "TestUser42"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_set_nickname_too_short(self, client: AsyncClient, test_user: User):
        """PUT /api/auth/nickname с ником из 1 символа — 422 (min_length=2)."""
        resp = await client.put(
            "/api/auth/nickname",
            json={"nickname": "a"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_set_nickname_invalid_chars(self, client: AsyncClient, test_user: User):
        """PUT /api/auth/nickname с запрещёнными символами — 422."""
        resp = await client.put(
            "/api/auth/nickname",
            json={"nickname": "hack@er"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 422
