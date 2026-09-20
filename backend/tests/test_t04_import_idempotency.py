"""T04 ``SyncService.create_run`` scheduling contracts.

Covers the idempotency short-circuit and the inactive-source guard:

* a repeated ``idempotency_key`` returns the *same* run (no duplicate row);
* a source that is **not** ``active`` is refused with
  ``AppError(ErrorCode.CONFLICT, '数据源已禁用')`` **before** any ``SyncRun`` is
  persisted (gap round-3: the guard at ``app/services/sync_service.py:12`` had
  no test).
"""

import pytest
from sqlalchemy import select

from app.core.errors import AppError, ErrorCode
from app.db.models import DataSource, SyncRun
from app.services.sync_service import SyncService

@pytest.mark.asyncio
async def test_sync_idempotency_returns_existing_run(db):
    source = DataSource(code='idem-source', credential_ref='secret/ref')
    db.add(source); await db.flush()
    service = SyncService()
    first = await service.create_run(db, source, 'source:hash:template')
    second = await service.create_run(db, source, 'source:hash:template')
    assert first.id == second.id


@pytest.mark.asyncio
async def test_create_run_rejects_inactive_source_with_conflict(db):
    """A non-active source is refused with CONFLICT and no run is persisted.

    Contract read from ``app/services/sync_service.py`` ``create_run`` (9-13):
    the ``existing`` idempotency short-circuit runs first, then
    ``if source.status != 'active': raise AppError(ErrorCode.CONFLICT,
    '数据源已禁用')`` fires *before* the ``SyncRun`` insert.  We therefore use a
    fresh ``idempotency_key`` (no pre-existing run) so control actually reaches
    the guard, and assert the exact code / message / HTTP status plus the
    absence of a persisted run for that key.
    """
    source = DataSource(
        code="disabled-source",
        credential_ref="secret/ref",
        status="disabled",  # any non-'active' value trips the guard
    )
    db.add(source)
    await db.flush()

    service = SyncService()
    with pytest.raises(AppError) as error:
        await service.create_run(db, source, "disabled-source:hash:template")

    assert error.value.code == ErrorCode.CONFLICT
    assert error.value.message == "数据源已禁用"
    assert error.value.http_status == 409

    # The guard fires before the insert: no run row exists for that key.
    persisted = (
        await db.execute(
            select(SyncRun).where(
                SyncRun.idempotency_key == "disabled-source:hash:template"
            )
        )
    ).scalar_one_or_none()
    assert persisted is None
