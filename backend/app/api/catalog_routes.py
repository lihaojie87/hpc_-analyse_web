from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.models import PerformanceRecord, Software, Profile, DataTemplate, TemplateVersion
from app.db.session import get_db
from app.deps.auth_deps import get_current_user, require_permission
from app.schemas.catalog import RecordCreateIn, RecordPatchIn
from app.services.catalog_service import (
    create_record,
    get_record,
    record_dict,
    record_dict_with_names,
    submit_record,
    update_record,
    list_public_catalog_records,
    get_public_catalog_record,
)
from app.services.rbac_service import get_roles_permissions

router = APIRouter(prefix="/records")
public_router = APIRouter(prefix="/catalog/records")


@public_router.get("")
async def list_public_records(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    software_id: str | None = Query(default=None, alias="softwareId"),
    profile_id: str | None = Query(default=None, alias="profileId"),
    keyword: str | None = Query(default=None),
    lifecycle_status: str | None = Query(default=None, alias="lifecycleStatus"),
    # Backward-compatible aliases retained for already deployed clients.
    software: str | None = Query(default=None),
    profile: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user=Depends(require_permission("data:read")),
    db: AsyncSession = Depends(get_db),
):
    """List only records belonging to the current published catalog snapshot."""
    return await list_public_catalog_records(
        db, page=page, page_size=page_size,
        software=software_id or software,
        profile=profile_id or profile,
        keyword=keyword,
        status=lifecycle_status or status,
    )


@public_router.get("/{record_id}")
async def get_public_record(
    record_id: str,
    user=Depends(require_permission("data:read")),
    db: AsyncSession = Depends(get_db),
):
    """Return one current published snapshot record; never falls back to drafts."""
    return await get_public_catalog_record(db, record_id)


@router.post("")
async def create(
    payload: RecordCreateIn,
    user=Depends(require_permission("data:create")),
    db: AsyncSession = Depends(get_db),
):
    return record_dict(await create_record(db, payload, user))


@router.get("")
async def list_records(
    user=Depends(require_permission("data:read")),
    software_code: str | None = Query(default=None, alias="softwareCode"),
    db: AsyncSession = Depends(get_db),
):
    """List records visible to the current user.

    ``data:update-any`` is the explicit capability for cross-owner visibility;
    all other readers receive only their own records.
    """
    _, permissions = await get_roles_permissions(db, user.id)
    query = select(PerformanceRecord).where(PerformanceRecord.deleted.is_(False))
    if software_code:
        sw = (await db.execute(select(Software).where(Software.code == software_code))).scalar_one_or_none()
        if sw:
            query = query.where(PerformanceRecord.software_id == sw.id)
        else:
            return {"items": [], "pagination": {"page": 1, "pageSize": 20, "total": 0, "totalPages": 0}}
    if "data:update-any" not in permissions:
        query = query.where(PerformanceRecord.owner_user_id == user.id)
    rows = (await db.execute(query.order_by(PerformanceRecord.updated_at.desc()))).scalars().all()

    # Batch resolve names
    sw_ids = list({r.software_id for r in rows if r.software_id})
    pf_ids = list({r.profile_id for r in rows if r.profile_id})
    tv_ids = list({r.template_version_id for r in rows if r.template_version_id})

    sw_map = {}
    if sw_ids:
        sw_rows = (await db.execute(select(Software).where(Software.id.in_(sw_ids)))).scalars().all()
        sw_map = {s.id: s.name for s in sw_rows}
        sw_code_map = {s.id: s.code for s in sw_rows}
    pf_map = {}
    if pf_ids:
        pf_rows = (await db.execute(select(Profile).where(Profile.id.in_(pf_ids)))).scalars().all()
        pf_map = {p.id: p.name for p in pf_rows}

    items = []
    for r in rows:
        d = record_dict(r)
        d["softwareName"] = sw_map.get(r.software_id)
        d["softwareCode"] = sw_code_map.get(r.software_id)
        d["profileName"] = pf_map.get(r.profile_id)
        items.append(d)

    return {
        "items": items,
        "pagination": {
            "page": 1,
            "pageSize": len(rows) or 20,
            "total": len(rows),
            "totalPages": 1 if rows else 0,
        },
    }


@router.get("/{record_id}")
async def get(
    record_id: str,
    user=Depends(require_permission("data:read")),
    db: AsyncSession = Depends(get_db),
):
    """Read one record, with cross-owner visibility gated by update-any."""
    _, permissions = await get_roles_permissions(db, user.id)
    owner_filter = None if "data:update-any" in permissions else user.id
    record = await get_record(db, record_id, owner_user_id=owner_filter)
    return await record_dict_with_names(db, record)


def _parse_record_etag(if_match: str, record_id: str) -> int:
    """Validate and parse a strong resource-bound record ETag."""
    raw = if_match.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    expected_prefix = f"record-{record_id}-"
    if not raw.startswith(expected_prefix):
        raise AppError(ErrorCode.VALIDATION_ERROR, "If-Match 格式无效或与资源不匹配")
    revision_text = raw[len(expected_prefix) :]
    if not revision_text.isdigit() or int(revision_text) < 1:
        raise AppError(ErrorCode.VALIDATION_ERROR, "If-Match 格式无效或与资源不匹配")
    return int(revision_text)


@router.patch("/{record_id}")
async def patch(
    record_id: str,
    payload: RecordPatchIn,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch a record with RBAC and optimistic concurrency enforcement."""
    # Protocol preconditions are validated first so authenticated clients get
    # the documented 428 even when their role cannot update records.
    if if_match is None:
        raise AppError(ErrorCode.PRECONDITION_REQUIRED, "必须提供 If-Match")
    _, permissions = await get_roles_permissions(db, user.id)
    if "data:update-own" not in permissions and "data:update-any" not in permissions:
        raise AppError(ErrorCode.FORBIDDEN, "权限不足")

    expected_revision = _parse_record_etag(if_match, record_id)
    if payload.expectedRevision is not None and payload.expectedRevision != expected_revision:
        raise AppError(ErrorCode.VALIDATION_ERROR, "If-Match 格式无效或与 expectedRevision 不一致")

    allow_any = "data:update-any" in permissions
    # Owner filtering makes unauthorized detail access indistinguishable from
    # a missing record. update-any intentionally bypasses that filter.
    record = await get_record(
        db,
        record_id,
        owner_user_id=None if allow_any else user.id,
    )
    try:
        updated = await update_record(
            db,
            record,
            payload,
            user,
            expected_revision,
            authorization=permissions,
            allow_any=allow_any,
        )
    except AppError as exc:
        if exc.code == ErrorCode.CONFLICT:
            raise AppError(ErrorCode.PRECONDITION_FAILED, exc.message)
        raise
    return await record_dict_with_names(db, updated)


@router.post("/{record_id}/submit")
async def submit(
    record_id: str,
    user=Depends(require_permission("data:submit")),
    db: AsyncSession = Depends(get_db),
):
    return record_dict(await submit_record(db, await get_record(db, record_id), user))
