"""Tests for accounting rule validation (R1-R6)."""

from decimal import Decimal

from app.services.voucher_rules import (
    validate_voucher, RuleViolation,
    check_vat_split, check_payable_amount,
)
from app.models.financial import (
    Account, AccountType, AccountDirection,
    OriginalDocument,
)


class TestDebitCreditBalance:
    """R3: Total debits must equal total credits."""

    def test_balanced_passes(self, db, ledger):
        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "1002", "amount": Decimal("1000")}],
            [{"account_code": "2202", "amount": Decimal("1000")}],
        )
        assert not any(v.rule == "debit_credit_balance" for v in violations)

    def test_unbalanced_fails(self, db, ledger):
        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "1002", "amount": Decimal("1200")}],
            [{"account_code": "2202", "amount": Decimal("1000")}],
        )
        errors = [v for v in violations if v.rule == "debit_credit_balance"]
        assert len(errors) == 1
        assert errors[0].severity == "error"

    def test_multi_entry_balance(self, db, ledger):
        violations = validate_voucher(
            db, ledger.id,
            [
                {"account_code": "1405", "amount": Decimal("800")},
                {"account_code": "222101", "amount": Decimal("200")},
            ],
            [{"account_code": "22020101", "amount": Decimal("1000")}],
        )
        assert not any(v.rule == "debit_credit_balance" for v in violations)


class TestAccountDirection:
    """R5: Warn if direction contradicts account type normal balance."""

    def test_debit_to_liability_warns(self, db, ledger):
        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "2202", "amount": Decimal("500")}],
            [{"account_code": "1002", "amount": Decimal("500")}],
        )
        warnings = [v for v in violations if v.rule == "account_direction"]
        assert len(warnings) >= 1
        assert all(w.severity == "warning" for w in warnings)

    def test_credit_to_asset_warns(self, db, ledger):
        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "2202", "amount": Decimal("500")}],
            [{"account_code": "1002", "amount": Decimal("500")}],
        )
        warnings = [v for v in violations if v.rule == "account_direction"]
        # 1002 is asset, credit to asset = warning
        has_asset_warning = any("1002" in w.message for w in warnings)
        assert has_asset_warning


class TestPayableHierarchy:
    """R4: 2202/1122 entries must have >= 8 digit codes with valid parent chain."""

    def test_short_code_fails(self, db, ledger):
        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "1002", "amount": Decimal("500")}],
            [{"account_code": "2202", "amount": Decimal("500")}],  # 4-digit fails
        )
        errors = [v for v in violations if v.rule == "payable_hierarchy"]
        assert len(errors) == 1
        assert errors[0].severity == "error"

    def test_8digit_code_passes(self, db, ledger):
        # Create parent chain: 2202 → 220201 → 22020101
        parent = db.query(Account).filter(Account.ledger_id == ledger.id, Account.code == "2202").first()
        l2 = Account(ledger_id=ledger.id, code="220201", name="应付账款-临沂",
                     account_type=parent.account_type, balance_direction=parent.balance_direction,
                     parent_id=parent.id, opening_balance=0)
        db.add(l2)
        db.flush()
        l3 = Account(ledger_id=ledger.id, code="22020101", name="应付账款-临沂-测试公司",
                     account_type=parent.account_type, balance_direction=parent.balance_direction,
                     parent_id=l2.id, opening_balance=0)
        db.add(l3)
        db.flush()

        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "1002", "amount": Decimal("500")}],
            [{"account_code": "22020101", "amount": Decimal("500")}],
        )
        errors = [v for v in violations if v.rule == "payable_hierarchy"]
        assert len(errors) == 0

    def test_6digit_code_fails(self, db, ledger):
        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "1002", "amount": Decimal("500")}],
            [{"account_code": "220201", "amount": Decimal("500")}],  # 6-digit < 8
        )
        errors = [v for v in violations if v.rule == "payable_hierarchy"]
        assert len(errors) >= 1


