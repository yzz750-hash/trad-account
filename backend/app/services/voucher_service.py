"""Voucher service — core business logic extracted from routers.

ponytail: functions accept db + params, return domain objects or raise HTTPException.
The router handles HTTP concerns (parsing, response formatting, auth).
"""

import logging
from datetime import date
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.financial import (
    Voucher, VoucherEntry, Account, VoucherStatus, AccountDirection,
    AccountingPeriod, PeriodStatus, Ledger,
)

logger = logging.getLogger("trad_account")


def validate_balance(entries: list[dict], tolerance: Decimal = Decimal("0.01")) -> None:
    """Validate that debits equal credits. Raises HTTPException if unbalanced."""
    total_debit = sum(e["amount"] for e in entries if e["direction"] == AccountDirection.DEBIT)
    total_credit = sum(e["amount"] for e in entries if e["direction"] == AccountDirection.CREDIT)
    if abs(total_debit - total_credit) > tolerance:
        raise HTTPException(
            status_code=400,
            detail=f"Debit ({total_debit}) and Credit ({total_credit}) must be equal",
        )


def check_period_for_date(db: Session, ledger_id: int, d: date) -> None:
    """Verify the accounting period for the given date is OPEN. Raises HTTPException if not."""
    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == d.year,
        AccountingPeriod.month == d.month,
    ).with_for_update().first()

    if not period or period.status != PeriodStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail=f"Accounting period {d.year}-{d.month} is not OPEN.",
        )


def validate_currency_entries(entries: list[dict]) -> None:
    """Validate foreign-currency entries: amount ≈ original_amount × exchange_rate."""
    for entry in entries:
        if entry.get("currency_code") and entry["currency_code"] != "CNY" and entry.get("original_amount") is not None:
            expected = (entry["original_amount"] * entry["exchange_rate"]).quantize(Decimal("0.01"))
            if abs(entry["amount"] - expected) > Decimal("0.05"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Currency mismatch on {entry.get('account_code', '?')}: "
                           f"amount={entry['amount']} but expected={expected} "
                           f"(= {entry['original_amount']} x {entry['exchange_rate']})",
                )


def resolve_accounts(db: Session, ledger_id: int, codes: set[str]) -> dict[str, Account]:
    """Resolve account codes to Account objects. Raises HTTPException on missing."""
    if not codes:
        return {}
    accounts = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.code.in_(codes)
    ).all()
    by_code = {a.code: a for a in accounts}
    for code in codes:
        if code not in by_code:
            raise HTTPException(status_code=400, detail=f"Account code {code} not found")
    return by_code


def create_voucher(
    db: Session,
    ledger_id: int,
    voucher_date: date,
    entries: list[dict],
    voucher_number: str,
    attachments_count: int = 0,
    contract_number: str | None = None,
    source_type: str | None = None,
    extra_actions: callable | None = None,
) -> Voucher:
    """Create a voucher with full validation. extra_actions(db, voucher) called after flush."""

    if not entries or len(entries) < 2:
        raise HTTPException(status_code=400, detail="Voucher must have at least 2 entries")

    check_period_for_date(db, ledger_id, voucher_date)
    validate_balance(entries)
    validate_currency_entries(entries)

    codes = {e["account_code"] for e in entries}
    account_map = resolve_accounts(db, ledger_id, codes)

    v = Voucher(
        ledger_id=ledger_id,
        voucher_number=voucher_number,
        voucher_date=voucher_date,
        attachments_count=attachments_count,
        contract_number=contract_number,
        source_type=source_type,
        status=VoucherStatus.DRAFT,
    )
    db.add(v)
    db.flush()

    for entry in entries:
        account = account_map[entry["account_code"]]
        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=account.id,
            summary=entry["summary"],
            direction=entry["direction"],
            amount=entry["amount"],
            currency_code=entry.get("currency_code", "CNY"),
            original_amount=entry.get("original_amount"),
            exchange_rate=entry.get("exchange_rate", Decimal("1.0000")),
            partner_id=entry.get("partner_id"),
        ))

    if extra_actions:
        extra_actions(db, v)

    db.commit()
    db.refresh(v)
    return v


