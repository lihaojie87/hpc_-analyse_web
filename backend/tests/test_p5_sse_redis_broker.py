"""P5-A / findings #1-#3: broker resolution, client lock, worker reuse, TTL.

Coverage map:

* P5-A  -- ``get_broker`` resolves the same config-driven broker the worker uses
           (Redis when configured, in-process memory otherwise).
* #1    -- ``RedisEventBroker._client`` creates exactly one client under
           concurrent first use (was: one per caller -> connection leak).
* #2    -- ``EventWorker`` resolves its broker once and reuses it across polls.
* #3    -- the Redis dedupe key carries a TTL (was: unbounded key growth).

Tests marked ``real_redis`` run against the configured ``HPC_REDIS_URL``
(127.0.0.1:56379, RESP2) and are skipped when it is unset. The rest use fake
clients and exercise the logic offline.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.services import event_service
from app.services.event_service import (
    MemoryEventBroker,
    RedisEventBroker,
    get_broker,
    reset_broker_cache,
)
from app.tasks import event_worker

#: Captured at import time, before any per-test env scrub, so the real-Redis
#: tests can re-enable it inside their body.
REAL_REDIS_URL = os.getenv("HPC_REDIS_URL")


def require_redis() -> str:
    if not REAL_REDIS_URL:
        pytest.skip("HPC_REDIS_URL not configured; real Redis check skipped")
    return REAL_REDIS_URL


# --------------------------------------------------------------------------- #
# P5-A: config-driven broker resolution shared by API + worker
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_broker_without_config_returns_process_memory_broker(monkeypatch):
    monkeypatch.delenv("HPC_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_broker_cache()

    broker = await get_broker()

    assert isinstance(broker, MemoryEventBroker)
    # The SSE route and dispatch_pending's default must be the same instance.
    assert broker is event_service.broker


@pytest.mark.asyncio
async def test_get_broker_caches_first_resolution(monkeypatch):
    monkeypatch.delenv("HPC_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_broker_cache()

    calls: list[str | None] = []
    real_create = event_service.create_broker

    async def counting_create(url=None):
        calls.append(url)
        return await real_create(url)

    monkeypatch.setattr(event_service, "create_broker", counting_create)

    first = await get_broker()
    second = await get_broker()

    assert first is second
    assert len(calls) == 1, "the broker must be resolved exactly once per process"


@pytest.mark.asyncio
async def test_get_broker_is_concurrency_safe(monkeypatch):
    monkeypatch.delenv("HPC_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_broker_cache()

    created: list[MemoryEventBroker] = []
    real_create = event_service.create_broker

    async def slow_create(url=None):
        await asyncio.sleep(0.02)
        broker = await real_create(url)
        created.append(broker)  # type: ignore[arg-type]
        return broker

    monkeypatch.setattr(event_service, "create_broker", slow_create)

    brokers = await asyncio.gather(*[get_broker() for _ in range(6)])

    assert len(created) == 1
    assert all(b is brokers[0] for b in brokers)


@pytest.mark.asyncio
async def test_get_broker_resolves_real_redis_when_configured(monkeypatch):
    """P5-A: with Redis configured, the API-side accessor uses the Redis broker."""
    url = require_redis()
    monkeypatch.setenv("HPC_REDIS_URL", url)
    reset_broker_cache()

    broker = await get_broker()
    try:
        assert isinstance(broker, RedisEventBroker)
    finally:
        await broker.close()
        reset_broker_cache()


# --------------------------------------------------------------------------- #
# Finding #1: concurrent _client() must create exactly one client
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_client_created_once_under_concurrency_offline(monkeypatch):
    broker = RedisEventBroker("redis://127.0.0.1:56379/0")
    created: list[object] = []
    sentinel = object()

    async def fake_connect():
        await asyncio.sleep(0.02)  # widen the race window
        created.append(sentinel)
        return sentinel

    monkeypatch.setattr(broker, "_connect", fake_connect)

    clients = await asyncio.gather(*[broker._client() for _ in range(6)])

    assert len(created) == 1, "6 concurrent callers must build exactly one client"
    assert all(client is sentinel for client in clients)


@pytest.mark.asyncio
async def test_client_created_once_under_concurrency_real_redis():
    url = require_redis()
    broker = RedisEventBroker(url)
    original_connect = broker._connect
    count = 0

    async def counting_connect():
        nonlocal count
        count += 1
        await asyncio.sleep(0.02)
        return await original_connect()

    broker._connect = counting_connect  # instance attribute shadows the method
    try:
        clients = await asyncio.gather(*[broker._client() for _ in range(6)])
        assert count == 1
        assert all(client is clients[0] for client in clients)
    finally:
        await broker.close()


# --------------------------------------------------------------------------- #
# Finding #2: the worker resolves its broker once across polls
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_worker_resolves_broker_once_across_polls(monkeypatch):
    created: list[MemoryEventBroker] = []

    async def fake_create(url=None):
        broker = MemoryEventBroker()
        created.append(broker)
        return broker

    async def fake_dispatch(db, **kwargs):
        return 0

    monkeypatch.setattr(event_worker, "create_broker", fake_create)
    monkeypatch.setattr(event_worker, "dispatch_pending", fake_dispatch)

    worker = event_worker.EventWorker(event_worker.WorkerConfig(poll_interval=0.01))
    for _ in range(4):
        await worker.run_once()

    assert len(created) == 1, "a long-running worker must not rebuild its broker every poll"
    assert await worker._selected_broker() is created[0]
    await worker.aclose()


@pytest.mark.asyncio
async def test_worker_injected_broker_wins_and_is_not_created(monkeypatch):
    async def forbidden_create(url=None):
        raise AssertionError("create_broker must not run when a broker is injected")

    monkeypatch.setattr(event_worker, "create_broker", forbidden_create)

    injected = MemoryEventBroker()
    worker = event_worker.EventWorker(event_worker.WorkerConfig(), event_broker=injected)

    assert await worker._selected_broker() is injected
    await worker.aclose()  # injected broker is not owned -> no-op


@pytest.mark.asyncio
async def test_worker_aclose_closes_owned_broker_once(monkeypatch):
    closed: list[int] = []

    class ClosableBroker(MemoryEventBroker):
        async def close(self) -> None:
            closed.append(1)

    async def fake_create(url=None):
        return ClosableBroker()

    monkeypatch.setattr(event_worker, "create_broker", fake_create)

    worker = event_worker.EventWorker(event_worker.WorkerConfig())
    await worker._selected_broker()
    await worker.aclose()
    await worker.aclose()  # second close is a no-op

    assert closed == [1]


# --------------------------------------------------------------------------- #
# Finding #3: dedupe key must carry a TTL
# --------------------------------------------------------------------------- #
class _TTLRedis:
    """Minimal fake that records the arguments of the dedupe ``SET``."""

    def __init__(self) -> None:
        self.set_calls: list[dict] = []
        self.values: dict[str, str] = {}
        self.history: list[str] = []
        self.published: list[tuple[str, str]] = []

    async def set(self, key, value, nx=False, ex=None):
        self.set_calls.append({"key": key, "nx": nx, "ex": ex})
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def rpush(self, key, value):
        self.history.append(value)
        return len(self.history)

    async def ltrim(self, key, start, end):
        return True

    async def publish(self, channel, value):
        self.published.append((channel, value))
        return 1


@pytest.mark.asyncio
async def test_dedupe_key_sets_ttl_offline():
    redis = _TTLRedis()
    broker = RedisEventBroker("redis://test", dedupe_ttl_seconds=1800)
    broker._redis = redis

    await broker.publish({"type": "data_version.published", "data": {"versionNo": 1}}, event_id="evt-ttl")

    assert redis.set_calls, "publish must use SET NX for dedupe"
    assert redis.set_calls[0]["nx"] is True
    assert redis.set_calls[0]["ex"] == 1800, "the dedupe key must expire"


@pytest.mark.asyncio
async def test_dedupe_key_has_positive_ttl_real_redis():
    url = require_redis()
    channel = f"hpc:test:p5_ttl:{uuid.uuid4().hex[:8]}"
    broker = RedisEventBroker(url, channel=channel)
    dedupe_key = broker.dedupe_prefix + "p5-ttl"
    try:
        await broker.publish({"type": "data_version.published", "data": {"versionNo": 1}}, event_id="p5-ttl")
        client = await broker._client()
        ttl = await client.ttl(dedupe_key)
        assert ttl > 0, f"dedupe key must expire, got TTL={ttl}"
    finally:
        client = await broker._client()
        await client.delete(broker.history_key, dedupe_key)
        await broker.close()
