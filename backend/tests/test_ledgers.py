"""Tests for ledgers router (ledger CRUD and initialization)."""
import pytest

from app.models.financial import Ledger, Account, Voucher, VoucherStatus, VoucherNumberCounter


class TestCreateLedger:
    """Test POST /ledgers/ — create a new ledger with auto-initialization."""

    def test_create_ledger_initializes_accounts(self, client, db):
        """Creating a ledger seeds default accounts, period, and counters."""
        resp = client.post(
            "/api/v1/ledgers/",
            json={
                "name": "New Company",
                "company_name": "New Corp",
                "base_currency": "CNY",
                "start_year": 2025,
                "start_month": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Company"
        assert data["company_name"] == "New Corp"
        assert data["base_currency"] == "CNY"
        assert data["start_year"] == 2025
        assert data["start_month"] == 3
        assert "id" in data

        ledger_id = data["id"]

        # Verify default accounts created
        accounts = db.query(Account).filter(Account.ledger_id == ledger_id).all()
        assert len(accounts) >= 14
        codes = {a.code for a in accounts}
        assert "1001" in codes
        assert "4103" in codes
        assert "5001" in codes

        # Verify counters created
        counters = db.query(VoucherNumberCounter).filter(
            VoucherNumberCounter.ledger_id == ledger_id
        ).all()
        assert len(counters) >= 3  # 记-, 银记-, 核-, 期末调汇-

    def test_create_ledger_minimal(self, client, db):
        """Create ledger with only required fields."""
        resp = client.post(
            "/api/v1/ledgers/",
            json={
                "name": "Minimal Ledger",
                "start_year": 2024,
                "start_month": 1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Minimal Ledger"
        assert data["company_name"] is None
        assert data["base_currency"] == "CNY"


class TestListLedgers:
    """Test GET /ledgers/ — list all ledgers."""

    def test_list_ledgers(self, client, ledger):
        """List should include the test ledger fixture."""
        resp = client.get("/api/v1/ledgers/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = {l["id"] for l in data}
        assert ledger.id in ids

    def test_list_ledgers_includes_details(self, client, ledger):
        """Each ledger should have name, company_name, base_currency."""
        resp = client.get("/api/v1/ledgers/")
        ledgers = {l["id"]: l for l in resp.json()}
        assert ledgers[ledger.id]["name"] == "Test Company"
        assert ledgers[ledger.id]["company_name"] == "Test Corp"


class TestUpdateLedger:
    """Test PUT /ledgers/{id} — update ledger metadata."""

    def test_update_name(self, client, ledger, db):
        """Update the ledger name."""
        resp = client.put(
            f"/api/v1/ledgers/{ledger.id}",
            json={"name": "Renamed Company"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Company"

        db.refresh(ledger)
        assert ledger.name == "Renamed Company"

    def test_update_company_name(self, client, ledger):
        """Update company_name independently."""
        resp = client.put(
            f"/api/v1/ledgers/{ledger.id}",
            json={"company_name": "New Corp Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["company_name"] == "New Corp Name"

    def test_update_nonexistent(self, client):
        """Update non-existent ledger returns 404."""
        resp = client.put(
            "/api/v1/ledgers/99999",
            json={"name": "Ghost"},
        )
        assert resp.status_code == 404


class TestDeleteLedger:
    """Test DELETE /ledgers/{id} — delete a ledger."""

    def test_delete_empty_ledger(self, client, db):
        """Delete a ledger with no vouchers succeeds."""
        resp = client.post(
            "/api/v1/ledgers/",
            json={"name": "To Delete", "start_year": 2024, "start_month": 1},
        )
        ledger_id = resp.json()["id"]

        resp2 = client.delete(f"/api/v1/ledgers/{ledger_id}")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "success"

        # Verify gone
        assert db.query(Ledger).filter(Ledger.id == ledger_id).first() is None

    def test_delete_ledger_with_vouchers_rejected(self, client, ledger, db):
        """Cannot delete a ledger that has vouchers."""
        from datetime import date
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number="记-保护",
            voucher_date=date(2024, 1, 1),
            status=VoucherStatus.DRAFT,
        )
        db.add(v)
        db.commit()

        resp = client.delete(f"/api/v1/ledgers/{ledger.id}")
        assert resp.status_code == 400
        assert "已包含凭证" in resp.json()["detail"]

    def test_delete_nonexistent(self, client):
        """Delete non-existent ledger returns 404."""
        resp = client.delete("/api/v1/ledgers/99999")
        assert resp.status_code == 404
