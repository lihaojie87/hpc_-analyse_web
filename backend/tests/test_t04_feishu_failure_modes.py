"""T04 gap round-2 #1: Feishu adapter failure branches.

Pins the failure handling implemented in ``app/adapters/feishu.py``
(``FeishuAdapter._get`` lines 17-33 and ``fetch_snapshot`` line 60-61) that the
existing suites do not exercise:

* a ``httpx.TimeoutException`` / ``httpx.TransportError`` is retried and, once
  the budget is exhausted, surfaces as ``ValueError("SOURCE_TIMEOUT")``;
* HTTP ``401`` -> ``ValueError("SOURCE_AUTH_FAILED")`` (single attempt, no retry);
* HTTP ``403`` -> ``ValueError("SOURCE_FORBIDDEN")`` (single attempt, no retry);
* ``fetch_snapshot`` without a ``workbook_token`` -> ``ValueError("SOURCE_SCHEMA_CHANGED")``
  and **no HTTP call is issued**;
* the backoff schedule is exactly ``2 ** attempt`` (no base, no cap, no floor)
  and the ``Retry-After`` response header is **never** consulted.

Everything is offline and deterministic: a fake ``httpx.AsyncClient`` replays a
canned script and a fake ``asyncio.sleep`` records requested delays, so the
attempt count and backoff schedule are asserted exactly.

IMPORTANT (implementation convention, pinned *not* fixed here):
``app/adapters/feishu.py`` implements ``await asyncio.sleep(2 ** attempt)``
with no base/cap/min, and ``grep -ri retry-after app/`` matches **nothing** --
the standard ``Retry-After`` header is not honoured anywhere in the request
path.  ``架构设计-T04.md`` only mandates "指数退避和最大次数", so this is the
accepted convention rather than a defect.  ``test_backoff_is_power_of_two_and_ignores_retry_after``
deliberately pins that behaviour: **if ``Retry-After`` is ever implemented,
this test must be updated in the same change.**
"""

from types import SimpleNamespace

import httpx
import pytest

import app.adapters.feishu as feishu_module
from app.adapters.feishu import FeishuAdapter
from app.db.models import DataSource


class _FakeResponse:
    """Minimal stand-in for ``httpx.Response`` covering the adapter's usage."""

    def __init__(self, status_code: int, payload: dict | None = None, headers=None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://open.feishu.cn/")
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


def _fake_client_factory(script, calls):
    """Build a fake ``httpx.AsyncClient`` replaying ``script`` in order.

    Each script item is either a ``_FakeResponse`` or an exception *instance*
    that the fake ``get`` raises (used for the timeout/transport branches).
    """

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, path, params=None, headers=None):
            calls.append({"path": path, "params": params, "headers": headers})
            # Clamp to the final script item so an unexpected extra attempt is
            # still observable via ``len(calls)`` instead of raising IndexError.
            index = min(len(calls) - 1, len(script) - 1)
            action = script[index]
            if isinstance(action, BaseException):
                raise action
            return action

    return _FakeAsyncClient


def _install(monkeypatch, script):
    """Patch the adapter's HTTP client + sleep; return (calls, delays) recorders."""
    calls: list[dict] = []
    delays: list[float] = []

    async def _sleep(seconds):
        delays.append(seconds)

    # Shadow the module-level ``asyncio`` so only the adapter's ``asyncio.sleep``
    # is stubbed; the real event loop is untouched.
    monkeypatch.setattr(
        feishu_module, "asyncio", SimpleNamespace(sleep=_sleep)
    )
    monkeypatch.setattr(
        feishu_module.httpx,
        "AsyncClient",
        _fake_client_factory(script, calls),
    )
    return calls, delays


@pytest.mark.asyncio
async def test_timeout_retries_with_exponential_backoff_then_raises_source_timeout(monkeypatch):
    """Persistent timeout -> ``max_retries + 1`` attempts, delays 2**0, 2**1, then SOURCE_TIMEOUT."""
    script = [
        httpx.TimeoutException("attempt-0 timed out"),
        httpx.TimeoutException("attempt-1 timed out"),
        httpx.TimeoutException("attempt-2 timed out"),
        httpx.TimeoutException("attempt-3 timed out"),  # never reached (budget=2)
    ]
    calls, delays = _install(monkeypatch, script)
    adapter = FeishuAdapter(token="opaque", max_retries=2)

    with pytest.raises(ValueError) as error:
        await adapter._get("/open-apis/drive/v1/files")

    assert str(error.value) == "SOURCE_TIMEOUT"
    assert len(calls) == 3  # attempts 0,1,2 == max_retries + 1
    assert delays == [1, 2]  # 2**0, 2**1; final attempt never sleeps


