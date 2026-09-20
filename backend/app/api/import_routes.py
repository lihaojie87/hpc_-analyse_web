"""T04 import preview, dry-run, staging and retry endpoints."""
import re
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.deps.auth_deps import require_permission
from app.db.models import DataSource, ImportJob, Software, Profile, PerformanceRecord, DataTemplate, TemplateVersion, TemplateField, DataVersion, CatalogHead, PerformanceRecordVersion, SourceSnapshot
from app.services.import_service import ImportService
from app.services.sync_service import SyncService
from app.services.feishu_auth import get_feishu_token
from app.adapters.feishu import FeishuAdapter
from app.core.errors import AppError, ErrorCode

router = APIRouter(prefix='/import')


def _token_from_source(source: DataSource) -> str | None:
    if isinstance(source.config_json, dict):
        return source.config_json.get("token") or source.config_json.get("apiToken")
    return None


async def _resolve_token(source: DataSource) -> str:
    """Resolve Feishu token: config first, auto-resolve from env as fallback."""
    token = _token_from_source(source)
    if token:
        return token
    try:
        return await get_feishu_token()
    except Exception:
        raise AppError(ErrorCode.FORBIDDEN, "飞书凭证未配置")


async def _service(source: DataSource | None = None) -> ImportService:
    token = None
    if source:
        token = await _resolve_token(source)
    return ImportService(FeishuAdapter(token=token))


def _parse_feishu_url(url: str) -> dict:
    """Parse a Feishu sheet/bitable URL into provider and token."""
    url = url.strip()
    # https://{tenant}.feishu.cn/sheets/{spreadsheet_token}
    # https://{tenant}.feishu.cn/base/{app_token}?table={table_id}
    m = re.search(r'feishu\.cn/sheets/([A-Za-z0-9_-]+)', url)
    if m:
        return {"provider": "feishu", "workbookToken": m.group(1), "type": "sheet"}
    m = re.search(r'feishu\.cn/base/([A-Za-z0-9_-]+)', url)
    if m:
        return {"provider": "feishu", "workbookToken": m.group(1), "type": "base"}
    raise AppError(ErrorCode.VALIDATION_ERROR, "无法解析飞书链接，请提供 sheets 或 base 格式的 URL")


@router.post('/quick-setup')
async def quick_setup(
    payload: dict,
    user=Depends(require_permission('source:manage')),
    db: AsyncSession = Depends(get_db),
):
    """One-step setup from a Feishu URL: parse, create source, discover sheets."""
    url = payload.get("url", "").strip()
    if not url:
        raise AppError(ErrorCode.VALIDATION_ERROR, "请提供飞书链接")

    parsed = _parse_feishu_url(url)
    workbook_token = parsed["workbookToken"]
    code = payload.get("code") or f"feishu-{workbook_token[:8]}"

    # Find or create data source
    source = (
        await db.execute(select(DataSource).where(DataSource.workbook_token == workbook_token))
    ).scalar_one_or_none()

    if source:
        # Update token if config env is set
        try:
            fresh_token = await get_feishu_token()
            source.config_json = {**source.config_json, "token": fresh_token}
            await db.commit()
        except Exception:
            pass
    else:
        try:
            fresh_token = await get_feishu_token()
        except Exception:
            fresh_token = None
        source = DataSource(
            code=code,
            provider=parsed["provider"],
            workbook_token=workbook_token,
            credential_ref=f"feishu-{code}",
            config_json={"token": fresh_token} if fresh_token else {},
        )
        db.add(source)
        await db.commit()

    # Discover sheets
    token = await _resolve_token(source)
    adapter = FeishuAdapter(token=token)
    sheets = await adapter.discover_sheets(workbook_token)

    return {
        "sourceId": source.id,
        "code": source.code,
        "workbookToken": workbook_token,
        "type": parsed["type"],
        "sheets": sheets,
    }


@router.post('/previews')
async def preview(payload: dict, user=Depends(require_permission('source:manage')), db: AsyncSession=Depends(get_db)):
    source=(await db.execute(select(DataSource).where(DataSource.id==payload.get('sourceId'), DataSource.status=='active'))).scalar_one_or_none()
    if not source: raise AppError(ErrorCode.NOT_FOUND,'数据源不存在')
    return await (await _service(source)).preview(db, source, payload['sheetId'], payload.get('template', {}), payload.get('mapping', []), user.id)

