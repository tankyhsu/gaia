"""Add business-builder runtime state and read-tool evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0010_business_builder_runtime"
down_revision = "0009_guardrail_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    run_columns = {item["name"] for item in inspector.get_columns("runs")}
    if "pending_result_json" not in run_columns:
        op.add_column("runs", sa.Column("pending_result_json", sa.JSON(), nullable=True))
    if "action_plan_json" not in run_columns:
        op.add_column("runs", sa.Column("action_plan_json", sa.JSON(), nullable=True))
    if "human_gates" in tables:
        gate_columns = {item["name"] for item in inspector.get_columns("human_gates")}
        if "approval_view_json" not in gate_columns:
            op.add_column(
                "human_gates",
                sa.Column("approval_view_json", sa.JSON(), nullable=True),
            )
    if "tool_invocations" not in tables:
        op.create_table(
            "tool_invocations",
            sa.Column("invocation_id", sa.String(64), primary_key=True),
            sa.Column(
                "run_id",
                sa.String(64),
                sa.ForeignKey("runs.run_id"),
                nullable=False,
            ),
            sa.Column("scenario_id", sa.String(128), nullable=False),
            sa.Column("tool_name", sa.String(128), nullable=False),
            sa.Column("tool_version", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("input_ref", sa.String(80), nullable=False),
            sa.Column("output_ref", sa.String(80)),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False),
            sa.Column("error_code", sa.String(64)),
        )
        op.create_index(
            "ix_tool_invocations_run",
            "tool_invocations",
            ["run_id", "started_at"],
        )
        op.create_index(
            "ix_tool_invocations_status",
            "tool_invocations",
            ["status", "started_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "tool_invocations" in tables:
        op.drop_table("tool_invocations")
    if "human_gates" in tables:
        gate_columns = {item["name"] for item in inspector.get_columns("human_gates")}
        if "approval_view_json" in gate_columns:
            op.drop_column("human_gates", "approval_view_json")
    run_columns = {item["name"] for item in inspector.get_columns("runs")}
    if "action_plan_json" in run_columns:
        op.drop_column("runs", "action_plan_json")
    if "pending_result_json" in run_columns:
        op.drop_column("runs", "pending_result_json")
