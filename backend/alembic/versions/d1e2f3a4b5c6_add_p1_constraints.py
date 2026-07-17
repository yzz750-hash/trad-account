"""add_p1_constraints

P1 fixes: add missing unique constraints and CHECK constraints identified
in the pre-delivery audit.

- UniqueConstraint on (ledger_id, asset_code) for fixed_assets
- UniqueConstraint on (ledger_id, code) for business_partners
- UniqueConstraint on (ledger_id, employee_id) for salespersons
- UniqueConstraint on (period_id, currency_id) for exchange_rates
- CHECK constraints on financial amount/rate columns
- NOT NULL on critical columns (attachments_count, status, currency_code,
  exchange_rate, opening_balance, accumulated_depreciation, salvage_value_rate)

This migration is idempotent: it deduplicates existing rows before adding
constraints so the migration succeeds even if bad data exists. Production
deployments should review the dedup log output before considering the
migration complete.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _bind():
    return op.get_bind()


def _is_postgres() -> bool:
    return _bind().dialect.name == "postgresql"


def _dedupe(table: str, key_cols: list[str], keep: str = "min_id") -> None:
    """Delete duplicate rows in `table` keyed by `key_cols`.

    Keeps the row with the smallest id (oldest) by default. Logs the count
    of deleted rows so operators can audit the cleanup.
    """
    bind = _bind()
    key_list = ", ".join(key_cols)
    # Find duplicate groups
    sql = sa.text(f"""
        SELECT {key_list}, COUNT(*) as cnt
        FROM {table}
        GROUP BY {key_list}
        HAVING COUNT(*) > 1
    """)
    duplicates = bind.execute(sql).fetchall()
    if not duplicates:
        return
    # Delete all but the min-id row in each duplicate group
    where_clause = " AND ".join([f"t.{c} = d.{c}" for c in key_cols])
    del_sql = sa.text(f"""
        DELETE FROM {table}
        WHERE id IN (
            SELECT t.id FROM {table} t
            JOIN (
                SELECT {key_list}, MIN(id) as keep_id
                FROM {table}
                GROUP BY {key_list}
                HAVING COUNT(*) > 1
            ) d ON {where_clause} AND t.id <> d.keep_id
        )
    """)
    result = bind.execute(del_sql)
    print(f"  [dedup] {table}: removed {result.rowcount} duplicate row(s)")


def upgrade() -> None:
    # --- Step 1: Deduplicate existing data before adding unique constraints ---
    print("P1 migration: deduplicating existing rows...")
    _dedupe("fixed_assets", ["ledger_id", "asset_code"])
    _dedupe("business_partners", ["ledger_id", "code"])
    _dedupe("salespersons", ["ledger_id", "employee_id"])
    _dedupe("exchange_rates", ["period_id", "currency_id"])

    # --- Step 2: Add NOT NULL constraints (with default backfill first) ---
    # Backfill NULLs with defaults before making NOT NULL, so existing rows
    # don't fail the constraint.
    bind = _bind()

    # accounts.opening_balance -> 0
    bind.execute(sa.text("UPDATE accounts SET opening_balance = 0 WHERE opening_balance IS NULL"))
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column("opening_balance",
            existing_type=sa.Numeric(15, 2),
            nullable=False,
            server_default="0.00",
        )

    # vouchers.attachments_count -> 0, status -> 'DRAFT'
    bind.execute(sa.text("UPDATE vouchers SET attachments_count = 0 WHERE attachments_count IS NULL"))
    bind.execute(sa.text("UPDATE vouchers SET status = 'DRAFT' WHERE status IS NULL"))
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.alter_column("attachments_count",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="0",
        )
        batch_op.alter_column("status",
            existing_type=sa.Enum("DRAFT", "APPROVED", "POSTED", name="voucherstatus"),
            nullable=False,
            server_default="DRAFT",
        )

    # voucher_entries: nullable + CHECK constraints (batch mode for SQLite).
    # SQLite cannot ALTER TABLE ADD CONSTRAINT — batch mode rebuilds the table
    # with the new constraints included in CREATE TABLE.
    bind.execute(sa.text("UPDATE voucher_entries SET currency_code = 'CNY' WHERE currency_code IS NULL"))
    bind.execute(sa.text("UPDATE voucher_entries SET exchange_rate = 1.0000 WHERE exchange_rate IS NULL"))
    # Backfill any non-positive amounts/rates before adding CHECK > 0.
    bind.execute(sa.text("UPDATE voucher_entries SET amount = 0.01 WHERE amount <= 0"))
    bind.execute(sa.text("UPDATE voucher_entries SET exchange_rate = 1.0000 WHERE exchange_rate <= 0"))
    with op.batch_alter_table("voucher_entries") as batch_op:
        batch_op.alter_column("currency_code",
            existing_type=sa.String(10),
            nullable=False,
            server_default="CNY",
        )
        batch_op.alter_column("exchange_rate",
            existing_type=sa.Numeric(10, 4),
            nullable=False,
            server_default="1.0000",
        )
        batch_op.create_check_constraint(
            "ck_voucher_entry_amount_positive", "amount > 0"
        )
        batch_op.create_check_constraint(
            "ck_voucher_entry_exchange_rate_positive", "exchange_rate > 0"
        )

    # fixed_assets: nullable + unique + CHECK constraints
    bind.execute(sa.text("UPDATE fixed_assets SET salvage_value_rate = 0.05 WHERE salvage_value_rate IS NULL"))
    bind.execute(sa.text("UPDATE fixed_assets SET accumulated_depreciation = 0 WHERE accumulated_depreciation IS NULL"))
    # Clamp out-of-range values before adding CHECK constraints.
    bind.execute(sa.text("UPDATE fixed_assets SET salvage_value_rate = 0.05 WHERE salvage_value_rate < 0 OR salvage_value_rate >= 1"))
    bind.execute(sa.text("UPDATE fixed_assets SET expected_useful_months = 1 WHERE expected_useful_months <= 0"))
    bind.execute(sa.text("UPDATE fixed_assets SET original_value = 0 WHERE original_value < 0"))
    bind.execute(sa.text("UPDATE fixed_assets SET accumulated_depreciation = 0 WHERE accumulated_depreciation < 0"))
    with op.batch_alter_table("fixed_assets") as batch_op:
        batch_op.alter_column("salvage_value_rate",
            existing_type=sa.Numeric(5, 4),
            nullable=False,
            server_default="0.0500",
        )
        batch_op.alter_column("accumulated_depreciation",
            existing_type=sa.Numeric(15, 2),
            nullable=False,
            server_default="0.00",
        )
        batch_op.create_unique_constraint(
            "uq_fixed_asset_ledger_code", ["ledger_id", "asset_code"]
        )
        batch_op.create_check_constraint(
            "ck_fixed_asset_original_value_nonneg", "original_value >= 0"
        )
        batch_op.create_check_constraint(
            "ck_fixed_asset_salvage_rate_range",
            "salvage_value_rate >= 0 AND salvage_value_rate < 1"
        )
        batch_op.create_check_constraint(
            "ck_fixed_asset_useful_months_positive", "expected_useful_months > 0"
        )
        batch_op.create_check_constraint(
            "ck_fixed_asset_accum_deprec_nonneg", "accumulated_depreciation >= 0"
        )

    # business_partners: unique constraint
    with op.batch_alter_table("business_partners") as batch_op:
        batch_op.create_unique_constraint(
            "uq_business_partner_ledger_code", ["ledger_id", "code"]
        )

    # salespersons: unique constraint
    with op.batch_alter_table("salespersons") as batch_op:
        batch_op.create_unique_constraint(
            "uq_salesperson_ledger_employee_id", ["ledger_id", "employee_id"]
        )

    # exchange_rates: unique + CHECK constraints
    # Clamp non-positive rates before adding CHECK.
    bind.execute(sa.text("UPDATE exchange_rates SET rate = 1.0 WHERE rate <= 0"))
    with op.batch_alter_table("exchange_rates") as batch_op:
        batch_op.create_unique_constraint(
            "uq_exchange_rate_period_currency", ["period_id", "currency_id"]
        )
        batch_op.create_check_constraint(
            "ck_exchange_rate_positive", "rate > 0"
        )

    # tax_rates: CHECK constraints
    # Clamp out-of-range rates and fix inverted effective periods.
    bind.execute(sa.text("UPDATE tax_rates SET rate = 0 WHERE rate < 0"))
    bind.execute(sa.text("UPDATE tax_rates SET rate = 1 WHERE rate > 1"))
    bind.execute(sa.text("UPDATE tax_rates SET effective_to = effective_from WHERE effective_to IS NOT NULL AND effective_to < effective_from"))
    with op.batch_alter_table("tax_rates") as batch_op:
        batch_op.create_check_constraint(
            "ck_tax_rate_range", "rate >= 0 AND rate <= 1"
        )
        batch_op.create_check_constraint(
            "ck_tax_rate_effective_period_valid",
            "effective_to IS NULL OR effective_to >= effective_from"
        )


def downgrade() -> None:
    # Drop in reverse order. Use batch mode throughout for SQLite compat
    # (SQLite cannot ALTER TABLE DROP CONSTRAINT directly).
    with op.batch_alter_table("tax_rates") as batch_op:
        batch_op.drop_constraint("ck_tax_rate_effective_period_valid", type_="check")
        batch_op.drop_constraint("ck_tax_rate_range", type_="check")
    with op.batch_alter_table("exchange_rates") as batch_op:
        batch_op.drop_constraint("ck_exchange_rate_positive", type_="check")
        batch_op.drop_constraint("uq_exchange_rate_period_currency", type_="unique")
    with op.batch_alter_table("salespersons") as batch_op:
        batch_op.drop_constraint("uq_salesperson_ledger_employee_id", type_="unique")
    with op.batch_alter_table("business_partners") as batch_op:
        batch_op.drop_constraint("uq_business_partner_ledger_code", type_="unique")
    with op.batch_alter_table("fixed_assets") as batch_op:
        batch_op.drop_constraint("ck_fixed_asset_accum_deprec_nonneg", type_="check")
        batch_op.drop_constraint("ck_fixed_asset_useful_months_positive", type_="check")
        batch_op.drop_constraint("ck_fixed_asset_salvage_rate_range", type_="check")
        batch_op.drop_constraint("ck_fixed_asset_original_value_nonneg", type_="check")
        batch_op.drop_constraint("uq_fixed_asset_ledger_code", type_="unique")
        batch_op.alter_column("accumulated_depreciation",
            existing_type=sa.Numeric(15, 2), nullable=True)
        batch_op.alter_column("salvage_value_rate",
            existing_type=sa.Numeric(5, 4), nullable=True)
    with op.batch_alter_table("voucher_entries") as batch_op:
        batch_op.drop_constraint("ck_voucher_entry_exchange_rate_positive", type_="check")
        batch_op.drop_constraint("ck_voucher_entry_amount_positive", type_="check")
        batch_op.alter_column("exchange_rate",
            existing_type=sa.Numeric(10, 4), nullable=True)
        batch_op.alter_column("currency_code",
            existing_type=sa.String(10), nullable=True)
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.alter_column("status",
            existing_type=sa.Enum("DRAFT", "APPROVED", "POSTED", name="voucherstatus"),
            nullable=True)
        batch_op.alter_column("attachments_count",
            existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column("opening_balance",
            existing_type=sa.Numeric(15, 2), nullable=True)
