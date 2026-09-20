from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.models import (
    CatalogHead,
    DataTemplate,
    DataVersion,
    PerformanceRecord,
    PerformanceRecordVersion,
    Profile,
    Software,
    TemplateVersion,
)


async def create_record(db: AsyncSession, payload, actor):
    """Create a performance record owned by ``actor``."""
    existing = (
        await db.execute(
            select(PerformanceRecord).where(
                PerformanceRecord.stable_key == payload.stableKey
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise AppError(ErrorCode.CONFLICT, "稳定主键已存在")

    template_version = (
        await db.execute(
            select(TemplateVersion).where(TemplateVersion.id == payload.templateVersionId)
        )
    ).scalar_one_or_none()
    if not template_version:
        raise AppError(ErrorCode.NOT_FOUND, "模板版本不存在")
    # Records must be bound to a published template version; a draft or
    # otherwise non-published version is not a valid contract for data entry.
    if template_version.status != "published":
        raise AppError(ErrorCode.CONFLICT, "模板版本未发布")

    record = PerformanceRecord(
        stable_key=payload.stableKey,
        software_id=payload.softwareId,
        profile_id=payload.profileId,
        template_version_id=payload.templateVersionId,
        owner_user_id=actor.id,
        draft_payload=payload.payload,
    )
    db.add(record)
    await db.commit()
    return record


def record_dict(record: PerformanceRecord) -> dict:
    """Serialize a performance record and its strong, resource-bound ETag."""
    return {
        "id": record.id,
        "stableKey": record.stable_key,
        "softwareId": record.software_id,
        "profileId": record.profile_id,
        "templateVersionId": record.template_version_id,
        "ownerUserId": record.owner_user_id,
        "lifecycleStatus": record.lifecycle_status,
        "revision": record.revision,
        "payload": record.draft_payload,
        "etag": f'"record-{record.id}-{record.revision}"',
    }


async def record_dict_with_names(db: AsyncSession, record: PerformanceRecord) -> dict:
    """Serialize a record with resolved Software / Profile / Template names."""
    base = record_dict(record)
    if record.software_id:
        sw = await db.get(Software, record.software_id)
        base["softwareName"] = sw.name if sw else None
        base["softwareCode"] = sw.code if sw else None
    if record.profile_id:
        pr = await db.get(Profile, record.profile_id)
        base["profileName"] = pr.name if pr else None
    if record.template_version_id:
        tv = await db.get(TemplateVersion, record.template_version_id)
        if tv:
            dt = await db.get(DataTemplate, tv.template_id)
            base["templateName"] = dt.name if dt else None
    return base


async def get_current_catalog_version(db: AsyncSession) -> tuple[CatalogHead | None, DataVersion | None]:
    """Resolve the published snapshot currently exposed by the catalog head."""
    head = (await db.execute(
        select(CatalogHead).where(CatalogHead.scope_key == "performance_catalog")
    )).scalar_one_or_none()
    if not head or not head.current_version_id:
        return head, None
    version = (await db.execute(
        select(DataVersion).where(
            DataVersion.id == head.current_version_id,
            DataVersion.status == "published",
        )
    )).scalar_one_or_none()
    return head, version


async def list_public_catalog_records(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    software_id: str | None = None,
    profile_id: str | None = None,
    keyword: str | None = None,
    lifecycle_status: str | None = None,
    # Keep the original short names as compatibility aliases for internal callers.
    software: str | None = None,
    profile: str | None = None,
    status: str | None = None,
) -> dict:
    """List records from the current published immutable snapshot only."""
    software_id = software_id if software_id is not None else software
    profile_id = profile_id if profile_id is not None else profile
    lifecycle_status = lifecycle_status if lifecycle_status is not None else status
    head, version = await get_current_catalog_version(db)
    if not version:
        return {"items": [], "total": 0, "page": page, "pageSize": page_size,
                "dataVersionId": None, "versionNo": None}
    query = select(PerformanceRecord, PerformanceRecordVersion).join(
        PerformanceRecordVersion,
        PerformanceRecordVersion.record_id == PerformanceRecord.id,
    ).where(
        PerformanceRecordVersion.data_version_id == version.id,
        PerformanceRecord.deleted.is_(False),
    )
    rows = list((await db.execute(query)).all())
    filtered: list[tuple[PerformanceRecord, PerformanceRecordVersion]] = []
    for record, snapshot in rows:
        payload = snapshot.parsed_payload or snapshot.raw_payload or {}
        values = " ".join(str(value) for value in payload.values())
        if software_id and software_id.lower() not in record.software_id.lower():
            continue
        if profile_id and profile_id.lower() not in record.profile_id.lower():
            continue
        if lifecycle_status and lifecycle_status.lower() != record.lifecycle_status.lower():
            continue
        if keyword and keyword.lower() not in f"{record.stable_key} {values}".lower():
            continue
        filtered.append((record, snapshot))
    filtered.sort(key=lambda pair: (pair[0].stable_key, pair[0].id))
    total = len(filtered)
    start = (page - 1) * page_size
    items = [public_record_dict(record, snapshot) for record, snapshot in filtered[start:start + page_size]]
    return {"items": items, "total": total, "page": page, "pageSize": page_size,
            "dataVersionId": version.id, "versionNo": version.version_no}


def public_record_dict(record: PerformanceRecord, snapshot: PerformanceRecordVersion) -> dict:
    """Serialize a public snapshot without exposing owner or draft fields."""
    payload = snapshot.parsed_payload or snapshot.raw_payload or {}
    return {
        "id": record.id,
        "recordId": record.id,
        "stableKey": record.stable_key,
        "softwareId": record.software_id,
        "profileId": record.profile_id,
        "templateVersionId": record.template_version_id,
        "lifecycleStatus": record.lifecycle_status,
        "revision": snapshot.record_revision,
        "payload": payload,
        "rawPayload": snapshot.raw_payload or {},
        "parsedPayload": snapshot.parsed_payload or {},
        "derivedPayload": snapshot.derived_payload or {},
        "sourceSnapshotId": snapshot.source_snapshot_id,
        "sourceLocator": snapshot.source_locator,
    }


async def get_public_catalog_record(db: AsyncSession, record_id: str) -> dict:
    """Read one record from the current snapshot or raise a public 404."""
    _, version = await get_current_catalog_version(db)
    if not version:
        raise AppError(ErrorCode.NOT_FOUND, "记录不存在")
    result = await db.execute(select(PerformanceRecord, PerformanceRecordVersion).join(
        PerformanceRecordVersion,
        PerformanceRecordVersion.record_id == PerformanceRecord.id,
    ).where(
        PerformanceRecord.id == record_id,
        PerformanceRecordVersion.data_version_id == version.id,
        PerformanceRecord.deleted.is_(False),
    ))
    row = result.first()
    if not row:
        raise AppError(ErrorCode.NOT_FOUND, "记录不存在")
    return {**public_record_dict(row[0], row[1]), "dataVersionId": version.id, "versionNo": version.version_no}


async def get_record(
    db: AsyncSession, record_id: str, owner_user_id: str | None = None
) -> PerformanceRecord:
    """Get a non-deleted record, optionally constrained to its owner.

    Applying the owner predicate in SQL prevents callers without ``data:update-any``
    from learning whether another user's record exists.
    """
    query = select(PerformanceRecord).where(
        PerformanceRecord.id == record_id,
        PerformanceRecord.deleted.is_(False),
    )
    if owner_user_id is not None:
        query = query.where(PerformanceRecord.owner_user_id == owner_user_id)
    record = (await db.execute(query)).scalar_one_or_none()
    if not record:
        raise AppError(ErrorCode.NOT_FOUND, "记录不存在")
    return record


async def update_record(
    db: AsyncSession,
    record: PerformanceRecord,
    payload,
    actor,
    expected_revision: int | None,
    authorization: set[str] | frozenset[str] | None = None,
    allow_any: bool = False,
) -> PerformanceRecord:
    """Update a record after capability, lifecycle and revision checks.

    ``authorization`` is the caller's effective RBAC capability set.  The
    compatibility ``allow_any`` flag is retained for existing service callers;
    route handlers should pass the capability set so both update-own and
    update-any are enforced here as defense in depth.
    """
    # Keep the historical positional ``allow_any`` call shape working while
    # treating an explicitly supplied capability set as authoritative.
    legacy_call = isinstance(authorization, bool)
    capabilities = set() if legacy_call else set(authorization or ())
    can_update_any = (authorization if legacy_call else allow_any) or "data:update-any" in capabilities
    # Existing direct service callers predate RBAC injection; route handlers
    # always pass a capability set and therefore require data:update-own.
    can_update_own = authorization is None or "data:update-own" in capabilities
    is_owner = record.owner_user_id == actor.id
    if (is_owner and not (can_update_own or can_update_any)) or (
        not is_owner and not can_update_any
    ):
        raise AppError(ErrorCode.FORBIDDEN, "无权修改该记录")

    if expected_revision is None:
        raise AppError(ErrorCode.PRECONDITION_REQUIRED, "必须提供 If-Match 或 expectedRevision")
    if expected_revision != record.revision:
        raise AppError(ErrorCode.CONFLICT, "记录版本已变化")
    if record.lifecycle_status not in {"draft", "rejected"}:
        raise AppError(ErrorCode.CONFLICT, "当前状态不可修改")

    record.draft_payload = payload.payload
    record.revision += 1
    await db.commit()
    return record


async def submit_record(db: AsyncSession, record, actor):
    """Submit an owned draft record for review."""
    if record.owner_user_id != actor.id:
        raise AppError(ErrorCode.FORBIDDEN, "无权提交该记录")
    if record.lifecycle_status not in {"draft", "rejected"}:
        raise AppError(ErrorCode.CONFLICT, "当前状态不可提交")
    record.lifecycle_status = "submitted"
    await db.commit()
    return record
