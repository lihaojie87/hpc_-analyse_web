from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import User, Role, UserRole, RefreshToken
from app.core.security import *
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.services.rbac_service import get_roles_permissions

def user_dict(u: User, roles: list[str], perms: list[str]) -> dict:
    iso=lambda d: d.replace(tzinfo=timezone.utc).isoformat().replace("+00:00","Z") if d else None
    return {"id":u.id,"username":u.username,"email":u.email,"displayName":u.display_name,"isActive":u.is_active,"roles":roles,"permissions":perms,"createdAt":iso(u.created_at),"lastLoginAt":iso(u.last_login_at)}
async def issue(db: AsyncSession, u: User) -> dict:
    a,r,jti,exp=create_token_pair(u.id); db.add(RefreshToken(user_id=u.id,jti=jti,token_hash=hash_refresh_token(r),expires_at=exp)); await db.commit(); roles,perms=await get_roles_permissions(db,u.id)
    return {"user":user_dict(u,roles,perms),"accessToken":a,"refreshToken":r,"tokenType":"bearer","expiresIn":get_settings().jwt_access_ttl}
async def register(db: AsyncSession, payload) -> dict:
    exists=await db.execute(select(User).where((User.username==payload.username)|(User.email==payload.email if payload.email else False))); 
    if exists.scalar_one_or_none(): raise AppError(ErrorCode.USER_EXISTS,"用户名或邮箱已存在")
    viewer=(await db.execute(select(Role).where(Role.code=="viewer"))).scalar_one(); u=User(username=payload.username,email=payload.email,password_hash=hash_password(payload.password),display_name=payload.displayName); db.add(u); await db.flush(); db.add(UserRole(user_id=u.id,role_id=viewer.id)); await db.commit(); return await issue(db,u)
async def login(db: AsyncSession, username: str, password: str) -> dict:
    u=(await db.execute(select(User).where(User.username==username))).scalar_one_or_none(); now=datetime.now(timezone.utc).replace(tzinfo=None)
    if u and u.locked_until and u.locked_until>now: raise AppError(ErrorCode.ACCOUNT_LOCKED,"账户已锁定")
    if not u or not verify_password(password,u.password_hash):
        if u: u.failed_login_count+=1; s=get_settings(); u.locked_until=now.replace(microsecond=0)+__import__('datetime').timedelta(seconds=s.login_lock_seconds) if u.failed_login_count>=s.login_max_failures else u.locked_until; await db.commit()
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS,"用户名或密码错误")
    if not u.is_active: raise AppError(ErrorCode.AUTH_REQUIRED,"认证已失效")
    u.failed_login_count=0; u.last_login_at=now; await db.commit(); return await issue(db,u)
