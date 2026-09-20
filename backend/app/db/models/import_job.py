"""Import batch, row error, and diff persistence models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


def uid() -> str:
    """Return a new string UUID."""
    return str(uuid.uuid4())


class ImportJob(Base):
    """One complete, idempotent import batch."""

    __tablename__ = "import_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_import_job_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("source_snapshots.id"))
    template_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("template_versions.id"))
    data_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("data_versions.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_revision: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ImportRowError(Base):
    """Location and sanitized value for one row-level validation error."""

    __tablename__ = "import_row_errors"
    __table_args__ = (
        Index("ix_import_row_error_location", "import_job_id", "source_row", "source_cell", "field_path", "code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    import_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("import_jobs.id"), nullable=False)
    source_row: Mapped[str] = mapped_column(String(32), nullable=False)
    source_cell: Mapped[str | None] = mapped_column(String(32))
    field_path: Mapped[str | None] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    raw_value: Mapped[object | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ImportDiff(Base):
    """Stable-key based change between the incoming batch and current data."""

    __tablename__ = "import_diffs"
    __table_args__ = (Index("ix_import_diff_job_kind", "import_job_id", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    import_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("import_jobs.id"), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
