from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import Software, Profile
from app.deps.auth_deps import require_permission

router = APIRouter(prefix='/admin')

@router.get('/software')
async def list_software(user=Depends(require_permission('user:manage')), db: AsyncSession = Depends(get_db)):
    items = (await db.execute(select(Software).order_by(Software.name))).scalars().all()
    return {'items': [{'id': s.id, 'code': s.code, 'name': s.name, 'version': s.version, 'status': s.status} for s in items]}

@router.post('/software')
async def create_software(payload: dict, user=Depends(require_permission('user:manage')), db: AsyncSession = Depends(get_db)):
    code = str(payload.get('code', '')).strip()
    name = str(payload.get('name', '')).strip()
    version = str(payload.get('version', '')).strip() or None
    if not code or not name:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.VALIDATION_ERROR, 'code 和 name 不能为空')
    existing = (await db.execute(select(Software).where(Software.code == code))).scalar_one_or_none()
    if existing:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.CONFLICT, f'软件代码 {code} 已存在')
    sw = Software(code=code, name=name, version=version)
    db.add(sw)
    await db.commit()
    return {'id': sw.id, 'code': sw.code, 'name': sw.name, 'version': sw.version}

@router.get('/profiles')
async def list_profiles(software: str = None, user=Depends(require_permission('user:manage')), db: AsyncSession = Depends(get_db)):
    q = select(Profile).order_by(Profile.name)
    if software:
        q = q.where(Profile.software_id == software)
    items = (await db.execute(q)).scalars().all()
    return {'items': [{'id': p.id, 'code': p.code, 'name': p.name, 'softwareId': p.software_id, 'status': p.status} for p in items]}

@router.post('/profiles')
async def create_profile(payload: dict, user=Depends(require_permission('user:manage')), db: AsyncSession = Depends(get_db)):
    code = str(payload.get('code', '')).strip()
    name = str(payload.get('name', '')).strip()
    sw_id = str(payload.get('softwareId', '')).strip()
    if not code or not name or not sw_id:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.VALIDATION_ERROR, 'code, name, softwareId 不能为空')
    existing = (await db.execute(select(Profile).where(Profile.code == code))).scalar_one_or_none()
    if existing:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.CONFLICT, f'画像代码 {code} 已存在')
    pf = Profile(code=code, name=name, software_id=sw_id)
    db.add(pf)
    await db.commit()
    return {'id': pf.id, 'code': pf.code, 'name': pf.name, 'softwareId': pf.software_id}