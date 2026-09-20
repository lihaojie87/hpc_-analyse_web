"""T05.2 worker, lock, Redis broker and fault-isolation tests."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import OutboxEvent
from app.services.event_service import MemoryEventBroker, RedisEventBroker, dispatch_pending


class FailingBroker:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, event: dict, event_id: str | None = None) -> dict:
        self.calls += 1
        raise RuntimeError("broker unavailable")


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.history: list[str] = []
        self.published: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def rpush(self, key: str, value: str):
        self.history.append(value)
        return len(self.history)

    async def ltrim(self, key: str, start: int, end: int):
        return True

    async def publish(self, channel: str, value: str):
        self.published.append((channel, value))
        return 1


async def add_event(db, *, attempts: int = 0, locked_until=None) -> OutboxEvent:
    event = OutboxEvent(
        id=str(uuid.uuid4()), event_type="data_version.published", aggregate_type="data_version",
        aggregate_id=str(uuid.uuid4()), payload={"dataVersionId": "dv", "versionNo": 1},
        status="pending", attempts=attempts, locked_until=locked_until,
    )
    db.add(event)
    await db.commit()
    return event


@pytest.mark.asyncio
async def test_worker_broker_failure_isolated_and_retriable(db):
    event = await add_event(db)
    broker = FailingBroker()
    assert await dispatch_pending(db, event_broker=broker, max_attempts=3) == 0
    row = await db.get(OutboxEvent, event.id)
    assert row.status == "pending"
    assert row.attempts == 1


@pytest.mark.asyncio
async def test_worker_marks_failed_after_max_attempts(db):
    event = await add_event(db, attempts=2)
    assert await dispatch_pending(db, event_broker=FailingBroker(), max_attempts=3) == 0
    row = await db.get(OutboxEvent, event.id)
    assert row.status == "failed"
    assert row.attempts == 3


@pytest.mark.asyncio
async def test_sqlite_lock_expiry_allows_retry(db):
    expired = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    event = await add_event(db, locked_until=expired)
    broker = MemoryEventBroker()
    assert await dispatch_pending(db, event_broker=broker) == 1
    row = await db.get(OutboxEvent, event.id)
    assert row.status == "dispatched"


@pytest.mark.asyncio
async def test_memory_broker_deduplicates_stable_outbox_id():
    broker = MemoryEventBroker()
    first = await broker.publish({"type": "data_version.published", "data": {"versionNo": 1}}, event_id="event-1")
    second = await broker.publish({"type": "data_version.published", "data": {"versionNo": 1}}, event_id="event-1")
    assert first == second
    assert len(broker._history) == 1


@pytest.mark.asyncio
async def test_redis_broker_deduplicates_and_publishes_history():
    redis = FakeRedis()
    broker = RedisEventBroker("redis://test")
    broker._redis = redis
    first = await broker.publish({"type": "data_version.published", "data": {"versionNo": 2}}, event_id="event-r")
    second = await broker.publish({"type": "data_version.published", "data": {"versionNo": 2}}, event_id="event-r")
    assert first == second
    assert len(redis.history) == 1
    assert len(redis.published) == 1
    assert json.loads(redis.history[0])["id"] == "event-r"
