import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_token_pair, hash_password
from app.db.models import (
    CatalogHead,
    DataTemplate,
    DataVersion,
    PerformanceRecord,
    PerformanceRecordVersion,
    Profile,
    Role,
    Software,
    TemplateVersion,
    User,
    UserRole,
)


async def make_user(db, role_code: str, username: str) -> User:
    user = User(id=str(uuid.uuid4()), username=username, password_hash=hash_password("Test1234"))
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.code == role_code))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.flush()
    return user


async def seed_snapshot(db, owner: User, count: int = 3) -> list[PerformanceRecord]:
    software = Software(code=f"soft-{uuid.uuid4().hex[:8]}", name="Public Software")
    profile = Profile(code="profile-a", name="Profile A")
    template = DataTemplate(code=f"tpl-{uuid.uuid4().hex[:8]}", name="Public Template")
    db.add(software)
    await db.flush()
    profile.software_id = software.id
    db.add_all([profile, template])
    await db.flush()
    template_version = TemplateVersion(template_id=template.id, version_no=1, schema_json={}, created_by=owner.id)
    db.add(template_version)
    await db.flush()
    records: list[PerformanceRecord] = []
    for index in range(count):
        record = PerformanceRecord(
            stable_key=f"public-{index:02d}", software_id=software.id, profile_id=profile.id,
            template_version_id=template_version.id, owner_user_id=owner.id,
            draft_payload={"metric": index, "keyword": "visible"},
        )
        db.add(record)
        records.append(record)
    await db.flush()
    version = DataVersion(version_no=1, revision=1, status="published", checksum="checksum", record_count=count)
    db.add(version)
    await db.flush()
    for record in records:
        db.add(PerformanceRecordVersion(
            record_id=record.id, data_version_id=version.id, record_revision=record.revision,
            raw_payload=record.draft_payload, parsed_payload=record.draft_payload, derived_payload={},
        ))
    head = (await db.execute(select(CatalogHead).where(CatalogHead.scope_key == "performance_catalog"))).scalar_one()
    head.current_version_id = version.id
    head.current_revision = 1
    await db.commit()
    return records


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token_pair(user.id)[0]}"}


@pytest.mark.asyncio
async def test_viewer_reads_current_public_snapshot(client, db):
    owner = await make_user(db, "provider", "t05-owner")
    viewer = await make_user(db, "viewer", "t05-viewer")
    records = await seed_snapshot(db, owner)
    response = await client.get("/api/v1/catalog/records", headers=headers(viewer))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3 and len(body["items"]) == 3
    assert body["dataVersionId"] and body["versionNo"] == 1
    assert {item["id"] for item in body["items"]} == {record.id for record in records}
    assert "ownerUserId" not in body["items"][0]


@pytest.mark.asyncio
async def test_public_detail_and_filters_are_snapshot_bound(client, db):
    owner = await make_user(db, "provider", "t05-owner-detail")
    viewer = await make_user(db, "viewer", "t05-viewer-detail")
    records = await seed_snapshot(db, owner)
    detail = await client.get(f"/api/v1/catalog/records/{records[0].id}", headers=headers(viewer))
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["dataVersionId"]
    assert {"rawPayload", "parsedPayload", "derivedPayload", "sourceSnapshotId", "sourceLocator"}.issubset(detail_body)
    assert detail_body["rawPayload"]["metric"] == 0
    filtered = await client.get(
        f"/api/v1/catalog/records?softwareId={records[0].software_id}&profileId={records[0].profile_id}&lifecycleStatus=draft",
        headers=headers(viewer),
    )
    assert filtered.status_code == 200 and filtered.json()["total"] == 3
    filtered = await client.get("/api/v1/catalog/records?keyword=public-01", headers=headers(viewer))
    assert filtered.status_code == 200 and filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["stableKey"] == "public-01"


@pytest.mark.asyncio
async def test_public_pagination_is_stable_without_duplicates(client, db):
    owner = await make_user(db, "provider", "t05-owner-page")
    viewer = await make_user(db, "viewer", "t05-viewer-page")
    await seed_snapshot(db, owner, 5)
    first = await client.get("/api/v1/catalog/records?page=1&pageSize=2", headers=headers(viewer))
    second = await client.get("/api/v1/catalog/records?page=2&pageSize=2", headers=headers(viewer))
    assert first.status_code == second.status_code == 200
    ids1 = [item["id"] for item in first.json()["items"]]
    ids2 = [item["id"] for item in second.json()["items"]]
    assert len(set(ids1) & set(ids2)) == 0 and first.json()["total"] == second.json()["total"] == 5


@pytest.mark.asyncio
async def test_empty_current_returns_empty_success(client, db):
    viewer = await make_user(db, "viewer", "t05-viewer-empty")
    await db.commit()
    response = await client.get("/api/v1/catalog/records", headers=headers(viewer))
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0


@pytest.mark.asyncio
async def test_unknown_and_non_current_records_are_hidden(client, db):
    owner = await make_user(db, "provider", "t05-owner-hidden")
    viewer = await make_user(db, "viewer", "t05-viewer-hidden")
    records = await seed_snapshot(db, owner)
    hidden = PerformanceRecord(
        stable_key="draft-only", software_id=records[0].software_id, profile_id=records[0].profile_id,
        template_version_id=records[0].template_version_id, owner_user_id=owner.id,
    )
    db.add(hidden)
    await db.commit()
    response = await client.get(f"/api/v1/catalog/records/{hidden.id}", headers=headers(viewer))
    unknown = await client.get("/api/v1/catalog/records/not-present", headers=headers(viewer))
    assert response.status_code == unknown.status_code == 404


@pytest.mark.asyncio
async def test_catalog_has_no_write_routes(client, db):
    viewer = await make_user(db, "viewer", "t05-viewer-write")
    response = await client.post("/api/v1/catalog/records", headers=headers(viewer), json={})
    assert response.status_code in {404, 405, 422}
