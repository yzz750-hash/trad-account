"""add_exchange_rate_precision_and_openitem_index

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for reconcile-suggestions filtering
    op.create_index("ix_open_items_ledger_type_status", "open_items",
                    ["ledger_id", "item_type", "status"])

    # Exchange rate: 4 decimal places insufficient for KRW/VND/JPY
    # batch_alter_table required for SQLite (no ALTER COLUMN TYPE support)
    with op.batch_alter_table("exchange_rates") as batch_op:
        batch_op.alter_column("rate",
                              existing_type=sa.Numeric(10, 4),
                              type_=sa.Numeric(12, 8),
                              existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("exchange_rates") as batch_op:
        batch_op.alter_column("rate",
                              existing_type=sa.Numeric(12, 8),
                              type_=sa.Numeric(10, 4),
                              existing_nullable=False)

    op.drop_index("ix_open_items_ledger_type_status", table_name="open_items")
