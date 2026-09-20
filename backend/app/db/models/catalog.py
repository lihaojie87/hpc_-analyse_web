import uuid
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, utcnow

def uid() -> str: return str(uuid.uuid4())
class Software(Base):
    __tablename__='software'; __table_args__=(UniqueConstraint('code',name='uq_software_code'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); code: Mapped[str]=mapped_column(String(64)); name: Mapped[str]=mapped_column(String(128)); version: Mapped[str|None]=mapped_column(String(64)); status: Mapped[str]=mapped_column(String(20),default='active'); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); updated_at: Mapped[datetime|None]=mapped_column(DateTime,onupdate=utcnow)
class Profile(Base):
    __tablename__='profiles'; __table_args__=(UniqueConstraint('software_id','code',name='uq_profile_software_code'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); software_id: Mapped[str]=mapped_column(String(36),ForeignKey('software.id')); code: Mapped[str]=mapped_column(String(64)); name: Mapped[str]=mapped_column(String(128)); status: Mapped[str]=mapped_column(String(20),default='active'); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); updated_at: Mapped[datetime|None]=mapped_column(DateTime,onupdate=utcnow)
class PerformanceRecord(Base):
    __tablename__='performance_records'; __table_args__=(UniqueConstraint('stable_key',name='uq_performance_record_stable_key'),CheckConstraint('revision >= 1',name='ck_record_revision'))
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); stable_key: Mapped[str]=mapped_column(String(512)); software_id: Mapped[str]=mapped_column(String(36),ForeignKey('software.id')); profile_id: Mapped[str]=mapped_column(String(36),ForeignKey('profiles.id')); template_version_id: Mapped[str]=mapped_column(String(36),ForeignKey('template_versions.id')); owner_user_id: Mapped[str]=mapped_column(String(36),ForeignKey('users.id')); lifecycle_status: Mapped[str]=mapped_column(String(24),default='draft'); draft_payload: Mapped[dict]=mapped_column(JSON,default=dict); rejection_reason: Mapped[str|None]=mapped_column(String(1000)); revision: Mapped[int]=mapped_column(Integer,default=1); deleted: Mapped[bool]=mapped_column(Boolean,default=False); deleted_at: Mapped[datetime|None]=mapped_column(DateTime); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); updated_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,onupdate=utcnow)
class PerformanceRecordVersion(Base):
    __tablename__='performance_record_versions'; __table_args__=(UniqueConstraint('data_version_id','record_id',name='uq_record_version'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); record_id: Mapped[str]=mapped_column(String(36),ForeignKey('performance_records.id')); data_version_id: Mapped[str]=mapped_column(String(36),ForeignKey('data_versions.id')); record_revision: Mapped[int]=mapped_column(Integer); raw_payload: Mapped[dict]=mapped_column(JSON,default=dict); parsed_payload: Mapped[dict]=mapped_column(JSON,default=dict); derived_payload: Mapped[dict]=mapped_column(JSON,default=dict); source_snapshot_id: Mapped[str|None]=mapped_column(String(36),ForeignKey('source_snapshots.id')); source_locator: Mapped[str|None]=mapped_column(String(512)); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)
class SourceSnapshot(Base):
    __tablename__='source_snapshots'; __table_args__=(UniqueConstraint('source_id','source_revision','content_hash',name='uq_source_snapshot'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); source_id: Mapped[str]=mapped_column(String(36),ForeignKey('data_sources.id')); source_revision: Mapped[str|None]=mapped_column(String(128)); content_hash: Mapped[str]=mapped_column(String(128)); raw_payload: Mapped[dict]=mapped_column(JSON,default=dict); status: Mapped[str]=mapped_column(String(20),default='captured'); tombstone: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False); captured_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); created_by: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id'))
