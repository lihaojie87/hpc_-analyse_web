import pytest
from app.core.errors import AppError
from app.db.models import DataVersion, CatalogHead, User
from app.services.version_service import approve, publish
from sqlalchemy import select

@pytest.mark.asyncio
async def test_stale_publish_does_not_change_head(db):
    owner = User(username='atomic-owner', password_hash='x'); reviewer = User(username='atomic-reviewer', password_hash='x')
    db.add_all([owner, reviewer]); await db.flush()
    head = (await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one()
    version = DataVersion(version_no=1, revision=1, status='staging', checksum='x', record_count=1, created_by=owner.id)
    db.add(version); await db.flush(); await approve(db, version, reviewer)
    with pytest.raises(AppError): await publish(db, version, reviewer, head.current_revision + 1)
    fresh = (await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one()
    assert fresh.current_version_id is None and fresh.current_revision == 0
