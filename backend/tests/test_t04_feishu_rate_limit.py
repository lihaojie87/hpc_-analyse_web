"""T04 coverage gap #6: Feishu adapter 429 backoff / ``Retry-After`` behaviour.

Pins the rate-limit contract implemented in ``app/adapters/feishu.py``
(``FeishuAdapter._get``, roughly lines 17-33):

* retryable statuses ``{429, 500, 502, 503, 504}`` are retried up to
  ``max_retries`` times, with a **deterministic** delay of ``2 ** attempt``
  seconds between attempts;
* the retry budget yields at most ``max_retries + 1`` HTTP attempts;
* a 429 on the *last* allowed attempt is never retried -- it raises
  ``ValueError("SOURCE_RATE_LIMITED")``;
* when the budget is exhausted after a 429 the adapter raises the same
  ``SOURCE_RATE_LIMITED`` error and stops.

None of the tests touch the network or wall-clock time: a fake ``httpx.AsyncClient``
serves canned responses and a fake ``sleep`` records the requested delays, so the
retry count and backoff schedule are asserted exactly.

NOTE (doc/impl discrepancy, reported to team-lead, *not* fixed here):
``Retry-After`` is **not** consulted by the implementation -- the delay is always
``2 ** attempt`` regardless of the header.  ``架构设计-T04.md`` only mandates
"指数退避和最大次数", so this is treated as the implementation convention rather
than a defect; the header-present case is nevertheless asserted so the observed
behaviour is pinned.  See ``outputs/t04-coverage-gap-tests.md``.
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
        # Mirrors httpx: non-success, non-special statuses surface as
        # HTTPStatusError which the adapter does NOT catch -> no retry.
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://open.feishu.cn/")
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


def _fake_client_factory(responses, calls):
    """Build a fake ``httpx.AsyncClient`` class serving ``responses`` in order."""

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
            # Clamp to the final response so an unexpected extra attempt is
            # still observable through ``len(calls)`` rather than raising IndexError.
            index = min(len(calls) - 1, len(responses) - 1)
            return responses[index]

    return _FakeAsyncClient


def _make_sleep(recorder):
    async def _sleep(seconds):
        recorder.append(seconds)

    return _sleep


def _install(monkeypatch, responses):
    """Patch the adapter's HTTP client + sleep; return (calls, delays) recorders."""
    calls: list[dict] = []
    delays: list[float] = []
    # Shadow the adapter module's ``asyncio`` attribute so only the adapter's
    # ``asyncio.sleep`` is stubbed -- the global event loop is untouched.
    monkeypatch.setattr(
        feishu_module, "asyncio", SimpleNamespace(sleep=_make_sleep(delays))
    )
    monkeypatch.setattr(
        feishu_module.httpx,
        "AsyncClient",
        _fake_client_factory(responses, calls),
    )
    return calls, delays


@pytest.mark.asyncio
async def test_429_retries_with_exponential_backoff_then_succeeds(monkeypatch):
    """Two 429s then a 200 -> sleeps of exactly 2**0 then 2**1 seconds."""
    responses = [
        _FakeResponse(429),
        _FakeResponse(429),
        _FakeResponse(200, {"ok": True}),
    ]
    calls, delays = _install(monkeypatch, responses)
    adapter = FeishuAdapter(
        base_url="https://open.feishu.cn", token="opaque", max_retries=3
    )

    data = await adapter._get("/open-apis/sheets/v2/spreadsheets/book/values/sheet")

    assert data == {"ok": True}
    assert len(calls) == 3
    assert delays == [1, 2]  # 2**0, 2**1
    # The bearer token is attached to every attempt and never leaked elsewhere.
    assert all(call["headers"] == {"Authorization": "Bearer opaque"} for call in calls)