def post_voucher(db: Session, ledger_id: int, voucher_id: int) -> Voucher:
    """Post a draft voucher after validating period and balance."""
    v = db.query(Voucher).filter(
        Voucher.ledger_id == ledger_id, Voucher.id == voucher_id
    ).with_for_update().first()
    if not v:
        raise HTTPException(status_code=404, detail="Voucher not found")
    if v.status != VoucherStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only DRAFT vouchers can be posted")

    check_period_for_date(db, ledger_id, v.voucher_date)

    entries = db.query(VoucherEntry).filter(VoucherEntry.voucher_id == voucher_id).all()
    validate_balance([
        {"amount": e.amount, "direction": e.direction} for e in entries
    ])

    v.status = VoucherStatus.POSTED
    db.commit()
    db.refresh(v)
    return v


def unpost_voucher(db: Session, ledger_id: int, voucher_id: int) -> Voucher:
    """Unpost a posted voucher, returning it to DRAFT."""
    v = db.query(Voucher).filter(
        Voucher.ledger_id == ledger_id, Voucher.id == voucher_id
    ).with_for_update().first()
    if not v:
        raise HTTPException(status_code=404, detail="Voucher not found")
    if v.status == VoucherStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Voucher is already in draft status")

    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == v.voucher_date.year,
        AccountingPeriod.month == v.voucher_date.month,
    ).first()
    if period and period.status == PeriodStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Cannot unpost: accounting period is closed.")

    old_status = v.status.value
    v.status = VoucherStatus.DRAFT
    db.commit()
    logger.info("Voucher %s (id=%s) unposted from %s via ledger %s",
                v.voucher_number, voucher_id, old_status, ledger_id)
    return v


def batch_post_vouchers(
    db: Session, ledger_id: int, voucher_ids: list[int]
) -> tuple[list[int], list[dict]]:
    """Batch post vouchers. Returns (success_ids, error_dicts)."""
    posted: list[int] = []
    errors: list[dict] = []

    for vid in voucher_ids:
        v = db.query(Voucher).filter(
            Voucher.ledger_id == ledger_id, Voucher.id == vid
        ).with_for_update().first()
        if not v:
            errors.append({"id": vid, "voucher_number": "", "reason": "Voucher not found"})
            continue
        if v.status != VoucherStatus.DRAFT:
            errors.append({"id": vid, "voucher_number": v.voucher_number, "reason": "Only DRAFT vouchers can be reviewed"})
            continue

        try:
            check_period_for_date(db, ledger_id, v.voucher_date)
        except HTTPException as e:
            errors.append({"id": vid, "voucher_number": v.voucher_number, "reason": e.detail})
            continue

        entries = db.query(VoucherEntry).filter(VoucherEntry.voucher_id == vid).all()
        try:
            validate_balance([{"amount": e.amount, "direction": e.direction} for e in entries])
        except HTTPException as e:
            errors.append({"id": vid, "voucher_number": v.voucher_number, "reason": e.detail})
            continue

        v.status = VoucherStatus.POSTED
        posted.append(vid)

    db.commit()
    return posted, errors


def batch_unpost_vouchers(
    db: Session, ledger_id: int, voucher_ids: list[int]
) -> tuple[list[int], list[dict]]:
    """Batch unpost vouchers. Returns (success_ids, error_dicts)."""
    unposted: list[int] = []
    errors: list[dict] = []

    for vid in voucher_ids:
        v = db.query(Voucher).filter(
            Voucher.ledger_id == ledger_id, Voucher.id == vid
        ).first()
        if not v:
            errors.append({"id": vid, "voucher_number": "", "reason": "Voucher not found"})
            continue
        if v.status == VoucherStatus.DRAFT:
            errors.append({"id": vid, "voucher_number": v.voucher_number, "reason": "Voucher is already in draft status"})
            continue

        period = db.query(AccountingPeriod).filter(
            AccountingPeriod.ledger_id == ledger_id,
            AccountingPeriod.year == v.voucher_date.year,
            AccountingPeriod.month == v.voucher_date.month,
        ).first()
        if period and period.status == PeriodStatus.CLOSED:
            errors.append({"id": vid, "voucher_number": v.voucher_number, "reason": f"Accounting period {v.voucher_date.year}-{v.voucher_date.month} is CLOSED"})
            continue

        old_status = v.status.value
        v.status = VoucherStatus.DRAFT
        unposted.append(vid)
        logger.info("Batch unpost: Voucher %s (id=%s) unposted from %s via ledger %s",
                    v.voucher_number, vid, old_status, ledger_id)

    db.commit()
    return unposted, errors
