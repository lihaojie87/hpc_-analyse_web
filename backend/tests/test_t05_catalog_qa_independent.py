"""Independent QA gates for T05 public catalog endpoints."""

from test_t05_catalog_public import headers, make_user, seed_snapshot


async def test_all_read_roles_share_current_snapshot_and_have_no_write_routes(client, db):
    owner = await make_user(db, "provider", "qa-t05-owner")
    viewer = await make_user(db, "viewer", "qa-t05-viewer")
    provider = await make_user(db, "provider", "qa-t05-provider")
    admin = await make_user(db, "admin", "qa-t05-admin")
    records = await seed_snapshot(db, owner, count=2)

    responses = [
        await client.get("/api/v1/catalog/records", headers=headers(user))
        for user in (viewer, provider, admin)
    ]
    assert [response.status_code for response in responses] == [200, 200, 200]
    expected_ids = {record.id for record in records}
    for response in responses:
        body = response.json()
        assert {item["id"] for item in body["items"]} == expected_ids
        assert body["versionNo"] == 1
        assert body["dataVersionId"]

    methods = ("post", "put", "patch", "delete")
    for method in methods:
        response = await client.request(
            method,
            "/api/v1/catalog/records",
            headers=headers(viewer),
            json={},
        )
        assert response.status_code not in {200, 201, 202, 204}, (
            method,
            response.status_code,
        )
        response = await client.request(
            method,
            f"/api/v1/catalog/records/{records[0].id}",
            headers=headers(viewer),
            json={},
        )
        assert response.status_code not in {200, 201, 202, 204}, (
            method,
            response.status_code,
        )


async def test_prd_software_id_filter_is_server_side(client, db):
    owner = await make_user(db, "provider", "qa-t05-filter-owner")
    viewer = await make_user(db, "viewer", "qa-t05-filter-viewer")
    records = await seed_snapshot(db, owner, count=3)
    software_id = records[0].software_id

    response = await client.get(
        f"/api/v1/catalog/records?softwareId={software_id}",
        headers=headers(viewer),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(records)
    assert all(item["softwareId"] == software_id for item in body["items"])


async def test_detail_is_current_snapshot_only_and_has_version_metadata(client, db):
    owner = await make_user(db, "provider", "qa-t05-detail-owner")
    viewer = await make_user(db, "viewer", "qa-t05-detail-viewer")
    records = await seed_snapshot(db, owner, count=1)

    response = await client.get(
        f"/api/v1/catalog/records/{records[0].id}", headers=headers(viewer)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dataVersionId"] and body["versionNo"] == 1
    assert "ownerUserId" not in body
    assert "draftPayload" not in body
    # Public projection must preserve the immutable snapshot components and
    # source provenance; it must not collapse them into the draft payload.
    assert body["rawPayload"] == {"metric": 0, "keyword": "visible"}
    assert body["parsedPayload"] == {"metric": 0, "keyword": "visible"}
    assert body["derivedPayload"] == {}
    assert "sourceSnapshotId" in body and "sourceLocator" in body

    lifecycle_filtered = await client.get(
        "/api/v1/catalog/records?lifecycleStatus=not-a-real-status",
        headers=headers(viewer),
    )
    assert lifecycle_filtered.status_code == 200
    assert lifecycle_filtered.json()["total"] == 0

    unknown = await client.get(
        "/api/v1/catalog/records/does-not-exist", headers=headers(viewer)
    )
    assert unknown.status_code == 404
