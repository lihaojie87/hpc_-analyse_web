import os
import uuid

os.environ.setdefault("HPC_ENV", "test")
os.environ.setdefault("HPC_JWT_SECRET", "test-secret-at-least-32-bytes-long")
os.environ.setdefault("HPC_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("HPC_BOOTSTRAP_ADMIN_PASSWORD", "Admin1234")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from app.db.models import CatalogHead
from app.db.session import SessionLocal, configure_engine
from app.main import app
from app.seed.seed_permissions import seed


@pytest.fixture(scope="function", autouse=True)
def reset_event_broker(monkeypatch):
    """Make broker selection deterministic and free of cross-test state.

    The default suite must run offline: the event broker is scrubbed from the
    environment so ``get_broker`` resolves the in-process ``MemoryEventBroker``
    (and the cached resolution is cleared before and after every test). Real
    Redis/PG integration tests opt back in by setting the env inside the test
    body.
    """
    from app.services import event_service

    monkeypatch.delenv("HPC_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    event_service.reset_broker_cache()
    yield
    event_service.reset_broker_cache()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def database(tmp_path):
    """Create a fresh SQLite database and bind app/test sessions to it."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / ('test-' + uuid.uuid4().hex + '.db')}"
    previous_engine: AsyncEngine = configure_engine(database_url)
    try:
        from app.db.session import engine

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await seed()
        async with SessionLocal() as session:
            existing = (
                await session.execute(
                    select(CatalogHead).where(
                        CatalogHead.scope_key == "performance_catalog"
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(CatalogHead(scope_key="performance_catalog", current_revision=0))
                await session.commit()
        yield
    finally:
        from app.db.session import engine, restore_engine

        await engine.dispose()
        restore_engine(previous_engine)
        await previous_engine.dispose()


@pytest_asyncio.fixture
async def client(database):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def db(database):
    async with SessionLocal() as session:
        yield session
