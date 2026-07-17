"""Shared Pydantic schemas and helper functions for voucher modules."""

import time
import random
import logging
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer
from sqlalchemy.orm import Session
from sqlalchemy import func, Integer
from typing import List, Optional
from datetime import date
from decimal import Decimal

logger = logging.getLogger("trad_account")
from app.types import Money

from app.database import get_db
from app.auth import require_write
from app.routers.ledgers import get_ledger_id
from app.models.financial import (
    Voucher,
    VoucherEntry,
    Account,
    VoucherStatus,
    AccountDirection,
    OriginalDocument,
    Ledger,
)

MAX_VOUCHER_AMOUNT = Decimal("999999999.99")


# --- Pydantic models ---

class AIDebitEntrySchema(BaseModel):
    account_code: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    amount: Decimal = Field(gt=0, le=MAX_VOUCHER_AMOUNT)
    item_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=50)
    vendor: str = Field(default="", max_length=200)


class AIVoucherResponseSchema(BaseModel):
    debit_entries: list[AIDebitEntrySchema] = Field(min_length=1, max_length=200)
    credit_code: str = Field(default="2202", min_length=4, max_length=4, pattern=r"^\d{4}$")


class VoucherEntrySchema(BaseModel):
    account_code: str
    summary: str
    direction: str  # '借' or '贷'
    amount: Money
    currency_code: str = "CNY"
    original_amount: Optional[Decimal] = None
    exchange_rate: Decimal = Decimal("1.0000")
    partner_id: Optional[int] = None

    @field_validator("direction")
    def check_direction(cls, v):
        if v not in ["借", "贷"]:
            raise ValueError("Direction must be 借 or 贷")
        return v

    @field_validator("amount")
    def check_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class VoucherCreate(BaseModel):
    voucher_date: date
    voucher_number: Optional[str] = None
    attachments_count: int = 0
    contract_number: Optional[str] = None
    entries: List[VoucherEntrySchema]


class VoucherUpdate(BaseModel):
    entries: List[VoucherEntrySchema]


class AccountSchema(BaseModel):
    id: int
    code: str
    name: str
    model_config = ConfigDict(from_attributes=True)


class VoucherEntryResponse(BaseModel):
    id: int
    account_id: int
    account: AccountSchema
    summary: str
    direction: str
    amount: Money
    currency_code: str
    original_amount: Optional[Decimal] = None
    exchange_rate: Decimal
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("direction")
    def serialize_direction(self, value: str, _info) -> str:
        return {"DEBIT": "借", "CREDIT": "贷"}.get(value, value)


class VoucherResponse(BaseModel):
    id: int
    voucher_number: str
    voucher_date: date
    status: str
    contract_number: Optional[str] = None
    entries: List[VoucherEntryResponse] = []
    model_config = ConfigDict(from_attributes=True)


class BatchVoucherRequest(BaseModel):
    voucher_ids: List[int]

    @field_validator("voucher_ids")
    def check_voucher_ids(cls, v):
        if not v:
            raise ValueError("voucher_ids must not be empty")
        if len(v) > 200:
            raise ValueError("Batch limit is 200 vouchers")
        return v


class BatchGenerateRequest(BaseModel):
    doc_ids: list[int]


class ReconciliationMatchRequest(BaseModel):
    statement_item_id: int
    invoice_item_id: int
    discrepancy_amount: Money = Decimal("0")
    discrepancy_type: str = "bank_fee"


class VoucherResponsePage(BaseModel):
    items: List[VoucherResponse]
    total: int
    page: int
    page_size: int


# --- Helper functions ---

def _get_llm_config_for_ledger(db: Session, ledger_id: int) -> "LLMConfig":
    from app.llm import LLMConfig
    import os
    import logging as _logging
    _logger = _logging.getLogger("trad_account")

    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    api_key = ""
    provider = "deepseek"
    model_name = "deepseek-chat"
    base_url = None

    if ledger and ledger.llm_api_key:
        api_key = ledger.llm_api_key
        provider = ledger.llm_provider or provider
        model_name = ledger.llm_model_name or model_name
        base_url = ledger.llm_base_url
    else:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if api_key:
            _logger.warning(
                "Ledger %d has no LLM API key configured, using global env var fallback", ledger_id
            )

    return LLMConfig(provider=provider, api_key=api_key, model_name=model_name, base_url=base_url)


