"""T04 gap round-2 #4: ``dry_run`` must not produce any business-data write.

Pins ``app/services/import_service.py`` ``ImportService.dry_run`` (lines 46-53).
A dry run is a *validation-only* pass: it must never create a ``DataVersion``,
a ``PerformanceRecordVersion``, an ``ImportDiff``, a ``SourceSnapshot`` nor
mutate a ``PerformanceRecord``.  The only writes it is allowed to make are its
own diagnostic rows and the job's own status/stats.

Counting scope (explicit): ``performance_records``, ``performance_record_versions``,
``import_diffs``, ``data_versions``, ``source_snapshots`` and ``import_row_errors``.
``ImportJob`` is deliberately excluded from the byte-count identity because
``dry_run`` is *expected* to record the run's status/stats on the job row.

* ``test_dry_run_clean_batch_writes_nothing`` -- all-valid batch: every counted
  table is row-count identical before and after, so "no write" holds literally.
* ``test_dry_run_partial_batch_writes_only_row_errors`` -- a partially invalid
  batch: the business tables are still untouched; the *only* new rows are the
  ``ImportRowError`` diagnostics (one per validation error), which is the
  documented purpose of the dry run.
"""

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError, ErrorCode
from app.db.models import (
    DataVersion,
    ImportDiff,
    ImportJob,
    ImportRowError,
    PerformanceRecord,
    PerformanceRecordVersion,
    SourceSnapshot,
)
from app.services.import_service import ImportService


class NoopAdapter:
    """Adapter placeholder; ``dry_run`` never fetches remotely."""


COUNTED_MODELS = (
    PerformanceRecord,
    PerformanceRecordVersion,
    ImportDiff,
    DataVersion,
    SourceSnapshot,
    ImportRowError,
)


async def _row_counts(db) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in COUNTED_MODELS:
        total = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        counts[model.__tablename__] = int(total)
    return counts


async def _job(db, key: str) -> ImportJob:
    job = ImportJob(idempotency_key=key, status="queued", stats={})
    db.add(job)
    await db.commit()
    return job


@pytest.mark.asyncio
async def test_dry_run_clean_batch_writes_nothing(db):
    """An all-valid dry run creates zero rows in every counted table."""
    job = await _job(db, "dry-run-clean-job")
    before = await _row_counts(db)
    # No existing rows yet: the identity assertion below is meaningful.
    assert all(count == 0 for count in before.values()), before

    records = [{"stableKey": "k-1"}, {"stableKey": "k-2"}]
    report = await ImportService(NoopAdapter()).dry_run(db, job.id, records)

    assert report["valid"] is True
    assert report["status"] == "validated"
    assert report["validCount"] == 2
    assert report["errors"] == []

    after = await _row_counts(db)
    assert after == before, f"dry_run wrote business data: before={before} after={after}"

    # The dry run reported its outcome on the job only (no business-data write).
    await db.refresh(job)
    assert job.status == "validated"
    assert job.error_code is None
    assert job.stats == {"rowCount": 2, "validCount": 2, "errorCount": 0}
    assert job.data_version_id is None


@pytest.mark.asyncio
async def test_dry_run_partial_batch_writes_only_row_errors(db):
    """A partially invalid dry run writes diagnostics but no staging artifacts."""
    job = await _job(db, "dry-run-partial-job")
    before = await _row_counts(db)

    records = [{"stableKey": "k-1"}, {"stableKey": ""}]  # second row: MISSING_STABLE_KEY
    report = await ImportService(NoopAdapter()).dry_run(db, job.id, records)

    assert report["valid"] is False
    assert report["status"] == "partial"
    assert report["validCount"] == 1
    assert len(report["errors"]) == 1
    assert report["errors"][0]["code"] == "MISSING_STABLE_KEY"

    after = await _row_counts(db)

    # Business/staging tables are untouched by the dry run.
    for table in ("performance_records", "performance_record_versions", "import_diffs", "data_versions", "source_snapshots"):
        assert after[table] == before[table], f"dry_run mutated {table}"

    # The only new rows are the one diagnostic per validation error.
    assert after["import_row_errors"] == before["import_row_errors"] + 1
    row_error = (
        await db.execute(
            select(ImportRowError).where(ImportRowError.import_job_id == job.id)
        )
    ).scalars().all()
    assert len(row_error) == 1
    assert row_error[0].code == "MISSING_STABLE_KEY"

    # Job records the dry-run outcome.  FIXED (was: "pinned, not fixed", asserted
    # ``error_code is None``): the validator never sets ``errorCode`` for a
    # partially invalid (non-empty) batch, so ``dry_run`` now applies the same
    # ``IMPORT_VALIDATION_FAILED`` fallback as ``create_staging`` and the two
    # paths agree.  The all-valid (``None``) and empty-batch (``NO_DATA``) results
    # are unchanged -- the fallback is guarded by ``not report['valid']``.
    await db.refresh(job)
    assert job.status == "partial"
    assert job.error_code == "IMPORT_VALIDATION_FAILED"
    assert job.stats == {"rowCount": 2, "validCount": 1, "errorCount": 1}
    assert job.data_version_id is None


@pytest.mark.asyncio
async def test_dry_run_and_create_staging_agree_on_partial_batch_error_code(db):
    """Cross-path consistency: a partially invalid batch records the same
    business code (``IMPORT_VALIDATION_FAILED``) for both ``dry_run`` and
    ``create_staging``, which is the closure of the pinned inconsistency."""
    records = [{"stableKey": "k-1"}, {"stableKey": ""}]  # second row: MISSING_STABLE_KEY

    dry_job = await _job(db, "dry-run-parity-job")
    dry_report = await ImportService(NoopAdapter()).dry_run(db, dry_job.id, records)
    assert dry_report["valid"] is False
    assert dry_report["status"] == "partial"
    await db.refresh(dry_job)
    assert dry_job.status == "partial"
    assert dry_job.error_code == "IMPORT_VALIDATION_FAILED"

    staging_job = await _job(db, "create-staging-parity-job")
    with pytest.raises(AppError) as error:
        await ImportService(NoopAdapter()).create_staging(db, staging_job.id, records)
    assert error.value.code == ErrorCode.VALIDATION_ERROR
    await db.refresh(staging_job)
    assert staging_job.status == "partial"
    assert staging_job.error_code == "IMPORT_VALIDATION_FAILED"

    # The two entry points now agree on the recorded code and status.
    assert dry_job.error_code == staging_job.error_code == "IMPORT_VALIDATION_FAILED"
    assert dry_job.status == staging_job.status == "partial"


@pytest.mark.asyncio
async def test_dry_run_unknown_job_raises_not_found(db):
    """A dry run against a missing job is a NOT_FOUND and writes nothing."""
    before = await _row_counts(db)
    with pytest.raises(AppError) as error:
        await ImportService(NoopAdapter()).dry_run(db, "does-not-exist", [{"stableKey": "k-1"}])
    assert error.value.code == ErrorCode.NOT_FOUND
    after = await _row_counts(db)
    assert after == before