@router.post('/previews/{job_id}/dry-run')
async def dry_run(job_id: str, payload: dict, user=Depends(require_permission('source:manage')), db: AsyncSession=Depends(get_db)):
    return await (await _service()).dry_run(db, job_id, payload.get('records', []))

@router.post('/jobs')
async def create_job(payload: dict, user=Depends(require_permission('sync:execute')), db: AsyncSession=Depends(get_db)):
    source=(await db.execute(select(DataSource).where(DataSource.id==payload.get('sourceId')))).scalar_one_or_none()
    if not source: raise AppError(ErrorCode.NOT_FOUND,'数据源不存在')
    existing=(await db.execute(select(ImportJob).where(ImportJob.idempotency_key==payload['idempotencyKey']))).scalar_one_or_none()
    if existing:
        source_revision = payload.get('sourceRevision')
        await SyncService().ensure_fresh(db, existing, source_revision)
        return {'id': existing.id, 'status': 'duplicate', 'idempotencyKey': existing.idempotency_key}
    job=ImportJob(idempotency_key=payload['idempotencyKey'], source_revision=payload.get('sourceRevision'), status='queued', created_by=user.id)
    db.add(job); await db.commit(); return {'id': job.id, 'status': job.status, 'idempotencyKey': job.idempotency_key}

@router.get('/jobs/{job_id}')
async def get_job(job_id: str, user=Depends(require_permission('source:manage')), db: AsyncSession=Depends(get_db)):
    job=(await db.execute(select(ImportJob).where(ImportJob.id==job_id))).scalar_one_or_none()
    if not job: raise AppError(ErrorCode.NOT_FOUND,'导入任务不存在')
    return {'id':job.id,'status':job.status,'attemptCount':job.attempt_count,'stats':job.stats,'errorCode':job.error_code,'dataVersionId':job.data_version_id}

@router.post('/jobs/{job_id}/retry')
async def retry(job_id: str, user=Depends(require_permission('sync:execute')), db: AsyncSession=Depends(get_db)):
    job=(await db.execute(select(ImportJob).where(ImportJob.id==job_id))).scalar_one_or_none()
    if not job: raise AppError(ErrorCode.NOT_FOUND,'导入任务不存在')
    result=await SyncService().retry(db, job)
    return {'id':result.id,'status':result.status,'attemptCount':result.attempt_count}