def _batch_resolve_accounts(db: Session, ledger_id: int, codes: set[str]) -> dict[str, Account]:
    if not codes:
        return {}
    accounts = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code.in_(codes)).all()
    return {a.code: a for a in accounts}


def _ensure_account_chain(db: Session, ledger_id: int, code: str, name: str, account_type, direction) -> Account:
    existing = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.code == code
    ).first()
    if existing:
        return existing

    name_parts = name.split("-")
    levels: list[tuple[str, str]] = []

    code_len = len(code)
    if code_len >= 8:
        levels = [
            (code[:4], "-".join(name_parts[:1]) if len(name_parts) >= 1 else name),
            (code[:6], "-".join(name_parts[:2]) if len(name_parts) >= 2 else name),
            (code, name),
        ]
    elif code_len == 6:
        levels = [
            (code[:4], "-".join(name_parts[:1]) if len(name_parts) >= 1 else name),
            (code, name),
        ]
    else:
        levels = [(code, name)]

    parent = None
    for level_idx, (lvl_code, lvl_name) in enumerate(levels):
        existing_lvl = db.query(Account).filter(
            Account.ledger_id == ledger_id, Account.code == lvl_code
        ).first()
        if existing_lvl:
            parent = existing_lvl
            continue

        if level_idx == 0:
            raise HTTPException(
                status_code=400,
                detail=f"根级科目 {lvl_code} 不存在，请先在科目设置中创建该科目。",
            )

        new_acct = Account(
            ledger_id=ledger_id,
            code=lvl_code,
            name=lvl_name,
            account_type=parent.account_type if parent else account_type,
            balance_direction=parent.balance_direction if parent else direction,
            parent_id=parent.id if parent else None,
            opening_balance=0,
        )
        db.add(new_acct)
        db.flush()
        parent = new_acct

    assert parent is not None
    return parent


def _ensure_child_account(db: Session, ledger_id: int, parent: Account, name: str) -> Account:
    existing = db.query(Account).filter(
        Account.ledger_id == ledger_id,
        Account.parent_id == parent.id,
        Account.name == name,
    ).first()
    if existing:
        return existing

    siblings = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.parent_id == parent.id
    ).all()
    max_suffix = 0
    for sib in siblings:
        try:
            suffix = int(sib.code[len(parent.code):])
            if suffix > max_suffix:
                max_suffix = suffix
        except (ValueError, IndexError):
            pass
    new_suffix = str(max_suffix + 1).zfill(2)

    new_acct = Account(
        ledger_id=ledger_id,
        code=parent.code + new_suffix,
        name=name,
        account_type=parent.account_type,
        balance_direction=parent.balance_direction,
        parent_id=parent.id,
        opening_balance=0,
    )
    db.add(new_acct)
    db.flush()
    return new_acct


def _build_3level_debit_account(db: Session, ledger_id: int, root_code: str, category: str, item_name: str) -> Account:
    root = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.code == root_code
    ).first()
    if not root:
        raise HTTPException(
            status_code=400,
            detail=f"根级科目 {root_code} 不存在，请先在科目设置中创建该科目。",
        )
    l2_name = f"{root.name}-{category}"
    l2 = _ensure_child_account(db, ledger_id, root, l2_name)
    l3_name = f"{l2.name}-{item_name}"
    return _ensure_child_account(db, ledger_id, l2, l3_name)


def _extract_city(vendor_name: str) -> str:
    """Extract city name from a Chinese company name.

    Chinese company names typically start with the city (2-4 chars).
    Examples: 临沂华威 → 临沂, 石家庄xx → 石家庄, 乌鲁木齐xx → 乌鲁木齐
    """
    four_char = {"乌鲁木齐", "呼和浩特", "齐齐哈尔"}
    three_char = {"石家庄", "张家口", "连云港", "秦皇岛", "驻马店", "三门峡", "佳木斯"}
    if len(vendor_name) >= 4 and vendor_name[:4] in four_char:
        return vendor_name[:4]
    if len(vendor_name) >= 3 and vendor_name[:3] in three_char:
        return vendor_name[:3]
    if len(vendor_name) >= 2:
        return vendor_name[:2]
    return vendor_name


