"""T04 gap round-2 #3: ``create_staging`` missing ``recordId`` -> rollback, no residue.

Pins ``app/services/import_service.py`` ``ImportService.create_staging``
(lines 65-104), specifically the reference-resolution guard at lines 79-89:

* every incoming record must resolve to a ``recordId`` (either supplied, or
  found by ``stable_key``); a record with neither rolls the transaction back,
  sets the job to ``partial`` / ``RECORD_NOT_FOUND`` and raises
  ``AppError(VALIDATION_ERROR)``;
* because the guard runs **before** any diff/version/record-version write, the
  rollback must leave **zero residue**: no ``DataVersion``, no
  ``PerformanceRecordVersion``, no ``ImportDiff`` and no changed
  ``PerformanceRecord``.  The tests below prove this with real row counts taken
  before and after the failing call -- asserting only the exception type would
  miss a half-written staging row.

A positive control is included: a batch whose records *do* resolve creates
exactly one staging ``DataVersion`` and the expected record-version rows, which
proves the zero-write assertion is not trivially true.
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


# Tables a staging write is allowed to touch.  ``ImportJob`` is excluded: the
# failed batch's own status/error report is an expected, permitted write.
TARGET_MODELS = (PerformanceRecord, PerformanceRecordVersion, ImportDiff, DataVersion)


async def _row_counts(db) -> dict[str, int]:
    """Snapshot the row count of every table a staging write could touch."""
    counts: dict[str, int] = {}
    for model in TARGET_MODELS:
        total = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        counts[model.__tablename__] = int(total)
    return counts


async def _seed_baseline(db) -> tuple[ImportJob, list[PerformanceRecord]]:
    """Seed two published records plus a queued import job (mirrors the batch gate suite)."""
    owner = User(username="rollback-owner", password_hash="x")
    software = Software(code="rollback-soft", name="Rollback Software")
    db.add_all([owner, software])
    await db.flush()
    profile = Profile(software_id=software.id, code="default", name="Default")
    template = DataTemplate(code="rollback-template", name="Rollback Template")
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
        idempotency_key="rollback-job",
        status="queued",
        source_revision="rev-1",
        stats={},
    )
    db.add(job)
    await db.commit()
    return job, records


@pytest.mark.asyncio
async def test_missing_record_id_rolls_back_with_no_staging_residue(db):
    """A batch containing an unresolvable record is rejected with zero residue."""
    job, records = await _seed_baseline(db)
    before = await _row_counts(db)
    assert before["performance_records"] == 2
    assert before["performance_record_versions"] == 0
    assert before["import_diffs"] == 0
    assert before["data_versions"] == 0

    # Two rows resolve normally; the third has no ``recordId`` and its
    # ``stableKey`` matches no existing record -> reference resolution fails.
    batch = [
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
            "stableKey": "k-missing",  # no recordId, no existing record
            "revision": 1,
            "parsed": {"a": 3},
            "raw": {"a": 3},
        },
    ]

    with pytest.raises(AppError) as error:
        await ImportService(NoopAdapter()).create_staging(db, job.id, batch)
    assert error.value.code == ErrorCode.VALIDATION_ERROR

    # The rollback left no residue: real row counts must be identical.
    after = await _row_counts(db)
    assert after == before, f"rollback left staging residue: before={before} after={after}"
    assert after["performance_record_versions"] == 0
    assert after["import_diffs"] == 0
    assert after["data_versions"] == 0

    # Existing records are untouched and no version was attached to the job.
    untouched = (
        await db.execute(
            select(PerformanceRecord.stable_key).order_by(PerformanceRecord.stable_key)
        )
    ).scalars().all()
    assert list(untouched) == ["k-existing-1", "k-existing-2"]
    assert job.data_version_id is None

    # The failure is reported on the job itself.
    await db.refresh(job)
    assert job.status == "partial"
    assert job.error_code == "RECORD_NOT_FOUND"


@pytest.mark.asyncio
async def test_resolvable_record_ids_create_exactly_one_staging_version(db):
    """Positive control: resolvable records create one DataVersion + N record versions."""
    job, records = await _seed_baseline(db)
    before = await _row_counts(db)

    batch = [
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
            "revision": 2,
            "parsed": {"a": 2},
            "raw": {"a": 2},
        },
    ]

    version = await ImportService(NoopAdapter()).create_staging(db, job.id, batch)

    after = await _row_counts(db)
    assert after["data_versions"] == before["data_versions"] + 1
    assert after["performance_record_versions"] == before["performance_record_versions"] + 2
    assert after["performance_records"] == before["performance_records"]  # not mutated
    assert after["import_diffs"] == before["import_diffs"]  # no tombstones for a full feed
    assert version.status == "staging"
    assert version.record_count == 2
    assert version.version_no == 1

    await db.refresh(job)
    assert job.status == "awaiting_review"
    assert job.data_version_id == version.id
