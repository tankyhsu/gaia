"""Add safe model invocation evidence linked to Runs."""

import sqlalchemy as sa
from alembic import op

revision = "0008_model_invocations"
down_revision = "0007_prompt_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "model_invocations" in tables:
        return
    op.create_table(
        "model_invocations",
        sa.Column("invocation_id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id")),
        sa.Column("scenario_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("model_parameters_hash", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(256), nullable=False),
        sa.Column("prompt_content_hash", sa.String(80)),
        sa.Column("request_ref", sa.String(80), nullable=False),
        sa.Column("response_ref", sa.String(80)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("usage_json", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_token_latency_ms", sa.Integer()),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
    )
    op.create_index(
        "ix_model_invocations_run",
        "model_invocations",
        ["run_id", "started_at"],
    )
    op.create_index(
        "ix_model_invocations_status",
        "model_invocations",
        ["status", "started_at"],
    )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "model_invocations" in tables:
        op.drop_table("model_invocations")
