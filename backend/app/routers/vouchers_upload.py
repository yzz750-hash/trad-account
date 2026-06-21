"""File upload endpoints: PDF invoice OCR and bank statement parsing."""

import os
import uuid
import re
import io
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from decimal import Decimal as D

logger = logging.getLogger("trad_account")

from app.database import get_db
from app.auth import require_write
from app.routers.ledgers import get_ledger_id
from app.models.financial import OriginalDocument

router = APIRouter()


@router.post("/upload-invoices")
async def upload_invoices(files: List[UploadFile] = File(...), db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    from app.ocr import process_invoice_with_ai, extract_structured_data_from_pdf

    upload_dir = os.path.abspath(os.path.join("uploads", "invoices"))
    os.makedirs(upload_dir, exist_ok=True)

    results: list = []

    for file in files:
        if file.filename is None or not file.filename.lower().endswith(".pdf"):
            results.append({"filename": file.filename or "unknown", "status": "error", "message": "Only PDF allowed"})
            continue

        safe_filename = f"{uuid.uuid4().hex}.pdf"
        file_path = os.path.join(upload_dir, safe_filename)

        try:
            with db.begin_nested():
                content = await file.read()
                if len(content) > 20 * 1024 * 1024:
                    results.append({"filename": file.filename, "status": "error", "message": "File too large (max 20MB)"})
                    continue
                if not content.startswith(b"%PDF"):
                    results.append({"filename": file.filename, "status": "error", "message": "Invalid PDF file (bad magic bytes)"})
                    continue
                with open(file_path, "wb") as buffer:
                    buffer.write(content)

                ocr_res = extract_structured_data_from_pdf(file_path)

                if ocr_res["status"] != "success":
                    results.append({"filename": file.filename, "status": "error", "message": ocr_res.get("message")})
                    continue

                raw_markdown = ocr_res["raw_markdown"]
                ai_result = process_invoice_with_ai(raw_markdown)

                if ai_result["status"] == "success":
                    doc = OriginalDocument(ledger_id=ledger_id, doc_type="INVOICE",
                        file_path=file_path, extracted_data=ai_result["data"])
                    db.add(doc)
                    db.flush()
                    results.append({
                        "filename": file.filename, "status": "success", "doc_id": doc.id,
                        "vendor_name": ai_result["data"].get("vendor_name", ""),
                        "items": ai_result["data"].get("items", [])
                    })
                else:
                    results.append({"filename": file.filename, "status": "error", "message": ai_result.get("message")})

        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"filename": file.filename, "status": "error", "message": f"Server Error: {str(e)}"})

    db.commit()
    return {"status": "success", "processed_files": results}


