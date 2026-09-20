"""Read-only preview layer for Feishu Base (bitable) sources.

This module is intentionally *outside* the formal import pipeline
(``app/services/import_service.py`` + ``app/api/import_routes.py``).  It lets a
caller inspect a Feishu Base -- identified by its ``/base/{app_token}`` URL --
and obtain a preview structure: the table's fields (columns), a page-capped
sample of records, and the detected stable-key candidate (the bitable
``record_id``).

Hard boundaries (the layer is *read-only* and *credential-isolated*):

* It never reads or hard-codes any real credential.  The Feishu access
  ``token`` must be supplied *explicitly* by the caller and is only forwarded
  to the existing ``FeishuAdapter`` bitable methods.  It does **not** consult
  ``DataSource.credential_ref`` or any secret store, so it cannot resolve a
  reference into a live token.
* It never writes to any database (production or local).  There is no
  ``AsyncSession`` parameter and no DB import anywhere in this module.
* It never writes back to the Feishu Base (only ``GET`` via the adapter).
* It never publishes / promotes anything and never changes a schema.

When a field mapping is absent, or the records do not carry a usable stable
key, the layer returns a *structured block* (``status == "blocked"``) describing
the gap instead of proceeding.  The block is purely informational; no side
effect ever occurs.  The "no token" case fails **closed** by raising
``ValueError("SOURCE_AUTH_FAILED")`` (reusing the adapter's contract) so the
caller can never obtain partial data from an anonymous request.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from app.adapters.feishu import FeishuAdapter

# Error codes reused from the existing adapter contract so callers can map
# failures uniformly.
AUTH_FAILED = "SOURCE_AUTH_FAILED"
INVALID_URL = "SOURCE_INVALID_BASE_URL"
MISSING_TABLE_ID = "SOURCE_MISSING_TABLE_ID"
MISSING_STABLE_KEY = "PREVIEW_MISSING_STABLE_KEY"
MISSING_MAPPING = "PREVIEW_MISSING_FIELD_MAPPING"


def parse_base_url(url: str) -> dict:
    """Extract ``app_token`` (and optional ``table_id``) from a Feishu Base URL.

    Accepts URLs of the form ``https://{host}/base/{app_token}`` with an
    optional ``?table={table_id}`` query parameter (the shape Feishu uses when
    you open a specific table inside a Base).  The function performs **no**
    network access; it only parses the string.

    Returns:
        ``{"app_token": str, "table_id": str | None}``

    Raises:
        ValueError("SOURCE_INVALID_BASE_URL") when the URL does not contain a
        usable ``/base/{app_token}`` path or the token is empty.
    """
    if not url or not isinstance(url, str):
        raise ValueError(INVALID_URL)
    parsed = urllib.parse.urlparse(url.strip())
    path = parsed.path
    marker = "/base/"
    idx = path.find(marker)
    if idx == -1:
        raise ValueError(INVALID_URL)
    remainder = path[idx + len(marker):].strip("/")
    if not remainder:
        raise ValueError(INVALID_URL)
    # Feishu Base URLs are flat under /base/; take the first path segment as
    # the app token and ignore anything deeper.
    app_token = remainder.split("/", 1)[0]
    if not app_token:
        raise ValueError(INVALID_URL)
    query = urllib.parse.parse_qs(parsed.query)
    table_ids = query.get("table")
    table_id = table_ids[0] if table_ids else None
    return {"app_token": app_token, "table_id": table_id}


@dataclass
class BitablePreviewRequest:
    """Explicit, credential-isolated request for a Base preview.

    Every credential-bearing value (``token``) is passed in explicitly; the
    layer never looks one up.  ``url`` and the explicit ``app_token`` /
    ``table_id`` are alternative ways to identify the Base -- ``url`` wins when
    both are present, with ``app_token`` / ``table_id`` used as overrides.
    """

    url: str | None = None
    app_token: str | None = None
    table_id: str | None = None
    token: str | None = None  # explicit Feishu access token; never sourced here
    provider: str = "feishu"
    mapping: list[dict] | None = None  # optional source->template field mapping
    max_records: int = 500  # controllable cap on records read (preview only)
    page_size: int = 100  # records per page (Feishu caps at 500)

    def resolve(self) -> dict:
        """Resolve the target Base identity and fail closed on missing inputs.

        Raises:
            ValueError("SOURCE_AUTH_FAILED") when no ``token`` was supplied.
            ValueError("SOURCE_INVALID_BASE_URL") when neither the URL nor the
                explicit ``app_token`` yields a usable app token.
        """
        if not self.token:
            raise ValueError(AUTH_FAILED)
        app_token = self.app_token
        table_id = self.table_id
        if self.url:
            parsed = parse_base_url(self.url)
            app_token = app_token or parsed["app_token"]
            table_id = table_id or parsed["table_id"]
        if not app_token:
            raise ValueError(INVALID_URL)
        return {"app_token": app_token, "table_id": table_id}


def _field_meta(field: dict) -> dict:
    return {
        "id": field.get("field_id") or field.get("id"),
        "name": field.get("name") or field.get("field_name"),
        "type": field.get("type"),
    }


class FeishuBitablePreviewService:
    """Read-only preview of a Feishu Base (bitable) table.

    The service is constructed with an optional ``FeishuAdapter`` so tests can
    inject a fake.  By default it instantiates a real ``FeishuAdapter`` but the
    preview flow only ever issues ``GET`` calls through it.
    """

    def __init__(self, adapter: FeishuAdapter | None = None) -> None:
        self.adapter = adapter or FeishuAdapter()

    async def preview(self, request: BitablePreviewRequest) -> dict:
        """Run the read-only preview and return a structured result.

        The returned dict always carries a ``status`` of either ``"preview"``
        or ``"blocked"``.  A blocked result still includes the read-only
        preview data (fields + record sample) plus a ``block`` payload that
        explains why formal import cannot proceed -- it never writes anything.

        Raises:
            ValueError("SOURCE_AUTH_FAILED") when no token is supplied
                (fail-closed; no partial data is returned).
            ValueError("SOURCE_INVALID_BASE_URL") when the Base identity
                cannot be resolved.
            ValueError("SOURCE_MISSING_TABLE_ID") when a table id is required
                but absent.
        """
        target = request.resolve()
        app_token, table_id = target["app_token"], target["table_id"]
        token = request.token

        if not table_id:
            raise ValueError(MISSING_TABLE_ID)

        # 1) Fields (columns) of the table.
        raw_fields = await self.adapter.list_bitable_fields(app_token, table_id, token=token)
        field_meta = [_field_meta(f) for f in raw_fields]

        # 2) Paginated record read with a controllable cap.
        records, pages_read, has_more = await self._read_records(app_token, table_id, token, request)

        # 3) Stable-key candidate detection (the bitable record_id).
        stable = self._detect_stable_key(records)

        preview_records = self._convert_records(records)
        truncated = len(preview_records) >= request.max_records and has_more

        result: dict[str, Any] = {
            "provider": request.provider,
            "app_token": app_token,
            "table_id": table_id,
            "fields": field_meta,
            "fieldCount": len(field_meta),
            "records": preview_records,
            "recordCount": len(preview_records),
            "pagesRead": pages_read,
            "hasMore": has_more,
            "truncated": truncated,
            "stableKey": stable,
            "mapping": list(request.mapping) if request.mapping else [],
            "block": None,
        }

        # 4a) No usable stable key -> cannot import idempotently.  Block, but
        #     keep the read-only preview so the caller can inspect the data.
        if not stable["present"]:
            result["status"] = "blocked"
            result["block"] = {
                "code": MISSING_STABLE_KEY,
                "message": "记录缺少稳定键（record_id），无法安全幂等导入。",
                "detail": {"sampleRecord": stable.get("sample")},
            }
            return result

        # 4b) No field mapping -> cannot map source columns to the template.
        #     Block with a structured reason instead of writing to the db.
        if not request.mapping:
            result["status"] = "blocked"
            result["block"] = {
                "code": MISSING_MAPPING,
                "message": "缺少字段映射，无法进入正式导入；仅返回只读预览。",
                "detail": {
                    "availableFields": [f["name"] for f in field_meta if f["name"]],
                },
            }
            return result

        # 5) Everything required is present: return the read-only preview.
        result["status"] = "preview"
        return result

    async def _read_records(
        self,
        app_token: str,
        table_id: str,
        token: str,
        request: BitablePreviewRequest,
    ) -> tuple[list[dict], int, bool]:
        """Page through records up to ``max_records``; returns (records, pages, has_more)."""
        records: list[dict] = []
        pages_read = 0
        has_more = False
        next_page: str | None = None
        cap = max(0, int(request.max_records))
        while len(records) < cap:
            page = await self.adapter.read_bitable_records(
                app_token,
                table_id,
                token=token,
                page_token=next_page,
                page_size=request.page_size,
            )
            pages_read += 1
            items = page.get("records") or []
            for item in items:
                if len(records) >= cap:
                    break
                records.append(item)
            has_more = bool(page.get("has_more"))
            next_page = page.get("page_token")
            # Stop when the source reports no more pages or gives no cursor.
            if not has_more or not next_page:
                break
        return records, pages_read, has_more

    def _detect_stable_key(self, records: list[dict]) -> dict:
        """Identify the stable-key candidate for idempotent import.

        Feishu bitable records always expose a ``record_id``; we surface that
        as the candidate.  If any read record is missing it, the candidate is
        reported as not present (a formal import would be unsafe).
        """
        if not records:
            # Empty table: the schema-level candidate (record_id) is still the
            # right one; nothing to verify against yet.
            return {"candidate": "record_id", "present": True, "sample": None}
        present = True
        sample = None
        for rec in records:
            rid = rec.get("record_id") if isinstance(rec, dict) else None
            if rid is None:
                rid = rec.get("recordId") if isinstance(rec, dict) else None
            if rid is None or str(rid).strip() == "":
                present = False
            if sample is None and rid is not None:
                sample = rid
        return {"candidate": "record_id", "present": present, "sample": sample}

    def _convert_records(self, records: list[dict]) -> list[dict]:
        """Flatten bitable records into a preview-friendly shape."""
        preview: list[dict] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rid = rec.get("record_id")
            if rid is None:
                rid = rec.get("recordId")
            preview.append(
                {
                    "record_id": rid,
                    "fields": rec.get("fields", {}),
                    "stableKey": rid,
                }
            )
        return preview
