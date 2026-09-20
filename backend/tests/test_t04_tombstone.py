"""T04 tombstone deletion-diff propagation tests."""

import pytest
from sqlalchemy import select

from app.db.models import (
    DataTemplate,
    ImportDiff,
    ImportJob,
    PerformanceRecord,
    Profile,
    Software,
    TemplateVersion,
    User,
)
from app.services.import_service import ImportService


class NoopAdapter:
    """Adapter placeholder; tombstone propagation does not fetch remotely."""


@pytest.mark.asyncio
async def test_propagate_tombstones_writes_deleted_diff_without_mutating_record(db):
    """Missing incoming stable keys become reviewable deleted diffs only."""
    owner = User(username="tombstone-owner", password_hash="x")
    software = Software(code="tombstone-soft", name="Tombstone Software")
    db.add_all([owner, software])
    await db.flush()
    profile = Profile(software_id=software.id, code="default", name="Default")
    template = DataTemplate(code="tombstone-template", name="Tombstone Template")
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
    record = PerformanceRecord(
        stable_key="missing-from-feed",
        software_id=software.id,
        profile_id=profile.id,
        template_version_id=template_version.id,
        owner_user_id=owner.id,
        draft_payload={"value": 1},
        lifecycle_status="published",
    )
    db.add(record)
    job = ImportJob(idempotency_key="tombstone-job", status="queued", stats={})
    db.add(job)
    await db.flush()

    service = ImportService(NoopAdapter())
    deleted_count = await service.propagate_tombstones(db, job.id, {"still-present"})
    await db.commit()

    assert deleted_count == 1
    diff = (
        await db.execute(
            select(ImportDiff).where(
                ImportDiff.import_job_id == job.id,
                ImportDiff.kind == "deleted",
            )
        )
    ).scalar_one()
    assert diff.stable_key == "missing-from-feed"
    assert diff.after_json == {"deleted": True}

    unchanged = await db.get(PerformanceRecord, record.id)
    assert unchanged is not None
    assert unchanged.deleted is False
    head_result = await db.execute(select(ImportDiff).where(ImportDiff.kind == "deleted"))
    assert len(head_result.scalars().all()) == 1
