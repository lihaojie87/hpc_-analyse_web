"""Read-only preview layer for Feishu Base (bitable) sources.

Covers the four required behaviours:

* ``/base/{app_token}`` URL parsing (valid + invalid);
* bounded, page-capped record pagination through the existing adapter;
* fail-closed when no explicit token is supplied;
* stable-key (record_id) detection in both the *present* and *missing* cases,
  plus the *missing mapping* block.

Everything is offline and deterministic: a fake ``httpx.AsyncClient`` replays
a canned script so no network call is made and the adapter's HTTP path is
exercised exactly as in production.  The suite also asserts that every
recorded call is a read against the bitable endpoints -- i.e. the layer never
writes to the Feishu Base, never touches a database, and never calls an import
route.  The module under test deliberately imports *no* DB session, so there is
nothing to stub there.
"""

from types import SimpleNamespace

import httpx
import pytest

import app.adapters.feishu as feishu_module
from app.services.feishu_bitable_preview import (
    AUTH_FAILED,
    INVALID_URL,
    MISSING_MAPPING,
    MISSING_STABLE_KEY,
    BitablePreviewRequest,
    FeishuBitablePreviewService,
    parse_base_url,
)


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
    """Replay ``script`` (list of ``_FakeResponse``) in order, recording calls."""

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
            index = min(len(calls) - 1, len(script) - 1)
            return script[index]

    return _FakeAsyncClient


def _install(monkeypatch, script):
    """Patch the adapter's HTTP client + sleep; return (calls, delays) recorders."""
    calls: list[dict] = []
    delays: list[float] = []

    async def _sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(feishu_module, "asyncio", SimpleNamespace(sleep=_sleep))
    monkeypatch.setattr(
        feishu_module.httpx,
        "AsyncClient",
        _fake_client_factory(script, calls),
    )
    return calls, delays


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def test_parse_base_url_extracts_app_token_and_table_id():
    parsed = parse_base_url("https://bytedance.feishu.cn/base/APP123?table=tblXYZ&view=viw1")
    assert parsed == {"app_token": "APP123", "table_id": "tblXYZ"}


def test_parse_base_url_without_table_returns_none_table_id():
    parsed = parse_base_url("https://www.feishu.cn/base/APP999")
    assert parsed == {"app_token": "APP999", "table_id": None}


def test_parse_base_url_rejects_non_base_url():
    with pytest.raises(ValueError) as error:
        parse_base_url("https://feishu.cn/sheets/ABC")
    assert str(error.value) == INVALID_URL


def test_parse_base_url_rejects_empty_token():
    with pytest.raises(ValueError) as error:
        parse_base_url("https://feishu.cn/base/")
    assert str(error.value) == INVALID_URL


def test_parse_base_url_rejects_blank_input():
    with pytest.raises(ValueError) as error:
        parse_base_url("")
    assert str(error.value) == INVALID_URL


# ---------------------------------------------------------------------------
# No token -> fail closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preview_without_token_fails_closed(monkeypatch):
    """A missing explicit token must raise SOURCE_AUTH_FAILED and read nothing."""
    # No HTTP patch installed on purpose: the failure happens before any call.
    service = FeishuBitablePreviewService()

    with pytest.raises(ValueError) as error:
        await service.preview(
            BitablePreviewRequest(
                url="https://feishu.cn/base/APP123?table=tblX",
                token=None,
                mapping=[{"sourceColumn": "Name", "targetPath": "name"}],
            )
        )

    assert str(error.value) == AUTH_FAILED


@pytest.mark.asyncio
async def test_preview_without_app_token_fails_closed(monkeypatch):
    service = FeishuBitablePreviewService()
    with pytest.raises(ValueError) as error:
        await service.preview(BitablePreviewRequest(token="explicit-token", mapping=[]))
    assert str(error.value) == INVALID_URL


# ---------------------------------------------------------------------------
# Pagination (bounded, page-capped)
# ---------------------------------------------------------------------------

def _fields_payload():
    return _FakeResponse(
        200,
        {
            "data": {
                "items": [
                    {"field_id": "f1", "name": "Name", "type": "text"},
                    {"field_id": "f2", "name": "Score", "type": "number"},
                ]
            }
        },
    )


def _record_page(records, has_more, page_token):
    return _FakeResponse(
        200,
        {"data": {"items": records, "has_more": has_more, "page_token": page_token}},
    )


@pytest.mark.asyncio
async def test_preview_reads_all_pages_when_cap_is_large(monkeypatch):
    script = [
        _fields_payload(),
        _record_page([{"record_id": "r1", "fields": {"Name": "a"}}, {"record_id": "r2", "fields": {"Name": "b"}}], True, "cur2"),
        _record_page([{"record_id": "r3", "fields": {"Name": "c"}}], True, "cur3"),
        _record_page([{"record_id": "r4", "fields": {"Name": "d"}}], False, None),
    ]
    calls, _ = _install(monkeypatch, script)
    service = FeishuBitablePreviewService()

    result = await service.preview(
        BitablePreviewRequest(
            url="https://feishu.cn/base/APP123?table=tblX",
            token="explicit-token",
            mapping=[{"sourceColumn": "Name", "targetPath": "name"}],
            max_records=100,
            page_size=2,
        )
    )

    assert result["status"] == "preview"
    assert result["recordCount"] == 4
    assert result["pagesRead"] == 3
    assert result["hasMore"] is False
    assert result["truncated"] is False
    # The page cursors were threaded through: page 2 used cur2, page 3 used cur3.
    assert calls[1]["params"].get("page_token") is None
    assert calls[2]["params"].get("page_token") == "cur2"
    assert calls[3]["params"].get("page_token") == "cur3"


