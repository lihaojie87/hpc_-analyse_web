import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, utcnow
class AuditLog(Base):
    __tablename__='audit_log'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    actor_user_id: Mapped[str|None]=mapped_column(String(36),ForeignKey('users.id'),index=True)
    action: Mapped[str]=mapped_column(String(64)); target_type: Mapped[str|None]=mapped_column(String(64)); target_id: Mapped[str|None]=mapped_column(String(36)); target_revision: Mapped[int|None]=mapped_column(Integer); request_id: Mapped[str]=mapped_column(String(64),default='system'); before_json: Mapped[dict|None]=mapped_column(JSON); after_json: Mapped[dict|None]=mapped_column(JSON); detail: Mapped[dict|None]=mapped_column(JSON); ip_address: Mapped[str|None]=mapped_column(String(64)); user_agent: Mapped[str|None]=mapped_column(String(512)); outcome: Mapped[str]=mapped_column(String(20),default='success'); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,index=True)
