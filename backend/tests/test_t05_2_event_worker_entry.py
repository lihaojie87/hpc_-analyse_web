"""Executable worker entry and restart/recovery tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.db.models import OutboxEvent
from app.services.event_service import MemoryEventBroker
from app.tasks.event_worker import EventWorker, WorkerConfig, main


class RecordingBroker(MemoryEventBroker):
    """Memory broker that records successful dispatches for assertions."""

    def __init__(self, fail_first: bool = False) -> None:
        super().__init__()
        self.fail_first = fail_first
        self.calls = 0

    async def publish(self, event: dict[str, Any], event_id: str | None = None) -> dict[str, Any]:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("injected transient broker outage")
        return await super().publish(event, event_id)


async def add_event(db: Any, *, locked_until: datetime | None = None) -> OutboxEvent:
    event = OutboxEvent(
        event_type="data_version.published",
        aggregate_type="data_version",
        aggregate_id="dv-worker",
        payload={"dataVersionId": "dv-worker", "versionNo": 1},
        status="pending",
        locked_until=locked_until,
    )
    db.add(event)
    await db.commit()
    return event


@pytest.mark.asyncio
async def test_worker_once_dispatches_committed_event_and_restart_is_idempotent(db):
    event = await add_event(db)
    broker = RecordingBroker()
    config = WorkerConfig(poll_interval=0.01, batch_size=10, worker_id="worker-once")
    worker = EventWorker(config, broker)

    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)
    assert row.status == "dispatched"
    assert broker.calls == 1


@pytest.mark.asyncio
async def test_worker_retries_transient_failure_after_restart(db):
    event = await add_event(db)
    broker = RecordingBroker(fail_first=True)
    config = WorkerConfig(max_attempts=3, worker_id="worker-restart")
    worker = EventWorker(config, broker)

    assert await worker.run_once() == 0
    failed_attempt = await db.get(OutboxEvent, event.id)
    await db.refresh(failed_attempt)
    assert failed_attempt.status == "pending"
    assert failed_attempt.attempts == 1

    assert await EventWorker(config, broker).run_once() == 1
    recovered = await db.get(OutboxEvent, event.id)
    await db.refresh(recovered)
    assert recovered.status == "dispatched"
    assert recovered.attempts == 2


@pytest.mark.asyncio
async def test_worker_recovers_expired_claim_after_crash(db):
    expired = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    event = await add_event(db, locked_until=expired)
    broker = RecordingBroker()
    worker = EventWorker(WorkerConfig(lock_seconds=10, worker_id="worker-recovered"), broker)

    assert await worker.run_once() == 1
    recovered = await db.get(OutboxEvent, event.id)
    await db.refresh(recovered)
    assert recovered.status == "dispatched"
    assert recovered.locked_by is None
    assert recovered.locked_until is None


def test_worker_cli_once_parses_and_returns_success(monkeypatch):
    """The module exposes an executable once mode without starting a loop."""
    import app.tasks.event_worker as event_worker

    async def fake_async_main(args):
        assert args.once is True
        assert args.batch_size == 2
        assert args.worker_id == "cli-test"
        return 0

    monkeypatch.setattr(event_worker, "_async_main", fake_async_main)
    assert main(["--once", "--batch-size", "2", "--worker-id", "cli-test"]) == 0
