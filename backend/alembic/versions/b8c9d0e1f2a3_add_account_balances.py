"""add_account_balances

Revision ID: b8c9d0e1f2a3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-20 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'account_balances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ledger_id', sa.Integer(), sa.ForeignKey('ledgers.id'), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=True),
        sa.Column('period_debit', sa.Numeric(15, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('period_credit', sa.Numeric(15, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('ending_debit', sa.Numeric(15, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('ending_credit', sa.Numeric(15, 2), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ledger_id', 'account_id', 'year', 'month', name='uq_account_balance_period'),
    )
    op.create_index('ix_account_balances_id', 'account_balances', ['id'])
    op.create_index('ix_account_balances_ledger_id', 'account_balances', ['ledger_id'])
    op.create_index('ix_account_balances_account_id', 'account_balances', ['account_id'])
    op.create_index('ix_account_balances_lookup', 'account_balances', ['ledger_id', 'year', 'month'])


def downgrade() -> None:
    op.drop_index('ix_account_balances_lookup', table_name='account_balances')
    op.drop_index('ix_account_balances_account_id', table_name='account_balances')
    op.drop_index('ix_account_balances_ledger_id', table_name='account_balances')
    op.drop_index('ix_account_balances_id', table_name='account_balances')
    op.drop_table('account_balances')
