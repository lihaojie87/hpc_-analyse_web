"""P5-A residual regression: ``dispatch_pending`` must publish to the *same*
broker the SSE endpoint subscribes with.

Previously ``dispatch_pending`` defaulted to the module-level in-process
``MemoryEventBroker`` (``selected_broker = event_broker or broker``), while the
SSE subscriber resolved a *Redis* broker via ``get_broker()``. When Redis was
configured, every SSE-triggered dispatch published to a broker nobody was
subscribed to and still marked the row ``dispatched`` -> permanent, silent event
loss. These tests pin the corrected, single-source behaviour.

Marked tests connect to the real Redis endpoint (``HPC_REDIS_URL``); the rest use
an injected recording broker and run offline.
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
    dispatch_pending,
    get_broker,
    reset_broker_cache,
)

REAL_REDIS_URL = os.getenv("HPC_REDIS_URL")


async def _add_event(db) -> OutboxEvent:
    event = OutboxEvent(
        id=str(uuid.uuid4()),
        event_type="data_version.published",
        aggregate_type="data_version",
        aggregate_id=str(uuid.uuid4()),
        payload={"dataVersionId": "dv-dispatch", "versionNo": 5},
        status="pending",
        attempts=0,
    )
    db.add(event)
    await db.commit()
    return event


@pytest.mark.asyncio
async def test_dispatch_pending_default_uses_get_broker_not_module_singleton(db, monkeypatch):
    """Offline proof that the default path resolves through ``get_broker()``."""
    monkeypatch.delenv("HPC_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_broker_cache()

    published: list[tuple[str, str | None]] = []

    class RecordingBroker(MemoryEventBroker):
        async def publish(self, event, event_id=None):
            published.append((event.get("type"), event_id))
            return await super().publish(event, event_id)

    resolved = RecordingBroker()

    async def fake_create(url=None):
        return resolved

    monkeypatch.setattr(event_service, "create_broker", fake_create)
    reset_broker_cache()

    # This is the broker the SSE subscriber would use.
    sse_broker = await get_broker()
    assert sse_broker is resolved

    event = await _add_event(db)
    dispatched = await dispatch_pending(db)  # no event_broker passed on purpose

    assert dispatched == 1
    assert published == [("data_version.published", event.id)]
    # Reverse assertion: the event must NOT have landed on the module-level
    # in-process singleton -- that is exactly the "dispatched to a foreign
    # broker" defect this test guards.
    assert event.id not in event_service.broker._published_by_id


@pytest.mark.asyncio
async def test_dispatch_pending_default_publishes_into_real_redis(db, monkeypatch):
    """Real Redis proof: an SSE-style dispatch lands on the subscriber's Redis."""
    if not REAL_REDIS_URL:
        pytest.skip("HPC_REDIS_URL not configured; real Redis dispatch check skipped")

    channel = f"hpc:test:p5_dispatch:{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("HPC_REDIS_URL", REAL_REDIS_URL)
    monkeypatch.setenv("HPC_REDIS_CHANNEL", channel)
    reset_broker_cache()

    event = await _add_event(db)
    dispatched = await dispatch_pending(db)  # no event_broker passed on purpose
    assert dispatched == 1

    sse_broker = await get_broker()  # exactly what the SSE endpoint subscribes with
    client = await sse_broker._client()
    try:
        history = await client.lrange(sse_broker.history_key, 0, -1)
        ids = [json.loads(item)["id"] for item in history]
        assert event.id in ids, "the dispatched event must be readable on the Redis broker"

        row = await db.get(OutboxEvent, event.id)
        await db.refresh(row)
        assert row.status == "dispatched"

        # Reverse assertion: never present on the process-local singleton.
        assert event.id not in event_service.broker._published_by_id
    finally:
        await client.delete(sse_broker.history_key, sse_broker.dedupe_prefix + event.id)
        await sse_broker.close()
        reset_broker_cache()
