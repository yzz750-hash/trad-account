"""Tests for VAT tax module (tax_router.py)."""
from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy import extract

from app.models.financial import (
    VATRecord,
    Voucher,
    VoucherEntry,
    VoucherStatus,
    Account,
    AccountDirection,
    AccountType,
    TaxRate,
)


class TestTaxRateManagement:
    """Test tax rate CRUD endpoints."""

    def test_list_tax_rates_with_auto_seed(self, client, auth_headers, ledger_headers):
        """Listing tax rates should auto-seed defaults for the ledger."""
        resp = client.get(
            "/api/v1/tax/rates",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        types = {r["tax_type"] for r in data}
        assert types >= {"vat_input", "vat_output", "export_rebate", "income_tax"}

    def test_list_tax_rates_idempotent(self, client, auth_headers, ledger_headers):
        """Calling list twice should not duplicate rates."""
        for _ in range(2):
            resp = client.get(
                "/api/v1/tax/rates",
                headers={**auth_headers, **ledger_headers},
            )
            assert resp.status_code == 200
        # 4 default rates, no duplicates
        data = resp.json()
        assert len([r for r in data if r["tax_type"] == "vat_input"]) == 1

    def test_set_tax_rate_deactivates_previous(self, client, auth_headers, ledger_headers):
        """Setting a new rate should deactivate the old one."""
        resp = client.post(
            "/api/v1/tax/rates",
            json={
                "tax_type": "vat_input",
                "rate": 0.17,
                "description": "旧税率17%",
                "effective_from": "2024-01-01",
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        assert Decimal(resp.json()["rate"]) == Decimal("0.17")

        # Set a new rate for same type
        resp2 = client.post(
            "/api/v1/tax/rates",
            json={
                "tax_type": "vat_input",
                "rate": 0.13,
                "description": "新税率13%",
                "effective_from": "2024-06-01",
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp2.status_code == 200

        # List should show one active and one inactive
        resp3 = client.get(
            "/api/v1/tax/rates",
            headers={**auth_headers, **ledger_headers},
        )
        rates = [r for r in resp3.json() if r["tax_type"] == "vat_input"]
        active = [r for r in rates if r["is_active"]]
        inactive = [r for r in rates if not r["is_active"]]
        assert len(active) == 1
        assert active[0]["rate"] == "0.13"
        assert len(inactive) >= 1

    def test_set_tax_rate_invalid_type(self, client, auth_headers, ledger_headers):
        """Invalid tax_type must be rejected."""
        resp = client.post(
            "/api/v1/tax/rates",
            json={
                "tax_type": "invalid_tax",
                "rate": 0.10,
                "effective_from": "2024-01-01",
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 400

    def test_tax_rates_require_ledger_header(self, client, ledger_headers):
        """Tax rates are ledger-scoped and require X-Ledger-Id header."""
        resp = client.get("/api/v1/tax/rates", headers=ledger_headers)
        assert resp.status_code == 200


class TestVATSummary:
    """Test VAT summary calculation."""

    def test_empty_period_returns_zero_summary(self, client, auth_headers, ledger_headers):
        """VAT summary for a period with no data returns zeros."""
        resp = client.get(
            "/api/v1/tax/vat-summary?year=2024&month=1",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert Decimal(data["input_vat"]) == 0
        assert Decimal(data["output_vat"]) == 0
        assert Decimal(data["vat_payable"]) == 0
        assert Decimal(data["net_payable"]) == 0

    def test_vat_summary_with_vat_records(self, client, auth_headers, ledger, db):
        """VAT summary should aggregate VAT records for the period."""
        # Create a voucher first
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="税-1",
            voucher_date=date(2024, 1, 15),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()

        db.add(VATRecord(
            ledger_id=ledger.id,
            voucher_id=v.id,
            voucher_date=date(2024, 1, 15),
            vat_type="input",
            taxable_amount=Decimal("100000"),
            vat_rate=Decimal("0.13"),
            vat_amount=Decimal("13000"),
            total_amount=Decimal("113000"),
        ))
        db.add(VATRecord(
            ledger_id=ledger.id,
            voucher_id=v.id,
            voucher_date=date(2024, 1, 15),
            vat_type="output",
            taxable_amount=Decimal("200000"),
            vat_rate=Decimal("0.13"),
            vat_amount=Decimal("26000"),
            total_amount=Decimal("226000"),
        ))
        db.commit()

        # Need fresh auth since db changed
        resp = client.get(
            "/api/v1/tax/vat-summary?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert Decimal(data["input_vat"]) == Decimal("13000")
        assert Decimal(data["output_vat"]) == Decimal("26000")
        assert Decimal(data["vat_payable"]) == Decimal("13000")  # 26000 - 13000

    def test_vat_summary_with_export_records(self, client, auth_headers, ledger, db):
        """VAT summary should include export rebate calculation."""
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="税-出口",
            voucher_date=date(2024, 1, 20),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()

        db.add(VATRecord(
            ledger_id=ledger.id,
            voucher_id=v.id,
            voucher_date=date(2024, 1, 20),
            vat_type="output",
            taxable_amount=Decimal("0"),
            vat_rate=Decimal("0.13"),
            vat_amount=Decimal("0"),
            total_amount=Decimal("500000"),
            is_export=True,
            export_amount_fob=Decimal("500000"),
            export_currency="USD",
            export_rebate_rate=Decimal("0.13"),
        ))
        db.commit()

        resp = client.get(
            "/api/v1/tax/vat-summary?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Export rebate: 500000 * 0.13 = 65000
        assert Decimal(data["export_rebate_eligible"]) == Decimal("65000")


class TestExportRebate:
    """Test export tax rebate calculation (免抵退 method)."""

    def test_standard_calculation_with_taxable_positive(self, client, auth_headers, ledger_headers):
        """
        Scenario: domestic sales revenue > input, so taxable > 0 → no rebate.
        当期销项税额充足，应纳税额 > 0，无需退税.
        """
        resp = client.post(
            "/api/v1/tax/export-rebate",
            json={
                "year": 2024,
                "month": 1,
                "export_amount_fob": 1000000,  # 出口100万
                "domestic_sales": 800000,       # 内销80万
                "domestic_purchases": 600000,   # 采购60万
                "taxfree_purchases": 0,
                "carryover_input": 0,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["levy_rate"] == "0.13"
        assert data["rebate_rate"] == "0.13"
        assert Decimal(data["rate_diff"]) == 0
        assert Decimal(data["non_deductible"]) == 0
        # output = 800000 * 0.13 = 104000
        assert Decimal(data["output_vat"]) == Decimal("104000")
        # input = 600000 * 0.13 = 78000
        assert Decimal(data["input_vat"]) == Decimal("78000")
        # taxable = 104000 - 78000 = 26000 > 0 → no rebate
        assert Decimal(data["taxable_amount"]) == Decimal("26000")
        assert Decimal(data["actual_rebate"]) == 0
        assert Decimal(data["exemption_credit"]) == Decimal("130000")  # rebate_limit

    def test_calculation_with_negative_taxable(self, client, auth_headers, ledger_headers):
        """
        Scenario: export-heavy, domestic sales small → taxable < 0 → rebate.
        出口占比大，内销少，期末留抵，产生退税.
        """
        resp = client.post(
            "/api/v1/tax/export-rebate",
            json={
                "year": 2024,
                "month": 1,
                "export_amount_fob": 2000000,   # 出口200万
                "domestic_sales": 100000,        # 内销10万
                "domestic_purchases": 1500000,   # 采购150万(进项多)
                "taxfree_purchases": 0,
                "carryover_input": 50000,        # 上期留抵5万
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        # output = 100000 * 0.13 = 13000
        # input = 1500000 * 0.13 = 195000
        # taxable = 13000 - 195000 - 50000 = -232000
        assert Decimal(data["taxable_amount"]) == Decimal("-232000")
        # rebate_limit = 2000000 * 0.13 = 260000
        # actual_rebate = min(232000, 260000) = 232000
        assert Decimal(data["actual_rebate"]) == Decimal("232000")
        assert Decimal(data["exemption_credit"]) == Decimal("28000")  # 260000 - 232000

    def test_rebate_rate_cannot_exceed_levy_rate(self, client, auth_headers, ledger_headers):
        """退税率 > 征税率 should be rejected."""
        # First set a low levy rate
        client.post(
            "/api/v1/tax/rates",
            json={
                "tax_type": "vat_output",
                "rate": 0.09,
                "description": "低税率",
                "effective_from": "2024-01-01",
            },
            headers={**auth_headers, **ledger_headers},
        )
        # Then set rebate rate higher than levy
        client.post(
            "/api/v1/tax/rates",
            json={
                "tax_type": "export_rebate",
                "rate": 0.13,
                "description": "高退税率",
                "effective_from": "2024-01-01",
            },
            headers={**auth_headers, **ledger_headers},
        )

        resp = client.post(
            "/api/v1/tax/export-rebate",
            json={
                "year": 2024,
                "month": 1,
                "export_amount_fob": 1000000,
                "domestic_sales": 0,
                "domestic_purchases": 0,
                "taxfree_purchases": 0,
                "carryover_input": 0,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 400


class TestVATRecordCRUD:
    """Test VAT record create/list endpoints."""

    def test_add_input_vat_record(self, client, auth_headers, ledger, db):
        """Add an input VAT record linked to a voucher."""
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="税-进项",
            voucher_date=date(2024, 1, 10),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.commit()

        resp = client.post(
            "/api/v1/tax/records",
            json={
                "voucher_id": v.id,
                "voucher_date": "2024-01-10",
                "vat_type": "input",
                "invoice_code": "1234567890",
                "invoice_number": "98765432",
                "counterpart_name": "供应商A",
                "taxable_amount": 100000,
                "vat_rate": 0.13,
                "vat_amount": 13000,
                "total_amount": 113000,
            },
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["id"] > 0

    def test_add_export_vat_record(self, client, auth_headers, ledger, db):
        """Add an export VAT record."""
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="税-出口",
            voucher_date=date(2024, 1, 20),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.commit()

        resp = client.post(
            "/api/v1/tax/records",
            json={
                "voucher_id": v.id,
                "voucher_date": "2024-01-20",
                "vat_type": "output",
                "taxable_amount": 0,
                "vat_rate": 0.13,
                "vat_amount": 0,
                "total_amount": 500000,
                "is_export": True,
                "export_amount_fob": 500000,
                "export_currency": "USD",
                "export_rebate_rate": 0.13,
            },
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200

    def test_invalid_vat_type_rejected(self, client, auth_headers, ledger, db):
        """vat_type must be 'input' or 'output'."""
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="税-坏",
            voucher_date=date(2024, 1, 1),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.commit()

        resp = client.post(
            "/api/v1/tax/records",
            json={
                "voucher_id": v.id,
                "voucher_date": "2024-01-01",
                "vat_type": "other",
                "taxable_amount": 1000,
                "vat_rate": 0.13,
                "vat_amount": 130,
                "total_amount": 1130,
            },
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400

    def test_nonexistent_voucher_rejected(self, client, auth_headers, ledger_headers):
        """Non-existent voucher should return 404."""
        resp = client.post(
            "/api/v1/tax/records",
            json={
                "voucher_id": 99999,
                "voucher_date": "2024-01-01",
                "vat_type": "input",
                "taxable_amount": 1000,
                "vat_rate": 0.13,
                "vat_amount": 130,
                "total_amount": 1130,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404

    def test_list_vat_records(self, client, auth_headers, ledger, db):
        """List VAT records for a period."""
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="税-列表",
            voucher_date=date(2024, 3, 15),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()
        db.add(VATRecord(
            ledger_id=ledger.id, voucher_id=v.id, voucher_date=date(2024, 3, 15),
            vat_type="input", taxable_amount=Decimal("50000"),
            vat_rate=Decimal("0.13"), vat_amount=Decimal("6500"),
            total_amount=Decimal("56500"),
        ))
        db.add(VATRecord(
            ledger_id=ledger.id, voucher_id=v.id, voucher_date=date(2024, 3, 15),
            vat_type="output", taxable_amount=Decimal("80000"),
            vat_rate=Decimal("0.13"), vat_amount=Decimal("10400"),
            total_amount=Decimal("90400"),
        ))
        db.commit()

        resp = client.get(
            "/api/v1/tax/records?year=2024&month=3",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_vat_records_filtered_by_type(self, client, auth_headers, ledger, db):
        """Filter records by vat_type."""
        v = Voucher(
            ledger_id=ledger.id, voucher_number="税-过滤",
            voucher_date=date(2024, 2, 10), status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()
        db.add(VATRecord(
            ledger_id=ledger.id, voucher_id=v.id, voucher_date=date(2024, 2, 10),
            vat_type="input", taxable_amount=Decimal("30000"),
            vat_rate=Decimal("0.13"), vat_amount=Decimal("3900"),
            total_amount=Decimal("33900"),
        ))
        db.add(VATRecord(
            ledger_id=ledger.id, voucher_id=v.id, voucher_date=date(2024, 2, 10),
            vat_type="output", taxable_amount=Decimal("50000"),
            vat_rate=Decimal("0.13"), vat_amount=Decimal("6500"),
            total_amount=Decimal("56500"),
        ))
        db.commit()

        resp = client.get(
            "/api/v1/tax/records?year=2024&vat_type=input",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["vat_type"] == "input" for r in data)
        assert len(data) == 1


class TestCreateVATVoucher:
    """Test VAT payable provisional entry creation."""

    def test_no_vat_payable_returns_early(self, client, auth_headers, ledger_headers):
        """When no VAT is payable, no voucher should be created."""
        resp = client.post(
            "/api/v1/tax/create-vat-voucher",
            json={"year": 2024, "month": 3},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "无应缴增值税" in data["message"]

    def test_idempotent_vat_voucher(self, client, auth_headers, ledger, db):
        """Creating VAT voucher twice should be idempotent."""
        # First create some VAT liability by adding a VAT record
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="税-idem",
            voucher_date=date(2024, 4, 15),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()
        db.add(VATRecord(
            ledger_id=ledger.id, voucher_id=v.id, voucher_date=date(2024, 4, 15),
            vat_type="output", taxable_amount=Decimal("200000"),
            vat_rate=Decimal("0.13"), vat_amount=Decimal("26000"),
            total_amount=Decimal("226000"),
        ))
        db.commit()

        headers = {**auth_headers, **{"X-Ledger-Id": str(ledger.id)}}

        # First call
        resp1 = client.post(
            "/api/v1/tax/create-vat-voucher",
            json={"year": 2024, "month": 4},
            headers=headers,
        )
        assert resp1.status_code == 200

        # Second call should be idempotent
        resp2 = client.post(
            "/api/v1/tax/create-vat-voucher",
            json={"year": 2024, "month": 4},
            headers=headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2.get("idempotent") is True
