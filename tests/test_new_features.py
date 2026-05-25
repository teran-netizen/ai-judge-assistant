"""
Тесты для новых фич v3.11:
- Экспорт .docx (сервис + эндпоинт)
- Токеновый биллинг (пакеты, баланс, approx_simple_cases)
- Регистрационный бонус
- Админ-панель: награда за фидбек в токенах

Запуск:
    pytest tests/test_new_features.py -v
"""

import uuid
import io
import pytest
import pytest_asyncio
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Case, Transaction, Feedback
from app.config import get_settings

from conftest import auth_headers


# ══════════════════════════════════════════════════════
# Tests: docx_export service (unit)
# ══════════════════════════════════════════════════════

class TestDocxExportService:
    """Юнит-тесты сервиса docx_export.py (без БД)."""

    def test_build_docx_basic(self):
        from app.services.docx_export import build_docx
        buf = build_docx("Тестовое дело", "Первый абзац\nВторой абзац\nТретий")
        assert isinstance(buf, io.BytesIO)
        data = buf.read()
        assert len(data) > 100  # не пустой файл
        # Проверяем magic bytes .docx (это ZIP)
        assert data[:2] == b'PK'

    def test_build_docx_empty_text(self):
        from app.services.docx_export import build_docx
        buf = build_docx("Пустое", "")
        data = buf.read()
        assert data[:2] == b'PK'

    def test_build_docx_multiline(self):
        from app.services.docx_export import build_docx
        text = "\n".join(f"Абзац {i}" for i in range(100))
        buf = build_docx("100 абзацев", text)
        data = buf.read()
        assert len(data) > 500

    def test_build_docx_special_chars(self):
        from app.services.docx_export import build_docx
        buf = build_docx("Дело №123/2024", 'Ст. 228 УК РФ — "особые" <обстоятельства> & условия')
        data = buf.read()
        assert data[:2] == b'PK'

    def test_safe_filename_basic(self):
        from app.services.docx_export import safe_filename
        result = safe_filename("Тестовое дело", "550e8400-e29b-41d4-a716-446655440000")
        assert result.endswith(".docx")
        assert "550e8400" in result

    def test_safe_filename_special_chars(self):
        from app.services.docx_export import safe_filename
        result = safe_filename("Дело №123/2024 (Иванов)", "abcdef12-3456-7890-abcd-ef1234567890")
        assert "/" not in result
        assert "№" not in result
        assert result.endswith(".docx")

    def test_safe_filename_empty_title(self):
        from app.services.docx_export import safe_filename
        result = safe_filename("!!!", "abcdef12-0000-0000-0000-000000000000")
        assert "решение" in result

    def test_safe_filename_long_title(self):
        from app.services.docx_export import safe_filename
        long_title = "А" * 200
        result = safe_filename(long_title, "abcdef12-0000-0000-0000-000000000000")
        # Имя файла не должно быть слишком длинным
        assert len(result) < 100


# ══════════════════════════════════════════════════════
# Tests: export_docx endpoint (integration)
# ══════════════════════════════════════════════════════

