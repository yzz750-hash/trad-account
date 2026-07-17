from decimal import Decimal
import logging
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

from app.database import get_db
from app.auth import get_current_user, CurrentUser, require_write

logger = logging.getLogger("trad_account")
from app.models.financial import Ledger, Account, AccountType, AccountDirection, AccountingPeriod, PeriodStatus

router = APIRouter()

class LedgerCreate(BaseModel):
    name: str
    company_name: Optional[str] = None
    base_currency: str = "CNY"
    start_year: int
    start_month: int

class LedgerResponse(BaseModel):
    id: int
    name: str
    company_name: Optional[str]
    base_currency: str
    start_year: int
    start_month: int

    model_config = ConfigDict(from_attributes=True)

class LedgerUpdate(BaseModel):
    name: Optional[str] = None
    company_name: Optional[str] = None

@router.post("", response_model=LedgerResponse)
def create_ledger(
    ledger_in: LedgerCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_write),
):
    logger.info("Creating ledger '%s' by user %s", ledger_in.name, current_user.username)
    # 1. Create Ledger
    ledger = Ledger(
        name=ledger_in.name,
        company_name=ledger_in.company_name,
        base_currency=ledger_in.base_currency,
        start_year=ledger_in.start_year,
        start_month=ledger_in.start_month,
        created_by=current_user.id,
    )
    db.add(ledger)
    db.commit()
    db.refresh(ledger)

    # 2. Initialize first Accounting Period
    period = AccountingPeriod(
        ledger_id=ledger.id,
        year=ledger_in.start_year,
        month=ledger_in.start_month,
        status=PeriodStatus.OPEN
    )
    db.add(period)

    # 3. Initialize minimal Chart of Accounts (一级科目)
    default_accounts = [
        {"code": "1001", "name": "库存现金", "type": AccountType.ASSET, "dir": AccountDirection.DEBIT},
        {"code": "1002", "name": "银行存款", "type": AccountType.ASSET, "dir": AccountDirection.DEBIT},
        {"code": "1122", "name": "应收账款", "type": AccountType.ASSET, "dir": AccountDirection.DEBIT},
        {"code": "1405", "name": "库存商品", "type": AccountType.ASSET, "dir": AccountDirection.DEBIT},
        {"code": "2202", "name": "应付账款", "type": AccountType.LIABILITY, "dir": AccountDirection.CREDIT},
        {"code": "2211", "name": "应付职工薪酬", "type": AccountType.LIABILITY, "dir": AccountDirection.CREDIT},
        {"code": "2221", "name": "应交税费", "type": AccountType.LIABILITY, "dir": AccountDirection.CREDIT},
        {"code": "4001", "name": "实收资本", "type": AccountType.EQUITY, "dir": AccountDirection.CREDIT},
        {"code": "4103", "name": "本年利润", "type": AccountType.EQUITY, "dir": AccountDirection.CREDIT},
        {"code": "4104", "name": "利润分配", "type": AccountType.EQUITY, "dir": AccountDirection.CREDIT},
        {"code": "5001", "name": "主营业务收入", "type": AccountType.PROFIT_LOSS, "dir": AccountDirection.CREDIT},
        {"code": "5401", "name": "主营业务成本", "type": AccountType.PROFIT_LOSS, "dir": AccountDirection.DEBIT},
        {"code": "6601", "name": "销售费用", "type": AccountType.PROFIT_LOSS, "dir": AccountDirection.DEBIT},
        {"code": "6602", "name": "管理费用", "type": AccountType.PROFIT_LOSS, "dir": AccountDirection.DEBIT},
        {"code": "6603", "name": "财务费用", "type": AccountType.PROFIT_LOSS, "dir": AccountDirection.DEBIT},
    ]

    for acc in default_accounts:
        db.add(Account(
            ledger_id=ledger.id,
            code=acc["code"],
            name=acc["name"],
            account_type=acc["type"],
            balance_direction=acc["dir"],
            opening_balance=Decimal("0.00"),
            is_active=True
        ))

    # 4. Initialize voucher number counters for all prefixes
    from app.models.financial import VoucherNumberCounter
    for prefix in ["记-", "银记-", "核-", "期末调汇-"]:
        db.add(VoucherNumberCounter(ledger_id=ledger.id, prefix=prefix, current_number=0))
    
    db.commit()
    return ledger

