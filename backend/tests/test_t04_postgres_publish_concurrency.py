"""T04 gap round-2 #6: PostgreSQL-only publish race for the atomic-publish path.

WHY THIS SKIPS LOCALLY
----------------------
Atomic publish relies on ``SELECT ... FOR UPDATE`` row locking plus a
compare-and-set on ``CatalogHead.current_revision`` (see
``app/services/version_service.py::publish``).  SQLite serialises writers, so it
**cannot** reproduce the two-transactions-commit-interleaved race that
PostgreSQL exercises; asserting it on SQLite would be a false positive.

The test is guarded by ``skipif(not POSTGRES_URL)`` and is reported as
**skipped**, never as a pass, when ``HPC_POSTGRES_TEST_URL`` is unset.  Set it to
a disposable/local PostgreSQL instance and run
``pytest tests/test_t04_postgres_publish_concurrency.py`` to execute.

ISOLATION
---------
This test and ``test_t02_postgres_concurrency.py`` target the *same* database.
Both use ``tests/pg_isolation.py`` so that neither depends on an empty database
nor on being the only writer:

* run-unique usernames (no ``users_username_key`` collisions, no picking up
  reviewers left behind by an earlier run);
* ``version_no`` taken from the live ``MAX(version_no)`` under the head row
  lock, so the two files can no longer collide on ``uq_data_version_no``;
* assertions expressed relative to the head revision observed before the race;
* id/token-scoped teardown that restores the shared ``catalog_heads`` row.

The lock/CAS semantics asserted below are unchanged.
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
    reason=(
        "HPC_POSTGRES_TEST_URL not configured; production PostgreSQL concurrency "
        "not covered (no local PG/Docker)"
    ),
)
async def test_two_postgres_transactions_only_one_t04_publish_wins():
    """Two concurrent publishes at the same head revision: exactly one must win.

    Proven facts when executed on PostgreSQL:
    * both transactions read the same ``current_revision`` and attempt to publish;
    * the ``FOR UPDATE`` lock + revision compare-and-set allow only one commit;
    * the loser raises and rolls back (``sum(results) == 1``);
    * ``CatalogHead.current_revision`` advances by exactly one;
    * exactly one of this run's ``DataVersion`` rows ends up ``published``.
    """
    async with pg_race_scope("t04-pg-race") as scope:
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

            published = (
                await db.execute(
                    select(DataVersion).where(
                        DataVersion.id.in_(scope.version_ids),
                        DataVersion.status == "published",
                    )
                )
            ).scalars().all()
            assert len(published) == 1
