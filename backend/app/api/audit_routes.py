from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.deps.auth_deps import require_permission
from app.services.audit_service import list_logs
router=APIRouter(prefix='/audit-logs')
@router.get('')
async def logs(user=Depends(require_permission('audit:read')),db:AsyncSession=Depends(get_db)):
 return {'items':[{'id':x.id,'action':x.action,'targetType':x.target_type,'targetId':x.target_id,'requestId':x.request_id,'targetRevision':x.target_revision,'outcome':x.outcome,'createdAt':x.created_at.isoformat()+'Z'} for x in await list_logs(db)],'pagination':{'page':1,'pageSize':100}}
