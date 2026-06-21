"""Closing service — core financial operations extracted from the router.

ponytail: functions accept db + params, return data tuples. The router handles
HTTP concerns (status codes, idempotency, response formatting).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
import calendar as _cal

from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException

from app.models.financial import (
    Account,
    AccountBalance,
    Voucher,
    VoucherEntry,
    VoucherStatus,
    AccountDirection,
    AccountType,
    FixedAsset,
    AccountingPeriod,
    Currency,
    ExchangeRate,
    Ledger,
    PeriodStatus,
)

D = Decimal


def check_no_draft_vouchers(db: Session, ledger_id: int, year: int, month: int) -> None:
    """Block period-end operations if any DRAFT vouchers exist for the period."""
    draft_count = db.query(Voucher).filter(
        Voucher.ledger_id == ledger_id,
        func.extract('year', Voucher.voucher_date) == year,
        func.extract('month', Voucher.voucher_date) == month,
        Voucher.status == VoucherStatus.DRAFT,
    ).count()
    if draft_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot proceed: {draft_count} unposted voucher(s) exist for {year}-{month:02d}. Post or delete them first.",
        )


def check_period_open(db: Session, ledger_id: int, year: int, month: int) -> None:
    """Raise HTTPException if the accounting period is not OPEN."""
    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == year,
        AccountingPeriod.month == month,
    ).first()
    if period and period.status != PeriodStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail=f"Period {year}-{month:02d} is {period.status.value}. Cannot create vouchers in a closed period.",
        )


def compute_period_balances(db: Session, ledger_id: int, year: int, month: int) -> None:
    """Pre-compute AccountBalance rows for every active account in this period.

    Reads POSTED voucher entries for the period, chains from previous period's
    ending balances, and upserts. Called inside close_period's transaction.
    """
    accounts = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.is_active == True
    ).all()
    if not accounts:
        return

    account_ids = [a.id for a in accounts]

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
            func.extract('year', Voucher.voucher_date) == year,
            func.extract('month', Voucher.voucher_date) == month,
            Voucher.status == VoucherStatus.POSTED,
        )
        .group_by(VoucherEntry.account_id, VoucherEntry.direction)
        .all()
    )

    period_map = defaultdict(lambda: defaultdict(lambda: D("0")))
    for acct_id, direction, amt in rows:
        period_map[acct_id][direction] = D(str(amt or 0))

    if month > 1:
        prev_year, prev_month = year, month - 1
    else:
        prev_year, prev_month = year - 1, 12

    prev_ending = {}
    for pb in db.query(AccountBalance).filter(
        AccountBalance.ledger_id == ledger_id,
        AccountBalance.year == prev_year,
        AccountBalance.month == prev_month,
    ).with_for_update().all():
        prev_ending[pb.account_id] = pb

    for account in accounts:
        p_debit = period_map[account.id][AccountDirection.DEBIT]
        p_credit = period_map[account.id][AccountDirection.CREDIT]

        prev = prev_ending.get(account.id)
        prev_debit = prev.ending_debit if prev else D("0")
        prev_credit = prev.ending_credit if prev else D("0")

        ending_debit = prev_debit + p_debit
        ending_credit = prev_credit + p_credit

        existing = db.query(AccountBalance).filter(
            AccountBalance.ledger_id == ledger_id,
            AccountBalance.account_id == account.id,
            AccountBalance.year == year,
            AccountBalance.month == month,
        ).first()

        if existing:
            existing.period_debit = p_debit
            existing.period_credit = p_credit
            existing.ending_debit = ending_debit
            existing.ending_credit = ending_credit
        else:
            db.add(AccountBalance(
                ledger_id=ledger_id, account_id=account.id,
                year=year, month=month,
                period_debit=p_debit, period_credit=p_credit,
                ending_debit=ending_debit, ending_credit=ending_credit,
            ))

    db.flush()


def calculate_depreciation(
    db: Session, ledger_id: int, year: int, month: int
) -> tuple[Decimal, list[tuple[FixedAsset, Decimal]]]:
    """Calculate straight-line depreciation for all active fixed assets.

    Returns (total_depreciation, [(asset, monthly_amount), ...]).
    CAS: depreciation starts the month AFTER purchase.
    """
    period_start = date(year, month, 1)
    assets = db.query(FixedAsset).filter(
        FixedAsset.ledger_id == ledger_id,
        FixedAsset.is_active == True,
        FixedAsset.purchase_date < period_start,
    ).all()

    if not assets:
        return D("0"), [], False  # (total, details, had_any_assets)

    had_any = False
    total = D("0")
    details = []
    for asset in assets:
        had_any = True
        salvage_limit = asset.original_value * (1 - asset.salvage_value_rate)
        if asset.accumulated_depreciation >= salvage_limit:
            continue

        monthly_depr = (asset.original_value * (1 - asset.salvage_value_rate)) / asset.expected_useful_months
        monthly_depr = monthly_depr.quantize(D("0.01"))
        remaining = salvage_limit - asset.accumulated_depreciation
        actual_depr = min(monthly_depr, remaining)

        # Atomic SQL UPDATE
        db.query(FixedAsset).filter(
            FixedAsset.id == asset.id,
            FixedAsset.accumulated_depreciation < salvage_limit,
        ).update({
            FixedAsset.accumulated_depreciation: FixedAsset.accumulated_depreciation + actual_depr
        })
        total += actual_depr
        details.append((asset, actual_depr))
    db.flush()
    return total, details, had_any


def calculate_fx_revaluation(
    db: Session, ledger_id: int, year: int, month: int
) -> tuple[list[dict], Decimal]:
    """Calculate FX revaluation for all foreign-currency positions.

    Reads cumulative positions from ledger start to period end.
    Returns (entries_for_voucher, total_gain_loss) where each entry is a dict
    with keys: account_id, summary, direction, amount, currency_code.
    """
    _, last_day = _cal.monthrange(year, month)
    period_end = date(year, month, last_day)

    lgr = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    ledger_start = date(lgr.start_year, lgr.start_month, 1) if lgr else date(year, 1, 1)

    entries = db.query(VoucherEntry).join(Voucher).filter(
        Voucher.ledger_id == ledger_id,
        VoucherEntry.currency_code != 'CNY',
        VoucherEntry.currency_code.isnot(None),
        Voucher.voucher_date >= ledger_start,
        Voucher.voucher_date <= period_end,
        Voucher.status == VoucherStatus.POSTED,
    ).all()

    if not entries:
        return [], D("0")

    entry_account_ids = list({e.account_id for e in entries})
    accounts_map = {}
    if entry_account_ids:
        accs = db.query(Account).filter(
            Account.ledger_id == ledger_id, Account.id.in_(entry_account_ids)
        ).all()
        accounts_map = {a.id: a for a in accs}

    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == year,
        AccountingPeriod.month == month,
    ).first()
    if not period:
        return [], D("0")

    currencies_map = {c.code: c for c in db.query(Currency).all()}
    rates_list = db.query(ExchangeRate).filter(ExchangeRate.period_id == period.id).all()
    rates_map = {r.currency_id: r for r in rates_list}

    balances = defaultdict(lambda: {"orig": D("0"), "base": D("0"), "account": None})
    for e in entries:
        acc = accounts_map.get(e.account_id)
        if not acc:
            continue
        if not balances[(e.account_id, e.currency_code)]["account"]:
            balances[(e.account_id, e.currency_code)]["account"] = acc

        sign = 1 if e.direction == acc.balance_direction else -1
        balances[(e.account_id, e.currency_code)]["orig"] += D(str(e.original_amount or 0)) * sign
        balances[(e.account_id, e.currency_code)]["base"] += D(str(e.amount)) * sign

    voucher_entries = []
    total_gain_loss = D("0")

    for (acc_id, curr_code), bal in balances.items():
        if round(bal["orig"], 2) == 0:
            continue

        curr = currencies_map.get(curr_code)
        if not curr:
            continue
        rate = rates_map.get(curr.id)
        if not rate:
            continue

        target_base = (bal["orig"] * D(str(rate.rate))).quantize(D("0.01"))
        diff = target_base - D(str(bal["base"])).quantize(D("0.01"))

        if round(diff, 2) != 0:
            acc = bal["account"]
            if diff > 0:
                direction = acc.balance_direction
            else:
                direction = AccountDirection.CREDIT if acc.balance_direction == AccountDirection.DEBIT else AccountDirection.DEBIT

            voucher_entries.append({
                "account_id": acc.id,
                "summary": f"期末调汇 - {curr_code}",
                "direction": direction,
                "amount": abs(diff),
                "currency_code": "CNY",
            })
            fx_direction = AccountDirection.CREDIT if direction == AccountDirection.DEBIT else AccountDirection.DEBIT
            voucher_entries.append({
                "account_id": None,  # caller fills fx_account.id
                "summary": f"结转期末汇兑损益 - {acc.name}",
                "direction": fx_direction,
                "amount": abs(diff),
                "currency_code": "CNY",
            })
            total_gain_loss += diff

    return voucher_entries, total_gain_loss


def calculate_profit_loss_carry_forward(
    db: Session, ledger_id: int, year: int, month: int
) -> tuple[list[dict], Decimal]:
    """Calculate P&L carry-forward for the given month.

    Returns (entries_for_voucher, net_profit_impact) where each entry dict has:
    account_id, summary, direction, amount. The caller adds the 本年利润 entry.
    """
    pl_accounts = (
        db.query(Account)
        .filter(Account.ledger_id == ledger_id, Account.account_type == AccountType.PROFIT_LOSS)
        .all()
    )
    if not pl_accounts:
        return [], D("0")

    voucher_date = date(year, month, 28)
    pl_ids = [a.id for a in pl_accounts]

    balance_map = defaultdict(lambda: defaultdict(lambda: D("0")))
    if pl_ids:
        rows = (
            db.query(
                VoucherEntry.account_id,
                VoucherEntry.direction,
                func.sum(VoucherEntry.amount),
            )
            .join(Voucher)
            .filter(
                Voucher.ledger_id == ledger_id,
                VoucherEntry.account_id.in_(pl_ids),
                Voucher.voucher_date <= voucher_date,
                Voucher.status == VoucherStatus.POSTED,
            )
            .group_by(VoucherEntry.account_id, VoucherEntry.direction)
            .all()
        )
        for acct_id, direction, amt in rows:
            balance_map[acct_id][direction] = D(str(amt or 0))

    total_profit_impact = D("0")
    entries = []

    for acc in pl_accounts:
        sums = balance_map[acc.id]
        debits = sums[AccountDirection.DEBIT]
        credits = sums[AccountDirection.CREDIT]

        net_balance = (
            debits - credits
            if acc.balance_direction == AccountDirection.DEBIT
            else credits - debits
        )

        if net_balance == 0:
            continue

        close_direction = (
            AccountDirection.CREDIT
            if acc.balance_direction == AccountDirection.DEBIT
            else AccountDirection.DEBIT
        )

        entries.append({
            "account_id": acc.id,
            "summary": "结转本月损益",
            "direction": close_direction,
            "amount": abs(net_balance),
        })

        if acc.balance_direction == AccountDirection.CREDIT:
            total_profit_impact += net_balance
        else:
            total_profit_impact -= net_balance

    return entries, total_profit_impact
