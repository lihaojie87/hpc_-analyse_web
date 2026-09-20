"""Import orchestration: snapshots, validation, and isolated staging."""
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError, ErrorCode
from app.db.models import DataSource, SourceSnapshot, ImportJob, ImportRowError, ImportDiff, DataVersion, PerformanceRecordVersion
from app.normalizers.catalog_normalizer import CatalogNormalizer
from app.validators.import_validator import ImportValidator

class ImportService:
    """Run a complete batch without modifying CatalogHead/current data."""
    def __init__(self, adapter, normalizer=None, validator=None):
        self.adapter = adapter
        self.normalizer = normalizer or CatalogNormalizer()
        self.validator = validator or ImportValidator()

    async def preview(self, db: AsyncSession, source: DataSource, sheet_id: str, template: dict, mapping: list[dict], actor_id: str | None = None) -> dict:
        raw = await self.adapter.fetch_snapshot(source, sheet_id)
        headers, rows = list(raw.get("headers", [])), list(raw.get("rows", []))
        content_hash = raw.get("contentHash") or hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
        # A missing provider revision is represented only in the idempotency
        # key.  It must not be copied into source_revision as content_hash.
        source_revision = raw.get("sourceRevision")
        template_id = template.get('id') or template.get('versionId') or 'template'
        normalized_revision = str(source_revision).strip() if source_revision is not None else ''
        key_revision = normalized_revision or f"content:{content_hash}"
        key = f"{source.id}:{sheet_id}:{key_revision}:{template_id}"
        existing_job = (await db.execute(select(ImportJob).where(ImportJob.idempotency_key == key))).scalar_one_or_none()
        if existing_job:
            # Compare the provider revision before returning a replay result. A
            # mismatch marks the old job stale and performs no snapshot/diff/
            # version writes.
            from app.services.sync_service import SyncService
            await SyncService().ensure_fresh(db, existing_job, source_revision)
            existing_snapshot = await db.get(SourceSnapshot, existing_job.source_snapshot_id)
            return {'previewId': existing_job.id, 'snapshotId': existing_snapshot.id if existing_snapshot else None, 'headers': headers, 'samples': [], 'idempotencyKey': key, 'status': 'duplicate'}
        snapshot = SourceSnapshot(source_id=source.id, source_revision=source_revision, content_hash=content_hash, raw_payload=raw, created_by=actor_id)
        db.add(snapshot); await db.flush()
        parsed = [self.normalizer.normalize_row(dict(zip(headers, row)), template, mapping) for row in rows]
        job = ImportJob(idempotency_key=key, source_snapshot_id=snapshot.id, template_version_id=template_id if template_id != 'template' else None, source_revision=source_revision, status='previewed', stats={'rowCount': len(rows) }, created_by=actor_id)
        db.add(job); await db.commit()
        return {'previewId': job.id, 'snapshotId': snapshot.id, 'headers': headers, 'samples': parsed[:10], 'idempotencyKey': key, 'status': 'NO_DATA' if not rows else 'previewed'}

    async def dry_run(self, db: AsyncSession, job_id: str, records: list[dict]) -> dict:
        job = (await db.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one_or_none()
        if not job: raise AppError(ErrorCode.NOT_FOUND, '导入任务不存在')
        report = self.validator.validate(records)
        for error in report['errors']:
            db.add(ImportRowError(import_job_id=job.id, source_row=error['sourceRow'], code=error['code'], message=error['message']))
        # Mirror create_staging's fallback for an invalid batch so both paths
        # record the same business code; a valid batch still records None.
        job.error_code = report.get('errorCode', 'IMPORT_VALIDATION_FAILED') if not report['valid'] else None
        job.status = report['status']; job.stats = {'rowCount': len(records), 'validCount': report['validCount'], 'errorCount': len(report['errors'])}
        await db.commit(); return report

    async def propagate_tombstones(self, db: AsyncSession, job_id: str, incoming_stable_keys: set[str]) -> int:
        """Record deleted keys as reviewable diffs; never mutate current records."""
        from app.db.models import PerformanceRecord
        existing = (await db.execute(select(PerformanceRecord.stable_key).where(PerformanceRecord.deleted.is_(False)))).scalars().all()
        deleted = set(existing) - set(incoming_stable_keys)
        for stable_key in deleted:
            db.add(ImportDiff(import_job_id=job_id, stable_key=stable_key, kind='deleted', before_json={'stableKey': stable_key}, after_json={'deleted': True}))
        await db.flush()
        return len(deleted)

    async def create_staging(self, db: AsyncSession, job_id: str, records: list) -> DataVersion:
        job = (await db.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one_or_none()
        if not job: raise AppError(ErrorCode.NOT_FOUND, '导入任务不存在')
        report = self.validator.validate(records)
        if not report['valid']:
            # Validation is a hard batch gate: no diff, version, or row write
            # may be committed for an empty/partially-invalid payload.
            job.status = report['status']; job.error_code = report.get('errorCode', 'IMPORT_VALIDATION_FAILED'); await db.commit()
            raise AppError(ErrorCode.VALIDATION_ERROR, '整批校验失败，未创建 staging')
        from app.db.models import PerformanceRecord
        incoming_keys = {r.get('stableKey', '') for r in records}
        # Resolve every incoming record before any staging/diff write. This
        # preserves the whole-batch zero-write guarantee on missing references.
        prepared_records = []
        for record in records:
            record_id = record.get('recordId')
            if not record_id:
                existing = (await db.execute(select(PerformanceRecord).where(PerformanceRecord.stable_key == record.get('stableKey')))).scalar_one_or_none()
                record_id = existing.id if existing else None
            if not record_id:
                await db.rollback()
                job.status = 'partial'; job.error_code = 'RECORD_NOT_FOUND'
                await db.commit()
                raise AppError(ErrorCode.VALIDATION_ERROR, '记录缺少有效 recordId，未创建 staging')
            prepared_records.append((record, record_id))
        existing_records = (await db.execute(select(PerformanceRecord).where(PerformanceRecord.deleted.is_(False)))).scalars().all()
        deleted_records = [record for record in existing_records if record.stable_key not in incoming_keys]
        deleted_count = await self.propagate_tombstones(db, job_id, incoming_keys)
        latest = (await db.execute(select(DataVersion.version_no).order_by(DataVersion.version_no.desc()))).scalars().first() or 0
        checksum = hashlib.sha256(json.dumps(records, sort_keys=True, default=str).encode()).hexdigest()
        version = DataVersion(version_no=latest + 1, status='staging', checksum=checksum, record_count=len(records) + deleted_count, error_count=0, import_job_id=job.id, source_snapshot_id=job.source_snapshot_id, template_version_id=job.template_version_id, created_by=job.created_by)
        db.add(version); await db.flush()
        for record, record_id in prepared_records:
            parsed = record.get('parsed', record.get('payload', {}))
            raw = record.get('raw', record.get('payload', {}))
            derived = record.get('derived', {})
            db.add(PerformanceRecordVersion(record_id=record_id, data_version_id=version.id, record_revision=record.get('revision', 1), raw_payload=raw, parsed_payload=parsed, derived_payload=derived, source_snapshot_id=job.source_snapshot_id, source_locator=record.get('sourceLocator')))
        for deleted in deleted_records:
            db.add(PerformanceRecordVersion(record_id=deleted.id, data_version_id=version.id, record_revision=deleted.revision, raw_payload={'stableKey': deleted.stable_key}, parsed_payload={'stableKey': deleted.stable_key}, derived_payload={'deleted': True}, source_snapshot_id=job.source_snapshot_id, source_locator='tombstone'))
        job.data_version_id = version.id; job.status = 'awaiting_review'; job.stats = {'rowCount': len(records), 'deletedCount': deleted_count, 'errorCount': 0}; await db.commit(); return version