class TestExportDocxEndpoint:
    """Интеграционные тесты эндпоинта /api/cases/{id}/export/docx."""

    @pytest.mark.asyncio
    async def test_export_success(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Успешный экспорт — case с final_text."""
        case = Case(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Дело Иванова",
            status="completed",
            generated_text="Сгенерированный текст",
            final_text="Итоговый текст решения\nВторой абзац",
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.get(f"/api/cases/{case.id}/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 200
        assert "application/vnd.openxmlformats" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")
        # Проверяем что это валидный ZIP (docx)
        assert resp.content[:2] == b'PK'

    @pytest.mark.asyncio
    async def test_export_uses_generated_text_as_fallback(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Если final_text пуст, берётся generated_text."""
        case = Case(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Дело без финала",
            status="completed",
            generated_text="Только сгенерированный текст",
            final_text=None,
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.get(f"/api/cases/{case.id}/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 200
        assert resp.content[:2] == b'PK'

    @pytest.mark.asyncio
    async def test_export_no_text(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Пустой текст — 400."""
        case = Case(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Пустое дело",
            status="draft",
            generated_text=None,
            final_text=None,
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.get(f"/api/cases/{case.id}/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_export_whitespace_only_text(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Текст из одних пробелов — тоже 400."""
        case = Case(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Пробелы",
            status="completed",
            generated_text="   \n  \n  ",
            final_text=None,
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.get(f"/api/cases/{case.id}/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_export_not_found(self, client: AsyncClient, test_user: User):
        """Несуществующее дело — 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/cases/{fake_id}/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_export_unauthorized(self, client: AsyncClient):
        """Без токена — 401."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/cases/{fake_id}/export/docx")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_invalid_uuid(self, client: AsyncClient, test_user: User):
        """Кривой UUID — 400."""
        resp = await client.get("/api/cases/not-a-uuid/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_export_other_users_case(self, client: AsyncClient, test_user: User, admin_user: User, db_session: AsyncSession):
        """Чужое дело — 404 (не раскрываем существование)."""
        case = Case(
            id=uuid.uuid4(),
            user_id=admin_user.id,  # принадлежит другому юзеру
            title="Чужое дело",
            status="completed",
            final_text="Секретный текст",
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.get(f"/api/cases/{case.id}/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_export_filename_header(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Имя файла в Content-Disposition содержит ID дела."""
        case = Case(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Решение по делу",
            status="completed",
            final_text="Текст решения",
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.get(f"/api/cases/{case.id}/export/docx", headers=auth_headers(test_user))
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert str(case.id)[:8] in cd
        assert ".docx" in cd


# ══════════════════════════════════════════════════════
# Tests: Billing — token packages and approx_simple_cases
# ══════════════════════════════════════════════════════

class TestBillingTokenPackages:
    """Тесты токенового биллинга."""

    @pytest.mark.asyncio
    async def test_packages_have_approx_cases(self, client: AsyncClient):
        """Пакеты должны возвращать approx_simple_cases."""
        resp = await client.get("/api/billing/packages")
        assert resp.status_code == 200
        packages = resp.json()
        assert len(packages) >= 4  # 4 пакета
        for p in packages:
            assert "approx_simple_cases" in p
            assert p["approx_simple_cases"] > 0
            assert p["tokens"] > 0
            assert p["price_kopecks"] > 0
            assert p["price_rub"] == p["price_kopecks"] / 100

    @pytest.mark.asyncio
    async def test_packages_approx_cases_calculation(self, client: AsyncClient):
        """approx_simple_cases = tokens // tokens_per_simple_case."""
        s = get_settings()
        tpc = s.tokens_per_simple_case or 30_000
        resp = await client.get("/api/billing/packages")
        packages = resp.json()
        for p in packages:
            expected = p["tokens"] // tpc
            assert p["approx_simple_cases"] == expected

    @pytest.mark.asyncio
    async def test_balance_has_approx_cases(self, client: AsyncClient, test_user: User):
        """Баланс должен возвращать approx_simple_cases."""
        resp = await client.get("/api/billing/balance", headers=auth_headers(test_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "approx_simple_cases" in data
        s = get_settings()
        tpc = s.tokens_per_simple_case or 30_000
        assert data["approx_simple_cases"] == test_user.token_balance // tpc

    @pytest.mark.asyncio
    async def test_balance_zero_tokens(self, client: AsyncClient, db_session: AsyncSession):
        """Пользователь с 0 токенов — approx_simple_cases = 0."""
        user = User(
            id=uuid.uuid4(),
            yandex_id="zero_balance_user",
            email="zero@test.com",
            name="Zero Balance",
            token_balance=0,
            free_cases_left=0,
        )
        db_session.add(user)
        await db_session.commit()

        resp = await client.get("/api/billing/balance", headers=auth_headers(user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_balance"] == 0
        assert data["approx_simple_cases"] == 0

    @pytest.mark.asyncio
    async def test_purchase_valid_package(self, client: AsyncClient, test_user: User):
        """Покупка валидного пакета (с моком SBP)."""
        s = get_settings()
        first_package_tokens = list(s.token_packages.keys())[0]

        with patch("app.api.billing.create_sbp_payment") as mock_pay:
            mock_pay.return_value = {
                "order_id": "test-order-pkg",
                "type": "sbp_qr",
                "payment_url": "https://pay.test",
                "qr_payload": "https://qr.nspk.ru/test",
                "qr_image": "data:image/png;base64,abc",
            }
            resp = await client.post(
                "/api/billing/purchase",
                json={"tokens": first_package_tokens},
                headers=auth_headers(test_user),
            )
            assert resp.status_code == 200
            assert resp.json()["order_id"] == "test-order-pkg"

    @pytest.mark.asyncio
    async def test_purchase_invalid_package_tokens(self, client: AsyncClient, test_user: User):
        """Покупка несуществующего пакета — 400."""
        resp = await client.post(
            "/api/billing/purchase",
            json={"tokens": 12345},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════
# Tests: Auth — registration bonus
# ══════════════════════════════════════════════════════

class TestAuthRegistrationBonus:
    """Тесты бонуса при регистрации."""

    @pytest.mark.asyncio
    async def test_new_user_gets_registration_tokens(self, db_session: AsyncSession):
        """Новый пользователь получает registration_bonus_tokens."""
        from app.api.auth import _get_or_create
        s = get_settings()

        user, is_new = await _get_or_create(
            db_session, "yandex", "brand_new_pid_001", "new@test.com", "Новый Юзер", None,
        )
        assert is_new is True
        assert user.token_balance == s.registration_bonus_tokens

    @pytest.mark.asyncio
    async def test_existing_user_no_bonus(self, db_session: AsyncSession, test_user: User):
        """Существующий пользователь не получает бонус повторно."""
        from app.api.auth import _get_or_create

        original_balance = test_user.token_balance
        user, is_new = await _get_or_create(
            db_session, "yandex", test_user.yandex_id, test_user.email, test_user.name, None,
        )
        assert is_new is False
        assert user.token_balance == original_balance



# ══════════════════════════════════════════════════════
# Tests: Admin — feedback token rewards
# ══════════════════════════════════════════════════════

class TestAdminFeedbackRewards:
    """Тесты начисления награды за фидбек в токенах."""

    @pytest_asyncio.fixture
    async def feedback(self, db_session: AsyncSession, test_user: User) -> Feedback:
        fb = Feedback(
            id=uuid.uuid4(),
            user_id=test_user.id,
            category="suggestion",
            text="Добавьте экспорт в PDF",
            status="new",
        )
        db_session.add(fb)
        await db_session.commit()
        return fb

    @pytest.mark.asyncio
    async def test_reward_tokens(self, client: AsyncClient, admin_user: User, test_user: User, feedback: Feedback, db_session: AsyncSession):
        """Админ награждает юзера токенами за фидбек."""
        initial_balance = test_user.token_balance

        resp = await client.put(
            f"/api/admin/feedbacks/{feedback.id}",
            json={"status": "accepted", "response_text": "Спасибо!", "reward": 0, "reward_tokens": 100_000},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 200

        # Проверяем что баланс увеличился
        await db_session.refresh(test_user)
        assert test_user.token_balance == initial_balance + 100_000

        # Проверяем что фидбек стал rewarded
        await db_session.refresh(feedback)
        assert feedback.status == "rewarded"

    @pytest.mark.asyncio
    async def test_reward_creates_transaction(self, client: AsyncClient, admin_user: User, test_user: User, feedback: Feedback, db_session: AsyncSession):
        """Награда создаёт транзакцию."""
        from sqlalchemy import select

        resp = await client.put(
            f"/api/admin/feedbacks/{feedback.id}",
            json={"status": "accepted", "response_text": "Отличная идея!", "reward": 0, "reward_tokens": 150_000},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 200

        # Находим транзакцию
        txs = (await db_session.execute(
            select(Transaction).where(
                Transaction.user_id == test_user.id,
                Transaction.type == "rating_bonus",
            )
        )).scalars().all()
        assert len(txs) == 1
        assert txs[0].amount_tokens == 150_000

    @pytest.mark.asyncio
    async def test_no_double_reward(self, client: AsyncClient, admin_user: User, test_user: User, db_session: AsyncSession):
        """Повторная награда заблокирована."""
        fb = Feedback(
            id=uuid.uuid4(),
            user_id=test_user.id,
            category="bug",
            text="Баг при экспорте",
            status="rewarded",
            reward_kopecks=100,  # уже награждён
        )
        db_session.add(fb)
        await db_session.commit()

        resp = await client.put(
            f"/api/admin/feedbacks/{fb.id}",
            json={"status": "accepted", "reward": 100, "reward_tokens": 0},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_reject_feedback_no_reward(self, client: AsyncClient, admin_user: User, feedback: Feedback, test_user: User, db_session: AsyncSession):
        """Отклонение фидбека без награды — баланс не меняется."""
        initial_balance = test_user.token_balance

        resp = await client.put(
            f"/api/admin/feedbacks/{feedback.id}",
            json={"status": "rejected", "response_text": "Не актуально", "reward": 0, "reward_tokens": 0},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 200

        await db_session.refresh(test_user)
        assert test_user.token_balance == initial_balance

    @pytest.mark.asyncio
    async def test_feedback_not_found(self, client: AsyncClient, admin_user: User):
        """Несуществующий фидбек — 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.put(
            f"/api/admin/feedbacks/{fake_id}",
            json={"status": "accepted", "reward": 0, "reward_tokens": 50_000},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_feedback_reward_forbidden_for_non_admin(self, client: AsyncClient, test_user: User, feedback: Feedback):
        """Обычный юзер не может обрабатывать фидбек — 403."""
        resp = await client.put(
            f"/api/admin/feedbacks/{feedback.id}",
            json={"status": "accepted", "reward": 0, "reward_tokens": 50_000},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 403
