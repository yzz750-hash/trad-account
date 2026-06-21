"""add_missing_fk_indexes

Revision ID: e5f6a7b8c9d0
Revises: dafd8249d0e9
Create Date: 2026-06-18 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'dafd8249d0e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_exchange_rates_currency_id', 'exchange_rates', ['currency_id'])
    op.create_index('ix_reconciliation_records_invoice_item_id', 'reconciliation_records', ['invoice_item_id'])
    op.create_index('ix_reconciliation_records_statement_item_id', 'reconciliation_records', ['statement_item_id'])


def downgrade() -> None:
    op.drop_index('ix_reconciliation_records_statement_item_id', table_name='reconciliation_records')
    op.drop_index('ix_reconciliation_records_invoice_item_id', table_name='reconciliation_records')
    op.drop_index('ix_exchange_rates_currency_id', table_name='exchange_rates')
