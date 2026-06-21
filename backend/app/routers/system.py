from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import require_write, CurrentUser
from app.routers.ledgers import get_ledger_id
from app.models.financial import (
    Account, AccountBalance, AccountingPeriod, Currency, ExchangeRate,
    PeriodStatus, Voucher, VoucherEntry, VoucherStatus, AccountDirection,
)
from app.types import Money

router = APIRouter()

@router.get("/periods/current")
def get_current_period(db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    period = db.query(AccountingPeriod).filter(AccountingPeriod.ledger_id == ledger_id, AccountingPeriod.status == "OPEN").order_by(AccountingPeriod.year.desc(), AccountingPeriod.month.desc()).first()
    if period:
        return {"year": period.year, "month": period.month, "status": period.status.value}
    return None

@router.get("/currencies")
def get_currencies(db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    currencies = db.query(Currency).all()
    return [{"id": c.id, "code": c.code, "name": c.name, "is_base": c.is_base} for c in currencies]

@router.get("/rates")
def get_rates(year: int, month: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    period = db.query(AccountingPeriod).filter(AccountingPeriod.ledger_id == ledger_id, AccountingPeriod.year == year, AccountingPeriod.month == month).first()
    if not period:
        return []
    
    rates = db.query(ExchangeRate).filter(ExchangeRate.period_id == period.id).all()
    currency_ids = {r.currency_id for r in rates}
    currencies = {c.id: c for c in db.query(Currency).filter(Currency.id.in_(currency_ids)).all()} if currency_ids else {}
    return [{"currency_code": currencies[r.currency_id].code, "rate": r.rate} for r in rates if r.currency_id in currencies]

from pydantic import BaseModel
class RateUpdate(BaseModel):
    currency_code: str
    rate: Money

@router.post("/rates")
def update_rate(
    year: int,
    month: int,
    data: RateUpdate,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    current_user: CurrentUser = Depends(require_write),
):
    from fastapi import HTTPException
    period = db.query(AccountingPeriod).filter(AccountingPeriod.ledger_id == ledger_id, AccountingPeriod.year == year, AccountingPeriod.month == month).first()
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
        
    curr = db.query(Currency).filter(Currency.code == data.currency_code).first()
    if not curr:
        raise HTTPException(status_code=404, detail="Currency not found")
        
    rate_record = db.query(ExchangeRate).filter(ExchangeRate.period_id == period.id, ExchangeRate.currency_id == curr.id).first()
    if rate_record:
        rate_record.rate = data.rate
    else:
        new_rate = ExchangeRate(period_id=period.id, currency_id=curr.id, rate=data.rate)
        db.add(new_rate)
        
    db.commit()
    return {"status": "success"}


@router.post("/backfill-balances")
def backfill_balances(
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    current_user: CurrentUser = Depends(require_write),
):
    """Recompute AccountBalance rows for all closed periods in chronological order.

    Idempotent — safe to run multiple times. Each period is recomputed in its
    own mini-transaction so a failure mid-way leaves earlier periods intact.
    """
    from collections import defaultdict
    from sqlalchemy import func, extract

    closed_periods = (
        db.query(AccountingPeriod)
        .filter(
            AccountingPeriod.ledger_id == ledger_id,
            AccountingPeriod.status == PeriodStatus.CLOSED,
        )
        .order_by(AccountingPeriod.year.asc(), AccountingPeriod.month.asc())
        .all()
    )

    if not closed_periods:
        return {"status": "success", "message": "No closed periods to backfill."}

    accounts = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.is_active == True
    ).all()
    account_ids = [a.id for a in accounts]

    processed = 0
    for period in closed_periods:
        year, month = period.year, period.month

        # Period activity from POSTED vouchers
        rows = (
            db.query(
                VoucherEntry.account_id,
                VoucherEntry.direction,
                func.sum(VoucherEntry.amount),
            )
            .join(Voucher)
            .filter(
                Voucher.ledger_id == ledger_id,
                VoucherEntry.account_id.in_(account_ids),
                extract('year', Voucher.voucher_date) == year,
                extract('month', Voucher.voucher_date) == month,
                Voucher.status == VoucherStatus.POSTED,
            )
            .group_by(VoucherEntry.account_id, VoucherEntry.direction)
            .all()
        )

        period_map = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
        for acct_id, direction, amt in rows:
            period_map[acct_id][direction] = Decimal(str(amt or 0))

        # Previous period ending balances
        if month > 1:
            prev_year, prev_month = year, month - 1
        else:
            prev_year, prev_month = year - 1, 12

        prev_ending = {}
        for pb in db.query(AccountBalance).filter(
            AccountBalance.ledger_id == ledger_id,
            AccountBalance.year == prev_year,
            AccountBalance.month == prev_month,
        ).all():
            prev_ending[pb.account_id] = pb

        # Delete existing and re-insert
        db.query(AccountBalance).filter(
            AccountBalance.ledger_id == ledger_id,
            AccountBalance.year == year,
            AccountBalance.month == month,
        ).delete()

        for account in accounts:
            p_debit = period_map[account.id][AccountDirection.DEBIT]
            p_credit = period_map[account.id][AccountDirection.CREDIT]
            prev = prev_ending.get(account.id)
            prev_debit = prev.ending_debit if prev else Decimal("0")
            prev_credit = prev.ending_credit if prev else Decimal("0")

            db.add(AccountBalance(
                ledger_id=ledger_id, account_id=account.id,
                year=year, month=month,
                period_debit=p_debit, period_credit=p_credit,
                ending_debit=prev_debit + p_debit,
                ending_credit=prev_credit + p_credit,
            ))

        db.commit()
        processed += 1

    return {
        "status": "success",
        "message": f"Backfilled {processed} period(s) for ledger {ledger_id}.",
    }
