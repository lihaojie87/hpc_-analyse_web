"""Data-source management and provider discovery endpoints."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.feishu import FeishuAdapter
from app.core.errors import AppError, ErrorCode
from app.db.models import DataSource
from app.db.session import get_db
from app.deps.auth_deps import require_permission

router = APIRouter(prefix="/sources")


def _token_from_source(source: DataSource) -> str | None:
    """Extract Feishu API access token from source config JSON."""
    if isinstance(source.config_json, dict):
        return source.config_json.get("token") or source.config_json.get("apiToken")
    return None


def _make_adapter(source: DataSource) -> FeishuAdapter:
    """Create a FeishuAdapter with token from source config."""
    token = _token_from_source(source)
    return FeishuAdapter(token=token)


def _source_dict(source: DataSource) -> dict[str, Any]:
    """Serialize source metadata without exposing credentials."""
    return {
        "id": source.id,
        "code": source.code,
        "provider": source.provider,
        # Workbook tokens are provider identifiers and may be sensitive; do
        # not return them from management endpoints.
        "status": source.status,
        "revision": source.revision,
        "config": source.config_json,
        "createdAt": source.created_at.isoformat() if source.created_at else None,
        "updatedAt": source.updated_at.isoformat() if source.updated_at else None,
    }


def _require_text(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{name} 不能为空")
    return value.strip()


@router.get("")
async def list_sources(
    user=Depends(require_permission("source:manage")),
    db: AsyncSession = Depends(get_db),
):
    sources = (await db.execute(select(DataSource).order_by(DataSource.code))).scalars().all()
    return {
        "items": [_source_dict(source) for source in sources],
        "pagination": {"page": 1, "pageSize": len(sources) or 20, "total": len(sources), "totalPages": 1 if sources else 0},
    }


@router.post("")
async def create_source(
    payload: dict[str, Any],
    user=Depends(require_permission("source:manage")),
    db: AsyncSession = Depends(get_db),
):
    code = _require_text(payload, "code")
    credential_ref = _require_text(payload, "credentialRef")
    existing = (await db.execute(select(DataSource).where(DataSource.code == code))).scalar_one_or_none()
    if existing:
        raise AppError(ErrorCode.CONFLICT, "数据源编码已存在")
    source = DataSource(
        code=code,
        provider=str(payload.get("provider") or "feishu"),
        workbook_token=payload.get("workbookToken"),
        credential_ref=credential_ref,
        config_json=payload.get("config") if isinstance(payload.get("config"), dict) else {},
    )
    # If a token is provided directly, store it in config_json
    if payload.get("token") and isinstance(payload.get("token"), str):
        source.config_json = {**source.config_json, "token": payload["token"]}
    db.add(source)
    await db.commit()
    return _source_dict(source)


@router.get("/{source_id}")
async def get_source(
    source_id: str,
    user=Depends(require_permission("source:manage")),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(DataSource, source_id)
    if not source:
        raise AppError(ErrorCode.NOT_FOUND, "数据源不存在")
    return _source_dict(source)


@router.post("/{source_id}/discover")
async def discover_source(
    source_id: str,
    user=Depends(require_permission("source:manage")),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(DataSource, source_id)
    if not source:
        raise AppError(ErrorCode.NOT_FOUND, "数据源不存在")
    if source.status != "active":
        raise AppError(ErrorCode.CONFLICT, "数据源已禁用")
    adapter = _make_adapter(source)
    if source.workbook_token:
        sheets = await adapter.discover_sheets(source.workbook_token)
        return {"items": sheets}
    return await adapter.discover(source)


@router.get("/{source_id}/workbooks/{workbook_id}/sheets")
async def discover_sheets(
    source_id: str,
    workbook_id: str,
    user=Depends(require_permission("source:manage")),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(DataSource, source_id)
    if not source:
        raise AppError(ErrorCode.NOT_FOUND, "数据源不存在")
    if source.status != "active":
        raise AppError(ErrorCode.CONFLICT, "数据源已禁用")
    return {"items": await _make_adapter(source).discover_sheets(workbook_id)}


@router.post("/{source_id}/health")
async def source_health(
    source_id: str,
    user=Depends(require_permission("source:manage")),
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(DataSource, source_id)
    if not source:
        raise AppError(ErrorCode.NOT_FOUND, "数据源不存在")
    return await _make_adapter(source).health_check(source)