@pytest.mark.asyncio
async def test_preview_stops_at_record_cap_and_marks_truncated(monkeypatch):
    script = [
        _fields_payload(),
        _record_page([{"record_id": "r1", "fields": {"Name": "a"}}, {"record_id": "r2", "fields": {"Name": "b"}}], True, "cur2"),
        _record_page([{"record_id": "r3", "fields": {"Name": "c"}}], True, "cur3"),
        _record_page([{"record_id": "r4", "fields": {"Name": "d"}}], False, None),
    ]
    calls, _ = _install(monkeypatch, script)
    service = FeishuBitablePreviewService()

    result = await service.preview(
        BitablePreviewRequest(
            url="https://feishu.cn/base/APP123?table=tblX",
            token="explicit-token",
            mapping=[{"sourceColumn": "Name", "targetPath": "name"}],
            max_records=3,
            page_size=2,
        )
    )

    assert result["status"] == "preview"
    assert result["recordCount"] == 3  # r1, r2, r3 -- capped before r4
    assert result["pagesRead"] == 2  # page 3 was never fetched
    assert result["hasMore"] is True  # last fetched page still reported more
    assert result["truncated"] is True
    assert len(calls) == 3  # 1 fields + 2 record pages


@pytest.mark.asyncio
async def test_preview_passes_explicit_token_in_headers_and_only_reads(monkeypatch):
    script = [
        _fields_payload(),
        _record_page([{"record_id": "r1", "fields": {"Name": "a"}}], False, None),
    ]
    calls, _ = _install(monkeypatch, script)
    service = FeishuBitablePreviewService()

    result = await service.preview(
        BitablePreviewRequest(
            url="https://feishu.cn/base/APP123?table=tblX",
            token="explicit-token",
            mapping=[{"sourceColumn": "Name", "targetPath": "name"}],
        )
    )

    assert result["status"] == "preview"
    # Every call carries the explicit token in the Authorization header and
    # targets only bitable read endpoints (no writes, no db, no import route).
    for call in calls:
        assert call["headers"].get("Authorization") == "Bearer explicit-token"
        assert call["path"].startswith("/open-apis/bitable")


# ---------------------------------------------------------------------------
# Stable key (record_id): present vs missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preview_with_stable_key_present_returns_preview(monkeypatch):
    script = [
        _fields_payload(),
        _record_page(
            [
                {"record_id": "r1", "fields": {"Name": "a"}},
                {"record_id": "r2", "fields": {"Name": "b"}},
            ],
            False,
            None,
        ),
    ]
    _install(monkeypatch, script)
    service = FeishuBitablePreviewService()

    result = await service.preview(
        BitablePreviewRequest(
            url="https://feishu.cn/base/APP123?table=tblX",
            token="explicit-token",
            mapping=[{"sourceColumn": "Name", "targetPath": "name"}],
        )
    )

    assert result["status"] == "preview"
    assert result["block"] is None
    assert result["stableKey"]["candidate"] == "record_id"
    assert result["stableKey"]["present"] is True
    assert result["stableKey"]["sample"] == "r1"
    # Each converted record exposes the stable key.
    assert [r["stableKey"] for r in result["records"]] == ["r1", "r2"]


@pytest.mark.asyncio
async def test_preview_with_stable_key_missing_returns_structured_block(monkeypatch):
    # Records carry fields but no record_id at all.
    script = [
        _fields_payload(),
        _record_page([{"fields": {"Name": "a"}}, {"fields": {"Name": "b"}}], False, None),
    ]
    _install(monkeypatch, script)
    service = FeishuBitablePreviewService()

    result = await service.preview(
        BitablePreviewRequest(
            url="https://feishu.cn/base/APP123?table=tblX",
            token="explicit-token",
            mapping=[{"sourceColumn": "Name", "targetPath": "name"}],
        )
    )

    # Read-only preview data is still returned, but the status is blocked with
    # a structured reason -- nothing was written to any database.
    assert result["status"] == "blocked"
    assert result["stableKey"]["present"] is False
    assert result["recordCount"] == 2
    assert result["block"]["code"] == MISSING_STABLE_KEY
    assert "record_id" in result["block"]["message"]


# ---------------------------------------------------------------------------
# Missing mapping -> structured block (not a database write)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preview_without_mapping_returns_structured_block(monkeypatch):
    script = [
        _fields_payload(),
        _record_page([{"record_id": "r1", "fields": {"Name": "a"}}], False, None),
    ]
    _install(monkeypatch, script)
    service = FeishuBitablePreviewService()

    result = await service.preview(
        BitablePreviewRequest(
            url="https://feishu.cn/base/APP123?table=tblX",
            token="explicit-token",
            mapping=None,  # no field mapping supplied
        )
    )

    assert result["status"] == "blocked"
    assert result["block"]["code"] == MISSING_MAPPING
    assert "Name" in result["block"]["detail"]["availableFields"]
    assert result["recordCount"] == 1  # preview sample is still produced


@pytest.mark.asyncio
async def test_preview_empty_base_with_mapping_is_preview_not_blocked(monkeypatch):
    # An empty table has no records to verify a stable key against; the schema
    # level candidate (record_id) is still valid, so mapping presence decides.
    script = [
        _fields_payload(),
        _record_page([], False, None),
    ]
    _install(monkeypatch, script)
    service = FeishuBitablePreviewService()

    result = await service.preview(
        BitablePreviewRequest(
            url="https://feishu.cn/base/APP123?table=tblX",
            token="explicit-token",
            mapping=[{"sourceColumn": "Name", "targetPath": "name"}],
        )
    )

    assert result["status"] == "preview"
    assert result["recordCount"] == 0
    assert result["stableKey"]["present"] is True
