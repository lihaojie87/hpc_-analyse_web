from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import UserRole, RolePermission, Role, Permission
async def get_roles_permissions(db: AsyncSession, user_id: str) -> tuple[list[str],list[str]]:
    roles=(await db.execute(select(Role.code).join(UserRole,UserRole.role_id==Role.id).where(UserRole.user_id==user_id))).scalars().all()
    perms=(await db.execute(select(Permission.code).join(RolePermission,RolePermission.permission_id==Permission.id).join(UserRole,UserRole.role_id==RolePermission.role_id).where(UserRole.user_id==user_id))).scalars().all()
    return list(roles), list(dict.fromkeys(perms))