@pytest.mark.asyncio
async def test_429_retry_after_header_is_not_consulted(monkeypatch):
    """A present ``Retry-After`` does not change the deterministic ``2**attempt`` delay.

    Documents the implementation convention: the header is ignored.  Kept as a
    passing assertion (not weakened) so a future change to honour ``Retry-After``
    would force this test to be revisited.
    """
    responses = [
        _FakeResponse(429, headers={"Retry-After": "120"}),
        _FakeResponse(200, {"ok": True}),
    ]
    calls, delays = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    data = await adapter._get("/open-apis/drive/v1/files")

    assert data == {"ok": True}
    assert len(calls) == 2
    assert delays == [1]  # 2**0, independent of Retry-After: 120


@pytest.mark.asyncio
async def test_429_exhausts_retry_budget_and_stops_with_rate_limited(monkeypatch):
    """Persistent 429 -> ``max_retries + 1`` attempts, then SOURCE_RATE_LIMITED.

    With ``max_retries=2`` there are exactly 3 HTTP attempts (0,1,2).  The last
    attempt (attempt == max_retries) is *not* retried, so only 2 sleeps occur.
    """
    responses = [_FakeResponse(429) for _ in range(5)]  # more than the budget
    calls, delays = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=2)

    with pytest.raises(ValueError) as error:
        await adapter._get("/open-apis/drive/v1/files")

    assert str(error.value) == "SOURCE_RATE_LIMITED"
    assert len(calls) == 3  # attempts 0,1,2 == max_retries + 1
    assert delays == [1, 2]  # 2**0, 2**1; the final attempt is never slept


@pytest.mark.asyncio
async def test_429_with_zero_retry_budget_raises_without_sleeping(monkeypatch):
    """``max_retries=0`` -> a single attempt, no backoff, immediate SOURCE_RATE_LIMITED."""
    responses = [_FakeResponse(429)]
    calls, delays = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=0)

    with pytest.raises(ValueError) as error:
        await adapter._get("/open-apis/drive/v1/files")

    assert str(error.value) == "SOURCE_RATE_LIMITED"
    assert len(calls) == 1
    assert delays == []


@pytest.mark.asyncio
async def test_first_attempt_success_makes_single_call_and_no_sleep(monkeypatch):
    """A healthy first response is returned directly: one call, zero retries."""
    responses = [_FakeResponse(200, {"data": {"files": []}})]
    calls, delays = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=3)
    source = DataSource(code="rl-source", credential_ref="secret/ref")

    files = await adapter.discover_workbooks(source)

    assert files == []
    assert len(calls) == 1
    assert delays == []


@pytest.mark.asyncio
async def test_500_is_retried_like_429(monkeypatch):
    """The retryable set includes 5xx: a 500 then 200 retries once (2**0)."""
    responses = [_FakeResponse(500), _FakeResponse(200, {"ok": True})]
    calls, delays = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    data = await adapter._get("/open-apis/drive/v1/files")

    assert data == {"ok": True}
    assert len(calls) == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_non_retryable_status_is_not_retried(monkeypatch):
    """A 400 is not in the retryable set: one attempt, no backoff, error raised.

    This proves the earlier retry assertions are non-trivial -- retries happen
    *only* for the {429, 5xx} set, not for every error status.
    """
    responses = [_FakeResponse(400)]
    calls, delays = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    with pytest.raises(httpx.HTTPStatusError):
        await adapter._get("/open-apis/drive/v1/files")

    assert len(calls) == 1
    assert delays == []


# ----------------------------------------------------------------------
# Feishu Base (bitable) read capability.  T04 follow-up: extend the
# adapter with pure-client, testable methods that read a Base table's
# fields and (one page of) records, with explicit app_token/table_id/token
# and fail-closed behaviour when no token is available.  No network is
# touched; a fake ``httpx.AsyncClient`` serves canned payloads.
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_bitable_fields_lists_items_with_explicit_token(monkeypatch):
    """list_bitable_fields hits the fields endpoint and returns its items."""
    payload = {"code": 0, "data": {"items": [{"field_id": "f1", "name": "col1"}]}}
    responses = [_FakeResponse(200, payload)]
    calls, _ = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="instance-token", max_retries=3)

    fields = await adapter.list_bitable_fields("app_tok", "tbl_1", token="explicit-token")

    assert fields == [{"field_id": "f1", "name": "col1"}]
    assert len(calls) == 1
    assert calls[0]["path"] == "/open-apis/bitable/v1/apps/app_tok/tables/tbl_1/fields"
    assert calls[0]["params"] == {"page_size": 500}
    # The explicit argument token wins over the instance token.
    assert calls[0]["headers"] == {"Authorization": "Bearer explicit-token"}