def _build_vendor_account(db: Session, ledger_id: int, root_code: str, vendor_name: str) -> Account:
    """Build a 3-level accounts payable account: 2202 → city → vendor.

    Example: 2202 (应付账款) → 220201 (应付账款-临沂) → 22020101 (应付账款-临沂-临沂华威工具制造有限公司)
    """
    root = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.code == root_code
    ).first()
    if not root:
        raise HTTPException(
            status_code=400,
            detail=f"根级科目 {root_code} 不存在，请先在科目设置中创建该科目。",
        )
    city = _extract_city(vendor_name)
    l2_name = f"{root.name}-{city}"
    l2 = _ensure_child_account(db, ledger_id, root, l2_name)
    l3_name = f"{l2.name}-{vendor_name}"
    return _ensure_child_account(db, ledger_id, l2, l3_name)


def _infer_category(item_name: str) -> str:
    keywords = {
        "金属": "金属制品", "钢": "金属制品", "铁": "金属制品", "铝": "金属制品",
        "电子": "电子元件", "电器": "电子元件", "芯片": "电子元件",
        "塑料": "塑料制品", "橡胶": "橡胶制品",
        "纺织": "纺织制品", "服装": "纺织制品",
        "化工": "化工原料", "食品": "食品饮料",
        "办公": "办公用品", "纸": "办公用品",
        "家具": "家具设备",
        "配件": "机械配件", "零件": "机械配件",
    }
    for kw, cat in keywords.items():
        if kw in item_name:
            return cat
    return "一般商品"


def _call_llm_with_retry(prompt: str, config: "LLMConfig", max_retries: int = 3) -> str:
    from app.llm import get_llm_response

    last_error = None
    for attempt in range(max_retries):
        try:
            return get_llm_response(
                prompt=prompt, config=config, response_format={"type": "json_object"}
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries, delay, e,
                )

    logger.error("LLM call failed after %d attempts: %s", max_retries, last_error)
    raise RuntimeError(
        f"AI 服务暂时不可用（已重试 {max_retries} 次），请稍后再试。"
    ) from last_error


def get_next_voucher_number(db: Session, ledger_id: int, prefix: str = "记-") -> str:
    from app.models.financial import VoucherNumberCounter
    from sqlalchemy.exc import IntegrityError

    max_retries = 20
    for attempt in range(max_retries):
        try:
            counter = db.query(VoucherNumberCounter).filter(
                VoucherNumberCounter.ledger_id == ledger_id,
                VoucherNumberCounter.prefix == prefix,
            ).with_for_update().first()

            if counter:
                counter.current_number += 1
            else:
                logger.warning("Auto-healing missing VoucherNumberCounter for ledger=%s prefix=%s", ledger_id, prefix)
                max_num = db.query(
                    func.max(func.cast(func.substr(Voucher.voucher_number, len(prefix) + 1), Integer))
                ).filter(Voucher.ledger_id == ledger_id, Voucher.voucher_number.like(f"{prefix}%")).scalar()
                next_num = (max_num or 0) + 1
                counter = VoucherNumberCounter(ledger_id=ledger_id, prefix=prefix, current_number=next_num)
                db.add(counter)

            db.flush()
            return f"{prefix}{counter.current_number}"
        except IntegrityError:
            # After an IntegrityError the SQLAlchemy Session enters a "broken"
            # state where any further statements raise until rollback() is
            # called. Without this rollback, every subsequent retry attempt
            # would silently re-raise the same error and burn through all
            # retries in microseconds, then bubble up to the caller.
            db.rollback()
            if attempt < max_retries - 1:
                time.sleep(random.uniform(0.05, 0.2))
                continue
            raise


def _match_ai_entries_to_ocr(
    ai_entries: list[AIDebitEntrySchema],
    ocr_items: list[dict],
) -> list[tuple[AIDebitEntrySchema, dict]]:
    """Match AI-classified entries to OCR items by vendor + fuzzy item name.

    Returns a list of (ai_entry, ocr_item) pairs in the same order as ocr_items.
    Raises HTTPException if any OCR item cannot be matched.
    """
    unmatched_ocr = list(ocr_items)
    result: list[tuple[AIDebitEntrySchema, dict]] = []

    for ocr_item in ocr_items:
        ocr_name = str(ocr_item.get("item_name", "")).strip()
        ocr_vendor = str(ocr_item.get("_vendor", "")).strip()

        best: AIDebitEntrySchema | None = None
        best_score = 0

        for ai in ai_entries:
            ai_name = (ai.item_name or "").strip()
            ai_vendor = (ai.vendor or "").strip()

            if ocr_vendor and ai_vendor and ocr_vendor != ai_vendor:
                continue

            score = 0
            if ai_name and ocr_name:
                if ai_name == ocr_name:
                    score = 100
                elif ai_name in ocr_name or ocr_name in ai_name:
                    score = 80

            if score > best_score:
                best_score = score
                best = ai

        if best is None or best_score == 0:
            raise HTTPException(
                status_code=400,
                detail=f"AI 返回的商品 \"{ocr_name}\" 与 OCR 数据无法匹配，请重试。",
            )
        result.append((best, ocr_item))

    return result


