from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from decimal import Decimal
from app.database import get_db
from app.auth import require_write
from app.routers.ledgers import get_ledger_id
from app.models.financial import Account
from pydantic import BaseModel, ConfigDict
from app.types import Money

router = APIRouter()

class AccountSchema(BaseModel):
    id: int
    code: str
    name: str
    account_type: str
    balance_direction: str
    parent_id: int | None = None
    opening_balance: Money = Decimal("0.00")

    model_config = ConfigDict(from_attributes=True)

class AccountCreate(BaseModel):
    code: str
    name: str
    parent_id: int | None = None
    opening_balance: Money = Decimal("0.00")
    account_type: str | None = None
    balance_direction: str | None = None

class AccountUpdate(BaseModel):
    name: str | None = None
    opening_balance: Money | None = None

@router.get("/", response_model=List[AccountSchema])
def list_accounts(db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """Get all chart of accounts."""
    accounts = db.query(Account).filter(Account.ledger_id == ledger_id).order_by(Account.code).all()
    return [AccountSchema.model_validate(a) for a in accounts]

@router.post("/", response_model=AccountSchema)
def create_account(account: AccountCreate, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    """Add a new account, typically a sub-account."""
    from app.models.financial import AccountType, AccountDirection
    
    # Validate code format: digits only, 4-12 chars
    import re
    if not re.match(r'^\d{4,12}$', account.code):
        raise HTTPException(status_code=400, detail="Account code must be 4-12 digits.")

    # Check if code already exists
    if db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == account.code).first():
        raise HTTPException(status_code=400, detail="Account code already exists.")

    parent = None
    if account.parent_id:
        parent = db.query(Account).filter(Account.ledger_id == ledger_id, Account.id == account.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent account not found.")
        if not account.code.startswith(parent.code):
            raise HTTPException(status_code=400, detail=f"Sub-account code must start with parent code '{parent.code}'.")

    a_type = account.account_type
    b_dir = account.balance_direction
    
    if parent:
        # Inherit from parent
        a_type = parent.account_type.value if hasattr(parent.account_type, 'value') else parent.account_type
        b_dir = parent.balance_direction.value if hasattr(parent.balance_direction, 'value') else parent.balance_direction
        
    if not a_type or not b_dir:
        raise HTTPException(status_code=400, detail="account_type and balance_direction are required for top-level accounts.")
        
    try:
        new_acc = Account(
            ledger_id=ledger_id,
            code=account.code,
            name=account.name,
            parent_id=account.parent_id,
            account_type=AccountType(a_type),
            balance_direction=AccountDirection(b_dir),
            opening_balance=account.opening_balance
        )
        db.add(new_acc)
        db.commit()
        db.refresh(new_acc)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Failed to create account. Check that code, name, and type are valid.")
        
    return AccountSchema.model_validate(new_acc)

@router.put("/{account_id}", response_model=AccountSchema)
def update_account(account_id: int, account_data: AccountUpdate, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    """Update account name or opening balance."""
    acc = db.query(Account).filter(Account.ledger_id == ledger_id, Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found.")
        
    if account_data.name is not None:
        acc.name = account_data.name
    if account_data.opening_balance is not None:
        acc.opening_balance = account_data.opening_balance
        
    db.commit()
    db.refresh(acc)
    
    return AccountSchema.model_validate(acc)

@router.get("/trial-balance")
def check_trial_balance(db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    """Check if opening balances are balanced (Debit == Credit)."""
    from app.models.financial import AccountDirection
    
    accounts = db.query(Account).filter(Account.ledger_id == ledger_id).all()
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    # Batch-fetch parent_ids to identify leaf nodes
    account_ids = {a.id for a in accounts}
    if account_ids:
        from sqlalchemy import func
        parent_rows = (
            db.query(func.distinct(Account.parent_id))
            .filter(Account.ledger_id == ledger_id, Account.parent_id.in_(account_ids))
            .all()
        )
        parent_ids = {r[0] for r in parent_rows if r[0] is not None}
    else:
        parent_ids = set()

    for a in accounts:
        if a.id not in parent_ids:  # leaf node
            if a.balance_direction == AccountDirection.DEBIT:
                total_debit += Decimal(str(a.opening_balance))
            else:
                total_credit += Decimal(str(a.opening_balance))
                
    is_balanced = total_debit == total_credit
    return {
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": is_balanced,
        "difference": abs(total_debit - total_credit)
    }

@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    """Delete an account if it has no children and no voucher entries."""
    from app.models.financial import VoucherEntry
    
    acc = db.query(Account).filter(Account.ledger_id == ledger_id, Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found.")
        
    children_count = db.query(Account).filter(Account.ledger_id == ledger_id, Account.parent_id == acc.id).count()
    if children_count > 0:
        raise HTTPException(status_code=400, detail="不能删除包含下级子科目的父科目，请先删除底层的子科目。")
        
    entry_count = db.query(VoucherEntry).filter(VoucherEntry.account_id == acc.id).count()
    if entry_count > 0:
        raise HTTPException(status_code=400, detail="拦截：该科目已在历史凭证中使用过，为保障财务数据完整性，系统已永久封锁该科目的删除权限。")
        
    db.delete(acc)
    db.commit()
    return {"message": "Account successfully deleted."}

