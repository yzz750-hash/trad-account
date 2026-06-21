"""Tests for closing router (depreciation, profit-loss, FX revaluation, period close/unclose)."""
from datetime import date
from decimal import Decimal

import pytest

from app.models.financial import (
    AccountingPeriod,
    PeriodStatus,
    FixedAsset,
    Voucher,
    VoucherEntry,
    VoucherStatus,
    Account,
    AccountDirection,
    AccountType,
    Currency,
    ExchangeRate,
    AccountBalance,
)


class TestDepreciate:
    """Test POST /closing/depreciate — auto depreciation of fixed assets."""

    def test_no_active_assets(self, client, auth_headers, ledger_headers):
        """No fixed assets → returns early."""
        resp = client.post(
            "/api/v1/closing/depreciate?year=2024&month=1",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "No active fixed assets" in data["message"]

    def test_depreciate_creates_voucher(self, client, auth_headers, ledger, db):
        """Active fixed asset should generate a depreciation voucher."""
        asset = FixedAsset(
            ledger_id=ledger.id,
            asset_code="FA001",
            asset_name="办公设备",
            purchase_date=date(2023, 12, 1),
            original_value=Decimal("120000"),
            salvage_value_rate=Decimal("0.05"),
            expected_useful_months=60,
            accumulated_depreciation=Decimal("0"),
            is_active=True,
        )
        db.add(asset)
        db.commit()

        resp = client.post(
            "/api/v1/closing/depreciate?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Depreciation voucher created" in data["message"]

    def test_depreciate_idempotent(self, client, auth_headers, ledger, db):
        """Second depreciation call for same period should return idempotent."""
        asset = FixedAsset(
            ledger_id=ledger.id,
            asset_code="FA002",
            asset_name="车辆",
            purchase_date=date(2023, 12, 1),
            original_value=Decimal("240000"),
            salvage_value_rate=Decimal("0.05"),
            expected_useful_months=48,
            accumulated_depreciation=Decimal("0"),
            is_active=True,
        )
        db.add(asset)
        db.commit()

        headers = {**auth_headers, **{"X-Ledger-Id": str(ledger.id)}}

        resp1 = client.post("/api/v1/closing/depreciate?year=2024&month=1", headers=headers)
        assert resp1.status_code == 200

        resp2 = client.post("/api/v1/closing/depreciate?year=2024&month=1", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["idempotent"] is True

    def test_fully_depreciated_assets(self, client, auth_headers, ledger, db):
        """Asset at salvage limit should be skipped."""
        asset = FixedAsset(
            ledger_id=ledger.id,
            asset_code="FA003",
            asset_name="已折旧完设备",
            purchase_date=date(2023, 12, 1),
            original_value=Decimal("100000"),
            salvage_value_rate=Decimal("0.05"),
            expected_useful_months=60,
            accumulated_depreciation=Decimal("95000"),
            is_active=True,
        )
        db.add(asset)
        db.commit()

        resp = client.post(
            "/api/v1/closing/depreciate?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "fully depreciated" in data["message"]


class TestProfitLossCarryForward:
    """Test POST /closing/profit-loss — month-end P&L carry-forward."""

    def test_no_pl_entries(self, client, auth_headers, ledger_headers):
        """No profit/loss transactions → returns early."""
        resp = client.post(
            "/api/v1/closing/profit-loss?year=2024&month=3",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "No profit/loss entries" in data["message"]

    def test_carry_forward_creates_voucher(self, client, auth_headers, ledger, db, revenue_voucher, expense_voucher):
        """Revenue (50k) and expense (5k) → net profit 45k carried to 本年利润."""
        resp = client.post(
            "/api/v1/closing/profit-loss?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Net profit impact" in data["message"]
        assert "45000" in data["message"] or "45000.00" in data["message"]

    def test_carry_forward_idempotent(self, client, auth_headers, ledger, db, revenue_voucher):
        """Second carry-forward for same period should be idempotent."""
        headers = {**auth_headers, **{"X-Ledger-Id": str(ledger.id)}}

        resp1 = client.post("/api/v1/closing/profit-loss?year=2024&month=1", headers=headers)
        assert resp1.status_code == 200

        resp2 = client.post("/api/v1/closing/profit-loss?year=2024&month=1", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["idempotent"] is True

    def test_missing_profit_account(self, client, auth_headers, ledger, db):
        """If 本年利润 account does not exist, return 400."""
        db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.name == "本年利润"
        ).delete()
        db.commit()

        resp = client.post(
            "/api/v1/closing/profit-loss?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        assert "本年利润" in resp.json()["detail"]


class TestYearEnd:
    """Test POST /closing/year-end — year-end carry-forward to Retained Earnings."""

    def test_year_end_no_profit_entries(self, client, auth_headers, ledger_headers):
        """No entries in 本年利润 → returns early."""
        resp = client.post(
            "/api/v1/closing/year-end?year=2024",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "余额为零" in data["message"]

    def test_year_end_carry_forward(self, client, auth_headers, ledger, db, revenue_voucher, expense_voucher):
        """After P&L carry-forward populates 本年利润, year-end transfers to 利润分配."""
        headers = {**auth_headers, **{"X-Ledger-Id": str(ledger.id)}}

        resp_pl = client.post("/api/v1/closing/profit-loss?year=2024&month=1", headers=headers)
        assert resp_pl.status_code == 200

        # Now do year-end
        resp = client.post("/api/v1/closing/year-end?year=2024", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Retained Earnings" in data["message"]

    def test_year_end_idempotent(self, client, auth_headers, ledger, db, revenue_voucher, expense_voucher):
        """Second year-end for same year should be idempotent."""
        headers = {**auth_headers, **{"X-Ledger-Id": str(ledger.id)}}

        # Populate 本年利润 first
        resp_pl = client.post("/api/v1/closing/profit-loss?year=2024&month=1", headers=headers)
        assert resp_pl.status_code == 200

        resp1 = client.post("/api/v1/closing/year-end?year=2024", headers=headers)
        assert resp1.status_code == 200

        resp2 = client.post("/api/v1/closing/year-end?year=2024", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["idempotent"] is True

    def test_year_end_missing_profit_account(self, client, auth_headers, ledger, db):
        """If 4103 本年利润 is missing, return 400."""
        db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "4103"
        ).delete()
        db.commit()

        resp = client.post(
            "/api/v1/closing/year-end?year=2024",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        assert "4103" in resp.json()["detail"]

    def test_year_end_missing_retained_earnings(self, client, auth_headers, ledger, db):
        """If 4104 利润分配 is missing, return 400."""
        db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "4104"
        ).delete()
        db.commit()

        resp = client.post(
            "/api/v1/closing/year-end?year=2024",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        assert "4104" in resp.json()["detail"]


class TestFXRevaluation:
    """Test POST /closing/fx-revaluation — FX revaluation at period end."""

    def test_no_foreign_currency_entries(self, client, auth_headers, ledger_headers):
        """No FX entries → returns early."""
        resp = client.post(
            "/api/v1/closing/fx-revaluation?year=2024&month=1",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "无外币发生额" in data["message"]

    def test_fx_revaluation_idempotent(self, client, auth_headers, ledger, db):
        """Second FX revaluation for same period should be idempotent (after voucher generated)."""
        # Need to generate an actual FX voucher first for idempotency to be recorded.
        period = (
            db.query(AccountingPeriod)
            .filter(AccountingPeriod.ledger_id == ledger.id, AccountingPeriod.year == 2024, AccountingPeriod.month == 2)
            .first()
        )
        if not period:
            period = AccountingPeriod(ledger_id=ledger.id, year=2024, month=2, status=PeriodStatus.OPEN)
            db.add(period)
            db.flush()

        usd = Currency(code="USD", name="US Dollar", is_base=False)
        db.add(usd)
        db.flush()

        rate = ExchangeRate(period_id=period.id, currency_id=usd.id, rate=Decimal("7.30"))
        db.add(rate)
        db.flush()

        ar_account = (
            db.query(Account)
            .filter(Account.ledger_id == ledger.id, Account.code == "1122")
            .first()
        )

        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="记-FX-IDEM",
            voucher_date=date(2024, 2, 10),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()

        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=ar_account.id,
            summary="USD receivable",
            direction=AccountDirection.DEBIT,
            amount=Decimal("72500"),
            currency_code="USD",
            original_amount=Decimal("10000"),
            exchange_rate=Decimal("7.25"),
        ))
        db.commit()

        headers = {**auth_headers, **{"X-Ledger-Id": str(ledger.id)}}

        resp1 = client.post("/api/v1/closing/fx-revaluation?year=2024&month=2", headers=headers)
        assert resp1.status_code == 200

        resp2 = client.post("/api/v1/closing/fx-revaluation?year=2024&month=2", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["idempotent"] is True

    def test_fx_revaluation_with_rate_diff(self, client, auth_headers, ledger, db):
        """When exchange rate differs from entry rate, adjustment is generated."""
        period = (
            db.query(AccountingPeriod)
            .filter(AccountingPeriod.ledger_id == ledger.id, AccountingPeriod.year == 2024, AccountingPeriod.month == 2)
            .first()
        )
        if not period:
            period = AccountingPeriod(ledger_id=ledger.id, year=2024, month=2, status=PeriodStatus.OPEN)
            db.add(period)
            db.flush()

        usd = Currency(code="USD", name="US Dollar", is_base=False)
        db.add(usd)
        db.flush()

        rate = ExchangeRate(period_id=period.id, currency_id=usd.id, rate=Decimal("7.30"))
        db.add(rate)
        db.flush()

        ar_account = (
            db.query(Account)
            .filter(Account.ledger_id == ledger.id, Account.code == "1122")
            .first()
        )

        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="记-FX2",
            voucher_date=date(2024, 2, 10),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()

        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=ar_account.id,
            summary="USD receivable",
            direction=AccountDirection.DEBIT,
            amount=Decimal("72500"),
            currency_code="USD",
            original_amount=Decimal("10000"),
            exchange_rate=Decimal("7.25"),
        ))
        db.commit()

        resp = client.post(
            "/api/v1/closing/fx-revaluation?year=2024&month=2",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "FX revaluation completed" in data["message"]

    def test_fx_missing_6603_account(self, client, auth_headers, ledger, db):
        """If 6603 account is missing, returns error."""
        db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "6603"
        ).delete()
        db.commit()

        resp = client.post(
            "/api/v1/closing/fx-revaluation?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "6603" in data["detail"]


class TestClosePeriod:
    """Test POST /closing/close — close an accounting period."""

    def test_close_period_success(self, client, auth_headers, ledger, db):
        """Close an OPEN period with no draft vouchers."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=3, status=PeriodStatus.OPEN,
        )
        db.add(period)
        db.commit()

        resp = client.post(
            "/api/v1/closing/close?year=2024&month=3",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "closed successfully" in data["message"]

        db.refresh(period)
        assert period.status == PeriodStatus.CLOSED

    def test_close_already_closed_period(self, client, auth_headers, ledger, db):
        """Closing an already CLOSED period returns 400."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=4, status=PeriodStatus.CLOSED,
        )
        db.add(period)
        db.commit()

        resp = client.post(
            "/api/v1/closing/close?year=2024&month=4",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        assert "already closed" in resp.json()["detail"]

    def test_close_period_with_draft_vouchers(self, client, auth_headers, ledger, db):
        """Cannot close a period that has unposted (DRAFT) vouchers."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=5, status=PeriodStatus.OPEN,
        )
        db.add(period)
        db.flush()

        draft = Voucher(
            ledger_id=ledger.id,
            voucher_number="草稿-1",
            voucher_date=date(2024, 5, 15),
            status=VoucherStatus.DRAFT,
        )
        db.add(draft)
        db.commit()

        resp = client.post(
            "/api/v1/closing/close?year=2024&month=5",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        assert "unposted" in resp.json()["detail"].lower()

    def test_close_nonexistent_period(self, client, auth_headers, ledger_headers):
        """Closing a non-existent period returns 404."""
        resp = client.post(
            "/api/v1/closing/close?year=2099&month=1",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404


class TestUnclosePeriod:
    """Test POST /closing/unclose — reopen a closed period."""

    def test_unclose_period_success(self, client, auth_headers, ledger, db):
        """Reopen a CLOSED period."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=6, status=PeriodStatus.CLOSED,
        )
        db.add(period)
        db.commit()

        resp = client.post(
            "/api/v1/closing/unclose?year=2024&month=6",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "reopened" in data["message"]

        db.refresh(period)
        assert period.status == PeriodStatus.OPEN

    def test_unclose_already_open_period(self, client, auth_headers, ledger, db):
        """Unclosing an already OPEN period returns 400."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=7, status=PeriodStatus.OPEN,
        )
        db.add(period)
        db.commit()

        resp = client.post(
            "/api/v1/closing/unclose?year=2024&month=7",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        assert "already open" in resp.json()["detail"]

    def test_unclose_nonexistent_period(self, client, auth_headers, ledger_headers):
        """Unclosing a non-existent period returns 404."""
        resp = client.post(
            "/api/v1/closing/unclose?year=2099&month=1",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404


class TestAccountBalanceOnClose:
    """Verify AccountBalance rows are computed correctly when closing a period."""

    def test_close_creates_balance_rows(self, client, auth_headers, ledger, db):
        """Closing a period with posted vouchers should create AccountBalance rows."""
        bank = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "1002"
        ).first()
        capital = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "4001"
        ).first()

        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="记-TEST",
            voucher_date=date(2024, 1, 15),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()
        db.add(VoucherEntry(
            voucher_id=v.id, account_id=bank.id, summary="收款",
            direction=AccountDirection.DEBIT, amount=Decimal("100000"),
        ))
        db.add(VoucherEntry(
            voucher_id=v.id, account_id=capital.id, summary="实收资本",
            direction=AccountDirection.CREDIT, amount=Decimal("100000"),
        ))
        db.commit()

        resp = client.post(
            "/api/v1/closing/close?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200

        # Verify AccountBalance rows exist for this period
        balances = db.query(AccountBalance).filter(
            AccountBalance.ledger_id == ledger.id,
            AccountBalance.year == 2024,
            AccountBalance.month == 1,
        ).all()
        assert len(balances) > 0

        bank_bal = next(b for b in balances if b.account_id == bank.id)
        assert bank_bal.period_debit == Decimal("100000")
        assert bank_bal.period_credit == Decimal("0")
        assert bank_bal.ending_debit == Decimal("100000")

        capital_bal = next(b for b in balances if b.account_id == capital.id)
        assert capital_bal.period_credit == Decimal("100000")
        assert capital_bal.ending_credit == Decimal("100000")

    def test_unclose_deletes_balance_rows(self, client, auth_headers, ledger, db):
        """Unclosing a period should delete its AccountBalance rows."""
        period = db.query(AccountingPeriod).filter(
            AccountingPeriod.ledger_id == ledger.id,
            AccountingPeriod.year == 2024,
            AccountingPeriod.month == 1,
        ).first()
        period.status = PeriodStatus.CLOSED
        db.commit()

        # Create a balance row manually to verify deletion
        db.add(AccountBalance(
            ledger_id=ledger.id, account_id=1, year=2024, month=1,
            period_debit=Decimal("100"), period_credit=Decimal("0"),
            ending_debit=Decimal("100"), ending_credit=Decimal("0"),
        ))
        db.commit()

        resp = client.post(
            "/api/v1/closing/unclose?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200

        remaining = db.query(AccountBalance).filter(
            AccountBalance.ledger_id == ledger.id,
            AccountBalance.year == 2024,
            AccountBalance.month == 1,
        ).count()
        assert remaining == 0
