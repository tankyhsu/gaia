"""Remove Gaia's retired SQL execution ledger.

Temporal Workflow History and Visibility are the execution source of truth.
The retained observation tables use ``run_id`` as an external correlation
identifier, not as a relational foreign key.

Downgrade recreates empty legacy tables and foreign keys. Data deleted by the
upgrade is intentionally not recoverable through a schema downgrade.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

from gaia.persistence.legacy_runtime_models import LegacyBase

revision = "0015_remove_sql_runtime"
down_revision = "0014_runtime_leases"
branch_labels = None
depends_on = None

_CORRELATION_TABLES = (
    "artifacts",
    "model_invocations",
    "tool_invocations",
    "guardrail_decisions",
)
_LEDGER_TABLES = (
    "run_budgets",
    "human_gates",
    "side_effect_commands",
    "run_events",
    "idempotency_records",
    "runtime_leases",
    "runs",
)
_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _run_foreign_key(table_name: str) -> dict[str, Any] | None:
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table_name):
        if (
            foreign_key.get("referred_table") == "runs"
            and foreign_key.get("constrained_columns") == ["run_id"]
        ):
            return dict(foreign_key)
    return None


def _drop_run_foreign_key(table_name: str) -> None:
    foreign_key = _run_foreign_key(table_name)
    if foreign_key is None:
        return
    name = foreign_key.get("name") or f"fk_{table_name}_run_id_runs"
    with op.batch_alter_table(
        table_name,
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch:
        batch.drop_constraint(str(name), type_="foreignkey")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in _CORRELATION_TABLES:
        if table_name in tables:
            _drop_run_foreign_key(table_name)
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in _LEDGER_TABLES:
        if table_name in tables:
            op.drop_table(table_name)


def downgrade() -> None:
    LegacyBase.metadata.create_all(op.get_bind())
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in _CORRELATION_TABLES:
        if table_name not in tables or _run_foreign_key(table_name) is not None:
            continue
        with op.batch_alter_table(
            table_name,
            recreate="always",
            naming_convention=_NAMING_CONVENTION,
        ) as batch:
            batch.create_foreign_key(
                f"fk_{table_name}_run_id_runs",
                "runs",
                ["run_id"],
                ["run_id"],
            )
