"""T04 gap round-2 #2: ``SyncService.retry`` -> ``dead_letter`` state machine.

Pins ``app/services/sync_service.py`` ``SyncService.retry`` (lines 15-20):

* ``retry`` is only legal from ``failed`` / ``dead_letter``; any other status
  raises ``AppError(CONFLICT, '当前任务不可重试')`` **without** touching
  ``attempt_count``;
* a legal retry increments ``attempt_count`` by exactly one and re-queues the
  job (``status == 'queued'``, ``error_code`` cleared) until the attempt budget
  is exhausted;
* the moment ``attempt_count`` exceeds ``max_attempts`` the job lands in
  ``dead_letter`` and stays there;
* a ``dead_letter`` job is itself a legal retry source, so recovery re-enters
  the queue while the budget allows.

These assert the *complete* transition sequence (counts and terminal states),
not merely that a status field changed.
"""

import pytest

from app.core.errors import AppError, ErrorCode
from app.db.models import ImportJob
from app.services.sync_service import SyncService


@pytest.mark.asyncio
async def test_retry_increments_attempt_count_until_budget_then_dead_letters(db):
    """attempt_count 0->4 across four retries; the 4th (4 > 3) lands in dead_letter."""
    job = ImportJob(
        idempotency_key="retry-budget-job",
        status="failed",
        attempt_count=0,
        error_code="IMPORT_FAILED",
        stats={},
    )
    db.add(job)
    await db.commit()
    service = SyncService()

    # Retry 1: 0 -> 1, requeued, error cleared.
    await service.retry(db, job, max_attempts=3)
    assert job.attempt_count == 1
    assert job.status == "queued"
    assert job.error_code is None

    # The worker runs and fails again -> simulate by flipping status back.
    job.status = "failed"
    job.error_code = "IMPORT_FAILED"
    await db.commit()

    # Retry 2: 1 -> 2, requeued.
    await service.retry(db, job, max_attempts=3)
    assert job.attempt_count == 2
    assert job.status == "queued"

    job.status = "failed"
    job.error_code = "IMPORT_FAILED"
    await db.commit()

    # Retry 3: 2 -> 3, still within budget (3 <= 3) -> requeued.
    await service.retry(db, job, max_attempts=3)
    assert job.attempt_count == 3
    assert job.status == "queued"

    job.status = "failed"
    job.error_code = "IMPORT_FAILED"
    await db.commit()

    # Retry 4: 3 -> 4, exceeds budget (4 > 3) -> dead_letter.
    await service.retry(db, job, max_attempts=3)
    assert job.attempt_count == 4
    assert job.status == "dead_letter"

    # Persisted, not just in-memory.
    await db.refresh(job)
    assert (job.attempt_count, job.status) == (4, "dead_letter")


@pytest.mark.asyncio
async def test_retry_rejects_non_retryable_status_and_keeps_count(db):
    """A queued job cannot be retried; the CONFLICT is raised and no count changes."""
    job = ImportJob(
        idempotency_key="retry-invalid-state-job",
        status="queued",
        attempt_count=0,
        stats={},
    )
    db.add(job)
    await db.commit()

    with pytest.raises(AppError) as error:
        await SyncService().retry(db, job, max_attempts=3)

    assert error.value.code == ErrorCode.CONFLICT
    assert job.attempt_count == 0  # untouched by the rejected call
    await db.refresh(job)
    assert job.status == "queued"


@pytest.mark.asyncio
async def test_dead_letter_job_can_reenter_queue_within_budget(db):
    """``dead_letter`` is a legal retry source: a fresh budget re-queues it."""
    job = ImportJob(
        idempotency_key="retry-dead-letter-recovery-job",
        status="dead_letter",
        attempt_count=0,
        error_code="IMPORT_EXHAUSTED",
        stats={},
    )
    db.add(job)
    await db.commit()

    await SyncService().retry(db, job, max_attempts=3)

    assert job.attempt_count == 1
    assert job.status == "queued"
    assert job.error_code is None
    await db.refresh(job)
    assert (job.attempt_count, job.status) == (1, "queued")
