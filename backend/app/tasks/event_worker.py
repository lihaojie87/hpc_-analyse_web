"""Executable Outbox worker for cross-process event dispatch.

Run with ``python -m app.tasks.event_worker``.  The worker creates its own
SQLAlchemy session and broker, so it can run independently from API workers.
``--once`` is intended for deployments and deterministic tests; the default
mode loops until interrupted and never lets one dispatch failure terminate the
worker process.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import uuid
from dataclasses import dataclass
from typing import Sequence

from app.db.session import SessionLocal
from app.services.event_service import EventBroker, create_broker, dispatch_pending

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerConfig:
    """Runtime settings controlling one Outbox worker process."""

    poll_interval: float = 1.0
    batch_size: int = 100
    max_attempts: int = 5
    lock_seconds: int = 30
    worker_id: str = ""

    def normalized(self) -> "WorkerConfig":
        """Return validated settings with a generated process identity."""
        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.lock_seconds <= 0:
            raise ValueError("lock_seconds must be positive")
        return WorkerConfig(
            poll_interval=self.poll_interval,
            batch_size=self.batch_size,
            max_attempts=self.max_attempts,
            lock_seconds=self.lock_seconds,
            worker_id=self.worker_id or f"outbox-worker-{os.getpid()}-{uuid.uuid4().hex[:12]}",
        )


class EventWorker:
    """Poll committed Outbox rows and dispatch them through a broker."""

    def __init__(self, config: WorkerConfig | None = None, event_broker: EventBroker | None = None) -> None:
        self.config = (config or WorkerConfig()).normalized()
        self.event_broker = event_broker
        self._owned_broker: EventBroker | None = None
        self._broker_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        """Ask a looping worker to stop after its current poll."""
        self._stop_event.set()

    async def _selected_broker(self) -> EventBroker:
        """Return this worker's broker, resolving the configured one at most once.

        An externally injected ``event_broker`` always wins. Otherwise the
        config-driven broker is created on first use and cached for the whole
        process lifetime, so a long-running poll loop no longer opens (and
        leaks) a fresh connection every round.
        """
        if self.event_broker is not None:
            return self.event_broker
        if self._owned_broker is None:
            async with self._broker_lock:
                if self._owned_broker is None:
                    self._owned_broker = await create_broker()
        return self._owned_broker

    async def aclose(self) -> None:
        """Release a broker this worker created (never an injected one)."""
        if self._owned_broker is not None:
            await self._owned_broker.close()
            self._owned_broker = None

    async def run_once(self) -> int:
        """Dispatch one committed batch and return its success count."""
        selected_broker = await self._selected_broker()
        async with SessionLocal() as db:
            return await dispatch_pending(
                db,
                limit=self.config.batch_size,
                max_attempts=self.config.max_attempts,
                lock_seconds=self.config.lock_seconds,
                worker_id=self.config.worker_id,
                event_broker=selected_broker,
            )

    async def run(self) -> None:
        """Run polling loop until ``request_stop`` or process interruption."""
        try:
            while not self._stop_event.is_set():
                try:
                    dispatched = await self.run_once()
                    if dispatched:
                        LOGGER.info("outbox worker=%s dispatched=%d", self.config.worker_id, dispatched)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("outbox worker poll failed; continuing")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.poll_interval)
                except asyncio.TimeoutError:
                    continue
        finally:
            await self.aclose()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch committed HPC catalog Outbox events")
    parser.add_argument("--once", action="store_true", help="dispatch one batch and exit")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--lock-seconds", type=int, default=30)
    parser.add_argument("--worker-id", default="")
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    config = WorkerConfig(
        poll_interval=args.poll_interval,
        batch_size=args.batch_size,
        max_attempts=args.max_attempts,
        lock_seconds=args.lock_seconds,
        worker_id=args.worker_id,
    ).normalized()
    worker = EventWorker(config)
    if args.once:
        try:
            await worker.run_once()
        finally:
            await worker.aclose()
        return 0
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.request_stop)
        except (NotImplementedError, RuntimeError):
            LOGGER.debug("signal handler unavailable for %s", signum)
    await worker.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ``python -m app.tasks.event_worker``."""
    logging.basicConfig(level=os.getenv("HPC_LOG_LEVEL", "INFO"))
    try:
        return asyncio.run(_async_main(_parse_args(argv)))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
