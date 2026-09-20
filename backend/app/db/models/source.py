"""Persistent data-source and template field-mapping models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


def uid() -> str:
    """Return a new string UUID."""
    return str(uuid.uuid4())


class DataSource(Base):
    """Non-secret configuration for an external tabular data source."""

    __tablename__ = "data_sources"
    __table_args__ = (
        UniqueConstraint("code", name="uq_data_source_code"),
        CheckConstraint("revision >= 1", name="ck_data_source_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="feishu")
    workbook_token: Mapped[str | None] = mapped_column(String(255))
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class SourceCredentialRef(Base):
    """Reference to a credential held outside the application database.

    The value is an opaque secret-manager reference, never an access token or
    application secret.  This table intentionally has no credential payload.
    """

    __tablename__ = "source_credential_refs"
    __table_args__ = (UniqueConstraint("source_id", name="uq_source_credential_source"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_sources.id"), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="secret_manager")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class FieldMapping(Base):
    """Immutable mapping from a source column to a template field path."""

    __tablename__ = "field_mappings"
    __table_args__ = (
        UniqueConstraint("template_version_id", "target_path", name="uq_field_mapping_target"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    template_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_versions.id"), nullable=False)
    source_column: Mapped[str] = mapped_column(String(255), nullable=False)
    target_path: Mapped[str] = mapped_column(String(255), nullable=False)
    transform: Mapped[str | None] = mapped_column(String(64))
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
