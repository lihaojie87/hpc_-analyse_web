"""T04 gap round-2 #5: repeated ``preview`` of the same feed is idempotent.

Pins ``app/services/import_service.py`` ``ImportService.preview`` (lines 19-44).
The idempotency key is derived from ``source.id : sheet_id : provider-revision
(or content hash) : template``; a replay that resolves to the *same* key must:

* short-circuit on the existing job and return ``status == 'duplicate'``;
* reuse the original ``previewId`` / ``snapshotId`` / ``idempotencyKey``;
* perform **no** extra write -- the ``SourceSnapshot`` and ``ImportJob`` row
  counts must be identical after N replays (real DB counts, not a return-value
  check).

The tests drive the service with a small offline adapter, so no network is
touched and the "same batch" condition is exact (identical revision + payload).
"""

import pytest
from sqlalchemy import func, select

from app.db.models import DataSource, ImportJob, SourceSnapshot
from app.services.import_service import ImportService


class SnapshotAdapter:
    """Offline adapter returning a fixed provider revision and payload."""

    def __init__(self, revision: str | None = "rev-1") -> None:
        self.revision = revision

    async def fetch_snapshot(self, source, sheet_id):
        return {
            "headers": ["stable_key"],
            "rows": [["k-1"], ["k-2"]],
            "sourceRevision": self.revision,
            "contentHash": "hash-1",
        }


async def _counts(db) -> tuple[int, int]:
    snapshots = (await db.execute(select(func.count()).select_from(SourceSnapshot))).scalar_one()
    jobs = (await db.execute(select(func.count()).select_from(ImportJob))).scalar_one()
    return int(snapshots), int(jobs)


@pytest.mark.asyncio
async def test_repeated_preview_of_same_feed_is_idempotent(db):
    """Previewing the identical feed twice returns a duplicate and writes nothing more."""
    source = DataSource(code="preview-replay-source", credential_ref="secret/ref")
    db.add(source)
    await db.flush()
    service = ImportService(SnapshotAdapter("rev-1"))

    first = await service.preview(db, source, "sheet-1", {}, [], None)
    assert first["status"] == "previewed"
    assert first["previewId"]
    assert first["snapshotId"]
    assert first["samples"]  # the first preview carries sample rows
    snapshots_after_first, jobs_after_first = await _counts(db)
    assert (snapshots_after_first, jobs_after_first) == (1, 1)

    second = await service.preview(db, source, "sheet-1", {}, [], None)
    assert second["status"] == "duplicate"
    assert second["previewId"] == first["previewId"]
    assert second["snapshotId"] == first["snapshotId"]
    assert second["idempotencyKey"] == first["idempotencyKey"]
    assert second["samples"] == []

    third = await service.preview(db, source, "sheet-1", {}, [], None)
    assert third["status"] == "duplicate"
    assert third["previewId"] == first["previewId"]

    snapshots_after_replay, jobs_after_replay = await _counts(db)
    assert (snapshots_after_replay, jobs_after_replay) == (snapshots_after_first, jobs_after_first)

    # Exactly one snapshot/job exists and it is the first preview's row.
    job = (
        await db.execute(
            select(ImportJob).where(ImportJob.idempotency_key == first["idempotencyKey"])
        )
    ).scalar_one()
    assert job.id == first["previewId"]
    assert job.source_snapshot_id == first["snapshotId"]


@pytest.mark.asyncio
async def test_preview_replay_via_fresh_service_instance_is_still_idempotent(db):
    """Idempotency is database-backed: a brand-new service instance still dedupes."""
    source = DataSource(code="preview-replay-fresh-source", credential_ref="secret/ref")
    db.add(source)
    await db.flush()

    first = await ImportService(SnapshotAdapter("rev-7")).preview(
        db, source, "sheet-1", {}, [], None
    )
    before = await _counts(db)

    replay = await ImportService(SnapshotAdapter("rev-7")).preview(
        db, source, "sheet-1", {}, [], None
    )

    assert replay["status"] == "duplicate"
    assert replay["previewId"] == first["previewId"]
    assert await _counts(db) == before