@router.post('/demo-import')
async def demo_import(
    payload: dict,
    user=Depends(require_permission('source:manage')),
    db: AsyncSession = Depends(get_db),
):
    """Demo: full import pipeline from Feishu sheet to published records.

    Accepts: { "sourceId": "...", "sheetId": "..." }
    1. Fetches data from Feishu
    2. Creates Software/Profile/Template from sheet structure
    3. Creates PerformanceRecords
    4. Auto-publishes a data version
    """
    source_id = payload.get("sourceId", "")
    sheet_id = payload.get("sheetId", "")
    if not source_id or not sheet_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "需要 sourceId 和 sheetId")

    source = (await db.execute(
        select(DataSource).where(DataSource.id == source_id)
    )).scalar_one_or_none()
    if not source:
        raise AppError(ErrorCode.NOT_FOUND, "数据源不存在")

    # 1. Fetch raw data from Feishu
    token = await _resolve_token(source)
    adapter = FeishuAdapter(token=token)
    raw = await adapter.fetch_snapshot(source, sheet_id)
    headers = raw.get("headers", [])
    rows = raw.get("rows", [])

    if not rows:
        raise AppError(ErrorCode.VALIDATION_ERROR, "表格无数据行")

    # 2. Discover sheet name
    metainfo = await adapter._get(
        f"/open-apis/sheets/v2/spreadsheets/{source.workbook_token}/metainfo"
    )
    sheets_meta = metainfo.get("data", {}).get("sheets", [])
    sheet_name = next(
        (s.get("title", sheet_id) for s in sheets_meta if s.get("sheetId") == sheet_id),
        sheet_id,
    )

    # 3. Create or reuse Software from sheet name
    sw_code = sheet_name.replace(" ", "-").lower()
    software = (await db.execute(
        select(Software).where(Software.code == sw_code)
    )).scalar_one_or_none()
    if not software:
        software = Software(code=sw_code, name=sheet_name, version="1.0")
        db.add(software)
        await db.flush()

    # 4. Create template if none exists
    template = (await db.execute(
        select(DataTemplate).where(DataTemplate.code == "perf-metrics")
    )).scalar_one_or_none()
    if not template:
        template = DataTemplate(code="perf-metrics", name="性能指标模板", description="HPC 性能画像标准模板")
        db.add(template)
        await db.flush()

    # Template version
    tv = (await db.execute(
        select(TemplateVersion).where(
            TemplateVersion.template_id == template.id,
            TemplateVersion.status == "published",
        )
    )).scalar_one_or_none()
    if not tv:
        tv = TemplateVersion(
            template_id=template.id,
            version_no="1.0",
            status="published",
            schema_json={"type": "object", "properties": {"metrics": {"type": "object"}}},
        )
        db.add(tv)
        await db.flush()

    # 5. Parse rows into records
    # First row in Feishu sheets data: header row (we use as column labels)
    # Subsequent rows: metric_name in col[0], values in col[1:]
    column_labels = [h for h in headers if h] if headers else []
    effective_headers = column_labels[1:] if len(column_labels) > 1 else [f"列{i}" for i in range(len(headers[1:]) if headers else 0)]

    created_count = 0
    for row in rows:
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        metric_name = str(row[0]).strip() if row and row[0] else None
        if not metric_name:
            continue

        # Each column group becomes a Profile + PerformanceRecord
        for col_idx in range(1, min(len(row), len(effective_headers) + 1)):
            header_label = effective_headers[col_idx - 1] if col_idx - 1 < len(effective_headers) else f"col{col_idx}"
            value = row[col_idx] if col_idx < len(row) else None
            if value is None or str(value).strip() == "":
                continue

            profile_name = str(header_label).strip().replace("\n", " ")
            profile_code = profile_name[:50].replace(" ", "-").replace("：", "-").replace(":", "-").lower()

            profile = (await db.execute(
                select(Profile).where(
                    Profile.software_id == software.id,
                    Profile.code == profile_code,
                )
            )).scalar_one_or_none()
            if not profile:
                profile = Profile(software_id=software.id, code=profile_code, name=profile_name)
                db.add(profile)
                await db.flush()

            stable_key = f"{sw_code}/{profile_code}/{metric_name}".replace(" ", "-")[:500]

            existing = (await db.execute(
                select(PerformanceRecord).where(PerformanceRecord.stable_key == stable_key)
            )).scalar_one_or_none()

            if not existing:
                record_value = str(value).strip()
                try:
                    record_value_num = float(record_value) if record_value.replace(".", "").replace("-", "").isdigit() else record_value
                except ValueError:
                    record_value_num = record_value

                record = PerformanceRecord(
                    stable_key=stable_key,
                    software_id=software.id,
                    profile_id=profile.id,
                    template_version_id=tv.id,
                    owner_user_id=user.id,
                    lifecycle_status="published",
                    draft_payload={"metric": metric_name, "value": record_value_num, "unit": header_label},
                )
                db.add(record)
                await db.flush()
                created_count += 1

    # 6. Create a data version (auto-publish for demo)
    all_records = (await db.execute(
        select(PerformanceRecord)
        .where(PerformanceRecord.software_id == software.id, PerformanceRecord.deleted.is_(False))
    )).scalars().all()

    if all_records:
        latest_no = (await db.execute(
            select(DataVersion.version_no).order_by(DataVersion.version_no.desc())
        )).scalars().first()

        version_no = (latest_no or 0) + 1
        checksum = hex(hash(str([r.id for r in all_records])))[:16]
        dv = DataVersion(
            version_no=version_no,
            status="published",
            checksum=checksum,
            record_count=len(all_records),
            error_count=0,
            created_by=user.id,
        )
        db.add(dv)
        await db.flush()

        # Create immutable snapshots
        for record in all_records:
            db.add(PerformanceRecordVersion(
                record_id=record.id,
                data_version_id=dv.id,
                record_revision=record.revision,
                raw_payload=record.draft_payload,
                parsed_payload=record.draft_payload,
                derived_payload={},
            ))

        # Update CatalogHead
        head = (await db.execute(
            select(CatalogHead).where(CatalogHead.scope_key == "performance_catalog")
        )).scalar_one_or_none()
        if not head:
            head = CatalogHead(scope_key="performance_catalog", current_version_id=dv.id)
            db.add(head)
        else:
            head.current_version_id = dv.id

    await db.commit()

    return {
        "software": {"id": software.id, "code": software.code, "name": software.name},
        "templateVersionId": tv.id,
        "recordsCreated": created_count,
        "totalRecords": len(all_records),
        "dataVersion": version_no,
    }
