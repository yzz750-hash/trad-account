"""Seed level-2 trade accounts for a specific ledger.
Usage: python scripts/add_trade_accounts.py [ledger_id]
"""
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.financial import Account, AccountType, AccountDirection

LEDGER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
db = SessionLocal()

new_accounts = [
    {"code": "600101", "name": "内销收入", "parent_code": "6001", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "600102", "name": "外销收入", "parent_code": "6001", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "640101", "name": "内销成本", "parent_code": "6401", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "640102", "name": "外销成本", "parent_code": "6401", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
]
added = 0
for acc_data in new_accounts:
    parent_code = acc_data.pop("parent_code")
    parent = db.query(Account).filter(Account.code == parent_code, Account.ledger_id == LEDGER_ID).first()
    existing = db.query(Account).filter(Account.code == acc_data["code"], Account.ledger_id == LEDGER_ID).first()
    if not existing:
        new_acc = Account(**acc_data, ledger_id=LEDGER_ID)
        if parent:
            new_acc.parent_id = parent.id
        db.add(new_acc)
        added += 1
db.commit()
print(f"Successfully added {added} trade accounts for ledger_id={LEDGER_ID}.")
