"""add_ledger_created_by_and_constraints

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # H13: Add created_by to ledgers for cross-tenant access control
    op.add_column('ledgers', sa.Column('created_by', sa.Integer(), nullable=True))

    # H17: Add unique indexes (SQLite-compatible; same effect as unique constraints)
    op.create_index('uq_accounts_ledger_code', 'accounts', ['ledger_id', 'code'], unique=True)
    op.create_index('uq_voucher_counters_ledger_prefix', 'voucher_number_counters', ['ledger_id', 'prefix'], unique=True)
    op.create_index('uq_accounting_periods_ledger_ym', 'accounting_periods', ['ledger_id', 'year', 'month'], unique=True)
    op.create_index('uq_exchange_rates_period_currency', 'exchange_rates', ['period_id', 'currency_id'], unique=True)
    op.create_index('uq_closing_ops', 'closing_operations', ['ledger_id', 'operation_type', 'year', 'month'], unique=True)

    # H17: Add FK indexes for common join paths (only those not already in earlier migrations)
    op.create_index('ix_voucher_entries_voucher_id', 'voucher_entries', ['voucher_id'])
    op.create_index('ix_voucher_entries_account_id', 'voucher_entries', ['account_id'])
    op.create_index('ix_exchange_rates_period_id', 'exchange_rates', ['period_id'])


def downgrade() -> None:
    op.drop_index('ix_exchange_rates_period_id', table_name='exchange_rates')
    op.drop_index('ix_voucher_entries_account_id', table_name='voucher_entries')
    op.drop_index('ix_voucher_entries_voucher_id', table_name='voucher_entries')

    op.drop_index('uq_closing_ops', table_name='closing_operations')
    op.drop_index('uq_exchange_rates_period_currency', table_name='exchange_rates')
    op.drop_index('uq_accounting_periods_ledger_ym', table_name='accounting_periods')
    op.drop_index('uq_voucher_counters_ledger_prefix', table_name='voucher_number_counters')
    op.drop_index('uq_accounts_ledger_code', table_name='accounts')

    op.drop_column('ledgers', 'created_by')
