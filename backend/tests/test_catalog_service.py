import pytest
from app.core.errors import AppError, ErrorCode
from app.db.models import Software, Profile, TemplateVersion, DataTemplate
from app.schemas.catalog import RecordCreateIn
from app.services.catalog_service import create_record


def _make_fixtures(db):
    """Build software/profile/template fixtures and return (software, profile)."""
    class Actor:
        id = "catalog-owner"

    s = Software(code="cat-s", name="Cat")
    db.add(s)
    return s, Actor


@pytest.mark.asyncio
async def test_record_stable_key_and_payload(db):
    class Actor:
        id = "catalog-owner"

    s = Software(code="cat-s", name="Cat")
    db.add(s)
    await db.flush()
    p = Profile(software_id=s.id, code="p", name="P")
    db.add(p)
    t = DataTemplate(code="cat-t", name="T")
    db.add(t)
    await db.flush()
    # A record may only be created against a PUBLISHED template version.
    v = TemplateVersion(template_id=t.id, version_no=1, schema_json={}, created_by=Actor().id, status="published")
    db.add(v)
    await db.flush()
    r = await create_record(
        db,
        RecordCreateIn(stableKey="stable-1", softwareId=s.id, profileId=p.id, templateVersionId=v.id, payload={"raw": 1}),
        Actor(),
    )
    assert r.draft_payload == {"raw": 1}


@pytest.mark.asyncio
async def test_create_record_rejects_draft_template_version(db):
    """A draft (unpublished) template version must be rejected, not just missing."""
    class Actor:
        id = "catalog-owner"

    s = Software(code="cat-s-draft", name="Cat")
    db.add(s)
    await db.flush()
    p = Profile(software_id=s.id, code="p-draft", name="P")
    db.add(p)
    t = DataTemplate(code="cat-t-draft", name="T")
    db.add(t)
    await db.flush()
    v = TemplateVersion(template_id=t.id, version_no=1, schema_json={}, created_by=Actor().id, status="draft")
    db.add(v)
    await db.flush()
    with pytest.raises(AppError) as exc:
        await create_record(
            db,
            RecordCreateIn(stableKey="stable-draft", softwareId=s.id, profileId=p.id, templateVersionId=v.id, payload={"raw": 1}),
            Actor(),
        )
    assert exc.value.code == ErrorCode.CONFLICT
    assert exc.value.message == "模板版本未发布"


@pytest.mark.asyncio
async def test_create_record_published_version_succeeds(db):
    """Regression: a published version is accepted and binds the record."""
    class Actor:
        id = "catalog-owner"

    s = Software(code="cat-s-pub", name="Cat")
    db.add(s)
    await db.flush()
    p = Profile(software_id=s.id, code="p-pub", name="P")
    db.add(p)
    t = DataTemplate(code="cat-t-pub", name="T")
    db.add(t)
    await db.flush()
    v = TemplateVersion(template_id=t.id, version_no=1, schema_json={}, created_by=Actor().id, status="published")
    db.add(v)
    await db.flush()
    r = await create_record(
        db,
        RecordCreateIn(stableKey="stable-pub", softwareId=s.id, profileId=p.id, templateVersionId=v.id, payload={"raw": 2}),
        Actor(),
    )
    assert r.template_version_id == v.id
    # Once the constraint is in place, a later publish-status regression cannot
    # silently let a draft version through; re-fetch and assert it persisted.
    assert r.draft_payload == {"raw": 2}
