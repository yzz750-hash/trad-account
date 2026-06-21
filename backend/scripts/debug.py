"""
Debug script: create a voucher from an OCR-extracted document.
Usage: python scripts/debug.py [doc_id]
WARNING: This is a development/debugging script, not for production use.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import SessionLocal
from app.models.financial import OriginalDocument, Account, Voucher, VoucherEntry, AccountDirection, VoucherStatus
from datetime import date

LEDGER_ID = int(os.environ.get("LEDGER_ID", "1"))

db = SessionLocal()
try:
    doc_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    doc = db.query(OriginalDocument).filter(OriginalDocument.id == doc_id).first()
    if not doc:
        print(f"No document with id={doc_id}")
        sys.exit(1)

    print("extracted_data type:", type(doc.extracted_data))
    print("extracted_data content:", doc.extracted_data)

    total_amount = sum(float(item.get("amount", 0)) for item in doc.extracted_data["items"]
                       if str(item.get("amount", "")).replace(".", "", 1).isdigit())
    print("total_amount:", total_amount)

    acct_debit = db.query(Account).filter(Account.code == "1403", Account.ledger_id == LEDGER_ID).first()
    if not acct_debit:
        acct_debit = Account(code="1403", name="原材料", balance_direction=AccountDirection.DEBIT, ledger_id=LEDGER_ID)
        db.add(acct_debit)

    acct_credit = db.query(Account).filter(Account.code == "2202", Account.ledger_id == LEDGER_ID).first()
    if not acct_credit:
        acct_credit = Account(code="2202", name="应付账款", balance_direction=AccountDirection.CREDIT, ledger_id=LEDGER_ID)
        db.add(acct_credit)

    db.flush()
    print("Accts created")

    vendor_name = doc.extracted_data.get("vendor_name", "未知供应商")

    new_voucher = Voucher(
        ledger_id=LEDGER_ID,
        voucher_number=f"JV-{date.today().strftime('%Y%m%d')}-{doc_id}",
        voucher_date=date.today(),
        attachments_count=1,
        status=VoucherStatus.POSTED,
    )
    db.add(new_voucher)
    db.flush()
    print("Voucher created")

    db.add(VoucherEntry(
        voucher_id=new_voucher.id,
        account_id=acct_debit.id,
        summary=f"采购商品 - {vendor_name}",
        direction=AccountDirection.DEBIT,
        amount=total_amount,
    ))
    db.add(VoucherEntry(
        voucher_id=new_voucher.id,
        account_id=acct_credit.id,
        summary=f"应付货款 - {vendor_name}",
        direction=AccountDirection.CREDIT,
        amount=total_amount,
    ))

    doc.is_reconciled = True
    db.commit()
    print("Done - voucher created from OCR document")
except Exception as e:
    import traceback
    traceback.print_exc()
