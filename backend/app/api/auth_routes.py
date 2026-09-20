from fastapi import APIRouter, Depends, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.schemas.auth import RegisterIn, LoginIn, RefreshIn, ChangePasswordIn
from app.services.auth_service import register, login, user_dict
from app.deps.auth_deps import get_current_user
from app.db.models import User, RefreshToken
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_token, hash_refresh_token, verify_password, hash_password, create_token_pair
from app.core.rate_limit import limiter
from app.core.config import get_settings
router=APIRouter(prefix="/auth")
@router.post("/register",status_code=201)
async def register_route(p:RegisterIn,db:AsyncSession=Depends(get_db)): return await register(db,p)
@router.post("/login")
async def login_route(p:LoginIn,request:Request,db:AsyncSession=Depends(get_db)):
    if not limiter.allow(f"{p.username}:{request.client.host if request.client else ''}"): raise AppError(ErrorCode.RATE_LIMITED,"请求过于频繁")
    return await login(db,p.username,p.password)
@router.post("/refresh")
async def refresh(p:RefreshIn,db:AsyncSession=Depends(get_db)):
    try: d=decode_token(p.refreshToken)
    except Exception: raise AppError(ErrorCode.AUTH_TOKEN_INVALID,"刷新令牌无效")
    if d.get("type")!="refresh" or not d.get("jti"): raise AppError(ErrorCode.AUTH_TOKEN_INVALID,"刷新令牌无效")
    old=(await db.execute(select(RefreshToken).where(RefreshToken.jti==d["jti"]))).scalar_one_or_none()
    from datetime import datetime, timezone
    if not old or old.revoked or old.expires_at<datetime.now(timezone.utc).replace(tzinfo=None) or old.token_hash!=hash_refresh_token(p.refreshToken): raise AppError(ErrorCode.AUTH_TOKEN_REVOKED,"刷新令牌已失效")
    u=(await db.execute(select(User).where(User.id==old.user_id))).scalar_one_or_none()
    if not u or not u.is_active: raise AppError(ErrorCode.AUTH_REQUIRED,"认证已失效")
    a,r,j,exp=create_token_pair(u.id); old.revoked=True; old.revoked_at=datetime.now(timezone.utc).replace(tzinfo=None); old.replaced_by=j; db.add(RefreshToken(user_id=u.id,jti=j,token_hash=hash_refresh_token(r),expires_at=exp)); await db.commit(); return {"accessToken":a,"refreshToken":r,"tokenType":"bearer","expiresIn":get_settings().jwt_access_ttl}
@router.post("/logout")
async def logout(p:RefreshIn,user=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    try: d=decode_token(p.refreshToken); j=d.get("jti")
    except Exception: j=None
    if j:
        t=(await db.execute(select(RefreshToken).where(RefreshToken.jti==j,RefreshToken.user_id==user.id))).scalar_one_or_none()
        if t: t.revoked=True; await db.commit()
    return {"revoked":True}
@router.post("/logout-all")
async def logout_all(user=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    result=await db.execute(select(RefreshToken).where(RefreshToken.user_id==user.id,RefreshToken.revoked==False)); ts=result.scalars().all()
    for t in ts: t.revoked=True
    await db.commit(); return {"revokedCount":len(ts)}
@router.post("/change-password")
async def change(p:ChangePasswordIn,user=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    if not verify_password(p.oldPassword,user.password_hash): raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS,"旧密码错误")
    if len(p.newPassword)<8 or not any(c.isalpha() for c in p.newPassword) or not any(c.isdigit() for c in p.newPassword): raise AppError(ErrorCode.WEAK_PASSWORD,"密码至少8位且含字母和数字")
    user.password_hash=hash_password(p.newPassword); await db.commit(); return {"changed":True}
@router.get("/me")
async def me(user=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    from app.services.rbac_service import get_roles_permissions
    roles,perms=await get_roles_permissions(db,user.id); return user_dict(user,roles,perms)
