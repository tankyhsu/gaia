"""Backfill per-run event counters from historical append-only events."""

import sqlalchemy as sa
from alembic import op

revision = "0003_backfill_run_event_counter"
down_revision = "0002_run_event_counter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE runs
            SET event_sequence = CASE
                WHEN event_sequence < COALESCE(
                    (SELECT MAX(sequence) FROM run_events WHERE run_events.run_id = runs.run_id),
                    0
                )
                THEN COALESCE(
                    (SELECT MAX(sequence) FROM run_events WHERE run_events.run_id = runs.run_id),
                    0
                )
                ELSE event_sequence
            END
            """
        )
    )


def downgrade() -> None:
    pass
