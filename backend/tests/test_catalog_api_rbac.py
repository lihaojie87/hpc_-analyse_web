import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import create_token_pair
from app.db.models import (
    DataTemplate,
    PerformanceRecord,
    Profile,
    Role,
    Software,
    TemplateVersion,
    User,
    UserRole,
)
from app.core.security import hash_password


async def _user_with_role(db, role_code: str, username: str) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password("Test1234"),
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.code == role_code))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.flush()
    return user


async def _token(user: User) -> str:
    return create_token_pair(user.id)[0]


@pytest_asyncio.fixture
async def catalog_fixture(db):
    owner = await _user_with_role(db, "provider", "catalog-owner")
    other = await _user_with_role(db, "provider", "catalog-other")
    viewer = await _user_with_role(db, "viewer", "catalog-viewer")
    admin = (
        await db.execute(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code == "admin")
        )
    ).scalar_one()
    software = Software(code=f"catalog-{uuid.uuid4().hex[:8]}", name="Catalog")
    db.add(software)
    await db.flush()
    profile = Profile(software_id=software.id, code="default", name="Default")
    template = DataTemplate(code=f"template-{uuid.uuid4().hex[:8]}", name="Template")
    db.add_all([profile, template])
    await db.flush()
    version = TemplateVersion(
        template_id=template.id,
        version_no=1,
        schema_json={},
        created_by=owner.id,
    )
    db.add(version)
    await db.flush()
    record = PerformanceRecord(
        stable_key=f"record-{uuid.uuid4().hex}",
        software_id=software.id,
        profile_id=profile.id,
        template_version_id=version.id,
        owner_user_id=owner.id,
        draft_payload={"value": 1},
    )
    db.add(record)
    await db.commit()
    return {
        "owner": owner,
        "other": other,
        "viewer": viewer,
        "admin": admin,
        "record": record,
    }


@pytest.mark.asyncio
async def test_record_list_and_detail_are_owner_isolated(client, catalog_fixture):
    fixture = catalog_fixture
    owner_headers = {"Authorization": f"Bearer {await _token(fixture['owner'])}"}
    other_headers = {"Authorization": f"Bearer {await _token(fixture['other'])}"}
    owner_list = await client.get("/api/v1/records", headers=owner_headers)
    assert owner_list.status_code == 200
    assert [item["id"] for item in owner_list.json()["items"]] == [fixture["record"].id]
    detail = await client.get(
        f"/api/v1/records/{fixture['record'].id}", headers=other_headers
    )
    assert detail.status_code == 404
    other_list = await client.get("/api/v1/records", headers=other_headers)
    assert other_list.status_code == 200
    assert other_list.json()["items"] == []


@pytest.mark.asyncio
async def test_admin_can_read_and_edit_other_users_record(client, catalog_fixture):
    fixture = catalog_fixture
    headers = {"Authorization": f"Bearer {await _token(fixture['admin'])}"}
    detail = await client.get(
        f"/api/v1/records/{fixture['record'].id}", headers=headers
    )
    assert detail.status_code == 200
    response = await client.patch(
        f"/api/v1/records/{fixture['record'].id}",
        headers={**headers, "If-Match": detail.json()["etag"]},
        json={"payload": {"value": 2}},
    )
    assert response.status_code == 200
    assert response.json()["payload"] == {"value": 2}


@pytest.mark.asyncio
async def test_regular_user_cannot_patch_other_users_record(client, catalog_fixture):
    fixture = catalog_fixture
    headers = {"Authorization": f"Bearer {await _token(fixture['other'])}"}
    response = await client.patch(
        f"/api/v1/records/{fixture['record'].id}",
        headers={**headers, "If-Match": f'"record-{fixture["record"].id}-1"'},
        json={"payload": {"value": 99}},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "etag",
    ["record-wrong-id-1", '"record-wrong-id-1"', '"record-{id}-bad"'],
)
async def test_patch_rejects_invalid_or_mismatched_etag(client, catalog_fixture, etag):
    fixture = catalog_fixture
    headers = {"Authorization": f"Bearer {await _token(fixture['owner'])}"}
    rendered = etag.replace("{id}", fixture["record"].id)
    response = await client.patch(
        f"/api/v1/records/{fixture['record'].id}",
        headers={**headers, "If-Match": rendered},
        json={"payload": {"value": 3}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    # Invalid or cross-resource tags must fail before loading/mutating data.
    detail = await client.get(
        f"/api/v1/records/{fixture['record'].id}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["revision"] == 1
    assert detail.json()["payload"] == {"value": 1}


@pytest.mark.asyncio
async def test_viewer_can_list_records(client, catalog_fixture):
    """Regression guard for outputs/viewer-403-investigation.md: a viewer must be
    able to list records (data:read), not be blocked by 403 because the RBAC seed
    was never applied. The conftest seeds the DB, so this also locks the contract
    that a freshly seeded viewer owns data:read."""
    fixture = catalog_fixture
    headers = {"Authorization": f"Bearer {await _token(fixture['viewer'])}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert "data:read" in me.json()["permissions"]
    r = await client.get("/api/v1/records", headers=headers)
    assert r.status_code == 200
    # viewer owns no records in this fixture -> empty list, not 403
    assert r.json()["items"] == []
