from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import Role,Permission,RolePermission
from app.deps.auth_deps import require_permission
router=APIRouter()
@router.get("/roles")
async def roles(user=Depends(require_permission("user:manage")),db:AsyncSession=Depends(get_db)):
    rs=(await db.execute(select(Role))).scalars().all(); out=[]
    for r in rs:
        ps=(await db.execute(select(Permission.code).join(RolePermission,RolePermission.permission_id==Permission.id).where(RolePermission.role_id==r.id))).scalars().all(); out.append({"code":r.code,"name":r.name,"permissions":list(ps)})
    return out
@router.get("/permissions")
async def permissions(user=Depends(require_permission("user:manage")),db:AsyncSession=Depends(get_db)):
    return [{"code":p.code,"name":p.name,"category":p.category} for p in (await db.execute(select(Permission))).scalars().all()]
