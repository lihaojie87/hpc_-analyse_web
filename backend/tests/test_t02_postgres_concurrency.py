"""PostgreSQL-only publish race regression.

Skipped unless ``HPC_POSTGRES_TEST_URL`` is configured; SQLite does not provide
row-level locking semantics equivalent to production PostgreSQL.

Isolation (see ``tests/pg_isolation.py``): this test shares whatever database
``HPC_POSTGRES_TEST_URL`` points at with ``test_t04_postgres_publish_concurrency``
and with any previous run.  It therefore

* mints a run-unique token for every inserted username,
* derives ``data_versions.version_no`` from the live ``MAX(version_no)`` while
  holding the ``catalog_heads`` row lock (so it can never collide on
  ``uq_data_version_no``),
* asserts the head revision *relative* to the value observed before the race
  (never the absolute ``1``), and
* removes exactly the rows it created in ``finally``.

The concurrency contract itself is unchanged: two transactions read the same
head revision, both attempt to publish, and the ``FOR UPDATE`` lock plus the
compare-and-set must let exactly one win.
"""

import asyncio

import pytest
from sqlalchemy import select

from app.db.models import CatalogHead, DataVersion, User
from app.services.version_service import publish

try:  # `python -m pytest` puts the backend root on sys.path -> `tests` package
    from tests.pg_isolation import CATALOG_SCOPE, pg_race_scope, postgres_test_url
except ImportError:  # `pytest` console script puts the tests dir itself on sys.path
    from pg_isolation import CATALOG_SCOPE, pg_race_scope, postgres_test_url

POSTGRES_URL = postgres_test_url()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="HPC_POSTGRES_TEST_URL not configured; production concurrency not covered",
)
async def test_two_postgres_transactions_only_one_publish_wins():
    """Two concurrent publishes at the same head revision: exactly one wins."""
    async with pg_race_scope("t02-pg-race") as scope:
        barrier = asyncio.Barrier(2)

        async def attempt(version_id: str, reviewer_id: str) -> bool:
            async with scope.sessions() as db:
                version = (
                    await db.execute(
                        select(DataVersion).where(DataVersion.id == version_id)
                    )
                ).scalar_one()
                reviewer = (
                    await db.execute(select(User).where(User.id == reviewer_id))
                ).scalar_one()
                await barrier.wait()  # maximise interleaving
                try:
                    await publish(db, version, reviewer, scope.head_revision_before)
                    return True
                except Exception:
                    await db.rollback()
                    return False

        results = await asyncio.gather(
            attempt(scope.version_ids[0], scope.reviewers[0].id),
            attempt(scope.version_ids[1], scope.reviewers[1].id),
        )
        assert sum(results) == 1

        async with scope.sessions() as db:
            head = (
                await db.execute(
                    select(CatalogHead).where(CatalogHead.scope_key == CATALOG_SCOPE)
                )
            ).scalar_one()
            assert head.current_revision == scope.expected_head_revision_after_race

            # Scope the "exactly one published" assertion to this run's rows so a
            # catalogue that already holds published versions stays valid.
            published = (
                await db.execute(
                    select(DataVersion).where(
                        DataVersion.id.in_(scope.version_ids),
                        DataVersion.status == "published",
                    )
                )
            ).scalars().all()
            assert len(published) == 1
