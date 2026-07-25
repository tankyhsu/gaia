"""Add the durable transactional outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0005_outbox_events"
down_revision = "0004_configuration_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "outbox_events" in tables:
        return
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("event_key", sa.String(256)),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("headers_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(128)),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_outbox_events_delivery",
        "outbox_events",
        ["status", "available_at", "created_at"],
    )
    op.create_index("ix_outbox_events_lock", "outbox_events", ["locked_until"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "outbox_events" in tables:
        op.drop_table("outbox_events")
