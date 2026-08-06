"""Add durable per-Run execution budgets."""

import sqlalchemy as sa
from alembic import op

revision = "0011_run_budgets"
down_revision = "0010_business_builder_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "run_budgets" in inspector.get_table_names():
        return
    op.create_table(
        "run_budgets",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id"),
            primary_key=True,
        ),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_model_calls", sa.Integer(), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("steps_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waited_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if "run_budgets" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("run_budgets")
