"""Route-layer coverage for ``POST /api/v1/sync/runs``.

Closes the registered gap: ``app/api/sync_routes.py`` ``create_sync_run``
(lines 30-44) had zero route-layer tests.  This module drives the real ASGI
app over HTTP (``httpx.AsyncClient`` + ``ASGITransport``) and asserts the exact
HTTP status *and* the response error envelope code for every guard in the
handler:

* empty / missing / blank / non-string ``sourceId`` or ``idempotencyKey``
  -> ``AppError(VALIDATION_ERROR, 'sourceId 和 idempotencyKey 不能为空')``
  -> **HTTP 422**, ``error.code == 'VALIDATION_ERROR'``;
* a ``sourceId`` that resolves to no ``DataSource``
  -> ``AppError(NOT_FOUND, '数据源不存在')`` -> **HTTP 404**, ``'NOT_FOUND'``;
* an existing but non-``active`` source
  -> ``SyncService.create_run`` raises ``AppError(CONFLICT, '数据源已禁用')``
  -> must surface as **HTTP 409**, ``'CONFLICT'`` (the重点 path: the service
  raised the CONFLICT in existing tests, but the *route* surfacing it as 409
  was never verified);
* ordering semantics: when a run with the same idempotency key already exists,
  ``create_run`` returns it **before** re-reading ``source.status``, so a replay
  against a since-disabled source is a 200 (old run), never a 409.

Error envelope shape (``app/core/errors.py:19``):
``{"error": {"code": <str>, "message": <str>, "requestId": <str>}}``.

Auth: ``require_permission("sync:execute")`` (``app/deps/auth_deps.py:21``).
Only the ``admin`` role holds ``sync:execute`` (``app/seed/seed_permissions.py:8``),
so tests mint an admin access token directly via ``create_token_pair`` — the
same helper used by ``tests/test_catalog_api_rbac.py`` — to stay deterministic
and avoid the login rate limiter.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.security import create_token_pair, hash_password
from app.db.models import DataSource, Role, SyncRun, User, UserRole

SYNC_RUNS_URL = "/api/v1/sync/runs"


async def _admin_token(db) -> str:
    """Access token for the seeded bootstrap admin (sole holder of sync:execute)."""
    admin = (
        await db.execute(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code == "admin")
        )
    ).scalar_one()
    return create_token_pair(admin.id)[0]


async def _source(db, status: str) -> DataSource:
    """Persist a DataSource with the requested status and return it."""
    source = DataSource(
        code=f"src-{uuid.uuid4().hex[:12]}",
        credential_ref="secret://test-ref",
        status=status,
    )
    db.add(source)
    await db.commit()
    return source


async def _viewer_token(db) -> str:
    """Access token for a freshly seeded viewer (holds no sync:execute)."""
    user = User(
        id=str(uuid.uuid4()),
        username=f"sync-viewer-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Test1234"),
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.code == "viewer"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return create_token_pair(user.id)[0]


async def _run_count(db) -> int:
    return int(
        (await db.execute(select(func.count()).select_from(SyncRun))).scalar_one()
    )


# --- 1. VALIDATION_ERROR -> HTTP 422 -----------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {},                                          # both fields absent
        {"sourceId": "any-source"},                  # idempotencyKey absent
        {"idempotencyKey": "k-any"},                 # sourceId absent
        {"sourceId": "   ", "idempotencyKey": "k"},  # blank sourceId
        {"sourceId": "any-source", "idempotencyKey": "  "},  # blank key
        {"sourceId": "", "idempotencyKey": ""},      # empty strings
        {"sourceId": 123, "idempotencyKey": "k"},    # non-string sourceId
        {"sourceId": "any-source", "idempotencyKey": 123},   # non-string key
        {"sourceId": None, "idempotencyKey": None},  # explicit nulls
    ],
)
@pytest.mark.asyncio
async def test_create_sync_run_invalid_payload_is_422_validation_error(
    client, db, payload
):
    headers = {"Authorization": f"Bearer {await _admin_token(db)}"}

    response = await client.post(SYNC_RUNS_URL, headers=headers, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    # The batch was rejected before any run row was created.
    assert await _run_count(db) == 0


# --- 2. NOT_FOUND -> HTTP 404 -------------------------------------------------

@pytest.mark.asyncio
async def test_create_sync_run_unknown_source_is_404_not_found(client, db):
    headers = {"Authorization": f"Bearer {await _admin_token(db)}"}

    response = await client.post(
        SYNC_RUNS_URL,
        headers=headers,
        json={"sourceId": "no-such-source", "idempotencyKey": f"k-{uuid.uuid4().hex}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert await _run_count(db) == 0


# --- 3. inactive source -> CONFLICT surfaced as HTTP 409 (the key path) ------

@pytest.mark.asyncio
async def test_create_sync_run_inactive_source_is_409_conflict(client, db):
    source = await _source(db, status="inactive")
    headers = {"Authorization": f"Bearer {await _admin_token(db)}"}

    response = await client.post(
        SYNC_RUNS_URL,
        headers=headers,
        json={"sourceId": source.id, "idempotencyKey": f"k-{uuid.uuid4().hex}"},
    )

    # SyncService.create_run raises AppError(CONFLICT) -> the route must emit 409.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    # A rejected run leaves no row behind.
    assert await _run_count(db) == 0


# --- 4. ordering: existing key short-circuits before the status check --------

@pytest.mark.asyncio
async def test_create_sync_run_reuses_existing_key_without_rechecking_source(
    client, db
):
    """A replay of an already-seen key returns the old run, never a CONFLICT.

    ``SyncService.create_run`` (``app/services/sync_service.py:10-11``) looks up
    the idempotency key *first* and returns the existing run before it reads
    ``source.status``.  So after the source is disabled, re-posting the same key
    must still be a 200 with the identical run id -- not a 409.
    """
    source = await _source(db, status="active")
    headers = {"Authorization": f"Bearer {await _admin_token(db)}"}
    key = f"k-{uuid.uuid4().hex}"

    first = await client.post(
        SYNC_RUNS_URL, headers=headers, json={"sourceId": source.id, "idempotencyKey": key}
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    # Disable the source *after* the run already exists.
    source.status = "inactive"
    db.add(source)
    await db.commit()

    replay = await client.post(
        SYNC_RUNS_URL, headers=headers, json={"sourceId": source.id, "idempotencyKey": key}
    )

    assert replay.status_code == 200          # not 409: status is not re-checked
    assert replay.json()["id"] == first_id    # the original run is returned
    assert await _run_count(db) == 1          # no duplicate run created


# --- happy path (locks the success contract the error paths contrast with) ---

@pytest.mark.asyncio
async def test_create_sync_run_active_source_creates_queued_run(client, db):
    source = await _source(db, status="active")
    headers = {"Authorization": f"Bearer {await _admin_token(db)}"}
    key = f"k-{uuid.uuid4().hex}"

    response = await client.post(
        SYNC_RUNS_URL, headers=headers, json={"sourceId": source.id, "idempotencyKey": key}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sourceId"] == source.id
    assert body["idempotencyKey"] == key
    assert body["status"] == "queued"
    assert body["attemptCount"] == 0
    assert body["stats"] == {}
    assert await _run_count(db) == 1


# --- additional route-layer guard: permission gate ---------------------------

@pytest.mark.asyncio
async def test_create_sync_run_requires_sync_execute_permission(client, db):
    source = await _source(db, status="active")
    headers = {"Authorization": f"Bearer {await _viewer_token(db)}"}

    response = await client.post(
        SYNC_RUNS_URL,
        headers=headers,
        json={"sourceId": source.id, "idempotencyKey": f"k-{uuid.uuid4().hex}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert await _run_count(db) == 0
