"""Independent black-box/service gates for T05.1 Outbox + SSE."""

import asyncio
import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.core.security import create_token_pair, hash_password
from app.db.models import (
    CatalogHead,
    DataTemplate,
    DataVersion,
    OutboxEvent,
    PerformanceRecord,
    PerformanceRecordVersion,
    Profile,
    Role,
    Software,
    TemplateVersion,
    User,
    UserRole,
)
from app.services.event_service import broker, dispatch_pending, sse_message
from app.services.version_service import approve, publish


async def make_user(db, role_code: str, username: str) -> User:
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


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token_pair(user.id)[0]}"}


async def seed_approved_version(db, creator: User, reviewer: User) -> DataVersion:
    software = Software(code=f"s-{uuid.uuid4().hex[:8]}", name="SSE")
    profile = Profile(code=f"p-{uuid.uuid4().hex[:8]}", name="Profile")
    template = DataTemplate(code=f"t-{uuid.uuid4().hex[:8]}", name="Template")
    db.add(software)
    await db.flush()
    profile.software_id = software.id
    db.add_all([profile, template])
    await db.flush()
    template_version = TemplateVersion(
        template_id=template.id, version_no=1, schema_json={}, created_by=creator.id
    )
    db.add(template_version)
    await db.flush()
    record = PerformanceRecord(
        stable_key=f"r-{uuid.uuid4().hex[:8]}",
        software_id=software.id,
        profile_id=profile.id,
        template_version_id=template_version.id,
        owner_user_id=creator.id,
        draft_payload={"secret": "business-value"},
    )
    db.add(record)
    await db.flush()
    version = DataVersion(
        version_no=1,
        revision=1,
        status="approved",
        checksum="x",
        record_count=1,
        created_by=creator.id,
    )
    db.add(version)
    await db.flush()
    db.add(
        PerformanceRecordVersion(
            record_id=record.id,
            data_version_id=version.id,
            record_revision=record.revision,
            raw_payload=record.draft_payload,
            parsed_payload=record.draft_payload,
            derived_payload={},
        )
    )
    await db.flush()
    return version


@pytest.mark.asyncio
async def test_publish_stages_outbox_and_dispatches_only_after_commit(db):
    creator = await make_user(db, "provider", "t51-creator")
    reviewer = await make_user(db, "admin", "t51-reviewer")
    version = await seed_approved_version(db, creator, reviewer)
    head = (await db.execute(select(CatalogHead))).scalar_one()

    await publish(db, version, reviewer, head.current_revision)
    row = (
        await db.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == version.id)
        )
    ).scalar_one()
    assert row.status == "pending"
    assert row.payload.keys() >= {"dataVersionId", "versionNo", "publishedAt"}
    assert "business-value" not in json.dumps(row.payload)

    dispatched = await dispatch_pending(db)
    assert dispatched == 1
    assert row.status == "dispatched"
    assert row.attempts == 1


@pytest.mark.asyncio
async def test_publish_validation_failure_creates_no_outbox(db):
    creator = await make_user(db, "provider", "t51-fail-creator")
    reviewer = await make_user(db, "admin", "t51-fail-reviewer")
    version = await seed_approved_version(db, creator, reviewer)
    head = (await db.execute(select(CatalogHead))).scalar_one()

    with pytest.raises(AppError):
        await publish(db, version, reviewer, head.current_revision + 1)
    count = (
        await db.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == version.id))
    ).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_sse_authorization_protocol_and_payload_isolation(client, db, monkeypatch):
    viewer = await make_user(db, "viewer", "t51-viewer")
    await db.commit()

    event = {
        "id": "qa-event-1",
        "type": "data_version.published",
        "data": {"dataVersionId": "dv-1", "versionNo": 1},
    }

    async def finite_subscribe(last_event_id=None):
        yield event

    monkeypatch.setattr(broker, "subscribe", finite_subscribe)
    response = await client.get("/api/v1/events/stream", headers=auth_headers(viewer))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: qa-event-1" in response.text
    assert "event: data_version.published" in response.text
    assert "business-value" not in response.text
    assert "rawPayload" not in response.text

    unauthenticated = await client.get("/api/v1/events/stream")
    assert unauthenticated.status_code == 401


@pytest.mark.asyncio
async def test_last_event_id_replays_only_new_history():
    while broker._history:
        broker._history.popleft()
    broker._published_by_id.clear()
    broker._sequence = 0
    await broker.publish({"type": "data_version.published", "data": {"versionNo": 1}})
    await broker.publish({"type": "data_version.published", "data": {"versionNo": 2}})
    stream = broker.subscribe(last_event_id="1")
    first = await asyncio.wait_for(anext(stream), timeout=1)
    assert first["id"] == "2"
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("role_code", ["provider", "admin"])
async def test_provider_and_admin_can_read_sse_stream(client, db, monkeypatch, role_code):
    user = await make_user(db, role_code, f"t51-{role_code}-stream")
    await db.commit()

    async def finite_subscribe(last_event_id=None):
        yield {"id": "role-event", "type": "data_version.published", "data": {"dataVersionId": "dv-role", "versionNo": 2}}

    monkeypatch.setattr(broker, "subscribe", finite_subscribe)
    response = await client.get("/api/v1/events/stream", headers=auth_headers(user))
    assert response.status_code == 200
    assert "role-event" in response.text


@pytest.mark.asyncio
async def test_invalid_last_event_id_is_recovery_not_server_error(client, db, monkeypatch):
    viewer = await make_user(db, "viewer", "t51-invalid-last-event")
    await db.commit()
    seen: list[str | None] = []

    async def finite_subscribe(last_event_id=None):
        seen.append(last_event_id)
        yield {"id": "recovery-event", "type": "data_version.published", "data": {"dataVersionId": "dv-recovery", "versionNo": 3}}

    monkeypatch.setattr(broker, "subscribe", finite_subscribe)
    response = await client.get("/api/v1/events/stream", headers={**auth_headers(viewer), "Last-Event-ID": "not-a-number"})
    assert response.status_code == 200
    assert "recovery-event" in response.text
    assert seen == ["not-a-number"]
