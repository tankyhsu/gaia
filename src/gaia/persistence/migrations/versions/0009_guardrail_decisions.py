"""Add payload-free guardrail decision evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0009_guardrail_decisions"
down_revision = "0008_model_invocations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "guardrail_decisions" in tables:
        return
    op.create_table(
        "guardrail_decisions",
        sa.Column("decision_id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id")),
        sa.Column("scenario_id", sa.String(128), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("guardrail_id", sa.String(128), nullable=False),
        sa.Column("guardrail_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Float()),
        sa.Column("input_ref", sa.String(80), nullable=False),
        sa.Column("output_ref", sa.String(80)),
        sa.Column("code", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_guardrail_decisions_run",
        "guardrail_decisions",
        ["run_id", "started_at"],
    )
    op.create_index(
        "ix_guardrail_decisions_stage",
        "guardrail_decisions",
        ["stage", "action", "started_at"],
    )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "guardrail_decisions" in tables:
        op.drop_table("guardrail_decisions")
