"""Accounting rule validation for AI-generated and template vouchers.

Enforces 中小企业会计准则 (Accounting Standards for SMEs). All rules are
applied before commit; ERROR-level violations cause rollback, WARNING-level
are logged but allow the voucher to proceed.

ponytail: flat list of functions, no registry abstraction needed yet.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.financial import (
    Account, AccountType, AccountDirection,
    OriginalDocument, VoucherEntry,
)

logger = logging.getLogger("trad_account")

VAT_INPUT_CODE = "222101"
VAT_OUTPUT_CODE = "222102"


@dataclass
class RuleViolation:
    rule: str
    severity: str  # "error" | "warning"
    message: str


def validate_voucher(
    db: Session,
    ledger_id: int,
    debit_entries: list[dict],
    credit_entries: list[dict],
    source_doc_ids: list[int] | None = None,
) -> list[RuleViolation]:
    """Run all accounting rules. Returns list of violations (empty = clean)."""
    violations: list[RuleViolation] = []

    violations.extend(_check_debit_credit_balance(debit_entries, credit_entries))
    violations.extend(_check_account_direction(db, ledger_id, debit_entries, credit_entries))
    violations.extend(_check_payable_hierarchy(db, ledger_id, credit_entries))

    if source_doc_ids:
        violations.extend(_check_no_duplicate_docs(db, source_doc_ids))

    return violations


# --- R1: 价税分离 ---

def check_vat_split(
    ocr_items: list[dict],
    debit_entries: list[dict],
) -> list[RuleViolation]:
    """R1: OCR items with tax_amount > 0 must have matching VAT entries."""
    violations: list[RuleViolation] = []

    for item in ocr_items:
        raw_tax = str(item.get("tax_amount", "0")).strip() or "0"
        try:
            tax_amt = Decimal(raw_tax)
        except Exception:
            tax_amt = Decimal("0.00")

        if tax_amt <= 0:
            continue

        item_name = item.get("item_name", "?")

        # Find the VAT entry matching this item
        vat_found = False
        for de in debit_entries:
            code = de.get("account_code", "")
            if code == VAT_INPUT_CODE:
                summary = de.get("summary", "")
                if item_name in summary:
                    vat_found = True
                    if abs(de["amount"] - tax_amt) > Decimal("0.01"):
                        violations.append(RuleViolation(
                            rule="vat_split",
                            severity="error",
                            message=f"进项税额金额不匹配: {item_name} 的税额应为 {tax_amt}, "
                                    f"实际 {de['amount']}",
                        ))
                    break

        if not vat_found:
            violations.append(RuleViolation(
                rule="vat_split",
                severity="error",
                message=f"商品 \"{item_name}\" 含增值税 {tax_amt} 元，但未生成对应的 "
                        f"应交税费-进项税额(222101) 分录。请重试。",
            ))

    return violations


# --- R2: 应付/应收账款 = 价税合计 ---

def check_payable_amount(
    credit_entries: list[dict],
    ocr_total: Decimal,
) -> list[RuleViolation]:
    """R2: 应付账款(2202) credit total must equal 含税 invoice total."""
    payable_total = sum(
        e["amount"] for e in credit_entries
        if str(e.get("account_code", "")).startswith("2202")
    )

    if payable_total > 0 and abs(payable_total - ocr_total) > Decimal("0.01"):
        return [RuleViolation(
            rule="payable_amount",
            severity="error",
            message=f"应付账款金额 {payable_total} 不等于发票含税总金额 {ocr_total}。"
                    f"应付账款必须为价税合计。",
        )]
    return []


# --- R3: 借贷平衡 ---

def _check_debit_credit_balance(
    debit_entries: list[dict],
    credit_entries: list[dict],
) -> list[RuleViolation]:
    """R3: Total debits must equal total credits."""
    total_debit = sum(e["amount"] for e in debit_entries)
    total_credit = sum(e["amount"] for e in credit_entries)

    if abs(total_debit - total_credit) > Decimal("0.01"):
        return [RuleViolation(
            rule="debit_credit_balance",
            severity="error",
            message=f"借贷不平衡: 借方合计 {total_debit}, 贷方合计 {total_credit}, "
                    f"差额 {abs(total_debit - total_credit)}",
        )]
    return []


# --- R4: 应付/应收账款层级 ---

def _check_payable_hierarchy(
    db: Session,
    ledger_id: int,
    credit_entries: list[dict],
) -> list[RuleViolation]:
    """R4: 2202/1122 entries must have 3-level account structure (>= 8 digits)."""
    violations: list[RuleViolation] = []

    for ce in credit_entries:
        code = str(ce.get("account_code", ""))
        if not (code.startswith("2202") or code.startswith("1122")):
            continue
        if len(code) < 8:
            violations.append(RuleViolation(
                rule="payable_hierarchy",
                severity="error",
                message=f"科目 {code} 必须下钻到三级（至少8位）。"
                        f"应付/应收账款不允许直接挂一级科目。",
            ))
        else:
            # Verify parent chain exists
            parent_code = code[:6]
            grandparent_code = code[:4]
            existing = {
                c.code for c in db.query(Account).filter(
                    Account.ledger_id == ledger_id,
                    Account.code.in_([code, parent_code, grandparent_code]),
                ).all()
            }
            for needed in [grandparent_code, parent_code]:
                if needed not in existing:
                    violations.append(RuleViolation(
                        rule="payable_hierarchy",
                        severity="error",
                        message=f"科目 {code} 的父级科目 {needed} 不存在。",
                    ))

    return violations


# --- R5: 科目方向合规 ---

def _check_account_direction(
    db: Session,
    ledger_id: int,
    debit_entries: list[dict],
    credit_entries: list[dict],
) -> list[RuleViolation]:
    """R5: Warn if entry direction contradicts account's normal balance direction."""
    codes: set[str] = set()
    for e in debit_entries:
        codes.add(str(e.get("account_code", "")))
    for e in credit_entries:
        codes.add(str(e.get("account_code", "")))

    accounts = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.code.in_(codes)
    ).all()
    acct_map = {a.code: a for a in accounts}

    # Normal direction: ASSET/COST → DEBIT, LIABILITY/EQUITY → CREDIT, PROFIT_LOSS varies
    normal_debit = {AccountType.ASSET, AccountType.COST}

    violations: list[RuleViolation] = []

    for de in debit_entries:
        code = str(de.get("account_code", ""))
        acct = acct_map.get(code)
        if acct and acct.account_type not in normal_debit and acct.account_type == AccountType.LIABILITY:
            violations.append(RuleViolation(
                rule="account_direction",
                severity="warning",
                message=f"科目 {code} {acct.name} 为负债类，通常为贷方科目。"
                        f"当前为借方 {de['amount']} 元，请确认是否为特殊业务。",
            ))

    for ce in credit_entries:
        code = str(ce.get("account_code", ""))
        acct = acct_map.get(code)
        if acct and acct.account_type in normal_debit:
            violations.append(RuleViolation(
                rule="account_direction",
                severity="warning",
                message=f"科目 {code} {acct.name} 为资产/成本类，通常为借方科目。"
                        f"当前为贷方 {ce['amount']} 元，请确认是否为特殊业务。",
            ))

    return violations


# --- R6: 不重复生成 ---

def _check_no_duplicate_docs(
    db: Session,
    doc_ids: list[int],
) -> list[RuleViolation]:
    """R6: Same document IDs must not be used to generate duplicate vouchers."""
    reconciled = (
        db.query(OriginalDocument.id)
        .filter(
            OriginalDocument.id.in_(doc_ids),
            OriginalDocument.is_reconciled == True,
        )
        .all()
    )
    reconciled_ids = {r[0] for r in reconciled}
    if reconciled_ids:
        return [RuleViolation(
            rule="no_duplicate_docs",
            severity="error",
            message=f"以下文档已生成过凭证，不能重复生成: {sorted(reconciled_ids)}",
        )]
    return []
