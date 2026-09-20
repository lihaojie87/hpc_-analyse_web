"""Independent QA checks for the T05.2 executable Outbox worker."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.tasks.event_worker as event_worker
from app.tasks.event_worker import EventWorker, WorkerConfig, _parse_args


class FakeSession:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True
        return False


class SessionFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = FakeSession()
        self.sessions.append(session)
        return session


@pytest.mark.parametrize(
    "kwargs",
    [
        {"poll_interval": 0},
        {"batch_size": 0},
        {"max_attempts": 0},
        {"lock_seconds": 0},
    ],
)
def test_worker_config_rejects_non_positive_values(kwargs):
    with pytest.raises(ValueError):
        WorkerConfig(**kwargs).normalized()


@pytest.mark.asyncio
async def test_run_once_uses_fresh_session_and_passes_worker_options(monkeypatch):
    factory = SessionFactory()
    monkeypatch.setattr(event_worker, "SessionLocal", factory)
    calls = []

    async def fake_dispatch(db, **kwargs):
        calls.append((db, kwargs))
        return 2

    monkeypatch.setattr(event_worker, "dispatch_pending", fake_dispatch)
    worker = EventWorker(
        WorkerConfig(
            poll_interval=0.25,
            batch_size=7,
            max_attempts=4,
            lock_seconds=11,
            worker_id="qa-worker",
        ),
        event_broker=object(),
    )

    assert await worker.run_once() == 2
    assert len(factory.sessions) == 1
    assert factory.sessions[0].entered and factory.sessions[0].exited
    assert calls[0][0] is factory.sessions[0]
    assert calls[0][1] == {
        "limit": 7,
        "max_attempts": 4,
        "lock_seconds": 11,
        "worker_id": "qa-worker",
        "event_broker": worker.event_broker,
    }


@pytest.mark.asyncio
async def test_polling_worker_stops_after_request_and_survives_one_failure(monkeypatch):
    worker = EventWorker(WorkerConfig(poll_interval=0.01), event_broker=object())
    calls = 0

    async def fake_run_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected poll failure")
        worker.request_stop()
        return 0

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    await asyncio.wait_for(worker.run(), timeout=1)
    assert calls == 2


def test_cli_parser_supports_once_and_rejects_unknown_option():
    args = _parse_args(["--once", "--poll-interval", "0.2", "--batch-size", "3", "--max-attempts", "2", "--lock-seconds", "9", "--worker-id", "qa-cli"])
    assert args.once is True
    assert args.poll_interval == 0.2
    assert args.batch_size == 3
    assert args.max_attempts == 2
    assert args.lock_seconds == 9
    assert args.worker_id == "qa-cli"
    with pytest.raises(SystemExit):
        _parse_args(["--unknown-option"])