@router.post("/upload-statements")
async def upload_statements(files: List[UploadFile] = File(...), db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), _: None = Depends(require_write)):
    import pandas as pd
    from app.ocr import _detect_csv_columns_with_ai

    upload_dir = os.path.abspath(os.path.join("uploads", "statements"))
    os.makedirs(upload_dir, exist_ok=True)

    results: list = []

    for file in files:
        fname = (file.filename or "").lower()
        if not (fname.endswith(".csv") or fname.endswith(".xlsx") or fname.endswith(".xls") or fname.endswith(".txt")):
            results.append({"filename": file.filename, "status": "error", "message": "Only CSV/XLSX/XLS/TXT allowed"})
            continue

        try:
            with db.begin_nested():
                content = await file.read()
                if len(content) > 20 * 1024 * 1024:
                    results.append({"filename": file.filename, "status": "error", "message": "File too large (max 20MB)"})
                    continue
                if fname.endswith(".xlsx") and not (content[:2] == b"PK"):
                    results.append({"filename": file.filename, "status": "error", "message": "Invalid XLSX file"})
                    continue
                if fname.endswith(".xls") and not (content[:4] == b"\xd0\xcf\x11\xe0"):
                    results.append({"filename": file.filename, "status": "error", "message": "Invalid XLS file"})
                    continue

                if fname.endswith(".xlsx") or fname.endswith(".xls"):
                    df = pd.read_excel(io.BytesIO(content))
                else:
                    try:
                        csv_str = content.decode("utf-8")
                    except UnicodeDecodeError:
                        csv_str = content.decode("gbk", errors="ignore")
                    df = pd.read_csv(io.StringIO(csv_str))

                if df.empty or len(df.columns) == 0:
                    results.append({"filename": file.filename, "status": "error", "message": "Empty or unparseable file"})
                    continue

                sample_df = df.head(5)
                sample_csv = sample_df.to_csv(index=False)
                ai_result = _detect_csv_columns_with_ai(sample_csv)

                if ai_result["status"] != "success":
                    results.append({"filename": file.filename, "status": "error", "message": ai_result.get("message", "AI column detection failed")})
                    continue

                mapping = ai_result["mapping"]
                bank_name = mapping.get("bank_name", "")

                col_map = {}
                df_cols = list(df.columns)
                for key in ["date_col", "amount_col", "counterpart_col", "remarks_col"]:
                    target = mapping.get(key, "")
                    if not target:
                        continue
                    if target in df_cols:
                        col_map[key] = target
                    else:
                        target_lower = target.lower()
                        for c in df_cols:
                            if target_lower in c.lower():
                                col_map[key] = c
                                break

                transactions = []
                skip = mapping.get("skip_header_rows", 0)
                for idx, row in df.iterrows():
                    if idx < skip:
                        continue

                    def _cell(k):
                        if k not in col_map:
                            return ""
                        val = row[col_map[k]]
                        if pd.isna(val):
                            return ""
                        return str(val).strip()

                    date_str = _cell("date_col")
                    date_clean = re.sub(r'[^\d\-/]', '', date_str)
                    if re.match(r'^\d{8}$', date_clean):
                        date_clean = f"{date_clean[:4]}-{date_clean[4:6]}-{date_clean[6:]}"

                    counterpart = _cell("counterpart_col")
                    remarks = _cell("remarks_col")

                    amount_str = _cell("amount_col")
                    amount = D("0")
                    if "|" in amount_str:
                        debit_col, credit_col = amount_str.split("|", 1)
                        debit_str = str(row.get(debit_col.strip(), "")).strip() if debit_col.strip() in df_cols else ""
                        credit_str = str(row.get(credit_col.strip(), "")).strip() if credit_col.strip() in df_cols else ""
                        try:
                            debit_val = D(debit_str) if debit_str else D("0")
                        except Exception:
                            debit_val = D("0")
                        try:
                            credit_val = D(credit_str) if credit_str else D("0")
                        except Exception:
                            credit_val = D("0")
                        if debit_val > 0:
                            amount = debit_val
                        elif credit_val > 0:
                            amount = -credit_val
                    else:
                        try:
                            amount = D(amount_str.replace(",", "")) if amount_str else D("0")
                        except Exception:
                            amount = D("0")

                    if date_clean and counterpart and abs(amount) > D("0.001"):
                        transactions.append({
                            "transaction_date": date_clean,
                            "counterpart_name": counterpart,
                            "amount": str(amount),
                            "remarks": remarks,
                        })

                if not transactions:
                    results.append({"filename": file.filename, "status": "error", "message": "No valid transactions found in file"})
                    continue

                extension = os.path.splitext(file.filename)[1]
                safe_filename = f"{uuid.uuid4().hex}{extension}"
                doc = OriginalDocument(ledger_id=ledger_id, doc_type="BANK_STATEMENT",
                    file_path=safe_filename,
                    extracted_data={"bank_name": bank_name, "transactions": transactions})
                db.add(doc)
                db.flush()

            results.append({
                "filename": file.filename, "status": "success", "doc_id": doc.id,
                "bank_name": bank_name, "transaction_count": len(transactions),
            })

        except Exception:
            logger.exception("upload_statements error for file: %s", file.filename)
            results.append({"filename": file.filename, "status": "error", "message": "Processing failed. Please try again or contact support."})

    db.commit()
    return {"status": "success", "processed_files": results}
