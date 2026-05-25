"""
Smoke tests — 7 критических тестов основного flow.
Если хотя бы один из них падает, деплоить НЕЛЬЗЯ.

Запуск: pytest tests/test_smoke.py -v
"""
import pytest
import uuid

from tests.conftest import auth_headers


# ═══════════════════════════════════════════════════════════════
# 1. Health check — БД доступна
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_health(client):
    """GET /health — должен вернуть 200 и db=ok."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"


# ═══════════════════════════════════════════════════════════════
# 2. Auth — без токена 401, с токеном 200
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_auth_unauthorized(client):
    """GET /api/auth/me без токена — 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_me(client, test_user):
    """GET /api/auth/me с валидным JWT — 200 + данные юзера."""
    resp = await client.get("/api/auth/me", headers=auth_headers(test_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"


# ═══════════════════════════════════════════════════════════════
# 3. Billing — пакеты токенов доступны
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_billing_packages(client):
    """GET /api/billing/packages — возвращает список пакетов."""
    resp = await client.get("/api/billing/packages")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Каждый пакет содержит tokens и price_rub
    for pkg in data:
        assert "tokens" in pkg
        assert "price_rub" in pkg
        assert pkg["tokens"] > 0
        assert pkg["price_rub"] > 0


# ═══════════════════════════════════════════════════════════════
# 4. Создание дела
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_case(client, test_user):
    """POST /api/cases/ — создаёт дело и возвращает его."""
    resp = await client.post(
        "/api/cases/",
        json={"title": "Тестовое дело", "user_instructions": ""},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["title"] == "Тестовое дело"
    assert data["status"] == "draft"


# ═══════════════════════════════════════════════════════════════
# 5. Список дел — возвращает созданное дело
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_cases(client, test_user):
    """GET /api/cases/ — возвращает список дел текущего юзера."""
    # Сначала создаём дело
    await client.post(
        "/api/cases/",
        json={"title": "Для списка"},
        headers=auth_headers(test_user),
    )
    resp = await client.get("/api/cases/", headers=auth_headers(test_user))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


# ═══════════════════════════════════════════════════════════════
# 6. Получение дела по ID
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_case_by_id(client, test_user):
    """GET /api/cases/{id} — возвращает дело с файлами и chat_history."""
    create_resp = await client.post(
        "/api/cases/",
        json={"title": "По ID"},
        headers=auth_headers(test_user),
    )
    case_id = create_resp.json()["id"]

    resp = await client.get(f"/api/cases/{case_id}", headers=auth_headers(test_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == case_id
    assert "files" in data
    assert "chat_history" in data or data.get("chat_history") is None


# ═══════════════════════════════════════════════════════════════
# 7. Экспорт в DOCX — возвращает файл
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_docx(client, test_user, db_session):
    """GET /api/cases/{id}/export/docx — возвращает .docx файл."""
    from app.models import Case

    # Создаём дело с final_text напрямую в БД
    case = Case(
        id=uuid.uuid4(),
        user_id=test_user.id,
        title="Для экспорта",
        status="completed",
        final_text="ПРОЕКТ РЕШЕНИЯ\n\nИменем Российской Федерации\n\nТест экспорта.",
    )
    db_session.add(case)
    await db_session.commit()

    resp = await client.get(
        f"/api/cases/{case.id}/export/docx",
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats" in resp.headers.get("content-type", "")
    # Файл должен быть непустой
    assert len(resp.content) > 100
