"""T04 import preview, dry-run, staging and retry endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.deps.auth_deps import require_permission
from app.db.models import DataSource, ImportJob
from app.services.import_service import ImportService
from app.services.sync_service import SyncService
from app.adapters.feishu import FeishuAdapter
from app.core.errors import AppError, ErrorCode

router = APIRouter(prefix='/import')

def _service() -> ImportService:
    return ImportService(FeishuAdapter())

@router.post('/previews')
async def preview(payload: dict, user=Depends(require_permission('source:manage')), db: AsyncSession=Depends(get_db)):
    source=(await db.execute(select(DataSource).where(DataSource.id==payload.get('sourceId'), DataSource.status=='active'))).scalar_one_or_none()
    if not source: raise AppError(ErrorCode.NOT_FOUND,'数据源不存在')
    return await _service().preview(db, source, payload['sheetId'], payload.get('template', {}), payload.get('mapping', []), user.id)

@router.post('/previews/{job_id}/dry-run')
async def dry_run(job_id: str, payload: dict, user=Depends(require_permission('source:manage')), db: AsyncSession=Depends(get_db)):
    return await _service().dry_run(db, job_id, payload.get('records', []))

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
