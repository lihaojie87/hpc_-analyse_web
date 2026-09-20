"""Synchronization run and import lifecycle endpoints."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.models import DataSource, ImportJob, SyncRun
from app.db.session import get_db
from app.deps.auth_deps import require_permission
from app.services.sync_service import SyncService

router = APIRouter(prefix="/sync")


def _sync_dict(run: SyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "sourceId": run.source_id,
        "importJobId": run.import_job_id,
        "idempotencyKey": run.idempotency_key,
        "status": run.status,
        "attemptCount": run.attempt_count,
        "failureCode": run.failure_code,
        "stats": run.stats,
    }


@router.post("/runs")
async def create_sync_run(
    payload: dict[str, Any],
    user=Depends(require_permission("sync:execute")),
    db: AsyncSession = Depends(get_db),
):
    source_id = payload.get("sourceId")
    idempotency_key = payload.get("idempotencyKey")
    if not isinstance(source_id, str) or not source_id.strip() or not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise AppError(ErrorCode.VALIDATION_ERROR, "sourceId 和 idempotencyKey 不能为空")
    source = await db.get(DataSource, source_id)
    if not source:
        raise AppError(ErrorCode.NOT_FOUND, "数据源不存在")
    run = await SyncService().create_run(db, source, idempotency_key.strip(), user.id)
    return _sync_dict(run)


@router.get("/runs/{run_id}")
async def get_sync_run(
    run_id: str,
    user=Depends(require_permission("source:manage")),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(SyncRun, run_id)
    if not run:
        raise AppError(ErrorCode.NOT_FOUND, "同步任务不存在")
    return _sync_dict(run)


@router.post("/jobs/{job_id}/stale")
async def mark_job_stale(
    job_id: str,
    user=Depends(require_permission("sync:execute")),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ImportJob, job_id)
    if not job:
        raise AppError(ErrorCode.NOT_FOUND, "导入任务不存在")
    result = await SyncService().mark_stale(db, job)
    return {"id": result.id, "status": result.status, "errorCode": result.error_code}
