"""Clean test vouchers for re-running E2E test."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# PG password must be provided via PG_PASSWORD env var (or DATABASE_URL directly)
# to avoid committing credentials to version control.
os.environ.setdefault(
    "DATABASE_URL",
    f"postgresql+psycopg2://trad_user:{os.environ.get('PG_PASSWORD', 'SET_ME')}@localhost:5432/trad_account",
)
from app.database import SessionLocal
from app.models.financial import (
    Voucher, VoucherEntry, VoucherNumberCounter, ClosingOperation, AccountBalance,
    AccountingPeriod, PeriodStatus,
)

s = SessionLocal()
try:
    # Order matters: VoucherEntry & ClosingOperation reference Voucher via FK,
    # so they must be deleted BEFORE Voucher.
    s.query(VoucherEntry).delete()
    # Null out voucher_id in ClosingOperation first (some rows may reference
    # vouchers we're about to delete), then delete the rows themselves.
    s.query(ClosingOperation).update({ClosingOperation.voucher_id: None})
    s.query(ClosingOperation).delete()
    s.query(Voucher).delete()
    s.query(VoucherNumberCounter).delete()
    s.query(AccountBalance).delete()
    # Reset any CLOSED periods back to OPEN so re-runs can create vouchers.
    closed = s.query(AccountingPeriod).filter(AccountingPeriod.status != PeriodStatus.OPEN).all()
    for p in closed:
        p.status = PeriodStatus.OPEN
    s.commit()
    print(f"Cleaned vouchers/entries/counters/closing ops/balances; reset {len(closed)} period(s) to OPEN")
finally:
    s.close()
