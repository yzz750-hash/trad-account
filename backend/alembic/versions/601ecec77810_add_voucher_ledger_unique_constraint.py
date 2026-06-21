"""add_voucher_ledger_unique_constraint

Revision ID: 601ecec77810
Revises: b2c3d4e5f6a7
Create Date: 2026-06-18 13:04:47.887503

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '601ecec77810'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # H5: Add ledger-level unique constraint on voucher_number
    op.create_index(
        'uq_voucher_ledger_number', 'vouchers',
        ['ledger_id', 'voucher_number'], unique=True
    )


def downgrade() -> None:
    op.drop_index('uq_voucher_ledger_number', table_name='vouchers')
