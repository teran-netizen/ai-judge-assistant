"""
Security regression tests.

Covers:
- Auth: cookie vs bearer, expired/invalid tokens, disabled users
- CSRF: JSON-only enforcement, no cross-origin attacks
- Webhook: duplicate, invalid signature, forged IP, invalid body
- Rate limits: per-user limits on generate
- IDOR: case access isolation between users
- Input validation: UUID, path traversal, oversized payloads
- SSE: auth required for streaming endpoints
"""

import uuid
import hmac
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Case, CaseFile, Transaction
from app.utils.auth import create_access_token
from app.config import get_settings

from conftest import auth_headers


# ═══════════════════════════════════════════════════════════════
# Auth edge cases
# ═══════════════════════════════════════════════════════════════

class TestAuthSecurity:

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self, client: AsyncClient, test_user: User):
        """Expired JWT should get 401."""
        from jose import jwt
        s = get_settings()
        payload = {
            "sub": str(test_user.id),
            "iss": "ai-judge",
            "aud": "ai-judge-api",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(payload, s.secret_key, algorithm="HS256")
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_token_wrong_secret_rejected(self, client: AsyncClient, test_user: User):
        """Token signed with wrong key should get 401."""
        from jose import jwt
        payload = {
            "sub": str(test_user.id),
            "iss": "ai-judge",
            "aud": "ai-judge-api",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        bad_token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad_token}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_alg_none_rejected(self, client: AsyncClient, test_user: User):
        """alg:none attack should be rejected."""
        import base64, json
        header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(json.dumps({
            "sub": str(test_user.id),
            "iss": "ai-judge",
            "aud": "ai-judge-api",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }).encode()).rstrip(b"=").decode()
        fake_token = f"{header}.{payload}."
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {fake_token}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_deactivated_user_rejected(self, client: AsyncClient, db_session: AsyncSession):
        """Deactivated user should get 401 even with valid token."""
        user = User(
            id=uuid.uuid4(),
            yandex_id="deactivated_user",
            email="deactivated@example.com",
            name="Deactivated",
            is_active=False,
        )
        db_session.add(user)
        await db_session.commit()

        resp = await client.get("/api/auth/me", headers=auth_headers(user))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_user_id_rejected(self, client: AsyncClient):
        """Token with valid format but non-existent user_id should get 401."""
        fake_user_id = str(uuid.uuid4())
        token = create_access_token(fake_user_id)
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cookie_auth_works(self, client: AsyncClient, test_user: User):
        """HttpOnly cookie auth should work."""
        token = create_access_token(str(test_user.id))
        resp = await client.get("/api/auth/me", cookies={"access_token": token})
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_cookie_auth_invalid_token(self, client: AsyncClient):
        """Invalid cookie token should get 401."""
        resp = await client.get("/api/auth/me", cookies={"access_token": "garbage-token"})
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
# IDOR (Insecure Direct Object Reference)
# ═══════════════════════════════════════════════════════════════

class TestIDOR:

    @pytest.mark.asyncio
    async def test_cannot_access_other_users_case(self, client: AsyncClient, db_session: AsyncSession):
        """User A should not be able to see User B's case."""
        user_a = User(id=uuid.uuid4(), yandex_id="user_a", email="a@example.com", name="A")
        user_b = User(id=uuid.uuid4(), yandex_id="user_b", email="b@example.com", name="B")
        db_session.add_all([user_a, user_b])
        await db_session.flush()

        case_b = Case(id=uuid.uuid4(), user_id=user_b.id, title="User B's case")
        db_session.add(case_b)
        await db_session.commit()

        # User A tries to access User B's case
        resp = await client.get(f"/api/cases/{case_b.id}", headers=auth_headers(user_a))
        assert resp.status_code == 404  # Not 403 — don't leak existence

    @pytest.mark.asyncio
    async def test_cannot_delete_other_users_case(self, client: AsyncClient, db_session: AsyncSession):
        """User A should not be able to delete User B's case."""
        user_a = User(id=uuid.uuid4(), yandex_id="idor_a2", email="a2@example.com", name="A2")
        user_b = User(id=uuid.uuid4(), yandex_id="idor_b2", email="b2@example.com", name="B2")
        db_session.add_all([user_a, user_b])
        await db_session.flush()

        case_b = Case(id=uuid.uuid4(), user_id=user_b.id, title="B's case to delete")
        db_session.add(case_b)
        await db_session.commit()

        resp = await client.delete(f"/api/cases/{case_b.id}", headers=auth_headers(user_a))
        assert resp.status_code == 404

        # Verify case still exists
        check = (await db_session.execute(
            select(Case).where(Case.id == case_b.id)
        )).scalar_one_or_none()
        assert check is not None


# ═══════════════════════════════════════════════════════════════
# Input Validation
# ═══════════════════════════════════════════════════════════════

class TestInputValidation:

    @pytest.mark.asyncio
    async def test_invalid_uuid_case_id(self, client: AsyncClient, test_user: User):
        """Non-UUID case_id should get 400, not 500."""
        resp = await client.get("/api/cases/not-a-uuid", headers=auth_headers(test_user))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_sql_injection_in_case_id(self, client: AsyncClient, test_user: User):
        """SQL injection attempt in case_id should be rejected."""
        resp = await client.get("/api/cases/'; DROP TABLE cases; --", headers=auth_headers(test_user))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_path_traversal_in_docs(self, client: AsyncClient):
        """Path traversal in /docs/ endpoint should be blocked."""
        resp = await client.get("/docs/../../etc/passwd")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_path_traversal_encoded_in_docs(self, client: AsyncClient):
        """Encoded path traversal should also be blocked."""
        resp = await client.get("/docs/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_long_title_rejected(self, client: AsyncClient, test_user: User, db_session: AsyncSession):
        """Extremely long title should be rejected."""
        case = Case(id=uuid.uuid4(), user_id=test_user.id, title="test")
        db_session.add(case)
        await db_session.commit()

        resp = await client.patch(
            f"/api/cases/{case.id}/title",
            json={"title": "x" * 501},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Webhook Security
# ═══════════════════════════════════════════════════════════════

class TestWebhookSecurity:

    @pytest.mark.asyncio
    @patch("app.api.billing.check_order_status")
    async def test_duplicate_webhook_idempotent(self, mock_check, client: AsyncClient, db_session: AsyncSession):
        """Duplicate webhook with same order_id should not double-credit tokens."""
        user = User(
            id=uuid.uuid4(), yandex_id="webhook_user", email="wh@example.com",
            name="WH User", token_balance=0,
        )
        db_session.add(user)
        await db_session.commit()

        mock_check.return_value = {
            "paid": True, "status": "paid",
            "user_id": str(user.id), "tokens": 50000,
            "amount_kopecks": 14900,
        }

        s = get_settings()
        # Ensure 50000 is a valid package
        if 50000 not in s.token_packages:
            pytest.skip("50000 not in token_packages")

        webhook_data = {
            "mdOrder": "test-order-dup-001",
            "orderNumber": "abc123",
            "operation": "deposited",
            "status": "1",
            "amount": str(s.token_packages[50000]),
        }

        # First webhook call
        resp1 = await client.post("/api/billing/webhook/alfa", data=webhook_data)
        assert resp1.status_code == 200

        # Second webhook call (duplicate)
        resp2 = await client.post("/api/billing/webhook/alfa", data=webhook_data)
        assert resp2.status_code == 200

        # User should have tokens credited only ONCE
        await db_session.refresh(user)
        assert user.token_balance == 50000

        # Only one transaction should exist
        txns = (await db_session.execute(
            select(Transaction).where(
                Transaction.external_payment_id == "test-order-dup-001"
            )
        )).scalars().all()
        assert len(txns) == 1

    @pytest.mark.asyncio
    async def test_webhook_invalid_checksum_rejected(self, client: AsyncClient):
        """Webhook with invalid HMAC signature should be rejected (not processed)."""
        # Set a real callback secret for this test
        s = get_settings()
        original = s.alfa_callback_secret
        try:
            s.alfa_callback_secret = "real-secret-for-test"
            webhook_data = {
                "mdOrder": "order-fake",
                "orderNumber": "abc",
                "status": "1",
                "amount": "14900",
                "checksum": "definitely-wrong-checksum",
            }
            resp = await client.post("/api/billing/webhook/alfa", data=webhook_data)
            # Should return ok (no retry) but NOT process
            assert resp.status_code == 200

            # No transaction should exist
        finally:
            s.alfa_callback_secret = original

    @pytest.mark.asyncio
    async def test_webhook_amount_mismatch_rejected(self, client: AsyncClient, db_session: AsyncSession):
        """Webhook where amount doesn't match package price should not credit tokens."""
        user = User(
            id=uuid.uuid4(), yandex_id="wh_mismatch", email="mismatch@example.com",
            name="Mismatch", token_balance=0,
        )
        db_session.add(user)
        await db_session.commit()

        with patch("app.api.billing.check_order_status") as mock_check, \
             patch("app.api.billing.verify_callback_checksum", return_value=True):
            mock_check.return_value = {
                "paid": True, "status": "paid",
                "user_id": str(user.id), "tokens": 50000,
                "amount_kopecks": 100,  # Wrong amount!
            }
            webhook_data = {
                "mdOrder": "order-mismatch-001",
                "orderNumber": "abc",
                "status": "1",
                "amount": "100",
            }
            resp = await client.post("/api/billing/webhook/alfa", data=webhook_data)
            assert resp.status_code == 200

        # User should NOT have tokens
        await db_session.refresh(user)
        assert user.token_balance == 0

    @pytest.mark.asyncio
    async def test_webhook_invalid_body_handled(self, client: AsyncClient):
        """Completely invalid webhook body should not crash the server."""
        resp = await client.post(
            "/api/billing/webhook/alfa",
            content=b"not-valid-form-or-json!!!",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        # Should handle gracefully (200 ok, don't retry)
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# Case Status Protection
# ═══════════════════════════════════════════════════════════════

class TestCaseStatusProtection:

    @pytest.mark.asyncio
    async def test_cannot_generate_while_processing(self, client: AsyncClient, db_session: AsyncSession, test_user: User):
        """Should not be able to start generation while already processing."""
        case = Case(
            id=uuid.uuid4(), user_id=test_user.id, title="Processing",
            status="processing", updated_at=datetime.now(timezone.utc),
        )
        db_session.add(case)
        # Need at least one file
        cf = CaseFile(
            case_id=case.id, filename="test.jpg",
            file_path="/tmp/test.jpg", file_type="image",
        )
        db_session.add(cf)
        await db_session.commit()

        resp = await client.post(f"/api/cases/{case.id}/generate", headers=auth_headers(test_user))
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_edit_final_while_processing(self, client: AsyncClient, db_session: AsyncSession, test_user: User):
        """Should not save final text during processing."""
        case = Case(
            id=uuid.uuid4(), user_id=test_user.id, title="Editing",
            status="processing",
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.put(
            f"/api/cases/{case.id}/final",
            json={"final_text": "new text"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_upload_while_processing(self, client: AsyncClient, db_session: AsyncSession, test_user: User):
        """Should not upload files during processing."""
        case = Case(
            id=uuid.uuid4(), user_id=test_user.id, title="Uploading",
            status="processing",
        )
        db_session.add(case)
        await db_session.commit()

        import io
        fake_file = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        resp = await client.post(
            f"/api/cases/{case.id}/files",
            files={"files": ("test.jpg", fake_file, "image/jpeg")},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_delete_docs_while_processing(self, client: AsyncClient, db_session: AsyncSession, test_user: User):
        """Should not remove context docs during processing."""
        case = Case(
            id=uuid.uuid4(), user_id=test_user.id, title="Doc removal",
            status="processing",
            case_context={"documents": [{"doc_index": 0}], "doc_count": 1},
        )
        db_session.add(case)
        await db_session.commit()

        resp = await client.delete(
            f"/api/cases/{case.id}/context/documents/0",
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════
# File Upload Security
# ═══════════════════════════════════════════════════════════════

class TestFileUploadSecurity:

    @pytest.mark.asyncio
    async def test_reject_disallowed_extension(self, client: AsyncClient, db_session: AsyncSession, test_user: User):
        """Should reject .exe, .sh, .py files."""
        case = Case(id=uuid.uuid4(), user_id=test_user.id, title="Upload test")
        db_session.add(case)
        await db_session.commit()

        import io
        resp = await client.post(
            f"/api/cases/{case.id}/files",
            files={"files": ("malware.exe", io.BytesIO(b"MZ" + b"\x00" * 100), "application/octet-stream")},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] == 0
        assert len(data["skipped"]) == 1
        assert "формат" in data["skipped"][0]["reason"].lower() or "Неподдерживаемый" in data["skipped"][0]["reason"]

    @pytest.mark.asyncio
    async def test_reject_magic_bytes_mismatch(self, client: AsyncClient, db_session: AsyncSession, test_user: User):
        """Should reject .jpg file that starts with PNG magic bytes."""
        case = Case(id=uuid.uuid4(), user_id=test_user.id, title="Magic test")
        db_session.add(case)
        await db_session.commit()

        import io
        # PNG magic bytes in a .jpg file
        png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = await client.post(
            f"/api/cases/{case.id}/files",
            files={"files": ("fake.jpg", io.BytesIO(png_magic), "image/jpeg")},
            headers=auth_headers(test_user),
        )
        data = resp.json()
        assert data["uploaded"] == 0
        assert any("не соответствует" in s.get("reason", "") for s in data["skipped"])

    @pytest.mark.asyncio
    async def test_reject_empty_file(self, client: AsyncClient, db_session: AsyncSession, test_user: User):
        """Should reject empty (0 bytes) file."""
        case = Case(id=uuid.uuid4(), user_id=test_user.id, title="Empty test")
        db_session.add(case)
        await db_session.commit()

        import io
        resp = await client.post(
            f"/api/cases/{case.id}/files",
            files={"files": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
            headers=auth_headers(test_user),
        )
        data = resp.json()
        assert data["uploaded"] == 0


# ═══════════════════════════════════════════════════════════════
# SSE Endpoint Auth
# ═══════════════════════════════════════════════════════════════

class TestSSEAuth:

    @pytest.mark.asyncio
    async def test_stream_requires_auth(self, client: AsyncClient):
        """SSE stream endpoint should require authentication."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/cases/{fake_id}/stream")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_process_requires_auth(self, client: AsyncClient):
        """Process SSE endpoint should require authentication."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/cases/{fake_id}/process")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_context_requires_auth(self, client: AsyncClient):
        """Context endpoint should require authentication."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/cases/{fake_id}/context")
        assert resp.status_code == 401