@pytest.mark.asyncio
async def test_transient_timeout_then_success_retries_once(monkeypatch):
    """A single timeout followed by a 200 succeeds after one ``2**0`` backoff."""
    script = [
        httpx.TimeoutException("attempt-0 timed out"),
        _FakeResponse(200, {"ok": True}),
    ]
    calls, delays = _install(monkeypatch, script)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    data = await adapter._get("/open-apis/sheets/v2/spreadsheets/book/values/sheet")

    assert data == {"ok": True}
    assert len(calls) == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_transport_error_is_retried_like_timeout(monkeypatch):
    """``httpx.TransportError`` shares the timeout retry path."""
    script = [
        httpx.ConnectError("connection refused"),
        httpx.ConnectError("connection refused"),
        httpx.ConnectError("connection refused"),  # never reached (budget=1)
    ]
    calls, delays = _install(monkeypatch, script)
    adapter = FeishuAdapter(token="opaque", max_retries=1)

    with pytest.raises(ValueError) as error:
        await adapter._get("/open-apis/drive/v1/files")

    assert str(error.value) == "SOURCE_TIMEOUT"
    assert len(calls) == 2  # attempts 0,1 == max_retries + 1
    assert delays == [1]


@pytest.mark.asyncio
async def test_status_401_raises_source_auth_failed_without_retry(monkeypatch):
    """A 401 is terminal: one attempt, no backoff, ``SOURCE_AUTH_FAILED``."""
    script = [_FakeResponse(401), _FakeResponse(200, {"ok": True})]
    calls, delays = _install(monkeypatch, script)
    adapter = FeishuAdapter(token="expired", max_retries=3)

    with pytest.raises(ValueError) as error:
        await adapter._get("/open-apis/drive/v1/files")

    assert str(error.value) == "SOURCE_AUTH_FAILED"
    assert len(calls) == 1  # 401 is not in the retryable set
    assert delays == []


@pytest.mark.asyncio
async def test_status_403_raises_source_forbidden_without_retry(monkeypatch):
    """A 403 is terminal: one attempt, no backoff, ``SOURCE_FORBIDDEN``."""
    script = [_FakeResponse(403), _FakeResponse(200, {"ok": True})]
    calls, delays = _install(monkeypatch, script)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    with pytest.raises(ValueError) as error:
        await adapter._get("/open-apis/drive/v1/files")

    assert str(error.value) == "SOURCE_FORBIDDEN"
    assert len(calls) == 1
    assert delays == []


@pytest.mark.asyncio
async def test_fetch_snapshot_without_workbook_token_raises_source_schema_changed(monkeypatch):
    """``fetch_snapshot`` guards a missing ``workbook_token`` before any HTTP call."""
    calls, delays = _install(monkeypatch, [_FakeResponse(200, {"ok": True})])
    adapter = FeishuAdapter(token="opaque")
    source = DataSource(code="schema-changed-source", credential_ref="secret/ref")

    with pytest.raises(ValueError) as error:
        await adapter.fetch_snapshot(source, "sheet-1")

    assert str(error.value) == "SOURCE_SCHEMA_CHANGED"
    assert calls == []  # the guard fires before the workbook is ever requested
    assert delays == []


@pytest.mark.asyncio
async def test_backoff_is_power_of_two_and_ignores_retry_after(monkeypatch):
    """Pin the current backoff: strictly ``2**attempt`` and blind to ``Retry-After``.

    With ``max_retries=3`` and a persistent 429 whose every response carries
    ``Retry-After: 120``, the adapter still sleeps exactly ``[1, 2, 4]``
    (``2**0, 2**1, 2**2``) and never the header value.  This asserts the
    *observed* convention -- the header is not read anywhere in ``app/`` --
    rather than an aspiration.

    NOTE: if ``Retry-After`` is ever implemented, this test MUST be updated
    (its expectations encode "header ignored"), otherwise it will fail loudly
    and correctly.
    """
    script = [
        _FakeResponse(429, headers={"Retry-After": "120"}),
        _FakeResponse(429, headers={"Retry-After": "120"}),
        _FakeResponse(429, headers={"Retry-After": "120"}),
        _FakeResponse(429, headers={"Retry-After": "120"}),
    ]
    calls, delays = _install(monkeypatch, script)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    with pytest.raises(ValueError) as error:
        await adapter._get("/open-apis/drive/v1/files")

    assert str(error.value) == "SOURCE_RATE_LIMITED"
    assert len(calls) == 4  # attempts 0..3 == max_retries + 1
    assert delays == [1, 2, 4]  # exactly 2**0, 2**1, 2**2 -- no base/cap/min
    assert delays == [2 ** i for i in range(len(delays))]  # strictly powers of two
    assert 120 not in delays  # Retry-After is not consulted
