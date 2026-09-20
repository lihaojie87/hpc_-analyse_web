"""T04 coverage gap #2: a whole-batch validation failure must write zero rows.

Invariant under test (项目推进记录 §7 不变量 / `架构设计-T04.md` 校验门禁):
validation is a *hard batch gate*.  When an entire incoming batch fails
validation the system must never persist a half-written result -- no
``PerformanceRecordVersion``, no ``ImportDiff`` and no ``DataVersion`` may be
created, and no existing ``PerformanceRecord`` may be mutated.  The only
permitted write is the job's own terminal status/error report.

These tests assert *row-count identity* before/after the failing call so that a
silent partial write (a "半成品" staging) is caught rather than merely covered.
A negative control (``_tmp_gap2_negative_control.py``, run out of band) confirms
the assertion is live: bypassing the gate at runtime makes staging write rows,
so the ``after == before`` assertion genuinely detects partial writes.
"""

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError, ErrorCode
from app.db.models import (
    DataTemplate,
    DataVersion,
    ImportDiff,
    ImportJob,
    PerformanceRecord,
    PerformanceRecordVersion,
    Profile,
    Software,
    TemplateVersion,
    User,
)
from app.services.import_service import ImportService


class NoopAdapter:
    """Adapter placeholder; ``create_staging`` never fetches remotely."""


# Every table a staging write is allowed to touch.  ``ImportJob`` itself is
# intentionally excluded: recording the failed batch's own status is expected.
TARGET_MODELS = (PerformanceRecord, PerformanceRecordVersion, ImportDiff, DataVersion)


async def _row_counts(db) -> dict[str, int]:
    """Snapshot the row count of every table a staging write could touch."""
    snapshot: dict[str, int] = {}
    for model in TARGET_MODELS:
        total = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        snapshot[model.__tablename__] = int(total)
    return snapshot


async def _seed_baseline(db) -> tuple[ImportJob, list[PerformanceRecord]]:
    """Seed two existing published records plus a queued import job."""
    owner = User(username="zero-write-owner", password_hash="x")
    software = Software(code="zero-write-soft", name="Zero Write Software")
    db.add_all([owner, software])
    await db.flush()
    profile = Profile(software_id=software.id, code="default", name="Default")
    template = DataTemplate(code="zero-write-template", name="Zero Write Template")
    db.add_all([profile, template])
    await db.flush()
    template_version = TemplateVersion(
        template_id=template.id,
        version_no=1,
        schema_json={},
        created_by=owner.id,
    )
    db.add(template_version)
    await db.flush()
    records = [
        PerformanceRecord(
            stable_key="k-existing-1",
            software_id=software.id,
            profile_id=profile.id,
            template_version_id=template_version.id,
            owner_user_id=owner.id,
            draft_payload={"v": 1},
            lifecycle_status="published",
        ),
        PerformanceRecord(
            stable_key="k-existing-2",
            software_id=software.id,
            profile_id=profile.id,
            template_version_id=template_version.id,
            owner_user_id=owner.id,
            draft_payload={"v": 2},
            lifecycle_status="published",
        ),
    ]
    db.add_all(records)
    await db.flush()
    job = ImportJob(
        idempotency_key="zero-write-job",
        status="queued",
        source_revision="rev-1",
        stats={},
    )
    db.add(job)
    await db.commit()
    return job, records


async def _assert_zero_write(db, job: ImportJob, before: dict[str, int]) -> None:
    """Assert no target table changed and the job recorded the failure."""
    after = await _row_counts(db)
    assert after == before, f"failed batch wrote rows: before={before} after={after}"
    assert after["performance_record_versions"] == 0
    assert after["import_diffs"] == 0
    assert after["data_versions"] == 0
    untouched = (
        await db.execute(
            select(PerformanceRecord.stable_key).order_by(PerformanceRecord.stable_key)
        )
    ).scalars().all()
    assert list(untouched) == ["k-existing-1", "k-existing-2"]
    assert job.data_version_id is None


@pytest.mark.asyncio
async def test_batch_with_missing_stable_key_writes_no_rows_versions_or_diffs(db):
    """A batch containing a row without a stable key is rejected whole.

    The batch below has two valid rows and one row whose stable key is empty
    (``MISSING_STABLE_KEY``).  The single bad row must invalidate the whole batch
    so the staging gate fires before any diff/version/record-version write.
    """
    job, records = await _seed_baseline(db)
    before = await _row_counts(db)
    # Explicit baselines so the identity assertion below is meaningful.
    assert before["performance_records"] == 2
    assert before["performance_record_versions"] == 0
    assert before["import_diffs"] == 0
    assert before["data_versions"] == 0

    partially_invalid_batch = [
        {
            "stableKey": "k-existing-1",
            "recordId": records[0].id,
            "revision": 1,
            "parsed": {"a": 1},
            "raw": {"a": 1},
        },
        {
            "stableKey": "k-existing-2",
            "recordId": records[1].id,
            "revision": 1,
            "parsed": {"a": 2},
            "raw": {"a": 2},
        },
        {
            "stableKey": "",  # MISSING_STABLE_KEY -> whole batch invalid
            "recordId": records[1].id,
            "revision": 1,
            "parsed": {"a": 3},
            "raw": {"a": 3},
        },
    ]

    with pytest.raises(AppError) as error:
        await ImportService(NoopAdapter()).create_staging(
            db, job.id, partially_invalid_batch
        )
    assert error.value.code == ErrorCode.VALIDATION_ERROR

    await _assert_zero_write(db, job, before)

    # The failure is reported on the job itself.
    await db.refresh(job)
    assert job.status == "partial"
    assert job.error_code == "IMPORT_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_batch_with_duplicate_stable_key_writes_no_rows_versions_or_diffs(db):
    """A batch containing a duplicated stable key is likewise rejected whole."""
    job, records = await _seed_baseline(db)
    before = await _row_counts(db)

    partially_invalid_batch = [
        {
            "stableKey": "k-existing-1",
            "recordId": records[0].id,
            "revision": 1,
            "parsed": {"a": 1},
            "raw": {"a": 1},
        },
        {
            "stableKey": "k-dup",
            "recordId": records[1].id,
            "revision": 1,
            "parsed": {"a": 2},
            "raw": {"a": 2},
        },
        {
            "stableKey": "k-dup",  # DUPLICATE_STABLE_KEY -> whole batch invalid
            "recordId": records[1].id,
            "revision": 1,
            "parsed": {"a": 3},
            "raw": {"a": 3},
        },
    ]

    with pytest.raises(AppError) as error:
        await ImportService(NoopAdapter()).create_staging(
            db, job.id, partially_invalid_batch
        )
    assert error.value.code == ErrorCode.VALIDATION_ERROR

    await _assert_zero_write(db, job, before)

    await db.refresh(job)
    assert job.status == "partial"
    assert job.error_code == "IMPORT_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_empty_batch_writes_no_rows_versions_or_diffs(db):
    """An empty batch is a whole-batch failure: NO_DATA, still zero writes."""
    job, _ = await _seed_baseline(db)
    before = await _row_counts(db)

    with pytest.raises(AppError) as error:
        await ImportService(NoopAdapter()).create_staging(db, job.id, [])
    assert error.value.code == ErrorCode.VALIDATION_ERROR

    await _assert_zero_write(db, job, before)

    await db.refresh(job)
    assert job.status == "partial"
    assert job.error_code == "NO_DATA"
