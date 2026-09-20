"""Per-run isolation helpers for the PostgreSQL-only publish-race tests.

WHY THIS MODULE EXISTS
----------------------
``test_t02_postgres_concurrency.py`` and
``test_t04_postgres_publish_concurrency.py`` exercise the *same* lock / CAS
contract (``SELECT ... FOR UPDATE`` on ``catalog_heads`` plus a compare-and-set
on ``current_revision`` in ``app/services/version_service.py::publish``) and
both target whatever database ``HPC_POSTGRES_TEST_URL`` points at.

Historically each file hard-coded:

* usernames (``pg-race-owner``, ``t04-pg-race-reviewer-a``, ...);
* ``DataVersion.version_no`` values ``1`` and ``2``;
* the expectation ``CatalogHead.current_revision == 1``;

and neither cleaned up after itself.  That produced two defects that share one
root cause -- *the fixtures were not isolated*:

1. **Not repeatable.**  A second run of ``test_t02_...`` hit
   ``UniqueViolation: users_username_key`` (and the same for the T04 twin); and
   ``select(...).like('pg-race-reviewer-%')`` picked up reviewers left behind by
   the previous run, so the two racing sessions were not even the ones the test
   had just created.
2. **Mutually destructive.**  Whichever file ran second against the shared
   database hit ``UniqueViolation: uq_data_version_no`` on ``version_no = 1``.

The helpers below remove all three assumptions **without weakening the
concurrency semantics under test**:

* every run mints a unique token; all inserted identifiers embed it;
* ``version_no`` is derived from the current ``MAX(version_no)`` while holding
  the ``catalog_heads`` row lock, so two runs can never pick the same value and
  a non-empty database is perfectly acceptable;
* expectations are expressed *relative* to the head revision observed before the
  race rather than as an absolute ``1``;
* ``finally`` restores the shared ``catalog_heads`` row to its pre-run state and
  deletes exactly the rows this run created.

Deliberately **not** used: ``TRUNCATE``, whole-table deletes, or any statement
that touches rows the run did not create.  Deleting/restoring is always scoped
by primary key (``data_versions.id``) or by the run-unique token
(``users.username``).
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import CatalogHead, DataVersion, User

#: ``catalog_heads`` is a singleton keyed by ``scope_key`` (see 0002 migration).
CATALOG_SCOPE = "performance_catalog"


def postgres_test_url() -> str | None:
    """Return the configured test URL, or ``None`` when PostgreSQL is absent.

    Tests evaluate this at import time so the ``skipif`` guard behaves exactly
    as before (an unconfigured environment reports *skipped*, never a pass).
    """
    return os.getenv("HPC_POSTGRES_TEST_URL")


def run_token() -> str:
    """Mint a short, URL/identifier-safe token that is unique per test run."""
    return secrets.token_hex(6)


@dataclass
class PgRaceScope:
    """Everything a publish-race test needs, scoped to a single run."""

    token: str
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    owner: User
    reviewers: list[User]
    versions: list[DataVersion]
    head_created: bool
    head_revision_before: int
    head_version_id_before: str | None
    _version_ids: list[str] = field(default_factory=list)

    @property
    def version_ids(self) -> list[str]:
        """Primary keys of the two ``data_versions`` rows created by this run."""
        return self._version_ids

    @property
    def usernames(self) -> list[str]:
        """Usernames created by this run (owner + reviewers)."""
        return [self.owner.username, *(user.username for user in self.reviewers)]

    @property
    def expected_head_revision_after_race(self) -> int:
        """Exactly one winner means the head revision advances by one."""
        return self.head_revision_before + 1


async def _load_head(db: AsyncSession) -> CatalogHead | None:
    return (
        await db.execute(
            select(CatalogHead).where(CatalogHead.scope_key == CATALOG_SCOPE)
        )
    ).scalar_one_or_none()


async def _restore(scope: PgRaceScope) -> None:
    """Undo everything this run did, then leave the database as it was found."""
    async with scope.sessions() as db:
        head = await _load_head(db)
        if head is not None:
            if scope.head_created:
                # This run created the singleton: removing it restores the
                # pre-run state exactly (no other row referenced it before).
                await db.delete(head)
            else:
                # Restore the shared head *before* its target DataVersion is
                # removed, otherwise the FK from current_version_id blocks the
                # delete.
                head.current_revision = scope.head_revision_before
                head.current_version_id = scope.head_version_id_before
        if scope.version_ids:
            await db.execute(
                delete(DataVersion).where(DataVersion.id.in_(scope.version_ids))
            )
        if scope.usernames:
            await db.execute(
                delete(User).where(User.username.in_(scope.usernames))
            )
        await db.commit()


@asynccontextmanager
async def pg_race_scope(prefix: str) -> AsyncIterator[PgRaceScope]:
    """Prepare an isolated publish-race scope and guarantee its cleanup.

    ``prefix`` only shapes the generated usernames (e.g. ``"t02-pg-race"``) so
    leftovers would be attributable; isolation itself comes from the unique
    token and from the id-scoped teardown.

    Raises ``RuntimeError`` when ``HPC_POSTGRES_TEST_URL`` is unset -- callers
    are expected to be guarded by ``skipif`` and therefore never reach this.
    """
    url = postgres_test_url()
    if not url:
        raise RuntimeError("HPC_POSTGRES_TEST_URL is not configured")

    token = run_token()
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    owner = User(username=f"{prefix}-owner-{token}", password_hash="x")
    reviewers = [
        User(username=f"{prefix}-reviewer-{suffix}-{token}", password_hash="x")
        for suffix in ("a", "b")
    ]
    scope = PgRaceScope(
        token=token,
        engine=engine,
        sessions=sessions,
        owner=owner,
        reviewers=reviewers,
        versions=[],
        head_created=False,
        head_revision_before=0,
        head_version_id_before=None,
    )

    try:
        async with sessions() as setup:
            setup.add_all([owner, *reviewers])
            await setup.flush()

            # Lock the head row first: this serialises concurrent *setups* too,
            # which makes the MAX(version_no) read below race-free.
            head = (
                await setup.execute(
                    select(CatalogHead)
                    .where(CatalogHead.scope_key == CATALOG_SCOPE)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if head is None:
                head = CatalogHead(scope_key=CATALOG_SCOPE, current_revision=0)
                setup.add(head)
                scope.head_created = True
            else:
                scope.head_revision_before = head.current_revision
                scope.head_version_id_before = head.current_version_id

            highest = (
                await setup.execute(select(func.max(DataVersion.version_no)))
            ).scalar_one_or_none() or 0
            base = int(highest) + 1

            versions = [
                DataVersion(
                    version_no=base,
                    revision=1,
                    status="approved",
                    checksum=f"{prefix}-{token}-a",
                    record_count=1,
                    created_by=owner.id,
                ),
                DataVersion(
                    version_no=base + 1,
                    revision=1,
                    status="approved",
                    checksum=f"{prefix}-{token}-b",
                    record_count=1,
                    created_by=owner.id,
                ),
            ]
            setup.add_all(versions)
            await setup.commit()

            scope.versions = versions
            scope._version_ids = [version.id for version in versions]

        yield scope
    finally:
        try:
            await _restore(scope)
        finally:
            await engine.dispose()
