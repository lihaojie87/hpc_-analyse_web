import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, utcnow
class RefreshToken(Base):
    __tablename__="refresh_tokens"; id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4())); user_id: Mapped[str]=mapped_column(String(36), ForeignKey("users.id"), index=True); jti: Mapped[str]=mapped_column(String(36), unique=True, index=True); token_hash: Mapped[str]=mapped_column(String(255)); expires_at: Mapped[datetime]=mapped_column(DateTime); revoked: Mapped[bool]=mapped_column(Boolean, default=False); created_at: Mapped[datetime]=mapped_column(DateTime, default=utcnow); revoked_at: Mapped[datetime|None]=mapped_column(DateTime); replaced_by: Mapped[str|None]=mapped_column(String(36))