class TestVatSplit:
    """R1: OCR items with tax_amount must have matching 222101 VAT entry."""

    def test_item_with_tax_has_vat_entry(self):
        ocr_items = [
            {"item_name": "钢板", "amount": "1130", "tax_amount": "130"},
        ]
        debit_entries = [
            {"account_code": "1405", "amount": Decimal("1000"), "summary": "钢板"},
            {"account_code": "222101", "amount": Decimal("130"), "summary": "进项税额 - 钢板"},
        ]
        violations = check_vat_split(ocr_items, debit_entries)
        assert len(violations) == 0

    def test_item_with_tax_missing_vat_entry(self):
        ocr_items = [
            {"item_name": "钢板", "amount": "1130", "tax_amount": "130"},
        ]
        debit_entries = [
            {"account_code": "1405", "amount": Decimal("1130"), "summary": "钢板"},
        ]
        violations = check_vat_split(ocr_items, debit_entries)
        errors = [v for v in violations if v.rule == "vat_split"]
        assert len(errors) == 1
        assert errors[0].severity == "error"

    def test_vat_amount_mismatch(self):
        ocr_items = [
            {"item_name": "钢管", "amount": "2260", "tax_amount": "260"},
        ]
        debit_entries = [
            {"account_code": "1405", "amount": Decimal("2000"), "summary": "钢管"},
            {"account_code": "222101", "amount": Decimal("200"), "summary": "进项税额 - 钢管"},  # should be 260
        ]
        violations = check_vat_split(ocr_items, debit_entries)
        errors = [v for v in violations if v.rule == "vat_split"]
        assert len(errors) == 1

    def test_item_without_tax_no_vat_needed(self):
        ocr_items = [
            {"item_name": "办公用品", "amount": "500", "tax_amount": "0"},
        ]
        debit_entries = [
            {"account_code": "6602", "amount": Decimal("500"), "summary": "办公用品"},
        ]
        violations = check_vat_split(ocr_items, debit_entries)
        assert len(violations) == 0

    def test_vat_entry_matched_by_item_name_in_summary(self):
        ocr_items = [
            {"item_name": "铝板", "amount": "5650", "tax_amount": "650"},
        ]
        debit_entries = [
            {"account_code": "1405", "amount": Decimal("5000"), "summary": "铝板 x100"},
            {"account_code": "222101", "amount": Decimal("650"), "summary": "进项税额 - 铝板 x100 (供应商A)"},
        ]
        violations = check_vat_split(ocr_items, debit_entries)
        assert len(violations) == 0


class TestPayableAmount:
    """R2: 2202 payable credit total must equal tax-inclusive invoice total."""

    def test_payable_matches_ocr_total(self):
        credit_entries = [
            {"account_code": "22020101", "amount": Decimal("1130")},
        ]
        violations = check_payable_amount(credit_entries, Decimal("1130"))
        assert len(violations) == 0

    def test_payable_mismatch_fails(self):
        credit_entries = [
            {"account_code": "22020101", "amount": Decimal("1000")},  # missing tax
        ]
        violations = check_payable_amount(credit_entries, Decimal("1130"))
        errors = [v for v in violations if v.rule == "payable_amount"]
        assert len(errors) == 1
        assert errors[0].severity == "error"

    def test_multi_vendor_payable(self):
        credit_entries = [
            {"account_code": "22020101", "amount": Decimal("565")},
            {"account_code": "22020201", "amount": Decimal("565")},
        ]
        violations = check_payable_amount(credit_entries, Decimal("1130"))
        assert len(violations) == 0

    def test_non_2202_entries_ignored(self):
        credit_entries = [
            {"account_code": "22020101", "amount": Decimal("1000")},
            {"account_code": "1002", "amount": Decimal("100")},  # bank, ignored
        ]
        violations = check_payable_amount(credit_entries, Decimal("1000"))
        assert len(violations) == 0


class TestNoDuplicateDocs:
    """R6: Same document IDs must not be used to generate duplicate vouchers."""

    def test_unreconciled_docs_pass(self, db, ledger):
        doc = OriginalDocument(
            ledger_id=ledger.id,
            file_path="test_invoice.pdf",
            doc_type="INVOICE",
            is_reconciled=False,
        )
        db.add(doc)
        db.commit()

        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "1002", "amount": Decimal("500")}],
            [{"account_code": "22020101", "amount": Decimal("500")}],
            source_doc_ids=[doc.id],
        )
        errors = [v for v in violations if v.rule == "no_duplicate_docs"]
        assert len(errors) == 0

    def test_reconciled_docs_fail(self, db, ledger):
        doc = OriginalDocument(
            ledger_id=ledger.id,
            file_path="reconciled_invoice.pdf",
            doc_type="INVOICE",
            is_reconciled=True,
        )
        db.add(doc)
        db.commit()

        violations = validate_voucher(
            db, ledger.id,
            [{"account_code": "1002", "amount": Decimal("500")}],
            [{"account_code": "22020101", "amount": Decimal("500")}],
            source_doc_ids=[doc.id],
        )
        errors = [v for v in violations if v.rule == "no_duplicate_docs"]
        assert len(errors) == 1
        assert errors[0].severity == "error"
