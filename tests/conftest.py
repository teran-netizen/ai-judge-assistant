"""Pytest configuration and shared fixtures."""
import os
import uuid
import pytest
import pytest_asyncio

from datetime import datetime, timezone


def pytest_configure(config):
    """Ensure test env vars are set before any imports."""
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")
    os.environ.setdefault("DEBUG", "true")
    os.environ.setdefault("ALFA_TEST_MODE", "true")
    os.environ.setdefault("ALFA_CALLBACK_SECRET", "test-callback-secret")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://judge:dev_password_change_me@localhost:5432/ai_judge_test")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")


# ── Shared fixtures ──

from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app.models import User
from app.utils.auth import create_access_token
from app.config import get_settings


@pytest_asyncio.fixture
async def db_engine():
    """Create test engine and tables."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SEQUENCE IF NOT EXISTS users_display_id_seq"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP SEQUENCE IF EXISTS users_display_id_seq"))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Session with auto-rollback."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        id=uuid.uuid4(),
        yandex_id="test_yandex_123",
        email="test@example.com",
        name="Test User",
        token_balance=1_000_000,
        free_cases_left=5,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create a test admin user."""
    user = User(
        id=uuid.uuid4(),
        yandex_id="admin_yandex_456",
        email="admin@example.com",
        name="Admin",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


def auth_headers(user: User) -> dict:
    """JWT token headers for a test user."""
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """AsyncClient with overridden DB session."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
