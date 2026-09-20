"""P5-A real cross-process SSE linkage (worker process -> real Redis -> API broker).

Two independent proofs, both driving the *application* broker accessor
``get_broker()`` -- the exact code path the SSE endpoint uses:

1. ``test_worker_process_publishes_to_real_redis_and_api_broker_receives`` uses
   a throwaway SQLite database file (always available) so the cross-process
   Redis linkage is verified even when PostgreSQL is unavailable.
2. ``test_worker_process_publishes_to_real_redis_with_postgres`` uses a
   self-created ``hpc_p5_<6 hex>`` PostgreSQL database; it is skipped when
   PostgreSQL is not reachable.

In both cases process A is a real ``python -m app.tasks.event_worker --once``
subprocess and process B subscribes over the real Redis endpoint on a
run-unique channel. No broker, Redis or DB behaviour is faked.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import OutboxEvent
from app.services.event_service import RedisEventBroker, get_broker, reset_broker_cache

try:  # `python -m pytest` -> backend root on sys.path -> `tests` package
    from tests.pg_isolation import postgres_test_url, run_token
except ImportError:  # `pytest` console script -> tests dir on sys.path
    from pg_isolation import postgres_test_url, run_token

BACKEND_DIR = Path(__file__).resolve().parents[1]
REAL_REDIS_URL = os.getenv("HPC_REDIS_URL")
PG_SERVER_URL = os.getenv("HPC_PG_SERVER_URL") or postgres_test_url()


def _require_redis() -> str:
    if not REAL_REDIS_URL:
        pytest.skip("HPC_REDIS_URL not configured; real Redis cross-process check skipped")
    return REAL_REDIS_URL


async def _insert_outbox_row(async_db_url: str, event_id: str, version_no: int) -> None:
    """Create the schema (if new) and stage one committed pending Outbox row."""
    engine = create_async_engine(async_db_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with engine.begin() as conn:
            await conn.execute(
                OutboxEvent.__table__.insert().values(
                    id=event_id,
                    event_type="data_version.published",
                    aggregate_type="data_version",
                    aggregate_id=event_id,
                    payload={"dataVersionId": event_id, "versionNo": version_no},
                    status="pending",
                    attempts=0,
                )
            )
    finally:
        await engine.dispose()


async def _outbox_status(async_db_url: str, event_id: str) -> str | None:
    engine = create_async_engine(async_db_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            row = (
                await db.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))
            ).scalar_one_or_none()
            return row.status if row is not None else None
    finally:
        await engine.dispose()


def _run_worker_once(
    async_db_url: str, redis_url: str, channel: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HPC_ENV"] = "test"
    env["HPC_TEST_DATABASE_URL"] = async_db_url
    env["HPC_REDIS_URL"] = redis_url
    env["HPC_REDIS_CHANNEL"] = channel
    env.setdefault("HPC_JWT_SECRET", "test-secret-at-least-32-bytes-long")
    return subprocess.run(
        [sys.executable, "-m", "app.tasks.event_worker", "--once", "--worker-id", "p5-cross-process"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )


async def _purge_redis(subscriber: RedisEventBroker, event_id: str) -> None:
    client = await subscriber._client()
    await client.delete(subscriber.history_key, subscriber.dedupe_prefix + event_id)
    await subscriber.close()


async def _consume_until(subscriber: RedisEventBroker, event_id: str, timeout: float = 20.0) -> list[dict]:
    received: list[dict] = []

    async def consume() -> None:
        async for item in subscriber.subscribe(None):
            received.append(item)
            if item.get("id") == event_id:
                break

    await asyncio.wait_for(consume(), timeout=timeout)
    return received


async def _publish_and_receive(
    monkeypatch, async_db_url: str, event_id: str, version_no: int, live: bool
) -> list[dict]:
    """Run the worker subprocess and prove the API broker receives the event."""
    redis_url = _require_redis()
    channel = f"hpc:test:p5_xproc:{run_token()}"

    await _insert_outbox_row(async_db_url, event_id, version_no)

    monkeypatch.setenv("HPC_REDIS_URL", redis_url)
    monkeypatch.setenv("HPC_REDIS_CHANNEL", channel)
    reset_broker_cache()
    subscriber = await get_broker()
    assert isinstance(subscriber, RedisEventBroker)
    assert subscriber.channel == channel

    try:
        if live:
            received: list[dict] = []

            async def consume() -> None:
                async for item in subscriber.subscribe(None):
                    received.append(item)
                    if item.get("id") == event_id:
                        break

            task = asyncio.create_task(consume())
            # Register the SUBSCRIBE frame first; the worker subprocess startup
            # (interpreter + imports + connect) is far slower than this window.
            await asyncio.sleep(2.0)
            completed = await asyncio.to_thread(
                _run_worker_once, async_db_url, redis_url, channel
            )
            assert completed.returncode == 0, completed.stderr
            try:
                await asyncio.wait_for(task, timeout=20)
            except asyncio.TimeoutError:
                task.cancel()
                pytest.fail(
                    f"live subscriber never received the worker event "
                    f"(worker rc={completed.returncode}, stderr={completed.stderr!r})"
                )
            result = received
        else:
            completed = await asyncio.to_thread(
                _run_worker_once, async_db_url, redis_url, channel
            )
            assert completed.returncode == 0, completed.stderr
            # Deterministic: the worker already persisted the event in Redis
            # history, so the API accessor replay reads it back.
            result = await _consume_until(subscriber, event_id)

        assert await _outbox_status(async_db_url, event_id) == "dispatched"
        return result
    finally:
        try:
            await _purge_redis(subscriber, event_id)
        except Exception:  # noqa: BLE001
            pass
        reset_broker_cache()


@pytest.mark.asyncio
async def test_worker_process_publishes_to_real_redis_and_api_broker_receives(monkeypatch, tmp_path):
    """Deterministic cross-process check over real Redis (SQLite source DB)."""
    event_id = str(uuid.uuid4())
    db_file = tmp_path / "p5_cross_process.db"
    async_db_url = f"sqlite+aiosqlite:///{db_file}"

    received = await _publish_and_receive(monkeypatch, async_db_url, event_id, 4242, live=False)

    matched = next(item for item in received if item.get("id") == event_id)
    assert matched["type"] == "data_version.published"
    assert matched["data"]["versionNo"] == 4242


@pytest.mark.asyncio
async def test_worker_process_delivers_live_to_api_subscriber(monkeypatch, tmp_path):
    """Real-time (live pub/sub) cross-process check over real Redis."""
    event_id = str(uuid.uuid4())
    async_db_url = f"sqlite+aiosqlite:///{tmp_path / 'p5_live.db'}"

    received = await _publish_and_receive(monkeypatch, async_db_url, event_id, 777, live=True)

    assert any(item.get("id") == event_id for item in received), received


# --------------------------------------------------------------------------- #
# PostgreSQL variant (dedicated, retained hpc_p5_<6 hex> database)
#
# Discipline: this test NEVER runs ``DROP DATABASE`` -- the self-built database is
# created once (if absent) and kept; cleanup deletes only the row this run
# inserted. A fixed name avoids accumulating databases across runs.
# --------------------------------------------------------------------------- #
PG_XPROC_DBNAME = "hpc_p5_a11ce0"


def _pg_admin_connect(server_url: str):
    import psycopg

    parsed = urlparse(server_url)
    return psycopg.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username or "postgres",
        password=parsed.password or "",
        dbname="postgres",
        autocommit=True,
        connect_timeout=5,
    )


def _pg_database_url(server_url: str, dbname: str) -> str:
    parsed = urlparse(server_url)
    return urlunparse((parsed.scheme, parsed.netloc, "/" + dbname, "", "", ""))


def _ensure_pg_database(server_url: str, dbname: str) -> None:
    """Create the dedicated database only if it does not already exist."""
    with _pg_admin_connect(server_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{dbname}"')


async def _delete_outbox_row(async_db_url: str, event_id: str) -> None:
    from sqlalchemy import delete

    engine = create_async_engine(async_db_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_process_publishes_to_real_redis_with_postgres(monkeypatch):
    """Same linkage, sourced from a self-created PostgreSQL database.

    Skipped (never failed) when PostgreSQL is not reachable, so an outage of the
    shared test instance cannot be mistaken for a product regression. The
    database is created if absent and retained (no ``DROP DATABASE``).
    """
    _require_redis()
    if not PG_SERVER_URL:
        pytest.skip("HPC_PG_SERVER_URL / HPC_POSTGRES_TEST_URL not configured")

    dbname = PG_XPROC_DBNAME
    async_db_url = _pg_database_url(PG_SERVER_URL, dbname)

    try:
        await asyncio.to_thread(_ensure_pg_database, PG_SERVER_URL, dbname)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unavailable ({type(exc).__name__}: {exc})")

    event_id = str(uuid.uuid4())
    try:
        received = await _publish_and_receive(monkeypatch, async_db_url, event_id, 9001, live=False)
        matched = next(item for item in received if item.get("id") == event_id)
        assert matched["data"]["versionNo"] == 9001
    finally:
        try:
            await _delete_outbox_row(async_db_url, event_id)
        except Exception:  # noqa: BLE001 - best-effort row cleanup, DB is kept
            pass