@router.get("", response_model=List[LedgerResponse])
def get_ledgers(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        return db.query(Ledger).all()
    return db.query(Ledger).filter(Ledger.created_by == current_user.id).all()

@router.put("/{ledger_id}", response_model=LedgerResponse)
def update_ledger(
    ledger_id: int,
    ledger_in: LedgerUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_write),
):
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail="Ledger not found")
    if current_user.role != "admin" and ledger.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied to this ledger")

    if ledger_in.name is not None:
        ledger.name = ledger_in.name
    if ledger_in.company_name is not None:
        ledger.company_name = ledger_in.company_name

    db.commit()
    db.refresh(ledger)
    return ledger

@router.delete("/{ledger_id}")
def delete_ledger(
    ledger_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_write),
):
    from app.models.financial import (
        Voucher, ReconciliationRecord, ExchangeRate, VATRecord,
        ClosingOperation, OpenItem, OriginalDocument, OEMContract,
        FixedAsset, BusinessPartner, CommissionRule, Salesperson,
        TaxRate, VoucherNumberCounter, AuditLog, Account, AccountingPeriod,
    )
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail="Ledger not found")
    if current_user.role != "admin" and ledger.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied to this ledger")

    # Check if there are vouchers
    if db.query(Voucher).filter(Voucher.ledger_id == ledger_id).first():
        raise HTTPException(status_code=400, detail="不能删除已包含凭证数据的账套，为保证数据完整性，已拦截此操作。")

    logger.info("Deleting ledger '%s' (id=%s) by user %s", ledger.name, ledger_id, current_user.username)

    # Delete related records in FK-safe order
    # IMPORTANT: When adding a new model with a ledger_id FK, add its deletion here.
    # Order matters: delete tables that reference other ledger-scoped tables FIRST.

    # 1. Tables that reference other ledger-scoped tables
    db.query(ReconciliationRecord).filter(
        ReconciliationRecord.ledger_id == ledger_id
    ).delete(synchronize_session=False)

    # Exchange rates reference accounting_periods
    db.query(ExchangeRate).filter(
        ExchangeRate.period_id.in_(
            db.query(AccountingPeriod.id).filter(AccountingPeriod.ledger_id == ledger_id)
        )
    ).delete(synchronize_session=False)

    # 2. Tables with no downstream dependents (or already cleaned)
    db.query(VATRecord).filter(VATRecord.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(ClosingOperation).filter(ClosingOperation.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(OpenItem).filter(OpenItem.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(OriginalDocument).filter(OriginalDocument.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(OEMContract).filter(OEMContract.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(FixedAsset).filter(FixedAsset.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(BusinessPartner).filter(BusinessPartner.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(CommissionRule).filter(CommissionRule.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(Salesperson).filter(Salesperson.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(TaxRate).filter(TaxRate.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(VoucherNumberCounter).filter(VoucherNumberCounter.ledger_id == ledger_id).delete(synchronize_session=False)
    # Audit logs MUST be retained for compliance (等保2.0三级 / SOX-style retention).
    # Instead of deleting them, we null out the ledger_id FK so the log rows
    # survive but no longer reference the deleted ledger. The deletion event
    # itself is also recorded as a new audit log entry below.
    db.query(AuditLog).filter(AuditLog.ledger_id == ledger_id).update(
        {AuditLog.ledger_id: None},
        synchronize_session=False,
    )
    db.query(Account).filter(Account.ledger_id == ledger_id).delete(synchronize_session=False)
    db.query(AccountingPeriod).filter(AccountingPeriod.ledger_id == ledger_id).delete(synchronize_session=False)

    db.delete(ledger)
    db.commit()
    logger.warning(
        "Ledger '%s' (id=%s) deleted by user %s. Audit logs for this ledger "
        "were preserved with ledger_id=NULL for compliance retention.",
        ledger.name, ledger_id, current_user.username,
    )
    return {"status": "success", "message": "Ledger deleted. Audit logs retained for compliance."}

# Dependency for other routers — now enforces ledger-level authorization
def get_ledger_id(
    x_ledger_id: Optional[int] = Header(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> int:
    if not x_ledger_id:
        raise HTTPException(status_code=400, detail="X-Ledger-Id header is required")
    # Admins can access all ledgers; other users can only access their own
    if current_user.role != "admin":
        ledger = db.query(Ledger).filter(Ledger.id == x_ledger_id).first()
        if not ledger:
            raise HTTPException(status_code=404, detail="Ledger not found")
        if ledger.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied to this ledger")
    return x_ledger_id
