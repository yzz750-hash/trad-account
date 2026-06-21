"""Seed level-3 trade accounts for a specific ledger.
Usage: python scripts/add_level3.py [ledger_id]
"""
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.financial import Account, AccountType, AccountDirection

LEDGER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
db = SessionLocal()

new_accounts = [
    {"code": "60010101", "name": "A类产品内销", "parent_code": "600101", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "60010102", "name": "B类产品内销", "parent_code": "600101", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "60010201", "name": "北美区外销", "parent_code": "600102", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "60010202", "name": "欧洲区外销", "parent_code": "600102", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
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
print(f"Successfully added {added} level 3 trade accounts for ledger_id={LEDGER_ID}.")
