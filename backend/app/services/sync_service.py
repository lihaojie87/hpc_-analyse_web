"""Idempotent sync scheduling and retry state transitions."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError, ErrorCode
from app.db.models import DataSource, ImportJob, SyncRun

class SyncService:
    """Create safe-to-replay sync runs and isolate stale/dead-letter jobs."""
    async def create_run(self, db: AsyncSession, source: DataSource, idempotency_key: str, actor_id: str | None = None) -> SyncRun:
        existing = (await db.execute(select(SyncRun).where(SyncRun.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing: return existing
        if source.status != 'active': raise AppError(ErrorCode.CONFLICT, '数据源已禁用')
        run = SyncRun(source_id=source.id, idempotency_key=idempotency_key, status='queued', stats={},); db.add(run); await db.commit(); return run

    async def retry(self, db: AsyncSession, job: ImportJob, max_attempts: int = 3) -> ImportJob:
        if job.status not in {'failed', 'dead_letter'}: raise AppError(ErrorCode.CONFLICT, '当前任务不可重试')
        job.attempt_count += 1
        if job.attempt_count > max_attempts: job.status = 'dead_letter'
        else: job.status = 'queued'; job.error_code = None
        await db.commit(); return job

    async def mark_stale(self, db: AsyncSession, job: ImportJob) -> ImportJob:
        """Mark a job stale without creating snapshots, diffs, or versions."""
        job.status = 'stale'
        job.error_code = 'IMPORT_STALE'
        await db.commit()
        return job

    async def ensure_fresh(self, db: AsyncSession, job: ImportJob, source_revision: str | None) -> None:
        """Reject and persist a stale job before any import writes occur."""
        expected = (job.source_revision or '').strip()
        actual = (source_revision or '').strip()
        if expected and actual and expected != actual:
            await self.mark_stale(db, job)
            raise AppError(ErrorCode.CONFLICT, '来源版本已变化，导入任务已标记为 stale')
