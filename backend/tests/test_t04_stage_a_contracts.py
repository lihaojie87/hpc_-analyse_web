import pytest
from app.adapters.feishu import FeishuAdapter
from app.core.errors import AppError, ErrorCode
from app.db.models import DataSource, ImportJob
from app.services.import_service import ImportService
from app.services.sync_service import SyncService


class SnapshotAdapter:
    def __init__(self, revision):
        self.revision = revision

    async def fetch_snapshot(self, source, sheet_id):
        return {
            "headers": ["stable_key"],
            "rows": [["k-1"]],
            "sourceRevision": self.revision,
            "contentHash": "hash-1",
        }


@pytest.mark.asyncio
async def test_stale_preview_marks_existing_job_without_snapshot_write(db):
    source = DataSource(code="stage-a-source", credential_ref="secret/ref")
    db.add(source)
    await db.flush()
    job = ImportJob(
        idempotency_key=f"{source.id}:sheet-1:rev-2:template",
        source_revision="rev-1",
        status="queued",
    )
    db.add(job)
    await db.commit()

    with pytest.raises(AppError) as error:
        await ImportService(SnapshotAdapter("rev-2")).preview(
            db, source, "sheet-1", {}, [], None
        )
    assert error.value.code == ErrorCode.CONFLICT
    await db.refresh(job)
    assert job.status == "stale"
    assert job.error_code == "IMPORT_STALE"


@pytest.mark.asyncio
async def test_sync_mark_stale_sets_only_job_state(db):
    job = ImportJob(idempotency_key="stale", status="queued")
    db.add(job)
    await db.commit()
    await SyncService().mark_stale(db, job)
    await db.refresh(job)
    assert (job.status, job.error_code) == ("stale", "IMPORT_STALE")


@pytest.mark.asyncio
async def test_feishu_snapshot_uses_provider_revision(monkeypatch):
    adapter = FeishuAdapter(token="opaque")
    source = DataSource(code="revision-source", credential_ref="secret/ref", workbook_token="book")
    async def read_values(workbook_id, sheet_id, range_=None):
        return {"revision": 7, "valueRange": {"values": [["stable_key"], ["k-1"]]}}
    monkeypatch.setattr(adapter, "read_values", read_values)
    snapshot = await adapter.fetch_snapshot(source, "sheet-1")
    assert snapshot["sourceRevision"] == "7"
    assert snapshot["headers"] == ["stable_key"]
    assert snapshot["rows"] == [["k-1"]]


@pytest.mark.asyncio
async def test_feishu_snapshot_without_revision_keeps_none(monkeypatch):
    adapter = FeishuAdapter(token="opaque")
    source = DataSource(code="no-revision-source", credential_ref="secret/ref", workbook_token="book")
    async def read_values(workbook_id, sheet_id, range_=None):
        return {"valueRange": {"values": [["stable_key"], ["k-1"]]}}
    monkeypatch.setattr(adapter, "read_values", read_values)
    snapshot = await adapter.fetch_snapshot(source, "sheet-1")
    assert snapshot["sourceRevision"] is None
    assert snapshot["contentHash"]
