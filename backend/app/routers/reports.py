from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, case, or_, extract
from typing import List, Optional
from datetime import date
from decimal import Decimal
import calendar as _cal
from pydantic import BaseModel
from app.types import Money

from app.database import get_db
from app.routers.ledgers import get_ledger_id
from app.models.financial import (
    Account,
    AccountBalance,
    AccountingPeriod,
    PeriodStatus,
    Voucher,
    VoucherEntry,
    VoucherStatus,
    AccountDirection,
    AccountType,
    OpenItem,
    OpenItemStatus,
    OpenItemType,
    VATRecord,
)

router = APIRouter()


def _try_fast_balances(db: Session, ledger_id: int, year: int, month: int, account_ids: list[int]):
    """Return {account_id: (ending_debit, ending_credit)} from AccountBalance if period is closed, else None."""
    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == year,
        AccountingPeriod.month == month,
    ).first()
    if not period or period.status != PeriodStatus.CLOSED:
        return None
    rows = db.query(AccountBalance).filter(
        AccountBalance.ledger_id == ledger_id,
        AccountBalance.account_id.in_(account_ids),
        AccountBalance.year == year,
        AccountBalance.month == month,
    ).all()
    if not rows:
        return None  # ponytail: closed but no balances (e.g., empty period) — fall back to scan
    return {r.account_id: (r.ending_debit, r.ending_credit) for r in rows}


def _try_fast_period_balances(db: Session, ledger_id: int, year: int, month: int, account_ids: list[int]):
    """Return {account_id: (period_debit, period_credit)} from AccountBalance if period is closed, else None."""
    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == year,
        AccountingPeriod.month == month,
    ).first()
    if not period or period.status != PeriodStatus.CLOSED:
        return None
    rows = db.query(AccountBalance).filter(
        AccountBalance.ledger_id == ledger_id,
        AccountBalance.account_id.in_(account_ids),
        AccountBalance.year == year,
        AccountBalance.month == month,
    ).all()
    if not rows:
        return None
    return {r.account_id: (r.period_debit, r.period_credit) for r in rows}


class SubsidiaryEntryResponse(BaseModel):
    date: date
    voucher_number: str
    summary: str
    debit_amount: Money
    credit_amount: Money
    balance_direction: str
    balance: Money


class GeneralLedgerResponse(BaseModel):
    account_code: str
    account_name: str
    month: str  # e.g. "2024-03"
    debit_sum: Money
    credit_sum: Money
    balance: Money


