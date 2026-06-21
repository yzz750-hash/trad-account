"""Voucher CRUD endpoints: create, list, update, post, unpost, reverse, batch, print."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from datetime import date
from decimal import Decimal

logger = logging.getLogger("trad_account")

from app.database import get_db
from app.auth import require_write
from app.routers.ledgers import get_ledger_id
from app.models.financial import (
    Voucher, VoucherEntry, Account, VoucherStatus, AccountDirection, Ledger,
    AccountingPeriod, PeriodStatus,
)
from app.routers.voucher_utils import (
    VoucherEntrySchema, VoucherCreate, VoucherUpdate,
    VoucherResponse, VoucherResponsePage, BatchVoucherRequest,
    _batch_resolve_accounts, get_next_voucher_number,
)
from app.services import voucher_service as svc

router = APIRouter()


@router.post("/", response_model=VoucherResponse)
def create_voucher(voucher_data: VoucherCreate, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    """Create a new accounting voucher, ensuring debit equals credit."""
    entries = [
        {
            "account_code": e.account_code,
            "summary": e.summary,
            "direction": AccountDirection.DEBIT if e.direction == "借" else AccountDirection.CREDIT,
            "amount": e.amount,
            "currency_code": e.currency_code,
            "original_amount": e.original_amount,
            "exchange_rate": e.exchange_rate,
            "partner_id": e.partner_id,
        }
        for e in voucher_data.entries
    ]

    if not voucher_data.voucher_number or voucher_data.voucher_number.startswith("AUTO"):
        v_num = get_next_voucher_number(db, ledger_id)
    else:
        v_num = voucher_data.voucher_number

    v = svc.create_voucher(
        db, ledger_id,
        voucher_date=voucher_data.voucher_date,
        entries=entries,
        voucher_number=v_num,
        attachments_count=voucher_data.attachments_count,
        contract_number=voucher_data.contract_number,
    )
    return {"id": v.id, "voucher_number": v.voucher_number,
            "voucher_date": v.voucher_date, "status": v.status.value}


@router.post("/{voucher_id}/unpost")
def unpost_voucher(voucher_id: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    v = svc.unpost_voucher(db, ledger_id, voucher_id)
    return {"status": "success", "message": f"Voucher {v.voucher_number} returned to draft."}


@router.get("/", response_model=VoucherResponsePage)
def list_vouchers(
    search: Optional[str] = Query(None, description="Fuzzy search voucher_number and entry summary"),
    status: Optional[str] = Query(None, description="Filter by status (DRAFT/POSTED)"),
    start_date: Optional[date] = Query(None, description="Start date inclusive"),
    end_date: Optional[date] = Query(None, description="End date inclusive"),
    min_amount: Optional[Decimal] = Query(None, description="Minimum entry amount"),
    max_amount: Optional[Decimal] = Query(None, description="Maximum entry amount"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    from sqlalchemy.orm import joinedload

    base = db.query(Voucher).filter(Voucher.ledger_id == ledger_id)

    if search:
        base = base.filter(or_(
            Voucher.voucher_number.contains(search),
            Voucher.entries.any(VoucherEntry.summary.contains(search))
        ))
    if status:
        try:
            base = base.filter(Voucher.status == VoucherStatus(status))
        except ValueError:
            pass
    if start_date:
        base = base.filter(Voucher.voucher_date >= start_date)
    if end_date:
        base = base.filter(Voucher.voucher_date <= end_date)
    if min_amount is not None:
        base = base.filter(Voucher.entries.any(VoucherEntry.amount >= min_amount))
    if max_amount is not None:
        base = base.filter(Voucher.entries.any(VoucherEntry.amount <= max_amount))

    total = base.count()
    items = (
        base.options(joinedload(Voucher.entries).joinedload(VoucherEntry.account))
        .order_by(Voucher.voucher_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return VoucherResponsePage(items=items, total=total, page=page, page_size=page_size)


@router.post("/{voucher_id}/reverse", response_model=VoucherResponse)
def reverse_voucher(voucher_id: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    original = db.query(Voucher).filter(Voucher.ledger_id == ledger_id, Voucher.id == voucher_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="Voucher not found")

    today = date.today()
    svc.check_period_for_date(db, ledger_id, today)

    reversal = Voucher(ledger_id=ledger_id,
        voucher_number=get_next_voucher_number(db, ledger_id),
        voucher_date=today,
        status=VoucherStatus.DRAFT,
        source_type=f"REVERSAL of {original.voucher_number}",
    )
    db.add(reversal)
    db.flush()

    for entry in original.entries:
        db.add(VoucherEntry(
            voucher_id=reversal.id, account_id=entry.account_id,
            summary="冲销 " + (entry.summary or ""),
            direction=AccountDirection.CREDIT if entry.direction == AccountDirection.DEBIT else AccountDirection.DEBIT,
            amount=entry.amount, currency_code=entry.currency_code,
            original_amount=entry.original_amount, exchange_rate=entry.exchange_rate,
        ))

    db.commit()
    db.refresh(reversal)
    return reversal


@router.put("/{voucher_id}", response_model=VoucherResponse)
def update_draft_voucher(voucher_id: int, voucher_data: VoucherUpdate, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    voucher = db.query(Voucher).filter(Voucher.ledger_id == ledger_id, Voucher.id == voucher_id).with_for_update().first()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    if voucher.status != VoucherStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only DRAFT vouchers can be updated")

    entries = [
        {
            "account_code": e.account_code,
            "summary": e.summary,
            "direction": AccountDirection.DEBIT if e.direction == "借" else AccountDirection.CREDIT,
            "amount": e.amount,
            "currency_code": e.currency_code,
            "original_amount": e.original_amount,
            "exchange_rate": e.exchange_rate,
            "partner_id": e.partner_id,
        }
        for e in voucher_data.entries
    ]
    svc.validate_balance(entries)
    svc.validate_currency_entries(entries)

    db.query(VoucherEntry).filter(VoucherEntry.voucher_id == voucher_id).delete(synchronize_session='fetch')
    db.flush()

    codes = {e["account_code"] for e in entries}
    account_map = svc.resolve_accounts(db, ledger_id, codes)

    for entry in entries:
        account = account_map[entry["account_code"]]
        db.add(VoucherEntry(
            voucher_id=voucher_id, account_id=account.id, summary=entry["summary"],
            direction=entry["direction"], amount=entry["amount"],
            currency_code=entry.get("currency_code", "CNY"),
            original_amount=entry.get("original_amount"),
            exchange_rate=entry.get("exchange_rate", Decimal("1.0000")),
            partner_id=entry.get("partner_id"),
        ))

    db.commit()
    db.refresh(voucher)
    return voucher


@router.post("/{voucher_id}/post", response_model=VoucherResponse)
def post_draft_voucher(voucher_id: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    v = svc.post_voucher(db, ledger_id, voucher_id)
    return v


@router.post("/batch-review")
def batch_review_vouchers(body: BatchVoucherRequest, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    posted, errors = svc.batch_post_vouchers(db, ledger_id, body.voucher_ids)
    for vid in posted:
        logger.info("Batch review: Voucher id=%s posted via ledger %s", vid, ledger_id)
    return {"reviewed_count": len(posted), "failed_count": len(errors), "errors": errors}


@router.post("/batch-unpost")
def batch_unpost_vouchers(body: BatchVoucherRequest, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    unposted, errors = svc.batch_unpost_vouchers(db, ledger_id, body.voucher_ids)
    return {"unposted_count": len(unposted), "failed_count": len(errors), "errors": errors}


@router.get("/{voucher_id}/print")
def get_voucher_print(voucher_id: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    from sqlalchemy.orm import joinedload

    v = (
        db.query(Voucher)
        .filter(Voucher.ledger_id == ledger_id, Voucher.id == voucher_id)
        .options(joinedload(Voucher.entries).joinedload(VoucherEntry.account))
        .first()
    )

    if not v:
        raise HTTPException(status_code=404, detail="Voucher not found")

    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()

    return {
        "voucher_number": v.voucher_number,
        "voucher_date": str(v.voucher_date),
        "attachments_count": v.attachments_count,
        "entries": [
            {
                "account_code": entry.account.code,
                "account_name": entry.account.name,
                "summary": entry.summary,
                "direction": "借" if entry.direction == AccountDirection.DEBIT else "贷",
                "amount": entry.amount,
            }
            for entry in v.entries
        ],
        "ledger_name": ledger.name if ledger else "",
        "company_name": ledger.company_name if ledger else "",
    }
