import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, utcnow

def uid() -> str: return str(uuid.uuid4())
class DataVersion(Base):
    __tablename__='data_versions'; __table_args__=(UniqueConstraint('version_no',name='uq_data_version_no'),CheckConstraint('version_no >= 1',name='ck_data_version_no'),CheckConstraint('record_count >= 0',name='ck_data_version_count'))
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); version_no: Mapped[int]=mapped_column(Integer); revision: Mapped[int]=mapped_column(Integer,default=1); status: Mapped[str]=mapped_column(String(20),default='staging'); source_snapshot_id: Mapped[str|None]=mapped_column(String(36),ForeignKey('source_snapshots.id')); template_version_id: Mapped[str|None]=mapped_column(String(36),ForeignKey('template_versions.id')); checksum: Mapped[str]=mapped_column(String(128)); record_count: Mapped[int]=mapped_column(Integer,default=0); created_by: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id')); approved_by: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id')); published_by: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id')); failure_code: Mapped[str|None]=mapped_column(String(64)); failure_detail: Mapped[dict|None]=mapped_column(JSON); error_count: Mapped[int]=mapped_column(Integer,default=0,nullable=False); import_job_id: Mapped[str|None]=mapped_column(String(36),ForeignKey('import_jobs.id'),unique=True); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); approved_at: Mapped[datetime|None]=mapped_column(DateTime); published_at: Mapped[datetime|None]=mapped_column(DateTime)
class CatalogHead(Base):
    __tablename__='catalog_heads'; scope_key: Mapped[str]=mapped_column(String(64),primary_key=True); current_version_id: Mapped[str|None]=mapped_column(String(36),ForeignKey('data_versions.id')); current_revision: Mapped[int]=mapped_column(Integer,default=0); updated_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,onupdate=utcnow)
