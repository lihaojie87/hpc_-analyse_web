from pydantic import BaseModel
class UserOut(BaseModel):
    id: str; username: str; email: str|None=None; displayName: str|None=None; isActive: bool=True; roles: list[str]=[]; permissions: list[str]=[]; createdAt: str; lastLoginAt: str|None=None
class UserUpdate(BaseModel): isActive: bool|None=None; displayName: str|None=None
class RoleAssignIn(BaseModel): roleCode: str
class RoleOut(BaseModel): code: str; name: str; permissions: list[str]=[]
class PermissionOut(BaseModel): code: str; name: str; category: str|None=None
