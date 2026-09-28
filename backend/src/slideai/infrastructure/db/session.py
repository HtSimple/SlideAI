from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from slideai.core.config import Settings


def create_engine(settings: Settings):
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_engine(settings), expire_on_commit=False)
