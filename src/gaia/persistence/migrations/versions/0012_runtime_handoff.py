"""Add Runtime-owned persistent Agent Handoff state."""

import sqlalchemy as sa
from alembic import op

revision = "0012_runtime_handoff"
down_revision = "0011_run_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("runs")}
    if "handoff_json" not in columns:
        op.add_column("runs", sa.Column("handoff_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("runs")}
    if "handoff_json" in columns:
        op.drop_column("runs", "handoff_json")
