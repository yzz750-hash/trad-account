"""add_accounting_period_unique_and_missing_indexes

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-06-18 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # M5: Unique constraint on AccountingPeriod (ledger_id, year, month)
    op.create_index(
        'uq_accounting_period_ledger_year_month',
        'accounting_periods',
        ['ledger_id', 'year', 'month'],
        unique=True,
    )
    # M6: Missing indexes for query performance
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('ix_vouchers_voucher_date', 'vouchers', ['voucher_date'])
    op.create_index('ix_vat_records_voucher_date', 'vat_records', ['voucher_date'])


def downgrade() -> None:
    op.drop_index('ix_vat_records_voucher_date', table_name='vat_records')
    op.drop_index('ix_vouchers_voucher_date', table_name='vouchers')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('uq_accounting_period_ledger_year_month', table_name='accounting_periods')
