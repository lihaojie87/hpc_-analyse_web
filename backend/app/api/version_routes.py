from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import DataVersion,CatalogHead,PerformanceRecord
from app.deps.auth_deps import require_permission
from app.schemas.versioning import PublishIn,RollbackIn
from app.services.version_service import approve,publish,rollback,get_current
router=APIRouter(prefix='/data-versions')
@router.get('/current')
async def current(user=Depends(require_permission('data:read')),db:AsyncSession=Depends(get_db)): return await get_current(db)
@router.post('/{version_id}/rollback')
async def rollback_route(version_id:str,p:RollbackIn,user=Depends(require_permission('data:rollback')),db:AsyncSession=Depends(get_db)):
 v=await rollback(db,version_id,user,p.expectedHeadRevision); return {'id':v.id,'versionNo':v.version_no,'status':v.status}
@router.get('')
async def versions(user=Depends(require_permission('data:read')),db:AsyncSession=Depends(get_db)):
 return [{'id':v.id,'versionNo':v.version_no,'status':v.status,'recordCount':v.record_count,'checksum':v.checksum} for v in (await db.execute(select(DataVersion).where(DataVersion.status=='published'))).scalars().all()]
@router.post('/{version_id}/approve')
async def approve_route(version_id:str,user=Depends(require_permission('data:review')),db:AsyncSession=Depends(get_db)):
 v=(await db.execute(select(DataVersion).where(DataVersion.id==version_id))).scalar_one_or_none(); return {'id':(await approve(db,v,user)).id,'status':'approved'}
@router.post('/{version_id}/publish')
async def publish_route(version_id:str,p:PublishIn,user=Depends(require_permission('data:publish')),db:AsyncSession=Depends(get_db)):
 v=(await db.execute(select(DataVersion).where(DataVersion.id==version_id))).scalar_one_or_none(); v=await publish(db,v,user,p.expectedHeadRevision); return {'id':v.id,'status':v.status}
