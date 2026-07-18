"""Tests for report endpoints: balance sheet, income statement, cash flow,
subsidiary ledger, general ledger, P&L statement, dashboard, OEM contract P&L."""

from datetime import date
from decimal import Decimal

from app.models.financial import (
    Account, AccountType, AccountDirection,
    Voucher, VoucherEntry, VoucherStatus,
    VoucherNumberCounter,
)


class TestSubsidiaryLedger:
    def test_empty_ledger_returns_opening_balance(self, client, ledger_id):
        """Subsidiary ledger for an account with no entries returns opening balance row."""
        resp = client.get(
            "/api/v1/reports/subsidiary-ledger",
            params={
                "account_code": "1002",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1  # opening balance row only
        assert Decimal(data[0]["debit_amount"]) == 0
        assert Decimal(data[0]["credit_amount"]) == 0
        assert Decimal(data[0]["balance"]) == 0

    def test_with_posted_vouchers(self, client, ledger, ledger_id, posted_voucher):
        """Subsidiary ledger reflects posted voucher activity."""
        resp = client.get(
            "/api/v1/reports/subsidiary-ledger",
            params={
                "account_code": "1002",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2  # opening + at least 1 entry
        # Find the posted entry by voucher_number
        entry = [r for r in data if r["voucher_number"] == "记-1"][0]
        assert Decimal(entry["debit_amount"]) == Decimal("100000")
        assert Decimal(entry["credit_amount"]) == 0

    def test_balance_direction_debit(self, client, ledger, ledger_id, posted_voucher):
        """Debit-direction account (1002) balance = opening + debit - credit."""
        resp = client.get(
            "/api/v1/reports/subsidiary-ledger",
            params={
                "account_code": "1002",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        data = resp.json()
        last_row = data[-1]
        assert Decimal(last_row["balance"]) == Decimal("100000")  # 0 + 100000 - 0

    def test_balance_direction_credit(self, client, ledger, ledger_id, posted_voucher):
        """Credit-direction account (4001) balance = opening + credit - debit."""
        resp = client.get(
            "/api/v1/reports/subsidiary-ledger",
            params={
                "account_code": "4001",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        data = resp.json()
        last_row = data[-1]
        assert Decimal(last_row["balance"]) == Decimal("100000")

    def test_404_for_missing_account(self, client, ledger_id):
        resp = client.get(
            "/api/v1/reports/subsidiary-ledger",
            params={
                "account_code": "9999",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 404

    def test_draft_vouchers_excluded(self, client, db, ledger, ledger_id):
        """Draft vouchers should NOT appear in subsidiary ledger."""
        v = Voucher(
            ledger_id=ledger_id,
            voucher_number="记-draft",
            voucher_date=date(2024, 1, 10),
            status=VoucherStatus.DRAFT,
        )
        db.add(v)
        db.flush()
        bank = db.query(Account).filter(
            Account.ledger_id == ledger_id, Account.code == "1002"
        ).first()
        db.add(VoucherEntry(
            voucher_id=v.id, account_id=bank.id,
            summary="draft-entry", direction=AccountDirection.DEBIT, amount=999.99,
        ))
        db.commit()

        resp = client.get(
            "/api/v1/reports/subsidiary-ledger",
            params={
                "account_code": "1002",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        data = resp.json()
        drafts = [r for r in data if "draft" in r["summary"].lower()]
        assert len(drafts) == 0


class TestGeneralLedger:
    def test_monthly_aggregation(self, client, ledger_id, posted_voucher, revenue_voucher, expense_voucher):
        """General ledger aggregates posted entries by month."""
        resp = client.get(
            "/api/v1/reports/general-ledger",
            params={"year": 2024},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Find bank account (1002) for January
        jan_rows = [r for r in data if r["account_code"] == "1002" and r["month"] == "2024-01"]
        assert len(jan_rows) == 1
        jan = jan_rows[0]
        assert Decimal(jan["debit_sum"]) == Decimal("150000")  # 100k + 50k
        assert Decimal(jan["credit_sum"]) == Decimal("5000")  # from expense
        # balance for debit-direction account: opening + debit - credit
        assert Decimal(jan["balance"]) == Decimal("145000")  # 0 + 150000 - 5000

    def test_empty_year(self, client, ledger_id):
        resp = client.get(
            "/api/v1/reports/general-ledger",
            params={"year": 2025},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 0


class TestBalanceSheet:
    def test_basic_balance(self, client, ledger_id, posted_voucher):
        """After posting capital injection, assets = equity."""
        resp = client.get(
            "/api/v1/reports/balance-sheet",
            params={"as_of_date": "2024-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert Decimal(data["total_assets"]) == Decimal("100000")
        assert Decimal(data["total_equity"]) == Decimal("100000")
        assert Decimal(data["total_liabilities"]) == 0

    def test_balance_sheet_equation_with_only_balance_accounts(self, client, ledger_id, posted_voucher):
        """A = L + E must hold when only balance-sheet accounts are involved.
        P&L accounts (revenue/expense) break the equation until period-end close
        because their balances aren't reflected in equity."""
        resp = client.get(
            "/api/v1/reports/balance-sheet",
            params={"as_of_date": "2024-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        data = resp.json()
        # A = L + E (convert from Money strings to Decimal for arithmetic)
        assert Decimal(data["total_assets"]) == Decimal(data["total_liabilities"]) + Decimal(data["total_equity"])



class TestIncomeStatement:
    def test_revenue_and_expense(self, client, ledger_id, revenue_voucher, expense_voucher):
        resp = client.get(
            "/api/v1/reports/income-statement",
            params={"start_date": "2024-01-01", "end_date": "2024-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert Decimal(data["total_revenue"]) == Decimal("50000")
        assert Decimal(data["total_expense"]) == Decimal("5000")
        assert Decimal(data["net_income"]) == Decimal("45000")

    def test_empty_period(self, client, ledger_id):
        resp = client.get(
            "/api/v1/reports/income-statement",
            params={"start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        data = resp.json()
        assert Decimal(data["total_revenue"]) == 0
        assert Decimal(data["total_expense"]) == 0
        assert Decimal(data["net_income"]) == 0

    def test_income_statement_after_closing_not_zero(
        self, client, auth_headers, ledger, ledger_id, revenue_voucher, expense_voucher
    ):
        """Regression test: income statement must NOT zero out after P&L
        carry-forward + period close.

        Without the fix in reports.py (fast-path fallback when closing
        vouchers exist), the fast path would use AccountBalance.period_debit/
        credit which includes the offsetting entries of the P&L carry-forward
        voucher — cancelling out the original revenue/expense and making the
        income statement show 0/0/0 for a closed period.
        """
        headers = {**auth_headers, **{"X-Ledger-Id": str(ledger_id)}}

        # 1. Run P&L carry-forward → creates DRAFT voucher with source_type=PNL_CARRY_FORWARD
        resp_pl = client.post(
            "/api/v1/closing/profit-loss?year=2024&month=1", headers=headers
        )
        assert resp_pl.status_code == 200
        pl_voucher_id = resp_pl.json().get("voucher_id")
        assert pl_voucher_id, "P&L carry-forward should create a voucher"

        # 2. POST the P&L voucher so /closing/close accepts the period
        resp_post = client.post(
            f"/api/v1/vouchers/{pl_voucher_id}/post", headers=headers
        )
        assert resp_post.status_code == 200

        # 3. Close the period — triggers compute_period_balances which writes
        #    AccountBalance rows including the closing voucher's entries.
        resp_close = client.post(
            "/api/v1/closing/close?year=2024&month=1", headers=headers
        )
        assert resp_close.status_code == 200

        # 4. Query income statement for the closed period.
        resp = client.get(
            "/api/v1/reports/income-statement",
            params={"start_date": "2024-01-01", "end_date": "2024-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Without fix: total_revenue=0, total_expense=0, net_income=0
        # With fix: slow path excludes CLOSING_SOURCE_TYPES, original activity preserved
        assert Decimal(data["total_revenue"]) == Decimal("50000"), (
            f"Expected revenue 50000 after closing, got {data['total_revenue']} "
            f"(fast path may have included the closing voucher's offsetting entry)"
        )
        assert Decimal(data["total_expense"]) == Decimal("5000"), (
            f"Expected expense 5000 after closing, got {data['total_expense']}"
        )
        assert Decimal(data["net_income"]) == Decimal("45000"), (
            f"Expected net_income 45000 after closing, got {data['net_income']}"
        )



class TestCashFlowStatement:
    def test_operating_receipt(self, client, ledger_id, revenue_voucher):
        """Revenue from sales = operating inflow."""
        resp = client.get(
            "/api/v1/reports/cash-flow",
            params={"start_date": "2024-01-01", "end_date": "2024-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert Decimal(data["net_operating_cash_flow"]) == Decimal("50000")
        assert Decimal(data["net_financing_cash_flow"]) == 0

    def test_capital_injection_is_financing(self, client, ledger_id, posted_voucher):
        """Capital injection (credit 4001) = financing inflow."""
        resp = client.get(
            "/api/v1/reports/cash-flow",
            params={"start_date": "2024-01-01", "end_date": "2024-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        data = resp.json()
        assert Decimal(data["net_financing_cash_flow"]) == Decimal("100000")


class TestProfitLossStatement:
    def test_pl_structure(self, client, ledger_id, revenue_voucher, expense_voucher):
        resp = client.get(
            "/api/v1/reports/profit-loss-statement",
            params={"year": 2024, "month": 1},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Verify structure exists with required fields
        assert "operating_revenue" in data
        assert "operating_costs" in data
        assert "gross_profit" in data
        assert "expenses" in data
        assert "operating_profit" in data
        assert "net_profit" in data
        # All items should have current_month and ytd fields
        for key in ["operating_revenue", "operating_costs", "gross_profit", "operating_profit", "net_profit"]:
            assert "current_month" in data[key]
            assert "ytd" in data[key]
        # Gross profit = revenue - costs (convert from Money strings)
        expected_gross = Decimal(data["operating_revenue"]["current_month"]) - Decimal(data["operating_costs"]["current_month"])
        assert Decimal(data["gross_profit"]["current_month"]) == expected_gross


class TestDashboardSummary:
    def test_dashboard_returns_kpi(self, client, ledger_id, revenue_voucher):
        resp = client.get(
            "/api/v1/reports/dashboard-summary",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "monthly_revenue" in data
        assert "pending_prepayments" in data
        assert "unmatched_bank_txns" in data
        assert "pending_tasks" in data

    def test_dashboard_requires_ledger(self, client):
        resp = client.get("/api/v1/reports/dashboard-summary")
        assert resp.status_code == 400


class TestDecimalPrecision:
    def test_voucher_amounts_are_decimal(self, client, ledger_id, posted_voucher):
        """Monetary values in API responses must be strings for precision."""
        resp = client.get(
            "/api/v1/vouchers/",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        vouchers = resp.json()["items"]
        assert len(vouchers) > 0
        for v in vouchers:
            for entry in v.get("entries", []):
                assert isinstance(entry["amount"], str), \
                    f"amount should be string, got {type(entry['amount'])}: {entry['amount']}"

    def test_subsidiary_ledger_amounts_are_numbers(self, client, ledger_id, posted_voucher):
        account_code = (
            posted_voucher.entries[0].account.code
        )
        resp = client.get(
            "/api/v1/reports/subsidiary-ledger",
            params={
                "account_code": account_code,
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        rows = resp.json()
        for row in rows:
            for field in ("debit_amount", "credit_amount", "balance"):
                if field in row and row[field] is not None:
                    assert isinstance(row[field], str), \
                        f"{field} should be string, got {type(row[field])}: {row[field]}"

    def test_balance_sheet_amounts_are_numbers(self, client, ledger_id, posted_voucher):
        resp = client.get(
            "/api/v1/reports/balance-sheet",
            params={"as_of_date": "2024-01-31"},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        for section in ("assets", "liabilities", "equity"):
            for item in data.get(section, []):
                if "amount" in item and item["amount"] is not None:
                    assert isinstance(item["amount"], str), \
                        f"amount in {section} should be string, got {type(item['amount'])}"


class TestOemContractPnL:
    """Tests for GET /api/v1/reports/oem-contract/{contract_number}"""

    def _create_oem_voucher(self, db, ledger, contract_number, year=2024, month=1, day=15):
        """Helper: create a posted voucher with OEM contract entries.

        Voucher structure (balanced):
          Debit  1002 银行存款       30,000  (net cash received)
          Debit  5401 主营业务成本    60,000  (cost of goods sold)
          Debit  6601 销售费用       10,000  (selling expense)
          Credit 5001 主营业务收入  100,000  (revenue from OEM)
        Total debits = Total credits = 100,000
        """
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number=f"OEM-{contract_number}-{year}-{month:02d}-{day:02d}",
            voucher_date=date(year, month, day),
            status=VoucherStatus.POSTED,
            contract_number=contract_number,
        )
        db.add(v)
        db.flush()

        bank = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "1002"
        ).first()
        revenue = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "5001"
        ).first()
        cost = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "5401"
        ).first()
        expense = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "6601"
        ).first()

        db.add(VoucherEntry(
            voucher_id=v.id, account_id=bank.id,
            summary="OEM收款", direction=AccountDirection.DEBIT,
            amount=Decimal("30000.00"),
        ))
        db.add(VoucherEntry(
            voucher_id=v.id, account_id=cost.id,
            summary="OEM销售成本", direction=AccountDirection.DEBIT,
            amount=Decimal("60000.00"),
        ))
        db.add(VoucherEntry(
            voucher_id=v.id, account_id=expense.id,
            summary="OEM销售费用", direction=AccountDirection.DEBIT,
            amount=Decimal("10000.00"),
        ))
        db.add(VoucherEntry(
            voucher_id=v.id, account_id=revenue.id,
            summary="OEM销售收入", direction=AccountDirection.CREDIT,
            amount=Decimal("100000.00"),
        ))

        # Ensure counter exists
        counter = db.query(VoucherNumberCounter).filter(
            VoucherNumberCounter.ledger_id == ledger.id,
            VoucherNumberCounter.prefix == "OEM-",
        ).first()
        if not counter:
            db.add(VoucherNumberCounter(
                ledger_id=ledger.id, prefix="OEM-", current_number=1
            ))
        db.commit()
        db.refresh(v)
        return v

    def test_full_contract_pnl(self, client, db, ledger, ledger_id):
        """Full OEM contract P&L returns correct structure and aggregated values."""
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        resp = client.get(
            "/api/v1/reports/oem-contract/OEM-2024-001",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Verify structure
        assert data["contract_number"] == "OEM-2024-001"
        assert "revenue" in data
        assert "cost" in data
        assert "expenses" in data
        assert "gross_profit" in data
        assert "net_profit" in data
        assert "entries" in data

        # Verify aggregated values (Money serializes as strings)
        assert Decimal(data["revenue"]) == Decimal("100000")
        assert Decimal(data["cost"]) == Decimal("60000")
        assert Decimal(data["expenses"]) == Decimal("10000")
        assert Decimal(data["gross_profit"]) == Decimal("40000")  # 100000 - 60000
        assert Decimal(data["net_profit"]) == Decimal("30000")    # 40000 - 10000

        # Verify entries
        assert len(data["entries"]) == 4
        categories = {e["category"] for e in data["entries"]}
        assert "revenue" in categories
        assert "cost" in categories
        assert "expenses" in categories
        assert "other" in categories  # bank entry

        # Verify entry fields
        for entry in data["entries"]:
            assert isinstance(entry["date"], str)
            assert isinstance(entry["voucher_number"], str)
            assert isinstance(entry["account_code"], str)
            assert isinstance(entry["account_name"], str)
            assert isinstance(entry["summary"], str)
            assert entry["direction"] in ("DEBIT", "CREDIT")
            assert isinstance(entry["amount"], str)
            assert entry["category"] in ("revenue", "cost", "expenses", "other")

    def test_contract_not_found(self, client, ledger_id):
        """Querying a non-existent contract returns 404."""
        resp = client.get(
            "/api/v1/reports/oem-contract/NONEXISTENT",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 404
        assert "NONEXISTENT" in resp.json()["detail"]

    def test_year_filter(self, client, db, ledger, ledger_id):
        """Year filter limits results to matching year only."""
        self._create_oem_voucher(db, ledger, "OEM-2024-001", year=2024, month=3)
        self._create_oem_voucher(db, ledger, "OEM-2024-001", year=2025, month=5)

        # Query only 2024
        resp = client.get(
            "/api/v1/reports/oem-contract/OEM-2024-001",
            params={"year": 2024},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should only have entries from 2024 (1 voucher, 4 entries)
        assert len(data["entries"]) == 4
        assert Decimal(data["revenue"]) == Decimal("100000")
        assert Decimal(data["cost"]) == Decimal("60000")

    def test_year_month_filter(self, client, db, ledger, ledger_id):
        """Year + month filter further narrows results."""
        contract = "OEM-2024-MONTH"
        self._create_oem_voucher(db, ledger, contract, year=2024, month=1, day=10)
        self._create_oem_voucher(db, ledger, contract, year=2024, month=2, day=15)
        self._create_oem_voucher(db, ledger, contract, year=2024, month=3, day=20)

        # Query only January 2024
        resp = client.get(
            f"/api/v1/reports/oem-contract/{contract}",
            params={"year": 2024, "month": 1},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only 1 voucher (4 entries) for January
        assert len(data["entries"]) == 4
        assert Decimal(data["revenue"]) == Decimal("100000")

        # Query February
        resp2 = client.get(
            f"/api/v1/reports/oem-contract/{contract}",
            params={"year": 2024, "month": 2},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["entries"]) == 4

        # Query all months (no filter) — should aggregate all 3 vouchers
        resp3 = client.get(
            f"/api/v1/reports/oem-contract/{contract}",
            params={"year": 2024},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert len(data3["entries"]) == 12  # 3 vouchers * 4 entries
        assert Decimal(data3["revenue"]) == Decimal("300000")
        assert Decimal(data3["cost"]) == Decimal("180000")
        assert Decimal(data3["expenses"]) == Decimal("30000")
        assert Decimal(data3["gross_profit"]) == Decimal("120000")
        assert Decimal(data3["net_profit"]) == Decimal("90000")

    def test_entries_include_all_classifications(self, client, db, ledger, ledger_id):
        """All four classification categories appear for a standard OEM voucher."""
        self._create_oem_voucher(db, ledger, "OEM-CLASSIFY")

        resp = client.get(
            "/api/v1/reports/oem-contract/OEM-CLASSIFY",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Check individual entry classifications
        rev_entries = [e for e in data["entries"] if e["category"] == "revenue"]
        cost_entries = [e for e in data["entries"] if e["category"] == "cost"]
        exp_entries = [e for e in data["entries"] if e["category"] == "expenses"]
        other_entries = [e for e in data["entries"] if e["category"] == "other"]

        assert len(rev_entries) == 1
        assert rev_entries[0]["account_code"] == "5001"
        assert rev_entries[0]["direction"] == "CREDIT"

        assert len(cost_entries) == 1
        assert cost_entries[0]["account_code"] == "5401"
        assert cost_entries[0]["direction"] == "DEBIT"

        assert len(exp_entries) == 1
        assert exp_entries[0]["account_code"] == "6601"
        assert exp_entries[0]["direction"] == "DEBIT"

        assert len(other_entries) == 1
        assert other_entries[0]["account_code"] == "1002"
        assert other_entries[0]["category"] == "other"

    def test_draft_vouchers_excluded(self, client, db, ledger, ledger_id):
        """Draft vouchers with matching contract_number must not appear."""
        # Create a draft voucher with contract_number (should be excluded)
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="OEM-DRAFT",
            voucher_date=date(2024, 1, 10),
            status=VoucherStatus.DRAFT,
            contract_number="OEM-DRAFT-CT",
        )
        db.add(v)
        db.flush()
        revenue = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "5001"
        ).first()
        db.add(VoucherEntry(
            voucher_id=v.id, account_id=revenue.id,
            summary="Draft revenue", direction=AccountDirection.CREDIT,
            amount=Decimal("99999.00"),
        ))
        db.commit()

        resp = client.get(
            "/api/v1/reports/oem-contract/OEM-DRAFT-CT",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 404  # No POSTED vouchers found

    def test_empty_contract_no_posted_vouchers(self, client, ledger_id):
        """Contract with no entries at all returns 404."""
        resp = client.get(
            "/api/v1/reports/oem-contract/EMPTY-CT",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 404

    def test_amounts_are_numbers(self, client, db, ledger, ledger_id):
        """All monetary values in OEM contract P&L response must be strings for precision."""
        self._create_oem_voucher(db, ledger, "OEM-NUM-TEST")

        resp = client.get(
            "/api/v1/reports/oem-contract/OEM-NUM-TEST",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()

        for field in ("revenue", "cost", "expenses", "gross_profit", "net_profit"):
            assert isinstance(data[field], str), \
                f"{field} should be string, got {type(data[field])}: {data[field]}"

        for entry in data["entries"]:
            assert isinstance(entry["amount"], str), \
                f"entry amount should be string, got {type(entry['amount'])}"
