"""Commission calculation engine for OEM contract salesperson commissions.

Pure calculation module with no HTTP dependencies. Accepts a SQLAlchemy Session
and parameters, returns structured dataclass results.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import extract
from sqlalchemy.orm import Session

import calendar

from app.models.financial import (
    Account,
    AccountDirection,
    AccountType,
    CommissionBasis,
    CommissionRule,
    ContractStatus,
    OEMContract,
    Salesperson,
    Voucher,
    VoucherEntry,
    VoucherStatus,
)


def classify_voucher_entry(entry, account) -> tuple[str, Decimal]:
    """Classify a voucher entry into 'revenue', 'cost', 'expenses', or 'other'.

    Uses account_type and balance_direction as primary signals (enum-backed, reliable).
    Name-based matching is secondary refinement only.
    Shared by the OEM contract P&L endpoint and the commission engine.
    """
    amount = Decimal(str(entry.amount or 0))

    if account.account_type == AccountType.COST:
        return ("cost", amount)

    if account.account_type == AccountType.PROFIT_LOSS:
        # CREDIT side of P&L = revenue; DEBIT side = expense or cost
        if entry.direction == AccountDirection.CREDIT:
            return ("revenue", amount)
        # Refine debit-side: account codes starting with "54" (main/other business cost)
        # are cost accounts under Chinese GAAP, others are expenses.
        if account.code.startswith("54"):
            return ("cost", amount)
        return ("expenses", amount)

    return ("other", amount)


@dataclass
class ContractCommission:
    contract_number: str
    customer_name: Optional[str]
    revenue: Decimal
    cost: Decimal
    gross_profit: Decimal
    basis_amount: Decimal
    rate: Decimal
    commission_amount: Decimal


@dataclass
class SalespersonCommission:
    salesperson_id: int
    salesperson_name: str
    department: Optional[str]
    contracts: list = field(default_factory=list)
    total_commission: Decimal = Decimal("0")


@dataclass
class CommissionReport:
    period: str
    salespersons: list  # list[SalespersonCommission]
    total_commission: Decimal
    contract_count: int


def _batch_compute_contract_pnls(
    db: Session,
    contract_numbers: list[str],
    year: int,
    month: Optional[int],
    account_map: dict,
) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    """Batch-compute P&L for multiple contracts in a single DB query.

    Returns {contract_number: (revenue, cost, expenses)}.
    """
    if not contract_numbers:
        return {}

    query = (
        db.query(VoucherEntry, Voucher)
        .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
        .filter(
            Voucher.contract_number.in_(contract_numbers),
            Voucher.status == VoucherStatus.POSTED,
            extract("year", Voucher.voucher_date) == year,
        )
    )
    if month is not None:
        query = query.filter(extract("month", Voucher.voucher_date) == month)

    rows = query.all()

    # Initialize accumulators for all contracts
    result: dict[str, tuple[Decimal, Decimal, Decimal]] = {
        cn: (Decimal("0"), Decimal("0"), Decimal("0")) for cn in contract_numbers
    }

    for entry, voucher in rows:
        cn = voucher.contract_number
        if cn not in result:
            continue
        account = account_map.get(entry.account_id)
        if account is None:
            continue
        category, amount = classify_voucher_entry(entry, account)
        rev, cost, exp = result[cn]
        if category == "revenue":
            result[cn] = (rev + amount, cost, exp)
        elif category == "cost":
            result[cn] = (rev, cost + amount, exp)
        elif category == "expenses":
            result[cn] = (rev, cost, exp + amount)

    return result


def calculate_commission(
    db: Session,
    ledger_id: int,
    year: int,
    month: Optional[int] = None,
) -> CommissionReport:
    """Calculate salesperson commissions based on OEM contract P&L.

    Algorithm:
    1. Find active salespersons for the ledger.
    2. For each, find the effective CommissionRule (per-salesperson first,
       fall back to global rule where salesperson_id IS NULL).
    3. Find their active OEMContracts (status != CANCELLED).
    4. Batch-fetch all relevant vouchers and accounts, compute P&L per contract.
    5. Apply the rule's rate to the basis amount, aggregate per salesperson.
    """
    # Determine period label
    period = str(year) if month is None else f"{year}-{month:02d}"

    # 1. Active salespersons
    salespersons = (
        db.query(Salesperson)
        .filter(
            Salesperson.ledger_id == ledger_id,
            Salesperson.is_active == True,
        )
        .all()
    )

    # 2. Global rule (fallback)
    global_rule = (
        db.query(CommissionRule)
        .filter(
            CommissionRule.ledger_id == ledger_id,
            CommissionRule.salesperson_id == None,
            CommissionRule.is_active == True,
        )
        .first()
    )

    # Pre-build account lookup map for all accounts in this ledger
    accounts = db.query(Account).filter(Account.ledger_id == ledger_id).all()
    account_map = {a.id: a for a in accounts}

    if not salespersons:
        return CommissionReport(
            period=period,
            salespersons=[],
            total_commission=Decimal("0"),
            contract_count=0,
        )

    # Determine query date range for rule validation
    last_day = 31 if month is None else _last_day_of_month(year, month)
    rule_check_date = date(year, month or 12, last_day)
    rule_check_start = date(year, 1, 1) if month is None else date(year, month, 1)

    result_salespersons = []
    grand_total = Decimal("0")
    total_contract_count = 0

    # Phase 1: Collect all active contracts and batch-fetch their P&L
    sp_rules: dict[int, tuple] = {}  # salesperson_id -> (rule, [contracts])
    all_contract_numbers: list[str] = []

    for sp in salespersons:
        rule = (
            db.query(CommissionRule)
            .filter(
                CommissionRule.ledger_id == ledger_id,
                CommissionRule.salesperson_id == sp.id,
                CommissionRule.is_active == True,
                CommissionRule.effective_from <= rule_check_date,
                (
                    CommissionRule.effective_to == None
                ) | (CommissionRule.effective_to >= rule_check_start),
            )
            .first()
        )
        if rule is None:
            rule = global_rule
        if rule is None:
            continue

        contracts = (
            db.query(OEMContract)
            .filter(
                OEMContract.ledger_id == ledger_id,
                OEMContract.salesperson_id == sp.id,
                OEMContract.status != ContractStatus.CANCELLED,
            )
            .all()
        )
        if not contracts:
            continue

        sp_rules[sp.id] = (sp, rule, contracts)
        for c in contracts:
            all_contract_numbers.append(c.contract_number)

    # Single batch query for all contract P&Ls
    pnl_map = _batch_compute_contract_pnls(
        db, all_contract_numbers, year, month, account_map
    )

    # Phase 2: Compute commission using pre-fetched P&L data
    for sp, rule, contracts in sp_rules.values():
        sp_contracts = []
        sp_total = Decimal("0")

        for contract in contracts:
            revenue, cost, expenses = pnl_map.get(
                contract.contract_number, (Decimal("0"), Decimal("0"), Decimal("0"))
            )

            if revenue == 0 and cost == 0 and expenses == 0:
                continue  # No posted vouchers for this contract in the period

            gross_profit = revenue - cost
            net_profit = gross_profit - expenses

            if rule.basis == CommissionBasis.REVENUE:
                basis_amount = revenue
            elif rule.basis == CommissionBasis.NET_PROFIT:
                basis_amount = net_profit
            else:
                basis_amount = gross_profit

            rate = Decimal(str(rule.rate or 0))
            commission_amount = basis_amount * rate

            sp_contracts.append(
                ContractCommission(
                    contract_number=contract.contract_number,
                    customer_name=contract.customer_name,
                    revenue=revenue,
                    cost=cost,
                    gross_profit=gross_profit,
                    basis_amount=basis_amount,
                    rate=rate,
                    commission_amount=commission_amount,
                )
            )
            sp_total += commission_amount

        if sp_contracts:
            result_salespersons.append(
                SalespersonCommission(
                    salesperson_id=sp.id,
                    salesperson_name=sp.name,
                    department=sp.department,
                    contracts=sp_contracts,
                    total_commission=sp_total,
                )
            )
            grand_total += sp_total
            total_contract_count += len(sp_contracts)

    return CommissionReport(
        period=period,
        salespersons=result_salespersons,
        total_commission=grand_total,
        contract_count=total_contract_count,
    )


def _last_day_of_month(year: int, month: int) -> int:
    """Return the last day of a given month."""
    if month == 12:
        return 31
    return calendar.monthrange(year, month)[1]
