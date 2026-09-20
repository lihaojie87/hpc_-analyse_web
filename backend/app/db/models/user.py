import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, utcnow
class User(Base):
    __tablename__="users"; id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4())); username: Mapped[str]=mapped_column(String(64), unique=True, index=True); email: Mapped[str|None]=mapped_column(String(255), unique=True); password_hash: Mapped[str]=mapped_column(String(255)); display_name: Mapped[str|None]=mapped_column(String(128)); is_active: Mapped[bool]=mapped_column(Boolean, default=True); failed_login_count: Mapped[int]=mapped_column(Integer, default=0); locked_until: Mapped[datetime|None]=mapped_column(DateTime); last_login_at: Mapped[datetime|None]=mapped_column(DateTime); created_at: Mapped[datetime]=mapped_column(DateTime, default=utcnow); updated_at: Mapped[datetime|None]=mapped_column(DateTime, onupdate=utcnow); created_by: Mapped[str|None]=mapped_column(String(36), ForeignKey("users.id"))
class Role(Base):
    __tablename__="roles"; id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4())); code: Mapped[str]=mapped_column(String(32), unique=True, index=True); name: Mapped[str]=mapped_column(String(64)); description: Mapped[str|None]=mapped_column(String(255))
class Permission(Base):
    __tablename__="permissions"; id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4())); code: Mapped[str]=mapped_column(String(64), unique=True, index=True); name: Mapped[str]=mapped_column(String(128)); category: Mapped[str|None]=mapped_column(String(32)); description: Mapped[str|None]=mapped_column(String(255))
class UserRole(Base):
    __tablename__="user_roles"; user_id: Mapped[str]=mapped_column(String(36), ForeignKey("users.id"), primary_key=True); role_id: Mapped[str]=mapped_column(String(36), ForeignKey("roles.id"), primary_key=True); assigned_by: Mapped[str|None]=mapped_column(String(36), ForeignKey("users.id")); assigned_at: Mapped[datetime]=mapped_column(DateTime, default=utcnow)
class RolePermission(Base):
    __tablename__="role_permissions"; role_id: Mapped[str]=mapped_column(String(36), ForeignKey("roles.id"), primary_key=True); permission_id: Mapped[str]=mapped_column(String(36), ForeignKey("permissions.id"), primary_key=True)
