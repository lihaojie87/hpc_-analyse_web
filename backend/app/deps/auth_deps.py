from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import User
from app.core.security import decode_token
from app.core.errors import AppError, ErrorCode
from app.services.rbac_service import get_roles_permissions
bearer=HTTPBearer(auto_error=False)
async def get_current_user(creds: HTTPAuthorizationCredentials|None=Depends(bearer), db: AsyncSession=Depends(get_db)) -> User:
    if not creds: raise AppError(ErrorCode.AUTH_REQUIRED,"请先登录")
    try: data=decode_token(creds.credentials)
    except Exception: raise AppError(ErrorCode.AUTH_REQUIRED,"登录凭证无效")
    if data.get("type")!="access": raise AppError(ErrorCode.AUTH_REQUIRED,"登录凭证无效")
    u=(await db.execute(select(User).where(User.id==data.get("sub")))).scalar_one_or_none()
    if not u or not u.is_active: raise AppError(ErrorCode.AUTH_REQUIRED,"认证已失效")
    from datetime import datetime, timezone
    if u.locked_until and u.locked_until>datetime.now(timezone.utc).replace(tzinfo=None): raise AppError(ErrorCode.ACCOUNT_LOCKED,"账户已锁定")
    return u
def require_permission(*codes: str):
    async def dep(user: User=Depends(get_current_user), db: AsyncSession=Depends(get_db)) -> User:
        _, perms=await get_roles_permissions(db,user.id)
        if not any(code in perms for code in codes): raise AppError(ErrorCode.FORBIDDEN,"权限不足")
        return user
    return dep
def require_review_authorization(owner_id: str):
    async def dep(user: User=Depends(get_current_user), db: AsyncSession=Depends(get_db)) -> User:
        if user.id==owner_id: raise AppError(ErrorCode.FORBIDDEN,"提交者不能自审或自发布")
        _, perms=await get_roles_permissions(db,user.id)
        if "data:review" not in perms and "data:publish" not in perms: raise AppError(ErrorCode.FORBIDDEN,"权限不足")
        return user
    return dep
