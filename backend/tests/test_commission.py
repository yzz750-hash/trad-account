"""Tests for commission engine and GET /reports/commission endpoint."""

from datetime import date
from decimal import Decimal

from app.models.financial import (
    Account,
    AccountDirection,
    CommissionBasis,
    CommissionRule,
    ContractStatus,
    OEMContract,
    Salesperson,
    Voucher,
    VoucherEntry,
    VoucherNumberCounter,
    VoucherStatus,
)


class TestCommission:
    """Tests for commission calculation engine and API endpoint."""

    # ── helpers ──────────────────────────────────────────────────────────

    def _create_sp(self, db, ledger, name="张三", dept="美洲部", employee_id="E001"):
        sp = Salesperson(
            ledger_id=ledger.id,
            employee_id=employee_id,
            name=name,
            department=dept,
            is_active=True,
        )
        db.add(sp)
        db.flush()
        return sp

    def _create_rule(self, db, ledger, salesperson_id=None, basis="gross_profit", rate=0.03):
        rule = CommissionRule(
            ledger_id=ledger.id,
            salesperson_id=salesperson_id,
            rule_name=f"Rule-{salesperson_id or 'global'}",
            basis=CommissionBasis(basis),
            rate=Decimal(str(rate)),
            effective_from=date(2020, 1, 1),
        )
        db.add(rule)
        db.flush()
        return rule

    def _create_contract(self, db, ledger, sp, contract_number, customer="Test Customer"):
        c = OEMContract(
            ledger_id=ledger.id,
            contract_number=contract_number,
            salesperson_id=sp.id,
            customer_name=customer,
            contract_date=date(2024, 1, 1),
            status=ContractStatus.ACTIVE,
        )
        db.add(c)
        db.flush()
        return c

    def _create_oem_voucher(self, db, ledger, contract_number, year=2024, month=1, day=15):
        """Create a posted voucher with OEM contract P&L entries.

        Debit  1002 银行存款       30,000  (bank, net cash)
        Debit  5401 主营业务成本    60,000  (COGS)
        Debit  6601 销售费用       10,000  (selling expense)
        Credit 5001 主营业务收入  100,000  (revenue)
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

        entries = [
            (bank, "OEM收款", AccountDirection.DEBIT, Decimal("30000.00")),
            (cost, "OEM销售成本", AccountDirection.DEBIT, Decimal("60000.00")),
            (expense, "OEM销售费用", AccountDirection.DEBIT, Decimal("10000.00")),
            (revenue, "OEM销售收入", AccountDirection.CREDIT, Decimal("100000.00")),
        ]
        for acct, summary, direction, amount in entries:
            db.add(VoucherEntry(
                voucher_id=v.id, account_id=acct.id,
                summary=summary, direction=direction, amount=amount,
            ))

        counter = db.query(VoucherNumberCounter).filter(
            VoucherNumberCounter.ledger_id == ledger.id,
            VoucherNumberCounter.prefix == "OEM-",
        ).first()
        if not counter:
            db.add(VoucherNumberCounter(
                ledger_id=ledger.id, prefix="OEM-", current_number=1,
            ))
        db.commit()
        db.refresh(v)
        return v

    # ── engine tests ─────────────────────────────────────────────────────

    def test_empty_no_salespersons(self, db, ledger):
        """Zero active salespersons yields empty report."""
        from app.commission import calculate_commission

        report = calculate_commission(db, ledger.id, 2024)
        assert report.period == "2024"
        assert report.salespersons == []
        assert report.total_commission == Decimal("0")
        assert report.contract_count == 0

    def test_single_contract_gross_profit_basis(self, db, ledger):
        """One salesperson, one contract, gross_profit basis at 3%."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        report = calculate_commission(db, ledger.id, 2024)

        assert len(report.salespersons) == 1
        sp_report = report.salespersons[0]
        assert sp_report.salesperson_name == "张三"
        assert sp_report.department == "美洲部"
        assert len(sp_report.contracts) == 1

        ct = sp_report.contracts[0]
        assert ct.contract_number == "OEM-2024-001"
        assert ct.revenue == Decimal("100000")
        assert ct.cost == Decimal("60000")
        assert ct.gross_profit == Decimal("40000")
        assert ct.basis_amount == Decimal("40000")  # gross_profit basis
        assert ct.rate == Decimal("0.03")
        assert ct.commission_amount == Decimal("1200")  # 40000 * 0.03

        assert sp_report.total_commission == Decimal("1200")
        assert report.total_commission == Decimal("1200")
        assert report.contract_count == 1

    def test_revenue_basis(self, db, ledger):
        """CommissionBasis.REVENUE uses revenue as the basis."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "revenue", 0.05)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        report = calculate_commission(db, ledger.id, 2024)
        ct = report.salespersons[0].contracts[0]
        assert ct.basis_amount == Decimal("100000")  # revenue
        assert ct.commission_amount == Decimal("5000")  # 100000 * 0.05

    def test_net_profit_basis(self, db, ledger):
        """CommissionBasis.NET_PROFIT uses revenue - cost - expenses."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "net_profit", 0.10)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        report = calculate_commission(db, ledger.id, 2024)
        ct = report.salespersons[0].contracts[0]
        # net_profit = 100000 - 60000 - 10000 = 30000
        assert ct.basis_amount == Decimal("30000")
        assert ct.commission_amount == Decimal("3000")  # 30000 * 0.10

    def test_multiple_contracts_aggregation(self, db, ledger):
        """Two contracts for one salesperson aggregate correctly."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_contract(db, ledger, sp, "OEM-2024-002")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-002")

        report = calculate_commission(db, ledger.id, 2024)
        assert len(report.salespersons) == 1
        sp_report = report.salespersons[0]
        assert len(sp_report.contracts) == 2
        assert sp_report.total_commission == Decimal("2400")  # 2 * 1200
        assert report.total_commission == Decimal("2400")
        assert report.contract_count == 2

    def test_multiple_salespersons(self, db, ledger):
        """Two salespersons with different rates show correctly separated."""
        from app.commission import calculate_commission

        sp1 = self._create_sp(db, ledger, name="张三", employee_id="E001")
        sp2 = self._create_sp(db, ledger, name="李四", dept="欧洲部", employee_id="E002")
        self._create_rule(db, ledger, sp1.id, "gross_profit", 0.03)
        self._create_rule(db, ledger, sp2.id, "gross_profit", 0.05)
        self._create_contract(db, ledger, sp1, "OEM-2024-001")
        self._create_contract(db, ledger, sp2, "OEM-2024-002")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-002")

        report = calculate_commission(db, ledger.id, 2024)
        assert len(report.salespersons) == 2
        names = {s.salesperson_name for s in report.salespersons}
        assert names == {"张三", "李四"}

        sp_zhang = next(s for s in report.salespersons if s.salesperson_name == "张三")
        sp_li = next(s for s in report.salespersons if s.salesperson_name == "李四")
        assert sp_zhang.total_commission == Decimal("1200")  # 40000 * 0.03
        assert sp_li.total_commission == Decimal("2000")     # 40000 * 0.05
        assert report.total_commission == Decimal("3200")

    def test_month_filter(self, db, ledger):
        """Month parameter filters to only that month's vouchers."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001", month=1)
        self._create_oem_voucher(db, ledger, "OEM-2024-001", month=2)

        report_jan = calculate_commission(db, ledger.id, 2024, month=1)
        assert len(report_jan.salespersons[0].contracts) == 1
        assert report_jan.salespersons[0].total_commission == Decimal("1200")

        report_feb = calculate_commission(db, ledger.id, 2024, month=2)
        assert report_feb.salespersons[0].total_commission == Decimal("1200")

        report_full = calculate_commission(db, ledger.id, 2024)
        assert report_full.salespersons[0].total_commission == Decimal("2400")

    def test_inactive_salesperson_excluded(self, db, ledger):
        """Salesperson with is_active=False is excluded."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        # Deactivate
        sp.is_active = False
        db.commit()

        report = calculate_commission(db, ledger.id, 2024)
        assert report.salespersons == []
        assert report.total_commission == Decimal("0")

    def test_no_rule_configured(self, db, ledger):
        """Salesperson without a rule and no global rule is excluded."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        # No rule created
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        report = calculate_commission(db, ledger.id, 2024)
        assert report.salespersons == []
        assert report.total_commission == Decimal("0")

    def test_global_rule_fallback(self, db, ledger):
        """Salesperson with no specific rule falls back to global rule (salesperson_id=NULL)."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        # Only global rule, no per-salesperson rule
        self._create_rule(db, ledger, salesperson_id=None, basis="gross_profit", rate=0.04)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        report = calculate_commission(db, ledger.id, 2024)
        assert len(report.salespersons) == 1
        ct = report.salespersons[0].contracts[0]
        assert ct.rate == Decimal("0.04")
        assert ct.commission_amount == Decimal("1600")  # 40000 * 0.04

    def test_cancelled_contract_excluded(self, db, ledger):
        """Contract with status CANCELLED is excluded from calculation."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        cancelled = self._create_contract(db, ledger, sp, "OEM-2024-002")
        cancelled.status = ContractStatus.CANCELLED
        db.commit()
        self._create_oem_voucher(db, ledger, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-002")

        report = calculate_commission(db, ledger.id, 2024)
        assert len(report.salespersons) == 1
        # Only the active contract should appear
        contract_numbers = {c.contract_number for c in report.salespersons[0].contracts}
        assert contract_numbers == {"OEM-2024-001"}
        assert report.contract_count == 1

    def test_rate_zero(self, db, ledger):
        """Rate of 0 produces 0 commission but salesperson still appears."""
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.0)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        report = calculate_commission(db, ledger.id, 2024)
        assert len(report.salespersons) == 1
        assert report.salespersons[0].total_commission == Decimal("0")
        assert report.salespersons[0].contracts[0].commission_amount == Decimal("0")

    # ── endpoint integration tests ───────────────────────────────────────

    def test_endpoint_requires_year(self, client, ledger_id):
        """Missing year parameter returns 422."""
        resp = client.get(
            "/api/v1/reports/commission",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 422

    def test_endpoint_full_response(self, client, db, ledger, ledger_id):
        """Full integration: create data via DB, query endpoint, verify JSON."""
        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        resp = client.get(
            "/api/v1/reports/commission",
            params={"year": 2024},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["period"] == "2024"
        assert len(data["salespersons"]) == 1
        assert data["salespersons"][0]["salesperson_name"] == "张三"
        assert len(data["salespersons"][0]["contracts"]) == 1
        assert Decimal(str(data["total_commission"])) == Decimal("1200")
        assert data["contract_count"] == 1

        # Verify contract field types are JSON-safe (strings for precision)
        ct = data["salespersons"][0]["contracts"][0]
        assert isinstance(ct["revenue"], str)
        assert isinstance(ct["rate"], str)
        assert isinstance(ct["commission_amount"], str)

    def test_endpoint_month_filter(self, client, db, ledger, ledger_id):
        """Endpoint with month param returns correct period label and filtered data."""
        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001", month=6)

        resp = client.get(
            "/api/v1/reports/commission",
            params={"year": 2024, "month": 6},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "2024-06"

    def test_endpoint_ledger_isolation(self, client, db, ledger, ledger_id):
        """Data in ledger A does not leak into ledger B's commission report."""
        from app.models.financial import Ledger, AccountingPeriod, PeriodStatus

        sp_a = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp_a.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp_a, "OEM-2024-001")
        self._create_oem_voucher(db, ledger, "OEM-2024-001")

        # Create ledger B
        ledger_b = Ledger(
            name="Company B", company_name="Corp B", start_year=2024, start_month=1
        )
        db.add(ledger_b)
        db.flush()
        db.add(AccountingPeriod(ledger_id=ledger_b.id, year=2024, month=1, status=PeriodStatus.OPEN))
        db.commit()

        # Ledger B has NO salespersons, rules, or contracts — query should be empty
        resp = client.get(
            "/api/v1/reports/commission",
            params={"year": 2024},
            headers={"X-Ledger-Id": str(ledger_b.id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["salespersons"] == []
        assert Decimal(str(data["total_commission"])) == 0
