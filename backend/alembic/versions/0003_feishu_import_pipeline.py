"""Add Feishu source and import pipeline persistence."""

from alembic import op
import sqlalchemy as sa

revision = "0003_feishu_import_pipeline"
down_revision = "0002_catalog_template_versioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="feishu"),
        sa.Column("workbook_token", sa.String(255)),
        sa.Column("credential_ref", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("config_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("code", name="uq_data_source_code"),
        sa.CheckConstraint("revision >= 1", name="ck_data_source_revision"),
    )
    op.create_table(
        "source_credential_refs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("credential_ref", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="secret_manager"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("source_id", name="uq_source_credential_source"),
    )
    op.create_table(
        "field_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_version_id", sa.String(36), sa.ForeignKey("template_versions.id"), nullable=False),
        sa.Column("source_column", sa.String(255), nullable=False),
        sa.Column("target_path", sa.String(255), nullable=False),
        sa.Column("transform", sa.String(64)),
        sa.Column("aliases", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("template_version_id", "target_path", name="uq_field_mapping_target"),
    )
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("source_snapshot_id", sa.String(36), sa.ForeignKey("source_snapshots.id")),
        sa.Column("template_version_id", sa.String(36), sa.ForeignKey("template_versions.id")),
        sa.Column("data_version_id", sa.String(36), sa.ForeignKey("data_versions.id")),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_revision", sa.String(128)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("stats", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("started_at", sa.DateTime),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_import_job_idempotency"),
        sa.UniqueConstraint("data_version_id", name="uq_import_job_data_version"),
    )
    op.create_table(
        "import_row_errors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_job_id", sa.String(36), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("source_row", sa.String(32), nullable=False),
        sa.Column("source_cell", sa.String(32)),
        sa.Column("field_path", sa.String(255)),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("raw_value", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_import_row_error_location", "import_row_errors", ["import_job_id", "source_row", "source_cell", "field_path", "code"])
    op.create_table(
        "import_diffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_job_id", sa.String(36), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("stable_key", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("before_json", sa.JSON),
        sa.Column("after_json", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_import_diff_job_kind", "import_diffs", ["import_job_id", "kind"])
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("import_job_id", sa.String(36), sa.ForeignKey("import_jobs.id")),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("stats", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_sync_run_idempotency"),
        sa.UniqueConstraint("import_job_id", name="uq_sync_run_import_job"),
    )
    # source_snapshots_pkey is referenced by three dependent foreign keys
    # (data_versions, performance_record_versions, import_jobs). SQLite does not
    # enforce that dependency, so the "recreate the whole table" strategy works
    # there; PostgreSQL rejects it because the recreate issues a bare
    # ALTER TABLE source_snapshots DROP CONSTRAINT source_snapshots_pkey.
    # Branch on dialect and use direct native DDL on PostgreSQL instead.
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        # NOTE: narrowing source_id from VARCHAR(255) to VARCHAR(36) fails loudly
        # on PostgreSQL when a historical value exceeds 36 characters. That is
        # intended (a long value means the legacy data does not match the new
        # UUID contract). If such a dataset must be coerced explicitly, add
        # postgresql_using="source_id::varchar(36)" (or a truncating expression)
        # to the alter_column call below.
        op.alter_column(
            "source_snapshots",
            "source_id",
            existing_type=sa.String(255),
            type_=sa.String(36),
            existing_nullable=False,
        )
        op.create_foreign_key(
            "fk_source_snapshots_data_source",
            "source_snapshots",
            "data_sources",
            ["source_id"],
            ["id"],
        )
        op.add_column(
            "source_snapshots",
            sa.Column("tombstone", sa.Boolean, nullable=False, server_default=sa.false()),
        )
    else:
        with op.batch_alter_table("source_snapshots", recreate="always") as batch:
            batch.alter_column("source_id", existing_type=sa.String(255), type_=sa.String(36), existing_nullable=False)
            batch.create_foreign_key("fk_source_snapshots_data_source", "data_sources", ["source_id"], ["id"])
            batch.add_column(sa.Column("tombstone", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("data_versions", sa.Column("error_count", sa.Integer, nullable=False, server_default="0"))
    op.add_column("data_versions", sa.Column("import_job_id", sa.String(36)))
    op.create_index("uq_data_version_import_job", "data_versions", ["import_job_id"], unique=True)


def downgrade() -> None:
    # SQLite can materialize a unique constraint as an auto-index rather than
    # the explicit index name (and an interrupted migration may leave it out).
    # DROP INDEX IF EXISTS keeps downgrade safe across SQLite/PostgreSQL and
    # across partially-applied migration states.
    # SQLite represents a unique index created by Alembic as an implicit
    # auto-index in some environments. Drop the named index only when it is
    # present, while preserving the migration's original schema contract.
    bind = op.get_bind()
    index_names = {item["name"] for item in sa.inspect(bind).get_indexes("data_versions")}
    if "uq_data_version_import_job" in index_names:
        op.drop_index("uq_data_version_import_job", table_name="data_versions")
    op.drop_column("data_versions", "import_job_id")
    op.drop_column("data_versions", "error_count")
    # Recreate the legacy table and remove the FK only when it is present.
    # This keeps downgrade safe after a partially-applied migration.
    bind = op.get_bind()
    source_fks = sa.inspect(bind).get_foreign_keys("source_snapshots")
    has_source_fk = any(
        fk.get("name") == "fk_source_snapshots_data_source"
        or (fk.get("referred_table") == "data_sources" and fk.get("constrained_columns") == ["source_id"])
        for fk in source_fks
    )
    if bind.dialect.name == "postgresql":
        # Mirror of the upgrade branch: PostgreSQL cannot drop source_snapshots
        # via table-recreate while dependent FKs exist, so unwind the native DDL
        # explicitly and only drop the FK when it is actually present.
        if has_source_fk:
            op.drop_constraint("fk_source_snapshots_data_source", "source_snapshots", type_="foreignkey")
        op.drop_column("source_snapshots", "tombstone")
        op.alter_column(
            "source_snapshots",
            "source_id",
            existing_type=sa.String(36),
            type_=sa.String(255),
            existing_nullable=False,
        )
    else:
        with op.batch_alter_table("source_snapshots", recreate="always") as batch:
            if has_source_fk:
                batch.drop_constraint("fk_source_snapshots_data_source", type_="foreignkey")
            batch.drop_column("tombstone")
            batch.alter_column("source_id", existing_type=sa.String(36), type_=sa.String(255), existing_nullable=False)
    op.drop_table("sync_runs")
    op.drop_index("ix_import_diff_job_kind", table_name="import_diffs")
    op.drop_table("import_diffs")
    op.drop_index("ix_import_row_error_location", table_name="import_row_errors")
    op.drop_table("import_row_errors")
    op.drop_table("import_jobs")
    op.drop_table("field_mappings")
    op.drop_table("source_credential_refs")
    op.drop_table("data_sources")
