"""Durable Outbox dispatch and cross-process event brokers."""
import asyncio
import json
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent

LOGGER = logging.getLogger(__name__)


class EventBroker(Protocol):
    async def publish(self, event: dict, event_id: str | None = None) -> dict: ...

    async def subscribe(self, last_event_id: str | None = None) -> AsyncIterator[dict]: ...


class MemoryEventBroker:
    """Process-local broker used as SQLite/dev fallback with replay history."""

    def __init__(self, history_size: int = 256) -> None:
        self._history: deque[dict] = deque(maxlen=history_size)
        self._queues: set[asyncio.Queue[dict]] = set()
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._published_by_id: dict[str, dict] = {}

    async def publish(self, event: dict, event_id: str | None = None) -> dict:
        async with self._lock:
            if event_id and event_id in self._published_by_id:
                return self._published_by_id[event_id]
            self._sequence += 1
            message = {"id": event_id or str(self._sequence), **event}
            self._history.append(message)
            self._published_by_id[message["id"]] = message
            queues = list(self._queues)
        for queue in queues:
            await queue.put(message)
        return message

    async def subscribe(self, last_event_id: str | None = None) -> AsyncIterator[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        try:
            async with self._lock:
                history = list(self._history)
                if last_event_id and any(item["id"] == last_event_id for item in history):
                    index = next(i for i, item in enumerate(history) if item["id"] == last_event_id)
                    replay = history[index + 1:]
                else:
                    replay = history
                self._queues.add(queue)
            for item in replay:
                yield item
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._queues.discard(queue)

    async def close(self) -> None:
        """No-op: the memory broker holds no external resources."""
        return None


class RedisEventBroker:
    """Redis Pub/Sub broker with a bounded replay list and publish dedupe."""

    def __init__(
        self,
        redis_url: str,
        channel: str = "hpc:catalog:events",
        history_size: int = 256,
        dedupe_ttl_seconds: int = 86400,
    ) -> None:
        self.redis_url = redis_url
        self.channel = channel
        self.history_key = f"{channel}:history"
        self.dedupe_prefix = f"{channel}:dedupe:"
        self.history_size = history_size
        self.dedupe_ttl_seconds = dedupe_ttl_seconds
        self._redis: Any | None = None
        # Guards the first ``_client`` call so concurrent callers share one
        # client instead of leaking one connection each (see ``_client``).
        self._lock = asyncio.Lock()

    async def _connect(self) -> Any:
        """Connect a usable Redis client, falling back from RESP3 to RESP2.

        Redis <= 5 rejects the RESP3 ``HELLO`` handshake that redis-py issues
        during connect, so a second attempt is made with an explicit RESP2
        protocol. The fallback client is validated with ``PING`` before being
        returned; if both attempts fail the error propagates so ``create_broker``
        can degrade to the memory broker instead of caching a dead client.
        """
        from redis.asyncio import Redis

        client = Redis.from_url(self.redis_url, decode_responses=True)
        try:
            await client.ping()
            return client
        except Exception:
            await self._quiet_close(client)

        fallback = Redis.from_url(self.redis_url, decode_responses=True, protocol=2)
        try:
            await fallback.ping()
            return fallback
        except Exception:
            await self._quiet_close(fallback)
            raise

    async def _client(self) -> Any:
        """Return the single shared client, connecting at most once.

        The double-checked ``asyncio.Lock`` makes the first connection
        race-free: without it, N concurrent first callers each built their own
        client and leaked N-1 connections.
        """
        if self._redis is None:
            async with self._lock:
                if self._redis is None:
                    self._redis = await self._connect()
        return self._redis

    @staticmethod
    async def _quiet_close(client: Any) -> None:
        """Close a client without masking the original connection error."""
        try:
            await client.aclose()
        except Exception:
            try:
                await client.close()
            except Exception:
                pass

    async def publish(self, event: dict, event_id: str | None = None) -> dict:
        message = {"id": event_id or str(uuid.uuid4()), **event}
        client = await self._client()
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        if event_id:
            inserted = await client.set(
                self.dedupe_prefix + event_id, encoded, nx=True, ex=self.dedupe_ttl_seconds
            )
            if not inserted:
                previous = await client.get(self.dedupe_prefix + event_id)
                return json.loads(previous) if previous else message
        await client.rpush(self.history_key, encoded)
        await client.ltrim(self.history_key, -self.history_size, -1)
        await client.publish(self.channel, encoded)
        return message

    async def subscribe(self, last_event_id: str | None = None) -> AsyncIterator[dict]:
        client = await self._client()
        history_raw = await client.lrange(self.history_key, 0, -1)
        history = [json.loads(item) for item in history_raw]
        if last_event_id and any(item.get("id") == last_event_id for item in history):
            index = next(i for i, item in enumerate(history) if item.get("id") == last_event_id)
            replay = history[index + 1:]
        else:
            replay = history
        pubsub = client.pubsub()
        await pubsub.subscribe(self.channel)
        try:
            for item in replay:
                yield item
            async for raw in pubsub.listen():
                if raw.get("type") == "message":
                    yield json.loads(raw["data"])
        finally:
            await pubsub.unsubscribe(self.channel)
            await pubsub.close()

    async def close(self) -> None:
        """Close the cached connection, if one was ever established."""
        if self._redis is not None:
            await self._quiet_close(self._redis)
            self._redis = None


#: Process-local fallback broker. It is a single shared instance so that in
#: single-process/dev mode a publish reaches an in-process subscriber. It must
#: NEVER be used as an implicit default for a real call path: both the SSE
#: subscriber and ``dispatch_pending`` resolve the broker through
#: ``get_broker()``/``create_broker()``, which returns this instance only when
#: no Redis endpoint is configured (keeping publish/subscribe on one broker).
broker: EventBroker = MemoryEventBroker()

#: Cached result of the config-driven broker resolution (see ``get_broker``).
_broker_cache: EventBroker | None = None
_broker_lock = asyncio.Lock()


def reset_broker_cache() -> None:
    """Drop the cached broker so the next ``get_broker`` re-resolves config.

    Used by tests to make broker selection deterministic, and available to any
    caller that changes ``HPC_REDIS_URL`` / ``REDIS_URL`` at runtime.
    """
    global _broker_cache
    _broker_cache = None


async def get_broker() -> EventBroker:
    """Return the process broker, resolved once from configuration.

    The SSE endpoint and the Outbox worker must resolve the *same* broker
    implementation, otherwise a publish in the worker process never reaches a
    subscriber in the API process. ``create_broker`` honours ``HPC_REDIS_URL`` /
    ``REDIS_URL`` and degrades to the in-process ``MemoryEventBroker`` when
    neither is configured (single-process / local development).
    """
    global _broker_cache
    if _broker_cache is None:
        async with _broker_lock:
            if _broker_cache is None:
                _broker_cache = await create_broker()
    return _broker_cache


async def create_broker(redis_url: str | None = None) -> EventBroker:
    """Create Redis broker when configured; fall back to memory with warning.

    ``_client()`` already validates the connection (RESP3, then a RESP2 retry)
    with ``PING``; any failure here — including an endpoint that is genuinely
    unreachable — degrades to the memory broker instead of returning a client
    that would only fail later on publish.
    """
    url = redis_url or os.getenv("HPC_REDIS_URL") or os.getenv("REDIS_URL")
    if not url:
        return broker
    # ``HPC_REDIS_CHANNEL`` lets deployments/tests isolate the pub/sub channel;
    # it defaults to the production channel so behaviour is unchanged.
    channel = os.getenv("HPC_REDIS_CHANNEL", "hpc:catalog:events")
    candidate = RedisEventBroker(url, channel=channel)
    try:
        await candidate._client()
        return candidate
    except Exception as exc:
        LOGGER.warning("redis broker unavailable; using memory fallback: %s", exc)
        if candidate._redis is not None:
            await candidate._quiet_close(candidate._redis)
        return broker


async def enqueue_publish_event(db: AsyncSession, version_id: str, version_no: int, published_at: datetime) -> OutboxEvent:
    event = OutboxEvent(
        event_type="data_version.published", aggregate_type="data_version", aggregate_id=version_id,
        payload={"dataVersionId": version_id, "versionNo": version_no, "publishedAt": published_at.isoformat() + "Z"},
    )
    db.add(event)
    await db.flush()
    return event


async def dispatch_pending(db: AsyncSession, limit: int = 100, max_attempts: int = 5, lock_seconds: int = 30, worker_id: str | None = None, event_broker: EventBroker | None = None) -> int:
    """Claim committed events, dispatch safely, and release/complete claims.

    PostgreSQL uses ``FOR UPDATE SKIP LOCKED``; SQLite uses committed lock
    columns and expiry as a portable single-worker fallback.
    """
    # Resolve the *same* config-driven broker the SSE subscriber uses. Falling
    # back to the process-local ``MemoryEventBroker`` here would publish events
    # to a broker nobody is subscribed to (the subscriber is on Redis) while
    # still marking them dispatched -> silent, permanent event loss.
    selected_broker = event_broker or await get_broker()
    token = worker_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    query = select(OutboxEvent).where(
        OutboxEvent.status == "pending",
        or_(OutboxEvent.locked_by.is_(None), OutboxEvent.locked_until.is_(None), OutboxEvent.locked_until < now),
    ).order_by(OutboxEvent.created_at).limit(limit)
    if dialect == "postgresql":
        query = query.with_for_update(skip_locked=True)
    rows = (await db.execute(query)).scalars().all()
    locked_until = now + timedelta(seconds=lock_seconds)
    for event in rows:
        event.locked_by = token
        event.locked_until = locked_until
    await db.commit()
    dispatched = 0
    for event in rows:
        try:
            await selected_broker.publish({"type": event.event_type, "data": event.payload}, event_id=event.id)
            event.attempts += 1
            event.status = "dispatched"
            event.dispatched_at = datetime.now(timezone.utc).replace(tzinfo=None)
            event.locked_by = None
            event.locked_until = None
            dispatched += 1
        except Exception as exc:
            LOGGER.warning("outbox event dispatch failed id=%s attempt=%s: %s", event.id, event.attempts + 1, exc)
            event.attempts += 1
            event.status = "failed" if event.attempts >= max_attempts else "pending"
            event.locked_by = None
            event.locked_until = None
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return dispatched


def sse_message(event: dict) -> str:
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event['data'], separators=(',', ':'))}\n\n"
