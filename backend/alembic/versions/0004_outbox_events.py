"""Add durable outbox events for published catalog notifications."""
from alembic import op
import sqlalchemy as sa

revision = "0004_outbox_events"
down_revision = "0003_feishu_import_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("dispatched_at", sa.DateTime),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_by", sa.String(36)),
        sa.Column("locked_until", sa.DateTime),
    )
    op.create_index("ix_outbox_pending_created", "outbox_events", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_pending_created", table_name="outbox_events")
    op.drop_table("outbox_events")
