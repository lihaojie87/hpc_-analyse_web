import pytest
from sqlalchemy import select
from app.core.errors import AppError
from app.db.models import CatalogHead,DataVersion,User
from app.services.version_service import create_staging,approve,publish

@pytest.mark.asyncio
async def test_empty_staging_batch_is_rejected(db):
    class Owner: id='version-owner'
    with pytest.raises(AppError) as error:
        await create_staging(db,Owner(),[])
    assert error.value.code.value=='VALIDATION_ERROR'

@pytest.mark.asyncio
async def test_approved_version_switches_catalog_head(db):
    owner=(await db.execute(select(User))).scalars().first()
    reviewer=User(username='version-reviewer',password_hash='not-used'); db.add(reviewer); await db.flush()
    latest=(await db.execute(select(DataVersion.version_no).order_by(DataVersion.version_no.desc()))).scalars().first() or 0
    version=DataVersion(version_no=latest+1,revision=1,status='staging',checksum='abc',record_count=1,created_by=owner.id)
    db.add(version); await db.flush()
    await approve(db,version,reviewer)
    head=(await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one()
    await publish(db,version,reviewer,head.current_revision)
    assert version.status=='published'
    assert head.current_version_id==version.id and head.current_revision>=1
