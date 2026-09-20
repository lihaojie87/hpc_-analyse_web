from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.db.models import Software,Profile,DataTemplate,TemplateVersion,PerformanceRecord,DataVersion,CatalogHead
from app.core.errors import AppError
from app.services.version_service import create_staging,approve,publish,get_current,rollback

@pytest.mark.asyncio
async def test_if_match_required_and_stale_returns_428_412(client,db):
    created=await client.post('/api/v1/auth/register',json={'username':'etag-user','password':'EtagUser123'})
    assert created.status_code==201
    token=created.json()['accessToken']; uid=created.json()['user']['id']
    software=Software(code='etag-soft',name='ETag Software'); db.add(software); await db.flush()
    profile=Profile(software_id=software.id,code='p1',name='Profile'); db.add(profile); await db.flush()
    template=DataTemplate(code='etag-template',name='ETag Template'); db.add(template); await db.flush()
    version=TemplateVersion(template_id=template.id,version_no=1,schema_json={},status='published'); db.add(version); await db.flush()
    record=PerformanceRecord(stable_key='etag-user|etag-soft|p1|case1|run1',software_id=software.id,profile_id=profile.id,template_version_id=version.id,owner_user_id=uid,draft_payload={'x':1}); db.add(record); await db.commit()
    auth={'Authorization':f'Bearer {token}'}
    missing=await client.patch(f'/api/v1/records/{record.id}',headers=auth,json={'payload':{'x':2}})
    assert missing.status_code==428 and missing.json()['error']['code']=='PRECONDITION_REQUIRED'
    # Registration defaults to viewer; grant provider capability before the
    # successful optimistic-concurrency update.
    from sqlalchemy import select
    from app.db.models import Role, UserRole
    provider_role=(await db.execute(select(Role).where(Role.code=='provider'))).scalar_one()
    db.add(UserRole(user_id=uid, role_id=provider_role.id)); await db.commit()
    updated=await client.patch(f'/api/v1/records/{record.id}',headers={**auth,'If-Match':f'"record-{record.id}-1"'},json={'payload':{'x':2}})
    assert updated.status_code==200 and updated.json()['revision']==2
    stale=await client.patch(f'/api/v1/records/{record.id}',headers={**auth,'If-Match':f'"record-{record.id}-1"'},json={'payload':{'x':3}})
    assert stale.status_code==412 and stale.json()['error']['code']=='PRECONDITION_FAILED'

@pytest.mark.asyncio
async def test_failed_publish_preserves_current_and_rollback_creates_version(db):
    head=(await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one()
    from app.db.models import User
    owner=User(id='10000000-0000-0000-0000-000000000101',username='owner',password_hash='not-a-real-password-hash'); reviewer=User(id='10000000-0000-0000-0000-000000000102',username='reviewer',password_hash='not-a-real-password-hash'); rollback_admin=User(id='10000000-0000-0000-0000-000000000103',username='rollback-admin',password_hash='not-a-real-password-hash'); db.add_all([owner,reviewer,rollback_admin]); await db.flush()
    software=Software(code='version-soft',name='Version Software'); db.add(software); await db.flush()
    profile=Profile(software_id=software.id,code='p1',name='Profile'); db.add(profile); await db.flush()
    template=DataTemplate(code='version-template',name='Version Template'); db.add(template); await db.flush()
    tv=TemplateVersion(template_id=template.id,version_no=1,schema_json={},status='published'); db.add(tv); await db.flush()
    record=PerformanceRecord(stable_key='version-soft|p1|u|m|c|r1',software_id=software.id,profile_id=profile.id,template_version_id=tv.id,owner_user_id=owner.id,draft_payload={'metric':1}); db.add(record); await db.commit()
    first=await create_staging(db,owner,[record]); before=(head.current_version_id,head.current_revision)
    with pytest.raises(AppError): await publish(db,first,reviewer,0)
    await db.rollback()
    assert (head.current_version_id,head.current_revision)==before
    await approve(db,first,reviewer); await publish(db,first,reviewer,0)
    current=await get_current(db); assert current['dataVersionId']==first.id and len(current['records'])==1
    second=await rollback(db,first.id,rollback_admin,1)
    assert second.id!=first.id and second.version_no>first.version_no
    current2=await get_current(db); assert current2['dataVersionId']==second.id and current2['versionNo']==second.version_no
