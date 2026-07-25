"""Add per-run event sequence counter for concurrent-safe allocation."""

import sqlalchemy as sa
from alembic import op

revision = "0002_run_event_counter"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("runs")}
    if "event_sequence" not in columns:
        with op.batch_alter_table("runs") as batch:
            batch.add_column(
                sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0")
            )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("runs")}
    if "event_sequence" in columns:
        with op.batch_alter_table("runs") as batch:
            batch.drop_column("event_sequence")
