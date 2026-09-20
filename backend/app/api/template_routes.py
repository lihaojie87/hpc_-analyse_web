from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import DataTemplate,TemplateVersion,TemplateField
from app.deps.auth_deps import require_permission,get_current_user
from app.schemas.template import TemplateCreateIn,TemplateVersionIn
from app.services.template_service import create_template,create_version,publish_version
router=APIRouter(prefix='/templates')
@router.post('')
async def create(p:TemplateCreateIn,user=Depends(require_permission('template:manage')),db:AsyncSession=Depends(get_db)):
 t,v=await create_template(db,p,user); return {'id':t.id,'code':t.code,'name':t.name,'versionId':v.id}
@router.get('')
async def list_templates(user=Depends(require_permission('template:read','template:manage')),db:AsyncSession=Depends(get_db)):
 ts=(await db.execute(select(DataTemplate))).scalars().all(); return {'items':[{'id':t.id,'code':t.code,'name':t.name,'status':t.status,'revision':t.revision} for t in ts], 'pagination':{'page':1,'pageSize':20,'total':len(ts),'totalPages':1}}
@router.get('/{template_id}/versions')
async def versions(template_id:str,user=Depends(require_permission('template:read','template:manage')),db:AsyncSession=Depends(get_db)):
 return [{'id':v.id,'versionNo':v.version_no,'status':v.status,'revision':v.revision} for v in (await db.execute(select(TemplateVersion).where(TemplateVersion.template_id==template_id))).scalars().all()]
@router.post('/{template_id}/versions')
async def new_version(template_id:str,p:TemplateVersionIn,user=Depends(require_permission('template:manage')),db:AsyncSession=Depends(get_db)):
 v=await create_version(db,template_id,p,user); return {'id':v.id,'versionNo':v.version_no,'status':v.status,'revision':v.revision}
@router.post('/versions/{version_id}/publish')
async def publish(version_id:str,user=Depends(require_permission('template:manage')),db:AsyncSession=Depends(get_db)):
 v=await publish_version(db,version_id,user); return {'id':v.id,'status':v.status,'publishedBy':v.published_by}

@router.get('/versions/{version_id}/fields')
async def get_fields(version_id:str,user=Depends(require_permission('template:read','template:manage')),db:AsyncSession=Depends(get_db)):
 fields=(await db.execute(select(TemplateField).where(TemplateField.template_version_id==version_id).order_by(TemplateField.ordinal))).scalars().all()
 return {'items':[{'id':f.id,'path':f.path,'label':f.label,'dataType':f.data_type,'unit':f.unit,'required':f.required,'rules':f.rules_json} for f in fields]}
