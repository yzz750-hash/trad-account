"""add_closing_operation_unique_constraint

Revision ID: dafd8249d0e9
Revises: 601ecec77810
Create Date: 2026-06-18 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dafd8249d0e9'
down_revision: Union[str, None] = '601ecec77810'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_closing_operation_period', 'closing_operations',
        ['ledger_id', 'operation_type', 'year', 'month'], unique=True
    )


def downgrade() -> None:
    op.drop_index('uq_closing_operation_period', table_name='closing_operations')
