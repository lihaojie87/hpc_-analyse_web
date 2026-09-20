"""RBAC contract tests for the ``template:read`` permission code.

These lock the positive contract introduced by the template-read change
(provider/admin may read templates and template versions) and, equally
important, the negative contract (viewer must stay 403; provider must not
gain any template *management* capability).
"""

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import Permission, Role, RolePermission
from app.seed.seed_permissions import MATRIX, PERMS

ADMIN_CREDENTIALS = {"username": "admin", "password": "Admin1234"}


async def _login(client, username: str, password: str) -> str:
    """Return an access token for an existing account."""
    login = (
        await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
    ).json()
    return login["accessToken"]


async def _register_and_assign(client, username: str, password: str, role_code: str) -> str:
    """Register a fresh (viewer-default) account, promote it, return its token."""
    await client.post(
        "/api/v1/auth/register", json={"username": username, "password": password}
    )
    admin_token = await _login(client, **ADMIN_CREDENTIALS)
    users = (
        await client.get(
            "/api/v1/users", headers={"Authorization": f"Bearer {admin_token}"}
        )
    ).json()["items"]
    uid = next(u["id"] for u in users if u["username"] == username)
    assign = await client.post(
        f"/api/v1/users/{uid}/roles",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"roleCode": role_code},
    )
    assert assign.status_code == 200 and role_code in assign.json()["roles"]
    return await _login(client, username, password)


# --- Q5.1: positive read contracts -------------------------------------------


@pytest.mark.asyncio
async def test_provider_can_list_templates(client):
    """Provider reads templates so it can pick a version when creating records."""
    token = await _register_and_assign(client, "provider_read", "Provider123", "provider")
    r = await client.get(
        "/api/v1/templates", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200 and "items" in r.json()


@pytest.mark.asyncio
async def test_admin_can_list_templates(client):
    """Admin (holds template:manage) must also pass the read guard."""
    token = await _login(client, **ADMIN_CREDENTIALS)
    r = await client.get(
        "/api/v1/templates", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200 and "items" in r.json()


@pytest.mark.asyncio
async def test_provider_can_list_template_versions(client):
    """Second read endpoint provider needs (version selection). No data => 200 []."""
    token = await _register_and_assign(client, "provider_read", "Provider123", "provider")
    r = await client.get(
        "/api/v1/templates/nonexistent-template/versions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200 and isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_viewer_forbidden_templates(client):
    """Regression guard: viewer must NOT hold template:read."""
    await client.post(
        "/api/v1/auth/register", json={"username": "viewer_t", "password": "Viewer123"}
    )
    token = await _login(client, "viewer_t", "Viewer123")
    r = await client.get(
        "/api/v1/templates", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_viewer_forbidden_template_versions(client):
    """Regression guard: viewer must NOT read template versions either."""
    await client.post(
        "/api/v1/auth/register", json={"username": "viewer_t", "password": "Viewer123"}
    )
    token = await _login(client, "viewer_t", "Viewer123")
    r = await client.get(
        "/api/v1/templates/any-id/versions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


# --- Q5.2: anti-escalation guards ---------------------------------------------


@pytest.mark.asyncio
async def test_provider_cannot_create_template(client):
    token = await _register_and_assign(client, "provider_w", "Provider123", "provider")
    r = await client.post(
        "/api/v1/templates",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "tpl-x", "name": "Tpl X"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_provider_cannot_create_template_version(client):
    token = await _register_and_assign(client, "provider_w", "Provider123", "provider")
    r = await client.post(
        "/api/v1/templates/tpl-x/versions",
        headers={"Authorization": f"Bearer {token}"},
        json={"schema": {}},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_provider_cannot_publish_template_version(client):
    token = await _register_and_assign(client, "provider_w", "Provider123", "provider")
    r = await client.post(
        "/api/v1/templates/versions/ver-x/publish",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# --- Q5.3: matrix completeness + seed idempotency -----------------------------


@pytest.mark.asyncio
async def test_permission_matrix_is_complete(db):
    """Guard against a code being added to the endpoints but not to the seed."""
    assert len(PERMS) == 15 and "template:read" in PERMS

    # No orphan permission code: every declared code is bound to >=1 role.
    bound = set().union(*(set(codes) for codes in MATRIX.values()))
    assert set(PERMS) <= bound

    assert set(MATRIX["provider"]) == {
        "data:read",
        "data:create",
        "data:update-own",
        "data:submit",
        "data:export",
        "template:read",
    }
    assert set(MATRIX["viewer"]) == {"data:read", "data:export"}
    assert "template:read" not in MATRIX["viewer"]
    assert set(MATRIX["admin"]) == set(PERMS)

    # Materialised rows must match the declared matrix.
    perms = {p.code: p.id for p in (await db.execute(select(Permission))).scalars().all()}
    roles = {r.code: r.id for r in (await db.execute(select(Role))).scalars().all()}
    role_perm_ids = (await db.execute(select(RolePermission))).scalars().all()
    assert len(perms) == 15 and len(roles) == 3 and len(role_perm_ids) == 23

    id_to_code = {v: k for k, v in perms.items()}
    by_role: dict[str, set[str]] = {}
    for rp in role_perm_ids:
        code = next(rc for rc, rid in roles.items() if rid == rp.role_id)
        by_role.setdefault(code, set()).add(id_to_code[rp.permission_id])
    assert by_role["viewer"] == {"data:read", "data:export"}
    assert by_role["provider"] == set(MATRIX["provider"])
    assert by_role["admin"] == set(PERMS)


@pytest.mark.asyncio
async def test_seed_is_idempotent():
    """Running seed twice must not add duplicate rows."""
    from app.db.session import SessionLocal
    from app.seed.seed_permissions import seed

    async def counts() -> tuple[int, int, int]:
        async with SessionLocal() as session:
            return (
                len((await session.execute(select(Permission))).scalars().all()),
                len((await session.execute(select(Role))).scalars().all()),
                len((await session.execute(select(RolePermission))).scalars().all()),
            )

    await seed()
    first = await counts()
    await seed()
    second = await counts()
    assert first == second == (15, 3, 23)


@pytest.mark.asyncio
async def test_require_permission_any_of(monkeypatch, db):
    """Lock the new any-of semantics of require_permission(*codes)."""
    from app.deps import auth_deps

    class Actor:
        id = "u-any-of"

    async def allow_b(_db, _user_id):
        return [], ["b"]

    async def deny(_db, _user_id):
        return [], ["c"]

    dep = auth_deps.require_permission("a", "b")

    monkeypatch.setattr(auth_deps, "get_roles_permissions", allow_b)
    assert (await dep(user=Actor(), db=db)).id == "u-any-of"

    monkeypatch.setattr(auth_deps, "get_roles_permissions", deny)
    with pytest.raises(AppError) as err:
        await dep(user=Actor(), db=db)
    assert err.value.code.value == "FORBIDDEN"
