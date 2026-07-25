"""Add immutable prompt versions, release pointers and audit records."""

import sqlalchemy as sa
from alembic import op

revision = "0007_prompt_registry"
down_revision = "0006_remove_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "prompt_versions" not in tables:
        op.create_table(
            "prompt_versions",
            sa.Column("prompt_id", sa.String(128), primary_key=True),
            sa.Column("version", sa.String(128), primary_key=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("artifact_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("validation_json", sa.JSON()),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "prompt_id",
                "content_hash",
                name="uq_prompt_version_content",
            ),
        )
        op.create_index(
            "ix_prompt_versions_status",
            "prompt_versions",
            ["status", "updated_at"],
        )
    if "prompt_releases" not in tables:
        op.create_table(
            "prompt_releases",
            sa.Column("prompt_id", sa.String(128), primary_key=True),
            sa.Column("environment", sa.String(32), primary_key=True),
            sa.Column("version", sa.String(128), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("updated_by", sa.String(128), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "prompt_audits" not in tables:
        op.create_table(
            "prompt_audits",
            sa.Column("audit_id", sa.String(64), primary_key=True),
            sa.Column("prompt_id", sa.String(128), nullable=False),
            sa.Column("version", sa.String(128)),
            sa.Column("environment", sa.String(32)),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("actor", sa.String(128), nullable=False),
            sa.Column("details_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_prompt_audits_prompt",
            "prompt_audits",
            ["prompt_id", "created_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "prompt_audits" in tables:
        op.drop_table("prompt_audits")
    if "prompt_releases" in tables:
        op.drop_table("prompt_releases")
    if "prompt_versions" in tables:
        op.drop_table("prompt_versions")
