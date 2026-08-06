"""Add Gaia's durable audit projection.

Revision 0015 made Temporal the execution source of truth and dropped the SQL
ledger with it. That left every audit read -- who approved, under which policy
version, what was blocked -- answerable only for as long as Temporal keeps the
Workflow History, which its namespace retention deletes on a schedule.

These tables are the record that outlives it. They are written by the
`gaia.runtime.record_audit` Activity, never by request handlers, and they hold
no foreign key to Temporal: `run_id` is a correlation identifier whose owning
Workflow is expected to be gone.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_audit_projection"
down_revision = "0015_remove_sql_runtime"
branch_labels = None
depends_on = None

_TABLES = ("audit_run_events", "audit_human_gates", "audit_runs")


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "audit_runs" not in existing:
        op.create_table(
            "audit_runs",
            sa.Column("run_id", sa.String(64), primary_key=True),
            sa.Column("organization", sa.String(128), nullable=False),
            sa.Column("scenario_id", sa.String(128), nullable=False),
            sa.Column("mode", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_audit_runs_listing",
            "audit_runs",
            ["organization", "created_at", "run_id"],
        )
        op.create_index(
            "ix_audit_runs_status",
            "audit_runs",
            ["organization", "status"],
        )
        op.create_index(
            "ix_audit_runs_scenario",
            "audit_runs",
            ["organization", "scenario_id"],
        )

    if "audit_run_events" not in existing:
        op.create_table(
            "audit_run_events",
            sa.Column("run_id", sa.String(64), primary_key=True),
            sa.Column("sequence", sa.Integer(), primary_key=True),
            sa.Column("event_json", sa.JSON(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "audit_human_gates" not in existing:
        op.create_table(
            "audit_human_gates",
            sa.Column("gate_id", sa.String(200), primary_key=True),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("gate_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_audit_human_gates_run",
            "audit_human_gates",
            ["run_id", "created_at"],
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in _TABLES:
        if table in existing:
            op.drop_table(table)