@pytest.mark.asyncio
async def test_list_bitable_fields_falls_back_to_instance_token(monkeypatch):
    """Without an explicit token the instance token is used for auth."""
    payload = {"code": 0, "data": {"items": []}}
    responses = [_FakeResponse(200, payload)]
    calls, _ = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="instance-token", max_retries=3)

    fields = await adapter.list_bitable_fields("app_tok", "tbl_1")

    assert fields == []
    assert calls[0]["headers"] == {"Authorization": "Bearer instance-token"}


@pytest.mark.asyncio
async def test_read_bitable_records_first_page_returns_paging_shape(monkeypatch):
    """read_bitable_records normalises the records payload into a paging dict."""
    payload = {
        "code": 0,
        "data": {
            "items": [{"record_id": "r1", "fields": {"a": 1}}],
            "has_more": True,
            "page_token": "next-cursor",
        },
    }
    responses = [_FakeResponse(200, payload)]
    calls, _ = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    result = await adapter.read_bitable_records("app_tok", "tbl_1")

    assert result == {
        "records": [{"record_id": "r1", "fields": {"a": 1}}],
        "has_more": True,
        "page_token": "next-cursor",
    }
    assert calls[0]["path"] == "/open-apis/bitable/v1/apps/app_tok/tables/tbl_1/records"
    assert calls[0]["params"] == {"page_size": 100}


@pytest.mark.asyncio
async def test_read_bitable_records_second_page_passes_page_token(monkeypatch):
    """A non-None page_token is forwarded so callers can page through a Base."""
    payload = {"code": 0, "data": {"items": [], "has_more": False, "page_token": None}}
    responses = [_FakeResponse(200, payload)]
    calls, _ = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    result = await adapter.read_bitable_records("app_tok", "tbl_1", page_token="cursor-2")

    assert result["has_more"] is False
    assert calls[0]["params"] == {"page_size": 100, "page_token": "cursor-2"}


@pytest.mark.asyncio
async def test_read_bitable_records_clamps_page_size_to_feishu_cap(monkeypatch):
    """page_size is clamped into the valid [1, 500] range before the request."""
    responses = [_FakeResponse(200, {"data": {"items": []}})]
    calls, _ = _install(monkeypatch, responses)
    adapter = FeishuAdapter(token="opaque", max_retries=3)

    await adapter.read_bitable_records("app_tok", "tbl_1", page_size=9999)

    assert calls[0]["params"] == {"page_size": 500}


@pytest.mark.asyncio
async def test_bitable_methods_fail_closed_without_any_token(monkeypatch):
    """No token anywhere => SOURCE_AUTH_FAILED and *no* anonymous HTTP request.

    This is the fail-closed guarantee: the adapter must never hit the Feishu
    API unauthenticated.  The absence of any recorded call proves the request
    short-circuits before the HTTP layer.
    """
    responses = [_FakeResponse(200, {"data": {"items": []}})]
    calls, _ = _install(monkeypatch, responses)
    adapter = FeishuAdapter(max_retries=3)  # instance token is None

    for method in (
        adapter.list_bitable_fields("app_tok", "tbl_1"),
        adapter.read_bitable_records("app_tok", "tbl_1"),
    ):
        with pytest.raises(ValueError) as error:
            await method
        assert str(error.value) == "SOURCE_AUTH_FAILED"

    assert calls == []  # neither call ever reached the network
