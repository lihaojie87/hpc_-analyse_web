"""P5-B regression: startup RBAC seed must survive >=2 admin users.

``seed_permissions.seed`` used ``scalar_one_or_none()`` on a ``User``-join that
emits one row per admin membership. With two or more admins it raised
``MultipleResultsFound`` *before* ``commit()``, so the whole seed transaction was
rolled back and ``main._seed_on_startup`` swallowed the error -- silently
disabling RBAC seeding. These tests pin the corrected behaviour.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, func, select

from app.db.models import Permission, Role, RolePermission, User, UserRole
from app.db.session import SessionLocal
from app.seed.seed_permissions import PERMS, seed


async def _add_admin_user(db, username: str) -> User:
    """Attach a fresh admin user, increasing the admin-membership row count."""
    user = User(id=str(uuid.uuid4()), username=username, password_hash="x")
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.code == "admin"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.flush()
    return user


async def _admin_membership_count(db) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(UserRole)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.code == "admin")
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_seed_succeeds_and_commits_with_multiple_admin_users(db):
    """Pre-populate 2 extra admins, delete one grant, and prove seed() repairs it.

    The pre-seed deletion means a passing assertion proves seed() not only failed
    to raise but actually reached ``db.commit()`` (the grant is restored).
    """
    admin_role = (await db.execute(select(Role).where(Role.code == "admin"))).scalar_one()
    audit_perm = (await db.execute(select(Permission).where(Permission.code == "audit:read"))).scalar_one()

    # conftest's seed already created the bootstrap admin; add two more so the
    # admin-membership join returns >1 row (the historical failure trigger).
    await _add_admin_user(db, "p5-admin-alpha")
    await _add_admin_user(db, "p5-admin-beta")

    # Remove one admin grant so a repaired seed is observable via a change.
    await db.execute(
        delete(RolePermission).where(
            RolePermission.role_id == admin_role.id,
            RolePermission.permission_id == audit_perm.id,
        )
    )
    await db.commit()

    async with SessionLocal() as check:
        assert await _admin_membership_count(check) >= 3
        missing = (
            await check.execute(
                select(RolePermission).where(
                    RolePermission.role_id == admin_role.id,
                    RolePermission.permission_id == audit_perm.id,
                )
            )
        ).scalar_one_or_none()
        assert missing is None, "precondition: audit:read grant must be absent"

    # Before the fix this raised MultipleResultsFound (and never committed);
    # a regression makes this line raise, failing the test.
    await seed()

    async with SessionLocal() as verify:
        restored = (
            await verify.execute(
                select(RolePermission).where(
                    RolePermission.role_id == admin_role.id,
                    RolePermission.permission_id == audit_perm.id,
                )
            )
        ).scalar_one_or_none()
        assert restored is not None, "seed() must have committed the restored grant"

        granted = (
            await verify.execute(
                select(RolePermission).where(RolePermission.role_id == admin_role.id)
            )
        ).scalars().all()
        assert len(granted) == len(PERMS)

        codes = set((await verify.execute(select(Permission.code))).scalars().all())
        assert set(PERMS) <= codes


@pytest.mark.asyncio
async def test_seed_is_idempotent_with_multiple_admins(db):
    """Repeated seed() calls with several admins must stay quiet and idempotent."""
    await _add_admin_user(db, "p5-admin-gamma")
    await _add_admin_user(db, "p5-admin-delta")
    await db.commit()

    await seed()
    await seed()

    async with SessionLocal() as verify:
        admin_role = (await verify.execute(select(Role).where(Role.code == "admin"))).scalar_one()
        granted = (
            await verify.execute(
                select(RolePermission).where(RolePermission.role_id == admin_role.id)
            )
        ).scalars().all()
        # No duplicate grants accumulate across runs (composite PK + existence check).
        assert len(granted) == len(PERMS)
