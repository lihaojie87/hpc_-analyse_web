import uuid, asyncio
from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.models import Role, Permission, RolePermission, User, UserRole
from app.core.security import hash_password
ROLES={"viewer":"查看者","provider":"数据提供者","admin":"管理员"}
PERMS=["data:read","data:create","data:update-own","data:update-any","data:submit","data:review","data:publish","data:rollback","template:read","template:manage","source:manage","sync:execute","audit:read","data:export","user:manage"]
MATRIX={"viewer":["data:read","data:export"],"provider":["data:read","data:create","data:update-own","data:submit","data:export","template:read"],"admin":PERMS}
async def seed():
 async with SessionLocal() as db:
  for code,name in ROLES.items():
   if not (await db.execute(select(Role).where(Role.code==code))).scalar_one_or_none(): db.add(Role(id=str(uuid.uuid4()),code=code,name=name))
  await db.flush(); ps={p.code:p for p in (await db.execute(select(Permission))).scalars().all()}
  for code in PERMS:
   if code not in ps: p=Permission(id=str(uuid.uuid4()),code=code,name=code); db.add(p); ps[code]=p
  await db.flush()
  rs={r.code:r for r in (await db.execute(select(Role))).scalars().all()}
  for rc,codes in MATRIX.items():
   for pc in codes:
    if not (await db.execute(select(RolePermission).where(RolePermission.role_id==rs[rc].id,RolePermission.permission_id==ps[pc].id))).scalar_one_or_none(): db.add(RolePermission(role_id=rs[rc].id,permission_id=ps[pc].id))
  s=__import__('app.core.config',fromlist=['get_settings']).get_settings()
  # Existence check must tolerate any number of admin users: the join emits one
  # row per admin membership, so scalar_one_or_none() raised MultipleResultsFound
  # for >=2 admins, aborted the whole transaction, and silently disabled the
  # startup RBAC seed. limit(1) + first() only asks "does one exist?".
  admin_exists = (await db.execute(select(User.id).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id).where(Role.code == 'admin').limit(1))).first() is not None
  if s.env!='prod' and s.bootstrap_admin_email and s.bootstrap_admin_password and not admin_exists:
   u=User(username=s.bootstrap_admin_email.split('@')[0],email=s.bootstrap_admin_email,password_hash=hash_password(s.bootstrap_admin_password)); db.add(u); await db.flush(); db.add(UserRole(user_id=u.id,role_id=rs['admin'].id))
  await db.commit()
if __name__=='__main__': asyncio.run(seed())
