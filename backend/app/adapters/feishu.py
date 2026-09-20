"""Feishu adapter with credential isolation and bounded retries."""
import asyncio
import hashlib
import json
from typing import Any
import httpx
from app.db.models import DataSource

class FeishuAdapter:
    """Read Feishu workbooks without accessing catalog publication state."""
    def __init__(self, base_url: str = "https://open.feishu.cn", token: str | None = None, max_retries: int = 3) -> None:
        self.base_url, self._token, self.max_retries = base_url.rstrip('/'), token, max(0, max_retries)

    def _headers(self, token: str | None = None) -> dict[str, str]:
        used = token if token is not None else self._token
        return {"Authorization": f"Bearer {used}"} if used else {}

    async def _get(self, path: str, params: dict[str, Any] | None = None, token: str | None = None) -> dict:
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
                    response = await client.get(path, params=params, headers=self._headers(token))
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if response.status_code == 401: raise ValueError("SOURCE_AUTH_FAILED")
                if response.status_code == 403: raise ValueError("SOURCE_FORBIDDEN")
                if response.status_code == 429: raise ValueError("SOURCE_RATE_LIMITED")
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries: raise ValueError("SOURCE_TIMEOUT") from exc
                await asyncio.sleep(2 ** attempt)
        raise ValueError("SOURCE_TIMEOUT")

    async def _post(self, path: str, json_data: dict[str, Any] | None = None, params: dict[str, Any] | None = None, token: str | None = None) -> dict:
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
                    response = await client.post(path, json=json_data, params=params, headers=self._headers(token))
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if response.status_code == 401: raise ValueError("SOURCE_AUTH_FAILED")
                if response.status_code == 403: raise ValueError("SOURCE_FORBIDDEN")
                if response.status_code == 429: raise ValueError("SOURCE_RATE_LIMITED")
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries: raise ValueError("SOURCE_TIMEOUT") from exc
                await asyncio.sleep(2 ** attempt)
        raise ValueError("SOURCE_TIMEOUT")

    async def discover_workbooks(self, source: DataSource) -> list[dict]:
        data = await self._get("/open-apis/drive/v1/files", {"page_size": 50})
        return list(data.get("data", {}).get("files", []))

    async def discover_sheets(self, workbook_id: str) -> list[dict]:
        data = await self._get(f"/open-apis/sheets/v2/spreadsheets/{workbook_id}/metainfo")
        return list(data.get("data", {}).get("sheets", []))

    async def read_values(self, workbook_id: str, sheet_id: str, range_: str | None = None) -> dict:
        if range_:
            endpoint = f"/open-apis/sheets/v2/spreadsheets/{workbook_id}/values/{range_}"
        else:
            endpoint = f"/open-apis/sheets/v2/spreadsheets/{workbook_id}/values/{sheet_id}"
        data = await self._get(endpoint)
        return data.get("data", data)

    # ------------------------------------------------------------------
    # Feishu Base (bitable) read capability.
    #
    # These are pure client methods: they build the request and reuse the
    # existing ``_get`` HTTP path (retries + status mapping), so they are
    # fully testable without any network call.  Callers must supply an
    # explicit access ``token``; when neither the argument nor the instance
    # token is present the call fails closed with ``SOURCE_AUTH_FAILED`` and
    # never sends an anonymous request.  No token is ever hard-coded here.
    # ------------------------------------------------------------------

    def _resolve_token(self, token: str | None) -> str:
        resolved = token if token is not None else self._token
        if not resolved:
            raise ValueError("SOURCE_AUTH_FAILED")
        return resolved

    async def list_bitable_fields(self, app_token: str, table_id: str, token: str | None = None) -> list[dict]:
        """List the fields (columns) of a Feishu Base (bitable) table.

        Args:
            app_token: Base app token (``app_token`` from the Base URL).
            table_id: Table id within the Base.
            token: Feishu tenant/user access token.  Falls back to the
                instance token when omitted; if neither is present the call
                fails closed.

        Returns the ``items`` list from the fields endpoint unchanged.
        """
        auth_token = self._resolve_token(token)
        data = await self._get(
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            {"page_size": 500},
            token=auth_token,
        )
        return list(data.get("data", {}).get("items", []))

    async def read_bitable_records(
        self,
        app_token: str,
        table_id: str,
        token: str | None = None,
        page_token: str | None = None,
        page_size: int = 100,
    ) -> dict:
        """Read one page of records from a Feishu Base (bitable) table.

        Args:
            app_token: Base app token.
            table_id: Table id within the Base.
            token: Feishu access token (see :meth:`list_bitable_fields`);
                fails closed when missing.
            page_token: Opaque cursor for the next page; ``None`` fetches the
                first page.
            page_size: Page size (Feishu caps this at 500).

        Returns ``{"records", "has_more", "page_token"}`` so callers can drive
        pagination by feeding ``page_token`` back in.  Only a single page is
        fetched per call.
        """
        auth_token = self._resolve_token(token)
        params: dict[str, Any] = {"page_size": max(1, min(page_size, 500))}
        if page_token:
            params["page_token"] = page_token
        data = await self._get(
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            params,
            token=auth_token,
        )
        body = data.get("data", {}) if isinstance(data, dict) else {}
        items = body.get("items", []) if isinstance(body, dict) else []
        return {
            "records": list(items),
            "has_more": bool(body.get("has_more")) if isinstance(body, dict) else False,
            "page_token": body.get("page_token") if isinstance(body, dict) else None,
        }

    async def discover(self, source: DataSource) -> dict:
        workbooks = await self.discover_workbooks(source)
        return {"workbooks": workbooks}

    async def fetch_snapshot(self, source: DataSource, sheet_id: str) -> dict:
        """Fetch values and preserve a provider revision when one is supplied.

        Feishu value responses do not always expose a revision.  In that case
        ``sourceRevision`` remains ``None`` and the content hash is the stable
        idempotency fallback; the hash is never masqueraded as a provider
        revision.
        """
        if not source.workbook_token:
            raise ValueError("SOURCE_SCHEMA_CHANGED")
        # Use a broad range so sheets with data outside the default region are captured
        payload = await self.read_values(source.workbook_token, sheet_id,
                                         f"{sheet_id}!A1:ZZ500")
        value_range = payload.get("valueRange", {}) if isinstance(payload, dict) else {}
        values = value_range.get("values", []) if isinstance(value_range, dict) else []
        rows = values if isinstance(values, list) else []
        metadata = payload.get("meta", {}) if isinstance(payload, dict) else {}
        source_revision = None
        for candidate in (
            payload.get("revision") if isinstance(payload, dict) else None,
            payload.get("sourceRevision") if isinstance(payload, dict) else None,
            metadata.get("revision") if isinstance(metadata, dict) else None,
            value_range.get("revision") if isinstance(value_range, dict) else None,
        ):
            if candidate is not None and str(candidate).strip():
                source_revision = str(candidate).strip()
                break
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return {
            "headers": rows[0] if rows else [],
            "rows": rows[1:] if len(rows) > 1 else [],
            "sourceRevision": source_revision,
            "contentHash": hashlib.sha256(canonical.encode()).hexdigest(),
        }

    async def health_check(self, source: DataSource) -> dict:
        await self.discover_workbooks(source)
        return {"ok": True, "provider": "feishu"}
