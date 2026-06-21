"""add_commission_models

Revision ID: 3da39ab4d635
Revises: 7876b1259fc1
Create Date: 2026-06-17 21:41:50.341944

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3da39ab4d635'
down_revision: Union[str, None] = '7876b1259fc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'salespersons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ledger_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('department', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.ForeignKeyConstraint(['ledger_id'], ['ledgers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_salespersons_id', 'salespersons', ['id'])
    op.create_index('ix_salespersons_ledger_id', 'salespersons', ['ledger_id'])

    op.create_table(
        'oem_contracts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ledger_id', sa.Integer(), nullable=False),
        sa.Column('contract_number', sa.String(100), nullable=False),
        sa.Column('salesperson_id', sa.Integer(), nullable=True),
        sa.Column('customer_name', sa.String(255), nullable=True),
        sa.Column('contract_date', sa.Date(), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('currency', sa.String(10), default='CNY'),
        sa.Column('status', sa.String(15), default='ACTIVE'),
        sa.ForeignKeyConstraint(['ledger_id'], ['ledgers.id']),
        sa.ForeignKeyConstraint(['salesperson_id'], ['salespersons.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ledger_id', 'contract_number', name='uq_oem_contracts_ledger_contract'),
    )
    op.create_index('ix_oem_contracts_id', 'oem_contracts', ['id'])
    op.create_index('ix_oem_contracts_ledger_id', 'oem_contracts', ['ledger_id'])
    op.create_index('ix_oem_contracts_contract_number', 'oem_contracts', ['contract_number'])

    op.create_table(
        'commission_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ledger_id', sa.Integer(), nullable=False),
        sa.Column('salesperson_id', sa.Integer(), nullable=True),
        sa.Column('rule_name', sa.String(100), nullable=False),
        sa.Column('basis', sa.String(12), nullable=False, default='gross_profit'),
        sa.Column('rate', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.ForeignKeyConstraint(['ledger_id'], ['ledgers.id']),
        sa.ForeignKeyConstraint(['salesperson_id'], ['salespersons.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_commission_rules_id', 'commission_rules', ['id'])
    op.create_index('ix_commission_rules_ledger_id', 'commission_rules', ['ledger_id'])


def downgrade() -> None:
    op.drop_index('ix_commission_rules_ledger_id', table_name='commission_rules')
    op.drop_index('ix_commission_rules_id', table_name='commission_rules')
    op.drop_table('commission_rules')
    op.drop_index('ix_oem_contracts_contract_number', table_name='oem_contracts')
    op.drop_index('ix_oem_contracts_ledger_id', table_name='oem_contracts')
    op.drop_index('ix_oem_contracts_id', table_name='oem_contracts')
    op.drop_table('oem_contracts')
    op.drop_index('ix_salespersons_ledger_id', table_name='salespersons')
    op.drop_index('ix_salespersons_id', table_name='salespersons')
    op.drop_table('salespersons')
