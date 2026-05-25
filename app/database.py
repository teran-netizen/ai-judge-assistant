from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,        # макс 30 соединений (20 pool + 10 overflow) при пиковой нагрузке
    pool_pre_ping=True,     # проверяет соединение перед использованием (защита от перезапуска БД)
    pool_recycle=3600,       # пересоздаёт соединения старше 1 часа
    pool_timeout=10,         # ждать свободное соединение макс 10 сек (вместо дефолтных 30)
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """Сессия БД.

    Коммит по умолчанию выполняется только если в сессии есть реальные изменения.
    Read-only handlers не должны получать лишний COMMIT просто из-за открытой транзакции
    после SELECT.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
