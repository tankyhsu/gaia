"""Remove the retired configuration control-plane tables."""

import sqlalchemy as sa
from alembic import op

revision = "0006_remove_control_plane"
down_revision = "0005_outbox_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("configuration_audits", "configuration_revisions", "applications"):
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "applications" not in tables:
        op.create_table(
            "applications",
            sa.Column("application_id", sa.String(64), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "configuration_revisions" not in tables:
        op.create_table(
            "configuration_revisions",
            sa.Column("revision_id", sa.String(64), primary_key=True),
            sa.Column(
                "application_id",
                sa.String(64),
                sa.ForeignKey("applications.application_id"),
                nullable=False,
            ),
            sa.Column("profile", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("restart_required", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("activated_by", sa.String(128)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("activated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint(
                "application_id",
                "profile",
                "sequence",
                name="uq_config_revision_sequence",
            ),
        )
        op.create_index(
            "uq_active_configuration_revision",
            "configuration_revisions",
            ["application_id", "profile"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )
    if "configuration_audits" not in tables:
        op.create_table(
            "configuration_audits",
            sa.Column("audit_id", sa.String(64), primary_key=True),
            sa.Column(
                "application_id",
                sa.String(64),
                sa.ForeignKey("applications.application_id"),
                nullable=False,
            ),
            sa.Column(
                "revision_id",
                sa.String(64),
                sa.ForeignKey("configuration_revisions.revision_id"),
            ),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("actor", sa.String(128), nullable=False),
            sa.Column("from_status", sa.String(32)),
            sa.Column("to_status", sa.String(32)),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_configuration_audits_revision_id",
            "configuration_audits",
            ["revision_id"],
        )
