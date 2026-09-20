import pytest
from sqlalchemy import select
from app.core.errors import AppError, ErrorCode
from app.db.models import User, DataVersion, CatalogHead
from app.services.version_service import publish

@pytest.mark.asyncio
async def test_expired_head_revision_is_rejected_without_changing_current(db):
    owner=User(username='conc-owner',password_hash='x'); reviewer=User(username='conc-reviewer',password_hash='x'); db.add_all([owner,reviewer]); await db.flush()
    head=(await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one()
    first=DataVersion(version_no=1,revision=1,status='approved',checksum='a',record_count=1,created_by=owner.id); second=DataVersion(version_no=2,revision=1,status='approved',checksum='b',record_count=1,created_by=owner.id); db.add_all([first,second]); await db.commit()
    await publish(db,first,reviewer,0)
    current_id,revision=head.current_version_id,head.current_revision
    with pytest.raises(AppError) as error: await publish(db,second,reviewer,0)
    assert error.value.code==ErrorCode.PRECONDITION_FAILED
    fresh=(await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one()
    assert fresh.current_version_id==current_id and fresh.current_revision==revision
