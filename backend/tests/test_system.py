"""Tests for system router (periods, currencies, exchange rates)."""
from decimal import Decimal

import pytest

from app.models.financial import AccountingPeriod, PeriodStatus, Currency, ExchangeRate


class TestPeriods:
    """Test accounting period endpoints."""

    def test_get_current_period(self, client, auth_headers, ledger, ledger_headers, db):
        """Get the current open accounting period."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=3, status=PeriodStatus.OPEN,
        )
        db.add(period)
        db.commit()

        resp = client.get(
            "/api/v1/system/periods/current",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["year"] == 2024
        assert data["month"] == 3  # latest OPEN period
        assert "status" in data

    def test_no_period_returns_none(self, client, auth_headers, ledger, db):
        """When no OPEN period exists, returns None."""
        # Close all periods
        db.query(AccountingPeriod).filter(
            AccountingPeriod.ledger_id == ledger.id,
        ).update({"status": PeriodStatus.CLOSED})
        db.commit()

        resp = client.get(
            "/api/v1/system/periods/current",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        assert resp.json() is None

    def test_period_without_auth(self, client, ledger_headers):
        """Periods endpoint works without auth (ledger-scoped)."""
        resp = client.get("/api/v1/system/periods/current", headers=ledger_headers)
        assert resp.status_code == 200


class TestCurrencies:
    """Test currency listing endpoint."""

    def test_list_currencies(self, client, auth_headers, ledger, db):
        """List all configured currencies."""
        db.add(Currency(code="CNY", name="Chinese Yuan", is_base=True))
        db.add(Currency(code="USD", name="US Dollar", is_base=False))
        db.add(Currency(code="EUR", name="Euro", is_base=False))
        db.commit()

        resp = client.get(
            "/api/v1/system/currencies",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        codes = {c["code"] for c in data}
        assert "CNY" in codes
        assert "USD" in codes
        assert "EUR" in codes

    def test_currencies_without_auth(self, client, ledger_headers):
        """Currencies endpoint works without auth (global data)."""
        resp = client.get("/api/v1/system/currencies", headers=ledger_headers)
        assert resp.status_code == 200


class TestExchangeRates:
    """Test exchange rate endpoints."""

    def test_get_rates_for_period(self, client, auth_headers, ledger, db):
        """Get exchange rates for a specific period."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=2, status=PeriodStatus.OPEN,
        )
        db.add(period)
        db.flush()

        cny = Currency(code="CNY", name="Chinese Yuan", is_base=True)
        usd = Currency(code="USD", name="US Dollar", is_base=False)
        db.add(cny)
        db.add(usd)
        db.flush()

        db.add(ExchangeRate(period_id=period.id, currency_id=cny.id, rate=Decimal("1.00")))
        db.add(ExchangeRate(period_id=period.id, currency_id=usd.id, rate=Decimal("7.25")))
        db.commit()

        resp = client.get(
            "/api/v1/system/rates?year=2024&month=2",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        rates_by_code = {r["currency_code"]: r["rate"] for r in data}
        assert "CNY" in rates_by_code
        assert "USD" in rates_by_code
        assert float(rates_by_code["USD"]) == 7.25

    def test_no_period_returns_empty(self, client, auth_headers, ledger_headers):
        """No rates for non-existent period."""
        resp = client.get(
            "/api/v1/system/rates?year=2099&month=1",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_update_exchange_rate(self, client, auth_headers, ledger, db):
        """Update an exchange rate for a period."""
        # Period already exists from conftest fixture
        period = db.query(AccountingPeriod).filter(
            AccountingPeriod.ledger_id == ledger.id,
            AccountingPeriod.year == 2024,
            AccountingPeriod.month == 1,
        ).first()

        usd = Currency(code="USD", name="US Dollar", is_base=False)
        db.add(usd)
        db.commit()

        resp = client.post(
            "/api/v1/system/rates?year=2024&month=1",
            json={"currency_code": "USD", "rate": 7.25},
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Verify it was persisted
        resp2 = client.get(
            "/api/v1/system/rates?year=2024&month=1",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        rates = {r["currency_code"]: r["rate"] for r in resp2.json()}
        assert float(rates["USD"]) == 7.25

    def test_update_rate_missing_period(self, client, auth_headers, ledger_headers):
        """Updating rate for non-existent period returns 404."""
        resp = client.post(
            "/api/v1/system/rates?year=2099&month=1",
            json={"currency_code": "CNY", "rate": 1.0},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404

    def test_update_rate_missing_currency(self, client, auth_headers, ledger, db):
        """Updating rate for non-existent currency returns 404."""
        period = AccountingPeriod(
            ledger_id=ledger.id, year=2024, month=5, status=PeriodStatus.OPEN,
        )
        db.add(period)
        db.commit()

        resp = client.post(
            "/api/v1/system/rates?year=2024&month=5",
            json={"currency_code": "XYZ", "rate": 1.0},
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 404
