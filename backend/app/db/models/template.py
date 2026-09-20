import uuid
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, utcnow

def uid() -> str: return str(uuid.uuid4())
class DataTemplate(Base):
    __tablename__='data_templates'; __table_args__=(UniqueConstraint('code',name='uq_data_template_code'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); code: Mapped[str]=mapped_column(String(64)); name: Mapped[str]=mapped_column(String(128)); description: Mapped[str|None]=mapped_column(String(500)); status: Mapped[str]=mapped_column(String(20),default='active'); created_by: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id')); revision: Mapped[int]=mapped_column(Integer,default=1); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); updated_at: Mapped[datetime|None]=mapped_column(DateTime,onupdate=utcnow)
class TemplateVersion(Base):
    __tablename__='template_versions'; __table_args__=(UniqueConstraint('template_id','version_no',name='uq_template_version'),CheckConstraint('revision >= 1',name='ck_template_version_revision'))
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); template_id: Mapped[str]=mapped_column(String(36),ForeignKey('data_templates.id')); version_no: Mapped[int]=mapped_column(Integer); status: Mapped[str]=mapped_column(String(20),default='draft'); schema_json: Mapped[dict]=mapped_column(JSON,default=dict); created_by: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id')); published_by: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id')); revision: Mapped[int]=mapped_column(Integer,default=1); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); published_at: Mapped[datetime|None]=mapped_column(DateTime)
class TemplateField(Base):
    __tablename__='template_fields'; __table_args__=(UniqueConstraint('template_version_id','path',name='uq_template_field_path'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); template_version_id: Mapped[str]=mapped_column(String(36),ForeignKey('template_versions.id')); path: Mapped[str]=mapped_column(String(255)); label: Mapped[str]=mapped_column(String(128)); data_type: Mapped[str]=mapped_column(String(32)); unit: Mapped[str|None]=mapped_column(String(32)); required: Mapped[bool]=mapped_column(Boolean,default=False); rules_json: Mapped[dict]=mapped_column(JSON,default=dict); source_mapping_json: Mapped[dict]=mapped_column(JSON,default=dict); ordinal: Mapped[int]=mapped_column(Integer,default=0)