@router.get("/accounts/tree")
def get_accounts_tree(
    parent_id: Optional[int] = Query(None, description="Only return children of this account for lazy loading"),
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """
    Returns the account hierarchy. Supports 3+ levels and 500+ items per level.
    When parent_id is provided, returns only direct children (lazy loading).
    When omitted, returns the full tree (backward compatible).
    """
    if parent_id is not None:
        children = (
            db.query(Account)
            .filter(
                Account.ledger_id == ledger_id,
                Account.parent_id == parent_id,
                Account.is_active == True,
            )
            .all()
        )
        return [{"id": c.id, "code": c.code, "name": c.name, "children": []} for c in children]

    accounts = db.query(Account).filter(Account.ledger_id == ledger_id, Account.is_active == True).all()
    # Build tree in memory for high performance
    account_dict = {
        a.id: {"id": a.id, "code": a.code, "name": a.name, "children": []}
        for a in accounts
    }
    tree = []

    for a in accounts:
        if a.parent_id:
            if a.parent_id in account_dict:
                account_dict[a.parent_id]["children"].append(account_dict[a.id])  # type: ignore
        else:
            tree.append(account_dict[a.id])

    return tree


@router.get("/subsidiary-ledger", response_model=List[SubsidiaryEntryResponse])
def get_subsidiary_ledger(
    account_code: str,
    start_date: date,
    end_date: date,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(200, ge=1, le=500, description="Items per page (max 500)"),
    search: Optional[str] = Query(None, description="Fuzzy search voucher_number and summary"),
    min_amount: Optional[Decimal] = Query(None, description="Minimum debit or credit amount"),
    max_amount: Optional[Decimal] = Query(None, description="Maximum debit or credit amount"),
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """
    明细账 (Subsidiary Ledger)
    Filter by status == POSTED to meet compliance.
    Paginated — max 500 items per page.
    """
    # Validate date range: max 12 months (366 days)
    if (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Date range must not exceed 12 months")

    account = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == account_code).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Only include POSTED vouchers — paginated
    base_query = (
        db.query(VoucherEntry, Voucher)
        .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
        .filter(
            Voucher.ledger_id == ledger_id,
            VoucherEntry.account_id == account.id,
            Voucher.voucher_date >= start_date,
            Voucher.voucher_date <= end_date,
            Voucher.status == VoucherStatus.POSTED,
        )
        .order_by(Voucher.voucher_date.asc(), Voucher.id.asc())
    )

    if search:
        base_query = base_query.filter(or_(
            Voucher.voucher_number.contains(search),
            VoucherEntry.summary.contains(search)
        ))
    if min_amount is not None:
        base_query = base_query.filter(VoucherEntry.amount >= min_amount)
    if max_amount is not None:
        base_query = base_query.filter(VoucherEntry.amount <= max_amount)

    entries_query = base_query.offset((page - 1) * page_size).limit(page_size).all()

    # Calculate opening balance: try AccountBalance first, fall back to full scan
    past_debit = Decimal("0")
    past_credit = Decimal("0")
    fast_used = False
    # ponytail: fast path only when start_date is month-start (most common case)
    if start_date.day == 1:
        if start_date.month > 1:
            prev_year, prev_month = start_date.year, start_date.month - 1
        else:
            prev_year, prev_month = start_date.year - 1, 12
        fast = _try_fast_balances(db, ledger_id, prev_year, prev_month, [account.id])
        if fast is not None and account.id in fast:
            past_debit, past_credit = fast[account.id]
            fast_used = True

    if not fast_used:
        past_entries_query = (
            db.query(
                func.sum(
                    case(
                        (VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount),
                        else_=0,
                    )
                ).label("debit_sum"),
                func.sum(
                    case(
                        (VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount),
                        else_=0,
                    )
                ).label("credit_sum"),
            )
            .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
            .filter(
                Voucher.ledger_id == ledger_id,
                VoucherEntry.account_id == account.id,
                Voucher.voucher_date < start_date,
                Voucher.status == VoucherStatus.POSTED,
            )
            .first()
        )
        past_debit = past_entries_query.debit_sum or Decimal("0")
        past_credit = past_entries_query.credit_sum or Decimal("0")

    opening_balance = Decimal(str(account.opening_balance))
    if account.balance_direction == AccountDirection.DEBIT:
        current_balance = opening_balance + past_debit - past_credit
    else:
        current_balance = opening_balance + past_credit - past_debit

    results = []
    # Add opening balance row
    results.append(
        SubsidiaryEntryResponse(
            date=start_date,
            voucher_number="期初余额",
            summary="期初余额",
            debit_amount=Decimal("0"),
            credit_amount=Decimal("0"),
            balance_direction=account.balance_direction.value,
            balance=current_balance,
        )
    )

    for entry, voucher in entries_query:
        debit = (
            entry.amount if entry.direction == AccountDirection.DEBIT else Decimal("0")
        )
        credit = (
            entry.amount if entry.direction == AccountDirection.CREDIT else Decimal("0")
        )

        if account.balance_direction == AccountDirection.DEBIT:
            current_balance = current_balance + debit - credit
        else:
            current_balance = current_balance + credit - debit

        direction_str = (
            "平" if current_balance == 0 else ("借" if account.balance_direction == AccountDirection.DEBIT else "贷")
        )

        results.append(
            SubsidiaryEntryResponse(
                date=voucher.voucher_date,
                voucher_number=voucher.voucher_number,
                summary=entry.summary,
                debit_amount=debit,
                credit_amount=credit,
                balance_direction=direction_str,
                balance=abs(current_balance),
            )
        )

    return results


@router.get("/general-ledger", response_model=List[GeneralLedgerResponse])
def get_general_ledger(
    year: int,
    month: Optional[int] = Query(None, ge=1, le=12, description="Optional month filter (1-12)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(200, ge=1, le=500, description="Items per page (max 500)"),
    search: Optional[str] = Query(None, description="Fuzzy search account_code and account_name"),
    min_amount: Optional[Decimal] = Query(None, description="Minimum monthly debit or credit sum"),
    max_amount: Optional[Decimal] = Query(None, description="Maximum monthly debit or credit sum"),
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """
    总账: General Ledger (Monthly aggregations for accounts)
    Only includes POSTED vouchers. Paginated — max 500 items per page.
    If month is provided, returns only that month's data.
    """
    offset = (page - 1) * page_size

    accounts = db.query(Account).filter(Account.ledger_id == ledger_id, Account.is_active == True).all()
    response = []
    account_ids = [a.id for a in accounts]

    # Try fast path for past balances: year-end snapshot of previous year
    past_map: dict[int, tuple[Decimal, Decimal]] = {}
    if account_ids:
        fast_past = _try_fast_balances(db, ledger_id, year - 1, 12, account_ids)
        if fast_past is not None:
            past_map = fast_past
        else:
            past_rows = (
                db.query(
                    VoucherEntry.account_id,
                    func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debit_sum"),
                    func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credit_sum"),
                )
                .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
                .filter(
                    Voucher.ledger_id == ledger_id,
                    VoucherEntry.account_id.in_(account_ids),
                    extract("year", Voucher.voucher_date) < year,
                    Voucher.status == VoucherStatus.POSTED,
                )
                .group_by(VoucherEntry.account_id)
                .all()
            )
            past_map = {r.account_id: (r.debit_sum or Decimal("0"), r.credit_sum or Decimal("0")) for r in past_rows}

    # Batch-fetch monthly sums: use AccountBalance for closed months, scan VoucherEntry only for open months
    monthly_map: dict[int, dict[int, tuple[Decimal, Decimal]]] = {}
    closed_months: set[int] = set()
    if account_ids:
        balance_rows = db.query(AccountBalance).filter(
            AccountBalance.ledger_id == ledger_id,
            AccountBalance.account_id.in_(account_ids),
            AccountBalance.year == year,
        ).all()
        from collections import defaultdict as _dd
        _tmp: dict[int, dict[int, tuple[Decimal, Decimal]]] = _dd(lambda: _dd(lambda: (Decimal("0"), Decimal("0"))))
        for r in balance_rows:
            if r.month is not None:
                closed_months.add(r.month)
                _tmp[r.account_id][r.month] = (r.period_debit, r.period_credit)
        monthly_map = dict(_tmp)

        # VoucherEntry scan only for months without pre-computed balances
        target_months = {month} if month is not None else set(range(1, 13))
        open_months = target_months - closed_months
        if open_months:
            monthly_base = (
                db.query(
                    VoucherEntry.account_id,
                    extract("month", Voucher.voucher_date).label("month"),
                    func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debit_sum"),
                    func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credit_sum"),
                )
                .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
                .filter(
                    Voucher.ledger_id == ledger_id,
                    VoucherEntry.account_id.in_(account_ids),
                    extract("year", Voucher.voucher_date) == year,
                    extract("month", Voucher.voucher_date).in_(open_months),
                    Voucher.status == VoucherStatus.POSTED,
                )
                .group_by(VoucherEntry.account_id, extract("month", Voucher.voucher_date))
            )
            monthly_rows = monthly_base.all()
            for r in monthly_rows:
                _tmp[r.account_id][int(r.month)] = (r.debit_sum or Decimal("0"), r.credit_sum or Decimal("0"))
            monthly_map = dict(_tmp)

    for account in accounts:
        if search and search not in account.code and search not in account.name:
            continue

        past_debit, past_credit = past_map.get(account.id, (Decimal("0"), Decimal("0")))

        opening_balance = Decimal(str(account.opening_balance))
        if account.balance_direction == AccountDirection.DEBIT:
            current_balance = opening_balance + past_debit - past_credit
        else:
            current_balance = opening_balance + past_credit - past_debit

        month_dict = monthly_map.get(account.id, {})

        months = [month] if month is not None else list(range(1, 13))
        for m in months:
            debit_sum, credit_sum = month_dict.get(m, (Decimal("0"), Decimal("0")))
            if debit_sum == 0 and credit_sum == 0 and current_balance == 0:
                continue

            # Always update running balance (even for amount-filtered rows)
            if account.balance_direction == AccountDirection.DEBIT:
                current_balance = current_balance + debit_sum - credit_sum
            else:
                current_balance = current_balance + credit_sum - debit_sum

            # Amount range filter (check after balance update, affects only whether we include this row)
            amount_ok = True
            if min_amount is not None and max_amount is not None:
                amount_ok = (debit_sum >= min_amount or credit_sum >= min_amount) and (debit_sum <= max_amount or credit_sum <= max_amount)
            elif min_amount is not None:
                amount_ok = (debit_sum >= min_amount or credit_sum >= min_amount)
            elif max_amount is not None:
                amount_ok = (debit_sum <= max_amount or credit_sum <= max_amount)
            if not amount_ok:
                continue

            response.append(
                GeneralLedgerResponse(
                    account_code=account.code,
                    account_name=account.name,
                    month=f"{year}-{m:02d}",
                    debit_sum=debit_sum,
                    credit_sum=credit_sum,
                    balance=abs(current_balance),
                )
            )

    return response[offset:offset + page_size]


class TaxRebateResponse(BaseModel):
    contract_number: str
    total_rebate_amount: Money


@router.get("/tax-rebates", response_model=List[TaxRebateResponse])
def get_tax_rebates(db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """
    外贸报表：按合同号统计的退税明细总额
    Filters entries matching '退税' in the account name.
    """
    from sqlalchemy import func

    results = (
        db.query(
            Voucher.contract_number, func.sum(VoucherEntry.amount).label("total_rebate")
        )
        .join(VoucherEntry, Voucher.id == VoucherEntry.voucher_id)
        .join(Account, VoucherEntry.account_id == Account.id)
        .filter(
            Voucher.ledger_id == ledger_id,
            Account.name.like("%退税%"),
            Voucher.contract_number != None,
            Voucher.status == VoucherStatus.POSTED,
        )
        .group_by(Voucher.contract_number)
        .all()
    )

    return [
        TaxRebateResponse(
            contract_number=r.contract_number, total_rebate_amount=r.total_rebate
        )
        for r in results
    ]


class SalesByContractResponse(BaseModel):
    contract_number: str
    month: str
    total_sales: Money
    ytd_sales: Money


@router.get("/sales-by-contract", response_model=List[SalesByContractResponse])
def get_sales_by_contract(year: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """
    外贸报表：按月按合同号统计的销售明细报表（包含当月发生和年度累计）
    Filters entries in account type PROFIT_LOSS matching '收入'.
    """
    from sqlalchemy import func, extract

    results = (
        db.query(
            Voucher.contract_number,
            extract("month", Voucher.voucher_date).label("month"),
            func.sum(VoucherEntry.amount).label("total_sales"),
        )
        .join(VoucherEntry, Voucher.id == VoucherEntry.voucher_id)
        .join(Account, VoucherEntry.account_id == Account.id)
        .filter(
            Voucher.ledger_id == ledger_id,
            Account.account_type == AccountType.PROFIT_LOSS,
            Account.name.like("%收入%"),
            Voucher.contract_number != None,
            extract("year", Voucher.voucher_date) == year,
            Voucher.status == VoucherStatus.POSTED,
        )
        .group_by(Voucher.contract_number, extract("month", Voucher.voucher_date))
        .order_by(Voucher.contract_number, extract("month", Voucher.voucher_date))
        .all()
    )

    response: list = []
    ytd_tracker: dict[str, Decimal] = {}  # contract_number -> running total
    for r in results:
        contract = r.contract_number
        current_sales = r.total_sales
        ytd_tracker[contract] = ytd_tracker.get(contract, Decimal("0")) + current_sales

        response.append(
            SalesByContractResponse(
                contract_number=contract,
                month=f"{year}-{int(r.month):02d}",
                total_sales=current_sales,
                ytd_sales=ytd_tracker[contract],
            )
        )

    return response


class BalanceSheetItem(BaseModel):
    item_name: str
    amount: Money

class BalanceSheetResponse(BaseModel):
    assets: List[BalanceSheetItem]
    liabilities: List[BalanceSheetItem]
    equity: List[BalanceSheetItem]
    total_assets: Money
    total_liabilities: Money
    total_equity: Money
    # Accounting identity check: 资产 = 负债 + 权益. Exposing this lets the
    # frontend surface imbalances instead of silently presenting a wrong sheet.
    # A non-zero discrepancy indicates either unbalanced vouchers, a data
    # integrity bug, or equity plug entries that haven't been reconciled.
    is_balanced: bool
    balance_discrepancy: Money

@router.get("/balance-sheet", response_model=BalanceSheetResponse)
def get_balance_sheet(as_of_date: date, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """
    资产负债表: Balance Sheet as of a specific date.
    Calculates cumulative balances up to as_of_date.
    """
    from sqlalchemy import func
    
    accounts = db.query(Account).filter(Account.ledger_id == ledger_id, Account.is_active == True).all()
    
    assets = []
    liabilities = []
    equity = []
    
    relevant_type = [AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY]
    relevant_ids = [a.id for a in accounts if a.account_type in relevant_type]

    # Try fast path from pre-computed balances (closed period); fall back to full scan
    year, month = as_of_date.year, as_of_date.month
    balances: dict[int, tuple[Decimal, Decimal]] = {}
    fast = _try_fast_balances(db, ledger_id, year, month, relevant_ids) if relevant_ids else None

    if fast is not None:
        balances = fast
    elif relevant_ids:
        all_balances = (
            db.query(
                VoucherEntry.account_id,
                func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debit_sum"),
                func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credit_sum"),
            )
            .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
            .filter(
                Voucher.ledger_id == ledger_id,
                VoucherEntry.account_id.in_(relevant_ids),
                Voucher.voucher_date <= as_of_date,
                Voucher.status == VoucherStatus.POSTED,
            )
            .group_by(VoucherEntry.account_id)
            .all()
        )
        balances = {r.account_id: (r.debit_sum or Decimal("0"), r.credit_sum or Decimal("0")) for r in all_balances}

    for account in accounts:
        if account.account_type not in relevant_type:
            continue

        debit, credit = balances.get(account.id, (Decimal("0"), Decimal("0")))
        opening = Decimal(str(account.opening_balance))
        
        if account.balance_direction == AccountDirection.DEBIT:
            bal = opening + debit - credit
        else:
            bal = opening + credit - debit
            
        if bal != 0:
            item = BalanceSheetItem(item_name=f"{account.code} {account.name}", amount=bal)
            if account.account_type == AccountType.ASSET:
                assets.append(item)
            elif account.account_type == AccountType.LIABILITY:
                liabilities.append(item)
            elif account.account_type == AccountType.EQUITY:
                equity.append(item)
                
    total_assets = sum(a.amount for a in assets)
    total_liabilities = sum(l.amount for l in liabilities)
    total_equity = sum(e.amount for e in equity)
    
    # 会计恒等式校验: 资产 = 负债 + 权益
    # 允许 0.01 的舍入容差（Money 精度）。差异大于容差说明账务数据有问题，
    # 必须显式暴露给调用方，不能让前端展示一张"看起来对"但其实不平的报表。
    liability_plus_equity = total_liabilities + total_equity
    discrepancy = total_assets - liability_plus_equity
    is_balanced = abs(discrepancy) <= Decimal("0.01")
    if not is_balanced:
        logger = __import__("logging").getLogger("trad_account")
        logger.warning(
            "Balance sheet imbalance for ledger=%s as_of=%s: assets=%s vs (liabilities+equity)=%s, diff=%s",
            ledger_id, as_of_date, total_assets, liability_plus_equity, discrepancy,
        )
    
    return BalanceSheetResponse(
        assets=assets,
        liabilities=liabilities,
        equity=equity,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        is_balanced=is_balanced,
        balance_discrepancy=discrepancy,
    )

class IncomeStatementItem(BaseModel):
    item_name: str
    amount: Money

class IncomeStatementResponse(BaseModel):
    revenues: List[IncomeStatementItem]
    expenses: List[IncomeStatementItem]
    total_revenue: Money
    total_expense: Money
    net_income: Money

@router.get("/income-statement", response_model=IncomeStatementResponse)
def get_income_statement(start_date: date, end_date: date, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """
    利润表 (Income Statement) for a specific period.
    Sums P&L accounts' activity during the period.
    """
    from sqlalchemy import func
    
    accounts = db.query(Account).filter(Account.ledger_id == ledger_id, Account.is_active == True, Account.account_type == AccountType.PROFIT_LOSS).all()
    
    revenues = []
    expenses = []
    
    account_ids = [a.id for a in accounts]
    balances: dict[int, tuple[Decimal, Decimal]] = {}
    # Fast path: single-month closed period
    fast = None
    if account_ids and start_date.year == end_date.year and start_date.month == end_date.month:
        fast = _try_fast_period_balances(db, ledger_id, start_date.year, start_date.month, account_ids)
    if fast is not None:
        balances = fast
    elif account_ids:
        all_balances = (
            db.query(
                VoucherEntry.account_id,
                func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debit_sum"),
                func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credit_sum"),
            )
            .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
            .filter(
                Voucher.ledger_id == ledger_id,
                VoucherEntry.account_id.in_(account_ids),
                Voucher.voucher_date >= start_date,
                Voucher.voucher_date <= end_date,
                Voucher.status == VoucherStatus.POSTED,
            )
            .group_by(VoucherEntry.account_id)
            .all()
        )
        balances = {r.account_id: (r.debit_sum or Decimal("0"), r.credit_sum or Decimal("0")) for r in all_balances}

    for account in accounts:
        debit, credit = balances.get(account.id, (Decimal("0"), Decimal("0")))

        if account.balance_direction == AccountDirection.DEBIT:
            net = debit - credit
            if net != 0:
                expenses.append(IncomeStatementItem(item_name=f"{account.code} {account.name}", amount=net))
        else:
            net = credit - debit
            if net != 0:
                revenues.append(IncomeStatementItem(item_name=f"{account.code} {account.name}", amount=net))
                
    total_revenue = sum(r.amount for r in revenues)
    total_expense = sum(e.amount for e in expenses)
    net_income = total_revenue - total_expense
    
    return IncomeStatementResponse(
        revenues=revenues,
        expenses=expenses,
        total_revenue=total_revenue,
        total_expense=total_expense,
        net_income=net_income
    )


class CashFlowItem(BaseModel):
    item_name: str
    amount: Money

class CashFlowResponse(BaseModel):
    operating_inflows: List[CashFlowItem]
    operating_outflows: List[CashFlowItem]
    investing_inflows: List[CashFlowItem]
    investing_outflows: List[CashFlowItem]
    financing_inflows: List[CashFlowItem]
    financing_outflows: List[CashFlowItem]

    net_operating_cash_flow: Money
    net_investing_cash_flow: Money
    net_financing_cash_flow: Money
    net_increase_in_cash: Money
    ending_cash_balance: Money

@router.get("/cash-flow", response_model=CashFlowResponse)
def get_cash_flow_statement(start_date: date, end_date: date, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """
    现金流量表 (Cash Flow Statement).
    Automatically classifies cash flows based on the counterparty accounts in the same voucher.
    """
    from sqlalchemy.orm import joinedload
    
    # 1. Identify cash accounts (e.g. 1001 Cash, 1002 Bank)
    cash_accounts = db.query(Account).filter(Account.ledger_id == ledger_id, 
        Account.code.like('1001%') | Account.code.like('1002%')
    ).all()
    cash_account_ids = {a.id for a in cash_accounts}
    
    if not cash_account_ids:
        # Return empty if no cash accounts found
        return CashFlowResponse(
            operating_inflows=[], operating_outflows=[],
            investing_inflows=[], investing_outflows=[],
            financing_inflows=[], financing_outflows=[],
            net_operating_cash_flow=0, net_investing_cash_flow=0, net_financing_cash_flow=0,
            net_increase_in_cash=0, ending_cash_balance=0
        )
        
    # 2. Find all vouchers in the period that involve cash accounts
    cash_vouchers = (
        db.query(Voucher)
        .options(joinedload(Voucher.entries).joinedload(VoucherEntry.account))
        .join(VoucherEntry, Voucher.id == VoucherEntry.voucher_id)
        .filter(
            Voucher.ledger_id == ledger_id,
            VoucherEntry.account_id.in_(cash_account_ids),
            Voucher.voucher_date >= start_date,
            Voucher.voucher_date <= end_date,
            Voucher.status == VoucherStatus.POSTED
        )
        .distinct()
        .all()
    )
    
    # Categories
    operating_inflows, operating_outflows = {}, {}
    investing_inflows, investing_outflows = {}, {}
    financing_inflows, financing_outflows = {}, {}
    
    for v in cash_vouchers:
        # Separate cash entries and non-cash entries
        cash_entries = [e for e in v.entries if e.account_id in cash_account_ids]
        non_cash_entries = [e for e in v.entries if e.account_id not in cash_account_ids]
        
        # If it's just cash transfers (e.g. Cash to Bank), skip
        if not non_cash_entries:
            continue
            
        # Total cash impact in this voucher (Debit to cash = Inflow, Credit to cash = Outflow)
        total_cash_inflow = sum(e.amount for e in cash_entries if e.direction == AccountDirection.DEBIT)
        total_cash_outflow = sum(e.amount for e in cash_entries if e.direction == AccountDirection.CREDIT)
        net_cash_impact = Decimal(str(total_cash_inflow - total_cash_outflow))
        
        # If net cash impact is 0, skip
        if abs(net_cash_impact) < Decimal("0.01"):
            continue
            
        # Determine the primary counterparty account type to classify the cash flow
        # In a real system, we'd prorate or match exactly, but for MVP we pick the largest non-cash entry
        primary_counterparty = max(non_cash_entries, key=lambda e: e.amount)
        code = primary_counterparty.account.code
        name = primary_counterparty.account.name
        
        is_inflow = net_cash_impact > 0
        amount = abs(net_cash_impact)
        
        # Classification Algorithm:
        # 16*: Fixed Assets -> Investing
        # 20*: Short-term borrowings -> Financing
        # 25*: Long-term borrowings (2501 长期借款, 2502 应付债券) -> Financing
        # 27*: Long-term payables (2701 长期应付款) -> Financing
        # 4*: Equity -> Financing
        # Others -> Operating
        if code.startswith('16'):
            target_dict = investing_inflows if is_inflow else investing_outflows
            target_dict[name] = target_dict.get(name, 0) + amount
        elif code.startswith(('20', '25', '27', '4')):
            target_dict = financing_inflows if is_inflow else financing_outflows
            target_dict[name] = target_dict.get(name, 0) + amount
        else:
            target_dict = operating_inflows if is_inflow else operating_outflows
            target_dict[name] = target_dict.get(name, 0) + amount
            
    # Calculate ending balance of cash up to end_date
    ending_cash_balance = Decimal("0")
    if cash_account_ids:
        # Try fast path for closed period
        fast_ending = _try_fast_balances(db, ledger_id, end_date.year, end_date.month, list(cash_account_ids))
        if fast_ending is not None:
            ending_map = fast_ending
        else:
            ending_rows = (
                db.query(
                    VoucherEntry.account_id,
                    func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debit_sum"),
                    func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credit_sum"),
                )
                .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
                .filter(
                    Voucher.ledger_id == ledger_id,
                    VoucherEntry.account_id.in_(cash_account_ids),
                    Voucher.voucher_date <= end_date,
                    Voucher.status == VoucherStatus.POSTED,
                ).group_by(VoucherEntry.account_id).all()
            )
            ending_map = {r.account_id: (r.debit_sum or Decimal("0"), r.credit_sum or Decimal("0")) for r in ending_rows}
        for acc in cash_accounts:
            debit, credit = ending_map.get(acc.id, (Decimal("0"), Decimal("0")))
            bal = Decimal(str(acc.opening_balance)) + debit - credit
            ending_cash_balance += bal
        
    def to_list(d):
        return [CashFlowItem(item_name=k, amount=v) for k, v in d.items()]
        
    oi = to_list(operating_inflows)
    oo = to_list(operating_outflows)
    ii = to_list(investing_inflows)
    io = to_list(investing_outflows)
    fi = to_list(financing_inflows)
    fo = to_list(financing_outflows)
    
    net_op = sum(x.amount for x in oi) - sum(x.amount for x in oo)
    net_inv = sum(x.amount for x in ii) - sum(x.amount for x in io)
    net_fin = sum(x.amount for x in fi) - sum(x.amount for x in fo)
    
    return CashFlowResponse(
        operating_inflows=oi, operating_outflows=oo,
        investing_inflows=ii, investing_outflows=io,
        financing_inflows=fi, financing_outflows=fo,
        net_operating_cash_flow=net_op,
        net_investing_cash_flow=net_inv,
        net_financing_cash_flow=net_fin,
        net_increase_in_cash=net_op + net_inv + net_fin,
        ending_cash_balance=ending_cash_balance
    )


class ExpenseDetailResponse(BaseModel):
    month: str
    account_name: str
    total_expense: Money
    ytd_expense: Money


@router.get("/expense-details", response_model=List[ExpenseDetailResponse])
def get_expense_details(year: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """
    经营分析报表：按月汇总的各项期间费用明细（包含当月发生和年度累计）
    Filters entries in account type PROFIT_LOSS matching '费用'.
    """
    from sqlalchemy import func, extract

    results = (
        db.query(
            extract("month", Voucher.voucher_date).label("month"),
            Account.name.label("account_name"),
            func.sum(VoucherEntry.amount).label("total_expense"),
        )
        .join(VoucherEntry, Voucher.id == VoucherEntry.voucher_id)
        .join(Account, VoucherEntry.account_id == Account.id)
        .filter(
            Voucher.ledger_id == ledger_id,
            Account.account_type == AccountType.PROFIT_LOSS,
            Account.name.like("%费用%"),
            extract("year", Voucher.voucher_date) == year,
            Voucher.status == VoucherStatus.POSTED,
        )
        .group_by(Account.name, extract("month", Voucher.voucher_date))
        .order_by(Account.name, extract("month", Voucher.voucher_date))
        .all()
    )

    response: list = []
    ytd_tracker: dict[str, Decimal] = {}  # account_name -> running total
    for r in results:
        acc_name = r.account_name
        current_expense = r.total_expense
        ytd_tracker[acc_name] = ytd_tracker.get(acc_name, Decimal("0")) + current_expense

        response.append(
            ExpenseDetailResponse(
                month=f"{year}-{int(r.month):02d}",
                account_name=acc_name,
                total_expense=current_expense,
                ytd_expense=ytd_tracker[acc_name],
            )
        )

    return response




class ProfitLossItem(BaseModel):
    item_name: str
    current_month: Money
    ytd: Money


class ProfitLossStatementResponse(BaseModel):
    operating_revenue: ProfitLossItem
    operating_costs: ProfitLossItem
    gross_profit: ProfitLossItem
    expenses: List[ProfitLossItem]
    operating_profit: ProfitLossItem
    income_tax: ProfitLossItem
    net_profit: ProfitLossItem


@router.get("/profit-loss-statement", response_model=ProfitLossStatementResponse)
def get_profit_loss_statement(year: int, month: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """
    法定报表：利润表 (P&L Statement)
    """
    from sqlalchemy import func, extract

    # Batch-fetch all PL accounts and their debit/credit sums
    pl_accounts = db.query(Account).filter(
        Account.ledger_id == ledger_id,
        Account.account_type == AccountType.PROFIT_LOSS,
    ).all()
    pl_ids = [a.id for a in pl_accounts]

    def _batch_sum(month_from, month_to):
        """Return {account_id: (debits, credits)} for the given month range."""
        if not pl_ids:
            return {}
        rows = (
            db.query(
                VoucherEntry.account_id,
                func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debits"),
                func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credits"),
            )
            .join(Voucher)
            .filter(
                Voucher.ledger_id == ledger_id,
                VoucherEntry.account_id.in_(pl_ids),
                extract("year", Voucher.voucher_date) == year,
                extract("month", Voucher.voucher_date) >= month_from,
                extract("month", Voucher.voucher_date) <= month_to,
                Voucher.status == VoucherStatus.POSTED,
            ).group_by(VoucherEntry.account_id).all()
        )
        return {r.account_id: (Decimal(str(r.debits or 0)), Decimal(str(r.credits or 0))) for r in rows}

    curr_map = _batch_sum(month, month)
    ytd_map = _batch_sum(1, month)

    def _net(acc, data_map):
        d, c = data_map.get(acc.id, (Decimal("0"), Decimal("0")))
        return c - d if acc.balance_direction == AccountDirection.CREDIT else d - c

    def _group(like_str):
        accs = [a for a in pl_accounts if like_str in a.name]
        return sum(_net(a, curr_map) for a in accs), sum(_net(a, ytd_map) for a in accs)

    rev_curr, rev_ytd = _group("主营业务收入")
    cost_curr, cost_ytd = _group("主营业务成本")
    sell_exp_curr, sell_exp_ytd = _group("销售费用")
    mgt_exp_curr, mgt_exp_ytd = _group("管理费用")
    fin_exp_curr, fin_exp_ytd = _group("财务费用")

    gross_curr = rev_curr - cost_curr
    gross_ytd = rev_ytd - cost_ytd

    op_profit_curr = gross_curr - sell_exp_curr - mgt_exp_curr - fin_exp_curr
    op_profit_ytd = gross_ytd - sell_exp_ytd - mgt_exp_ytd - fin_exp_ytd

    # Income tax: query the active rate from TaxRate (default 25%)
    from app.models.financial import TaxRate
    tax_rate_row = (
        db.query(TaxRate)
        .filter(
            TaxRate.ledger_id == ledger_id,
            TaxRate.tax_type == "income_tax",
            TaxRate.is_active == True,
        )
        .order_by(TaxRate.effective_from.desc())
        .first()
    )
    income_tax_rate = Decimal(str(tax_rate_row.rate)) if tax_rate_row else Decimal("0.25")

    tax_curr = op_profit_curr * income_tax_rate if op_profit_curr > 0 else Decimal("0")
    tax_ytd = op_profit_ytd * income_tax_rate if op_profit_ytd > 0 else Decimal("0")
    net_curr = op_profit_curr - tax_curr
    net_ytd = op_profit_ytd - tax_ytd

    return ProfitLossStatementResponse(
        operating_revenue=ProfitLossItem(
            item_name="营业收入", current_month=rev_curr, ytd=rev_ytd
        ),
        operating_costs=ProfitLossItem(
            item_name="营业成本", current_month=cost_curr, ytd=cost_ytd
        ),
        gross_profit=ProfitLossItem(
            item_name="营业毛利", current_month=gross_curr, ytd=gross_ytd
        ),
        expenses=[
            ProfitLossItem(
                item_name="销售费用", current_month=sell_exp_curr, ytd=sell_exp_ytd
            ),
            ProfitLossItem(
                item_name="管理费用", current_month=mgt_exp_curr, ytd=mgt_exp_ytd
            ),
            ProfitLossItem(
                item_name="财务费用", current_month=fin_exp_curr, ytd=fin_exp_ytd
            ),
        ],
        operating_profit=ProfitLossItem(
            item_name="营业利润", current_month=op_profit_curr, ytd=op_profit_ytd
        ),
        income_tax=ProfitLossItem(
            item_name="所得税费用", current_month=tax_curr, ytd=tax_ytd
        ),
        net_profit=ProfitLossItem(
            item_name="净利润", current_month=net_curr, ytd=net_ytd
        ),
    )


class OemContractPnLEntryResponse(BaseModel):
    date: date
    voucher_number: str
    account_code: str
    account_name: str
    summary: str
    direction: str
    amount: Money
    category: str  # "revenue", "cost", "expense", "other"


class OemContractPnLResponse(BaseModel):
    contract_number: str
    revenue: Money
    cost: Money
    expenses: Money
    gross_profit: Money
    net_profit: Money
    entries: List[OemContractPnLEntryResponse]


class CommissionContractItem(BaseModel):
    contract_number: str
    customer_name: Optional[str]
    revenue: Money
    cost: Money
    gross_profit: Money
    basis_amount: Money
    rate: Money
    commission_amount: Money


class CommissionSalespersonItem(BaseModel):
    salesperson_id: int
    salesperson_name: str
    department: Optional[str]
    contracts: List[CommissionContractItem]
    total_commission: Money


class CommissionReportResponse(BaseModel):
    period: str
    salespersons: List[CommissionSalespersonItem]
    total_commission: Money
    contract_count: int


class DashboardSummaryResponse(BaseModel):
    monthly_revenue: Money
    monthly_revenue_trend: Optional[Money] = None  # percentage change vs previous month; None if no prior data
    pending_prepayments: Money
    pending_prepayment_count: int
    unmatched_bank_txns: int
    pending_tasks: list[dict]


@router.get("/oem-contract/{contract_number}", response_model=OemContractPnLResponse)
def get_oem_contract_pnl(
    contract_number: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """
    OEM合同损益报表: P&L by contract number.
    Aggregates revenue (收入, credit side), cost (成本, debit side),
    and expenses (费用, debit side) for a specific OEM contract.
    """
    from sqlalchemy import extract

    # Build base query: all POSTED vouchers with this contract_number
    query = (
        db.query(VoucherEntry, Voucher, Account)
        .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
        .join(Account, VoucherEntry.account_id == Account.id)
        .filter(
            Voucher.ledger_id == ledger_id,
            Voucher.contract_number == contract_number,
            Voucher.status == VoucherStatus.POSTED,
        )
    )

    if year is not None:
        query = query.filter(extract("year", Voucher.voucher_date) == year)
    if month is not None:
        query = query.filter(extract("month", Voucher.voucher_date) == month)

    rows = query.order_by(Voucher.voucher_date.asc(), Voucher.id.asc()).all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No posted vouchers found for contract '{contract_number}'",
        )

    revenue = Decimal("0")
    cost = Decimal("0")
    expenses = Decimal("0")
    entries: list = []

    from app.commission import classify_voucher_entry

    for entry, voucher, account in rows:
        amount = Decimal(str(entry.amount or 0))
        direction_str = entry.direction.value

        category, _ = classify_voucher_entry(entry, account)
        amount = Decimal(str(entry.amount or 0))

        if category == "revenue":
            revenue += amount
        elif category == "cost":
            cost += amount
        elif category == "expenses":
            expenses += amount

        entries.append(
            OemContractPnLEntryResponse(
                date=voucher.voucher_date,
                voucher_number=voucher.voucher_number,
                account_code=account.code,
                account_name=account.name,
                summary=entry.summary,
                direction=direction_str,
                amount=amount,
                category=category,
            )
        )

    gross_profit = revenue - cost
    net_profit = gross_profit - expenses

    return OemContractPnLResponse(
        contract_number=contract_number,
        revenue=revenue,
        cost=cost,
        expenses=expenses,
        gross_profit=gross_profit,
        net_profit=net_profit,
        entries=entries,
    )


@router.get("/commission", response_model=CommissionReportResponse)
def get_commission_report(
    year: int = Query(..., description="Year, e.g. 2026"),
    month: Optional[int] = Query(None, description="Month 1-12, omit for full year"),
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """佣金报表: Calculate salesperson commission based on OEM contract P&L."""
    from app.commission import calculate_commission

    return calculate_commission(db, ledger_id, year, month)


@router.get("/dashboard-summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """Dashboard KPI summary for the current ledger."""
    from datetime import datetime as dt
    from sqlalchemy import func, extract

    now = dt.now()
    year, month = now.year, now.month

    # 1. Monthly revenue: sum of income P&L accounts for current month (batch queries)
    from collections import defaultdict
    revenue_accounts = (
        db.query(Account)
        .filter(
            Account.ledger_id == ledger_id,
            Account.is_active == True,
            Account.account_type == AccountType.PROFIT_LOSS,
            Account.name.like("%收入%"),
        )
        .all()
    )
    revenue_ids = [a.id for a in revenue_accounts]
    rev_direction_map = {a.id: a.balance_direction for a in revenue_accounts}

    def _batch_account_sum(account_ids, year, month):
        """Return {account_id: (debit_sum, credit_sum)} for a given month."""
        if not account_ids:
            return {}
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
                extract("year", Voucher.voucher_date) == year,
                extract("month", Voucher.voucher_date) == month,
                Voucher.status == VoucherStatus.POSTED,
            )
            .group_by(VoucherEntry.account_id, VoucherEntry.direction)
            .all()
        )
        result = defaultdict(lambda: (Decimal("0"), Decimal("0")))
        for acct_id, direction, amt in rows:
            d, c = result[acct_id]
            amt = amt or Decimal("0")
            if direction == AccountDirection.DEBIT:
                result[acct_id] = (amt, c)
            else:
                result[acct_id] = (d, amt)
        return result

    def _calc_net(debit_cr_pair, balance_direction):
        d, c = debit_cr_pair
        net = c - d if balance_direction == AccountDirection.CREDIT else d - c
        return net

    curr_month_sums = _batch_account_sum(revenue_ids, year, month)
    monthly_revenue = sum(
        _calc_net(curr_month_sums.get(aid, (Decimal("0"), Decimal("0"))), rev_direction_map[aid])
        for aid in revenue_ids
    )

    # Previous month for trend
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    prev_month_sums = _batch_account_sum(revenue_ids, prev_year, prev_month)
    prev_revenue = sum(
        _calc_net(prev_month_sums.get(aid, (Decimal("0"), Decimal("0"))), rev_direction_map[aid])
        for aid in revenue_ids
    )

    # 收入趋势：避免负数基数导致趋势方向反转
    if prev_revenue > 0:
        monthly_revenue_trend = (monthly_revenue - prev_revenue) / prev_revenue * 100
    elif prev_revenue < 0:
        # 上月为负（如退货），本月转正视为 100% 增长，仍为负视为 -100%
        monthly_revenue_trend = Decimal("100") if monthly_revenue > 0 else Decimal("-100")
    else:
        monthly_revenue_trend = None

    # 2. Pending prepayments: sum of 预付账款 (1123) account balances
    prepay_accounts = (
        db.query(Account)
        .filter(
            Account.ledger_id == ledger_id,
            Account.is_active == True,
            Account.code.like("1123%"),
        )
        .all()
    )

    pending_prepayments = Decimal("0")
    # Batch-fetch debit/credit sums for all prepay accounts
    prepay_ids = [a.id for a in prepay_accounts]
    prepay_balances = {}
    if prepay_ids:
        rows = (
            db.query(
                VoucherEntry.account_id,
                func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debits"),
                func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credits"),
            )
            .join(Voucher)
            .filter(
                Voucher.ledger_id == ledger_id,
                VoucherEntry.account_id.in_(prepay_ids),
                Voucher.status == VoucherStatus.POSTED,
            ).group_by(VoucherEntry.account_id).all()
        )
        prepay_balances = {r.account_id: (Decimal(str(r.debits or 0)), Decimal(str(r.credits or 0))) for r in rows}
    for acc in prepay_accounts:
        debits, credits = prepay_balances.get(acc.id, (Decimal("0"), Decimal("0")))
        balance = Decimal(str(acc.opening_balance)) + debits - credits
        pending_prepayments += balance

    # Count open items once (not per-account)
    pending_prepayment_count = (
        db.query(func.count(OpenItem.id))
        .filter(
            OpenItem.ledger_id == ledger_id,
            OpenItem.status.in_([OpenItemStatus.OPEN, OpenItemStatus.PARTIAL]),
        )
        .scalar()
        or 0
    )

    # 3. Unmatched bank transactions
    unmatched_bank_txns = (
        db.query(func.count(OpenItem.id))
        .filter(
            OpenItem.ledger_id == ledger_id,
            OpenItem.item_type == OpenItemType.BANK_TXN,
            OpenItem.status.in_([OpenItemStatus.OPEN, OpenItemStatus.PARTIAL]),
        )
        .scalar()
        or 0
    )

    # 4. Pending tasks
    pending_tasks = []
    if pending_prepayment_count > 0:
        pending_tasks.append(
            {
                "type": "prepayment",
                "title": f"{pending_prepayment_count}笔预付账款待核销",
                "description": "需工厂发票核销预付账款，完成平账确认。",
            }
        )
    if unmatched_bank_txns > 0:
        pending_tasks.append(
            {
                "type": "bank_txn",
                "title": f"{unmatched_bank_txns}笔银行流水未入账",
                "description": "AI 待匹配银行流水至相应凭证。",
            }
        )
    # VAT awareness: check if there's pending VAT to report
    vat_pending_count = (
        db.query(func.count(VATRecord.id))
        .filter(
            VATRecord.ledger_id == ledger_id,
            extract("year", VATRecord.voucher_date) == year,
            extract("month", VATRecord.voucher_date) == month,
        )
        .scalar()
        or 0
    )
    if vat_pending_count > 0:
        pending_tasks.append(
            {
                "type": "vat_filing",
                "title": f"当期有{vat_pending_count}笔增值税记录待申报",
                "description": "请前往税务模块查看增值税汇总并生成纳税凭证。",
            }
        )
    else:
        pending_tasks.append(
            {
                "type": "vat_filing",
                "title": "增值税申报提醒",
                "description": "本月暂无增值税记录，如已发生业务请及时录入进项/销项税。",
            }
        )
    # OEM Commission check: count active salespersons and contracts
    from app.models.financial import Salesperson, OEMContract, ContractStatus

    active_sp_count = (
        db.query(func.count(Salesperson.id))
        .filter(Salesperson.ledger_id == ledger_id, Salesperson.is_active == True)
        .scalar()
    ) or 0

    active_oc_count = (
        db.query(func.count(OEMContract.id))
        .filter(
            OEMContract.ledger_id == ledger_id,
            OEMContract.status == ContractStatus.ACTIVE,
        )
        .scalar()
    ) or 0

    if active_sp_count > 0 and active_oc_count > 0:
        pending_tasks.append({
            "type": "oem_commission",
            "title": "OEM提成核算",
            "description": f"{active_sp_count}名业务员、{active_oc_count}个待核算合同，请前往佣金报表查看。",
        })
    elif active_sp_count == 0:
        pending_tasks.append({
            "type": "oem_commission",
            "title": "OEM提成设置提醒",
            "description": "尚未配置业务员信息，请先在基础数据中添加业务员和佣金规则。",
        })
    else:
        pending_tasks.append({
            "type": "oem_commission",
            "title": "OEM提成核算",
            "description": "已配置业务员，暂无活跃合同。",
        })

    return DashboardSummaryResponse(
        monthly_revenue=round(monthly_revenue, 2),
        monthly_revenue_trend=round(monthly_revenue_trend, 1) if monthly_revenue_trend is not None else None,
        pending_prepayments=round(pending_prepayments, 2),
        pending_prepayment_count=pending_prepayment_count,
        unmatched_bank_txns=unmatched_bank_txns,
        pending_tasks=pending_tasks,
    )


# -- Account Balance Table (科目余额表) --

class AccountBalanceRow(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    balance_direction: str  # "借" or "贷"
    opening_debit: str
    opening_credit: str
    period_debit: str
    period_credit: str
    ending_debit: str
    ending_credit: str


def _compute_opening_for_period(
    db: Session, ledger_id: int, year: int, month: int | None, account_ids: list[int]
) -> dict[int, tuple[Decimal, Decimal]]:
    """Compute (debit, credit) opening balances for the target period.

    month=1-12: opening = last month's ending (or Dec of prev year for Jan)
    month=None: YTD — opening = previous year Dec ending
    """
    if month is not None:
        prev_year = year if month > 1 else year - 1
        prev_month = month - 1 if month > 1 else 12
    else:
        prev_year = year - 1
        prev_month = 12

    # Try fast path (closed period)
    result = _try_fast_balances(db, ledger_id, prev_year, prev_month, account_ids)
    if result is not None:
        return result

    # Fallback: sum all vouchers up to (but not including) the target period
    if month is not None:
        cutoff_year = prev_year
        cutoff_month = prev_month
    else:
        cutoff_year = year - 1
        cutoff_month = 12

    # Include everything from opening through the cutoff
    # 使用月末最后一天，避免漏算 29-31 号凭证
    _, _cutoff_last_day = _cal.monthrange(cutoff_year, cutoff_month)
    _cutoff_date_str = f"{cutoff_year}-{cutoff_month:02d}-{_cutoff_last_day:02d}"
    rows = (
        db.query(
            VoucherEntry.account_id,
            func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debit_sum"),
            func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credit_sum"),
        )
        .join(Voucher)
        .filter(
            Voucher.ledger_id == ledger_id,
            VoucherEntry.account_id.in_(account_ids),
            Voucher.status == VoucherStatus.POSTED,
            func.date(Voucher.voucher_date)
            <= func.date(_cutoff_date_str),
        )
        .group_by(VoucherEntry.account_id)
        .all()
    )

    result = {}
    for r in rows:
        result[r.account_id] = (r.debit_sum or Decimal("0"), r.credit_sum or Decimal("0"))
    return result


@router.get("/account-balances", response_model=list[AccountBalanceRow])
def get_account_balances(
    year: int = Query(...),
    month: int | None = Query(None, ge=1, le=12),
    level: int | None = Query(None, ge=1, le=3, description="科目级别：1=一级(4位), 2=二级(6位), 3=三级(8位)"),
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """科目余额表：按年月查询各科目的期初、本期发生、期末余额。
    当指定level时，下级科目余额汇入上级后只展示该级科目。
    """
    from sqlalchemy import func as safunc
    all_accounts = (
        db.query(Account)
        .filter(Account.ledger_id == ledger_id, Account.is_active == True)
        .order_by(Account.code)
        .all()
    )

    if not all_accounts:
        return []

    all_ids = [a.id for a in all_accounts]

    # Build parent map: child_id → parent_id
    parent_map: dict[int, int] = {}
    for a in all_accounts:
        if a.parent_id is not None:
            parent_map[a.id] = a.parent_id

    # Compute balances for ALL accounts
    opening_map = _compute_opening_for_period(db, ledger_id, year, month, all_ids)

    if month is not None:
        period_map = _try_fast_period_balances(db, ledger_id, year, month, all_ids)
        if period_map is None:
            period_map = _compute_period_from_vouchers(db, ledger_id, year, month, all_ids)
    else:
        period_map = {}
        for m in range(1, 13):
            mp = _try_fast_period_balances(db, ledger_id, year, m, all_ids)
            if mp is None:
                mp = _compute_period_from_vouchers(db, ledger_id, year, m, all_ids)
            for aid, (d, c) in mp.items():
                pd, pc = period_map.get(aid, (Decimal("0"), Decimal("0")))
                period_map[aid] = (pd + d, pc + c)

    # Build row dict for all accounts
    row_by_id: dict[int, dict] = {}
    for a in all_accounts:
        open_d, open_c = opening_map.get(a.id, (Decimal("0"), Decimal("0")))
        own_open = Decimal(str(a.opening_balance or 0))
        if a.balance_direction == AccountDirection.DEBIT:
            open_d += own_open
        else:
            open_c += own_open

        p_d, p_c = period_map.get(a.id, (Decimal("0"), Decimal("0")))

        row_by_id[a.id] = {
            "account": a,
            "open_d": open_d,
            "open_c": open_c,
            "period_d": p_d,
            "period_c": p_c,
        }

    # Roll up: deepest first — add child balances to parent
    if level is not None:
        sorted_accounts = sorted(all_accounts, key=lambda x: len(x.code), reverse=True)
        for a in sorted_accounts:
            if a.id in parent_map:
                parent_id = parent_map[a.id]
                if parent_id in row_by_id:
                    child_row = row_by_id[a.id]
                    parent_row = row_by_id[parent_id]
                    parent_row["open_d"] += child_row["open_d"]
                    parent_row["open_c"] += child_row["open_c"]
                    parent_row["period_d"] += child_row["period_d"]
                    parent_row["period_c"] += child_row["period_c"]

    # Build output rows, filtered by level
    code_len = level * 2 + 2 if level is not None else None
    rows = []
    for a in all_accounts:
        if code_len is not None and len(a.code) != code_len:
            continue

        r = row_by_id[a.id]
        open_d = r["open_d"]
        open_c = r["open_c"]
        p_d = r["period_d"]
        p_c = r["period_c"]

        end_d = open_d + p_d
        end_c = open_c + p_c

        # Net opening
        if open_d >= open_c:
            open_d = open_d - open_c
            open_c = Decimal("0")
        else:
            open_c = open_c - open_d
            open_d = Decimal("0")

        # Net ending
        if end_d >= end_c:
            end_d = end_d - end_c
            end_c = Decimal("0")
        else:
            end_c = end_c - end_d
            end_d = Decimal("0")

        rows.append(AccountBalanceRow(
            account_id=a.id,
            account_code=a.code,
            account_name=a.name,
            balance_direction="借" if a.balance_direction == AccountDirection.DEBIT else "贷",
            opening_debit=str(open_d),
            opening_credit=str(open_c),
            period_debit=str(p_d),
            period_credit=str(p_c),
            ending_debit=str(end_d),
            ending_credit=str(end_c),
        ))

    return rows


def _compute_period_from_vouchers(
    db: Session, ledger_id: int, year: int, month: int, account_ids: list[int]
) -> dict[int, tuple[Decimal, Decimal]]:
    """Compute (period_debit, period_credit) by scanning VoucherEntry for the target month."""
    rows = (
        db.query(
            VoucherEntry.account_id,
            func.sum(case((VoucherEntry.direction == AccountDirection.DEBIT, VoucherEntry.amount), else_=0)).label("debit_sum"),
            func.sum(case((VoucherEntry.direction == AccountDirection.CREDIT, VoucherEntry.amount), else_=0)).label("credit_sum"),
        )
        .join(Voucher)
        .filter(
            Voucher.ledger_id == ledger_id,
            VoucherEntry.account_id.in_(account_ids),
            extract("year", Voucher.voucher_date) == year,
            extract("month", Voucher.voucher_date) == month,
            Voucher.status == VoucherStatus.POSTED,
        )
        .group_by(VoucherEntry.account_id)
        .all()
    )
    result = {}
    for r in rows:
        result[r.account_id] = (r.debit_sum or Decimal("0"), r.credit_sum or Decimal("0"))
    return result

