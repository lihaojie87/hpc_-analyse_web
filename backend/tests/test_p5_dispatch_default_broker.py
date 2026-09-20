"""P5-A residual regression: ``dispatch_pending`` must resolve the SAME broker as SSE.

The residual defect: the SSE endpoint calls ``dispatch_pending(db)`` **without**
an explicit broker, while its subscription side uses ``get_broker()`` (Redis when
configured). If the dispatch default falls back to the process-local
``MemoryEventBroker``, events are published where nobody is subscribed, yet the
row is still marked ``dispatched`` -- silent, permanent loss (and the standalone
worker will not re-dispatch an already-claimed row).

These tests assert the *observable* consequence, not just the returned count:
the event must really exist on the Redis side, and must NOT exist only on the
process-local memory broker.

Companion file: ``test_p5_dispatch_broker.py`` covers the offline default-path
resolution and a real-Redis round trip. This file adds the load-bearing cases
that were originally drafted separately and must not be dropped:

* the default path, when Redis is *unconfigured*, resolves to the shared memory
  singleton (so single-process deployments keep working);
* an SSE-style dispatch resolves the **very same object** ``get_broker()``
  returns (identity spy, not merely a call-count check);
* the reverse invariant ``dispatched <=> present on the target broker``.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

from app.db.models import OutboxEvent
from app.services import event_service
from app.services.event_service import (
    MemoryEventBroker,
    RedisEventBroker,
    dispatch_pending,
    get_broker,
    reset_broker_cache,
)

REAL_REDIS_URL = os.getenv("HPC_REDIS_URL")


def _reset_memory_broker() -> None:
    """Clear the process-local broker so 'did it land here?' is unambiguous."""
    while event_service.broker._history:
        event_service.broker._history.popleft()
    event_service.broker._published_by_id.clear()


async def _add_pending(db, event_id: str) -> None:
    db.add(
        OutboxEvent(
            id=event_id,
            event_type="data_version.published",
            aggregate_type="data_version",
            aggregate_id=event_id,
            payload={"dataVersionId": event_id, "versionNo": 5},
            status="pending",
            attempts=0,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_dispatch_pending_default_uses_memory_broker_when_unconfigured(db):
    """Unconfigured: the default resolution IS the single process memory broker."""
    _reset_memory_broker()
    event_id = str(uuid.uuid4())
    await _add_pending(db, event_id)

    dispatched = await dispatch_pending(db)

    assert dispatched == 1
    resolved = await get_broker()
    assert resolved is event_service.broker
    assert any(item["id"] == event_id for item in event_service.broker._history)


@pytest.mark.asyncio
async def test_dispatch_pending_default_publishes_to_configured_redis(monkeypatch, db):
    """Configured Redis: default dispatch must publish to Redis, not to memory."""
    if not REAL_REDIS_URL:
        pytest.skip("HPC_REDIS_URL not configured; real Redis check skipped")

    channel = f"hpc:test:p5_dispatch:{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("HPC_REDIS_URL", REAL_REDIS_URL)
    monkeypatch.setenv("HPC_REDIS_CHANNEL", channel)
    reset_broker_cache()
    _reset_memory_broker()

    event_id = str(uuid.uuid4())
    await _add_pending(db, event_id)

    broker = await get_broker()
    assert isinstance(broker, RedisEventBroker)
    assert broker.channel == channel

    # Spy: prove dispatch_pending used the very same object get_broker() returns.
    used: list[object] = []
    real_get_broker = event_service.get_broker

    async def spying_get_broker():
        resolved = await real_get_broker()
        used.append(resolved)
        return resolved

    monkeypatch.setattr(event_service, "get_broker", spying_get_broker)

    try:
        dispatched = await dispatch_pending(db)  # NOTE: no event_broker argument
        assert dispatched == 1
        assert used and all(item is broker for item in used), (
            "dispatch_pending must resolve the same broker get_broker() returns"
        )

        # (1) The event really reached Redis (read from the Redis side).
        client = await broker._client()
        raw = await client.lrange(broker.history_key, 0, -1)
        ids = [json.loads(item)["id"] for item in raw]
        assert event_id in ids, "event was not published to the configured Redis broker"
        assert await client.exists(broker.dedupe_prefix + event_id) == 1

        # (2) Negative: it must NOT be sitting on the process-local memory broker.
        assert all(item["id"] != event_id for item in event_service.broker._history), (
            "event was published to the unsubscribed process-local broker (silent-loss path)"
        )

        # (3) The row committed as dispatched AND the event exists on the target broker.
        row = await db.get(OutboxEvent, event_id)
        await db.refresh(row)
        assert row.status == "dispatched"
    finally:
        client = await broker._client()
        await client.delete(broker.history_key, broker.dedupe_prefix + event_id)
        await broker.close()
        reset_broker_cache()


@pytest.mark.asyncio
async def test_dispatch_pending_never_marks_dispatched_off_target_broker(monkeypatch, db):
    """Reverse case: a row must not be 'dispatched' while absent from the target broker."""
    if not REAL_REDIS_URL:
        pytest.skip("HPC_REDIS_URL not configured; real Redis check skipped")

    channel = f"hpc:test:p5_dispatch:{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("HPC_REDIS_URL", REAL_REDIS_URL)
    monkeypatch.setenv("HPC_REDIS_CHANNEL", channel)
    reset_broker_cache()
    _reset_memory_broker()

    event_id = str(uuid.uuid4())
    await _add_pending(db, event_id)

    broker = await get_broker()
    assert isinstance(broker, RedisEventBroker)
    try:
        assert await dispatch_pending(db) == 1

        client = await broker._client()
        on_target = await client.exists(broker.dedupe_prefix + event_id) == 1
        row = await db.get(OutboxEvent, event_id)
        await db.refresh(row)
        # Invariant: dispatched <=> present on the target broker. The old defect
        # produced dispatched=True with on_target=False.
        assert row.status == "dispatched"
        assert on_target, "row marked dispatched but the event is absent from the target broker"
    finally:
        client = await broker._client()
        await client.delete(broker.history_key, broker.dedupe_prefix + event_id)
        await broker.close()
        reset_broker_cache()
