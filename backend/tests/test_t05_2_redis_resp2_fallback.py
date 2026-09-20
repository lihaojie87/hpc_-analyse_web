"""RESP2 fallback coverage for RedisEventBroker (no real Redis required).

Redis <= 5 rejects the RESP3 ``HELLO`` handshake that redis-py issues on
connect. These tests inject fake clients so the fallback, the degradation path,
and the "never cache an unverified client" guarantee are all exercised in
offline CI.
"""
from __future__ import annotations

import logging

import pytest

from app.services.event_service import MemoryEventBroker, RedisEventBroker, create_broker


class FakeRedisClient:
    """Minimal async Redis stand-in whose ``PING`` outcome is configurable."""

    def __init__(self, protocol: int, ping_ok: bool) -> None:
        self.protocol = protocol
        self.ping_ok = ping_ok
        self.ping_calls = 0
        self.closed = False

    async def ping(self) -> bool:
        self.ping_calls += 1
        if not self.ping_ok:
            raise RuntimeError("unknown command `HELLO`, with args beginning with: `3`")
        return True

    async def aclose(self) -> None:
        self.closed = True

    async def close(self) -> None:
        self.closed = True


def install_fake_redis(monkeypatch, *, resp3_ok: bool, resp2_ok: bool) -> list[FakeRedisClient]:
    """Patch ``Redis.from_url`` to return controllable fake clients."""
    created: list[FakeRedisClient] = []

    def from_url(url: str, **kwargs):
        protocol = int(kwargs.get("protocol", 3))
        ok = resp3_ok if protocol != 2 else resp2_ok
        client = FakeRedisClient(protocol=protocol, ping_ok=ok)
        created.append(client)
        return client

    monkeypatch.setattr("redis.asyncio.Redis.from_url", from_url)
    return created


@pytest.mark.asyncio
async def test_client_falls_back_to_resp2_when_hello_unsupported(monkeypatch):
    created = install_fake_redis(monkeypatch, resp3_ok=False, resp2_ok=True)
    broker = RedisEventBroker("redis://127.0.0.1:56379/0")

    client = await broker._client()

    assert client is created[1]
    assert client.protocol == 2
    assert created[0].protocol == 3
    assert created[0].closed is True, "the failed RESP3 client must be closed"
    assert broker._redis is client


@pytest.mark.asyncio
async def test_client_is_validated_and_cached_once(monkeypatch):
    created = install_fake_redis(monkeypatch, resp3_ok=False, resp2_ok=True)
    broker = RedisEventBroker("redis://127.0.0.1:56379/0")

    first = await broker._client()
    second = await broker._client()

    assert first is second
    assert len(created) == 2, "only the RESP3 attempt and the RESP2 retry are created"
    assert first.ping_calls == 1, "the cached client is reused without reconnecting"


@pytest.mark.asyncio
async def test_create_broker_returns_redis_broker_on_resp2_fallback(monkeypatch):
    created = install_fake_redis(monkeypatch, resp3_ok=False, resp2_ok=True)

    broker = await create_broker("redis://127.0.0.1:56379/0")

    assert isinstance(broker, RedisEventBroker)
    assert broker._redis is created[1]


@pytest.mark.asyncio
async def test_client_raises_when_both_protocols_fail(monkeypatch):
    created = install_fake_redis(monkeypatch, resp3_ok=False, resp2_ok=False)
    broker = RedisEventBroker("redis://127.0.0.1:6390/0")

    with pytest.raises(RuntimeError):
        await broker._client()

    assert broker._redis is None, "an unverified client must never be cached"
    assert all(client.closed for client in created), "both failed clients must be closed"


@pytest.mark.asyncio
async def test_create_broker_degrades_when_truly_unavailable(monkeypatch, caplog):
    install_fake_redis(monkeypatch, resp3_ok=False, resp2_ok=False)

    with caplog.at_level(logging.WARNING, logger="app.services.event_service"):
        broker = await create_broker("redis://127.0.0.1:6390/0")

    assert isinstance(broker, MemoryEventBroker)
    assert any("memory fallback" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_create_broker_without_url_uses_memory(monkeypatch):
    monkeypatch.delenv("HPC_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    broker = await create_broker()

    assert isinstance(broker, MemoryEventBroker)


@pytest.mark.asyncio
async def test_create_broker_returns_redis_broker_when_resp3_supported(monkeypatch):
    created = install_fake_redis(monkeypatch, resp3_ok=True, resp2_ok=True)

    broker = await create_broker("redis://127.0.0.1:6379/0")

    assert isinstance(broker, RedisEventBroker)
    assert len(created) == 1, "a working RESP3 connection must not trigger a retry"
    assert created[0].protocol == 3
