from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def _url() -> str:
    settings = get_settings()
    return settings.test_database_url if settings.env == "test" else settings.database_url


_active_engine: AsyncEngine = create_async_engine(_url(), future=True)
_active_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _active_engine, expire_on_commit=False
)


class _EngineProxy:
    """Stable engine reference that can be swapped by isolated test fixtures.

    Application and tests import ``engine`` at module import time. A proxy keeps
    those references valid while ``configure_engine`` points them at a fresh
    per-test SQLite database.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(_active_engine, name)


class _SessionFactoryProxy:
    """Stable callable reference to the currently active session factory."""

    def __call__(self, *args: Any, **kwargs: Any) -> AsyncSession:
        return _active_session_factory(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(_active_session_factory, name)


engine = _EngineProxy()
SessionLocal = _SessionFactoryProxy()


def configure_engine(database_url: str) -> AsyncEngine:
    """Switch the active engine and return the previous engine for disposal."""
    global _active_engine, _active_session_factory
    previous = _active_engine
    _active_engine = create_async_engine(database_url, future=True)
    _active_session_factory = async_sessionmaker(_active_engine, expire_on_commit=False)
    return previous


def restore_engine(previous_engine: AsyncEngine) -> None:
    """Restore a previously active engine after an isolated test completes."""
    global _active_engine, _active_session_factory
    _active_engine = previous_engine
    _active_session_factory = async_sessionmaker(_active_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session bound to the currently active engine."""
    async with SessionLocal() as session:
        yield session
