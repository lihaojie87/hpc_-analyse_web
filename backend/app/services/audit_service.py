from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import AuditLog
SENSITIVE={'password','password_hash','accessToken','refreshToken','token','secret','credential'}
def sanitize(value):
    if isinstance(value,dict): return {k:('[REDACTED]' if k in SENSITIVE or any(s.lower() in k.lower() for s in SENSITIVE) else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list): return [sanitize(v) for v in value]
    return value
async def append(db: AsyncSession, *, actor_id: str|None, action: str, target_type: str|None=None, target_id: str|None=None, request_id: str='system', target_revision: int|None=None, before=None, after=None, detail=None, outcome='success') -> AuditLog:
    event=AuditLog(actor_user_id=actor_id,action=action,target_type=target_type,target_id=target_id,target_revision=target_revision,request_id=request_id,before_json=sanitize(before),after_json=sanitize(after),detail=sanitize(detail),outcome=outcome); db.add(event); await db.flush(); return event
async def list_logs(db: AsyncSession, limit: int=100): return (await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
