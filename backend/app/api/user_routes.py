from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import User,Role,UserRole
from app.deps.auth_deps import require_permission
from app.core.errors import AppError,ErrorCode
router=APIRouter(prefix="/users")
@router.get("")
async def users(user=Depends(require_permission("user:manage")),db:AsyncSession=Depends(get_db)):
    us=(await db.execute(select(User))).scalars().all()
    items=[]
    for u in us:
        roles=(await db.execute(select(Role.code).join(UserRole,UserRole.role_id==Role.id).where(UserRole.user_id==u.id))).scalars().all()
        items.append({"id":u.id,"username":u.username,"email":u.email,"displayName":u.display_name,"isActive":u.is_active,"roles":list(roles)})
    return {"items":items,"pagination":{"page":1,"pageSize":20,"total":len(items),"totalPages":1}}
@router.patch("/{user_id}")
async def update(user_id:str,payload:dict,user=Depends(require_permission("user:manage")),db:AsyncSession=Depends(get_db)):
    u=(await db.execute(select(User).where(User.id==user_id))).scalar_one_or_none()
    if not u: raise AppError(ErrorCode.NOT_FOUND,"用户不存在")
    if "isActive" in payload: u.is_active=bool(payload["isActive"])
    if "displayName" in payload: u.display_name=payload["displayName"]
    await db.commit(); return {"id":u.id,"username":u.username,"isActive":u.is_active}
@router.post("/{user_id}/roles")
async def assign(user_id:str,payload:dict,user=Depends(require_permission("user:manage")),db:AsyncSession=Depends(get_db)):
    u=(await db.execute(select(User).where(User.id==user_id))).scalar_one_or_none(); r=(await db.execute(select(Role).where(Role.code==payload.get("roleCode")))).scalar_one_or_none()
    if not u or not r: raise AppError(ErrorCode.NOT_FOUND,"用户或角色不存在")
    if payload.get("roleCode") not in {"viewer", "provider", "admin"}: raise AppError(ErrorCode.NOT_FOUND,"角色不存在")
    exists=(await db.execute(select(UserRole).where(UserRole.user_id==user_id,UserRole.role_id==r.id))).scalar_one_or_none()
    if exists: raise AppError(ErrorCode.CONFLICT,"角色已存在")
    db.add(UserRole(user_id=user_id,role_id=r.id,assigned_by=user.id)); await db.commit(); roles=(await db.execute(select(Role.code).join(UserRole,UserRole.role_id==Role.id).where(UserRole.user_id==user_id))).scalars().all(); return {"userId":user_id,"roles":list(roles)}
@router.delete("/{user_id}/roles/{role_code}")
async def remove(user_id:str,role_code:str,user=Depends(require_permission("user:manage")),db:AsyncSession=Depends(get_db)):
    r=(await db.execute(select(Role).where(Role.code==role_code))).scalar_one_or_none(); ur=(await db.execute(select(UserRole).where(UserRole.user_id==user_id,UserRole.role_id==r.id if r else False))).scalar_one_or_none()
    if ur: await db.delete(ur); await db.commit()
    return {"userId":user_id,"roles":[]}
