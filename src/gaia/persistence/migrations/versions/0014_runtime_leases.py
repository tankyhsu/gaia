"""Add runtime_leases table and command recovery_attempts column.

Both changes land in one revision (rather than two) because the lease table
and the `recovery_attempts` column are both prerequisites of the same task
(D1 in `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`): bounded, leased
startup recovery. Splitting them into two revisions would make them depend
on each other for no benefit.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_runtime_leases"
down_revision = "0013_runtime_continuation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "runtime_leases" not in inspector.get_table_names():
        op.create_table(
            "runtime_leases",
            sa.Column("name", sa.String(128), primary_key=True),
            sa.Column("owner", sa.String(256), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
    # `side_effect_commands` is only ever created by 0001_initial's
    # `Base.metadata.create_all`, never by an explicit `create_table` in a
    # later revision, so a chain that starts from a hand-rolled legacy
    # snapshot pinned after 0001 (see
    # tests/integration/test_migrations.py::test_legacy_event_counter_is_backfilled,
    # which only recreates the `runs`/`run_events` tables 0001 would have
    # produced, not the rest) will not have it. Guard on table existence, not
    # just column existence, the same way 0011 guards `run_budgets`.
    if "side_effect_commands" in inspector.get_table_names():
        columns = {item["name"] for item in inspector.get_columns("side_effect_commands")}
        if "recovery_attempts" not in columns:
            op.add_column(
                "side_effect_commands",
                sa.Column("recovery_attempts", sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "side_effect_commands" in inspector.get_table_names():
        columns = {item["name"] for item in inspector.get_columns("side_effect_commands")}
        if "recovery_attempts" in columns:
            op.drop_column("side_effect_commands", "recovery_attempts")
    if "runtime_leases" in inspector.get_table_names():
        op.drop_table("runtime_leases")