def _process_ai_debit_entries(
    db: Session,
    ledger_id: int,
    matched: list[tuple[AIDebitEntrySchema, dict]],
    voucher_id: int,
) -> tuple[Decimal, list[dict]]:
    """Create debit-side voucher entries from matched AI-OCR pairs.

    Handles VAT splitting: if ocr_item has tax_amount > 0, splits into
    goods amount (tax-exclusive) and VAT input (222101).

    Returns (total_debit, debit_entry_dicts) where each dict has
    account_code, amount, summary for rule validation.
    """
    VAT_INPUT_CODE = "222101"
    total_debit = Decimal("0.00")
    debit_entries: list[dict] = []

    for ai_entry, ocr_item in matched:
        root_code = ai_entry.account_code
        item_name = ai_entry.item_name
        vendor = ai_entry.vendor or ocr_item.get("_vendor", "")
        category = ai_entry.category or _infer_category(item_name)

        # Amount from OCR, NOT from AI
        raw_amount = str(ocr_item.get("amount", "0")).strip() or "0"
        try:
            amt = Decimal(raw_amount)
        except Exception:
            amt = Decimal("0.00")

        if amt <= 0:
            continue

        raw_tax = str(ocr_item.get("tax_amount", "0")).strip() or "0"
        try:
            tax_amt = Decimal(raw_tax)
        except Exception:
            tax_amt = Decimal("0.00")

        if tax_amt > 0 and tax_amt < amt:
            tax_exclusive = amt - tax_amt
            summary = _build_item_summary(ocr_item, vendor)
            acct = _build_3level_debit_account(db, ledger_id, root_code, category, item_name)
            db.add(VoucherEntry(
                voucher_id=voucher_id, account_id=acct.id, summary=summary,
                direction=AccountDirection.DEBIT, amount=tax_exclusive,
            ))
            total_debit += tax_exclusive
            debit_entries.append({"account_code": acct.code, "amount": tax_exclusive, "summary": summary})

            vat_acct = _ensure_account_chain(
                db, ledger_id, VAT_INPUT_CODE,
                "应交税费-应交增值税-进项税额",
                acct.account_type, acct.balance_direction,
            )
            db.add(VoucherEntry(
                voucher_id=voucher_id, account_id=vat_acct.id,
                summary=f"进项税额 - {summary}",
                direction=AccountDirection.DEBIT, amount=tax_amt,
            ))
            total_debit += tax_amt
            debit_entries.append({"account_code": VAT_INPUT_CODE, "amount": tax_amt, "summary": f"进项税额 - {summary}"})
        else:
            summary = _build_item_summary(ocr_item, vendor)
            acct = _build_3level_debit_account(db, ledger_id, root_code, category, item_name)
            db.add(VoucherEntry(
                voucher_id=voucher_id, account_id=acct.id, summary=summary,
                direction=AccountDirection.DEBIT, amount=amt,
            ))
            total_debit += amt
            debit_entries.append({"account_code": acct.code, "amount": amt, "summary": summary})

    return total_debit, debit_entries


def _build_item_summary(item: dict, vendor: str) -> str:
    """Build voucher entry summary from OCR item data."""
    name = item.get("item_name", "")
    qty = str(item.get("quantity", "")).strip()
    spec = str(item.get("specification", "")).strip()

    parts = [name]
    if qty and qty != "0":
        parts.append(f"×{qty}")
        if spec and spec != name:
            parts.append(spec)
    elif spec and spec != name:
        parts.append(spec)

    base = " ".join(parts)
    if vendor:
        base += f" ({vendor})"
    return base
