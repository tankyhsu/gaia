"""Add Runtime-owned post-action continuation state."""

import sqlalchemy as sa
from alembic import op

revision = "0013_runtime_continuation"
down_revision = "0012_runtime_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("runs")}
    if "continuation_json" not in columns:
        op.add_column("runs", sa.Column("continuation_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("runs")}
    if "continuation_json" in columns:
        op.drop_column("runs", "continuation_json")
