"""Tests for accounts router (chart of accounts CRUD, trial balance)."""
from decimal import Decimal

import pytest

from app.models.financial import (
    Account,
    AccountType,
    AccountDirection,
    Voucher,
    VoucherEntry,
    VoucherStatus,
)


class TestListAccounts:
    """Test GET /accounts/ — list chart of accounts."""

    def test_list_accounts(self, client, auth_headers, ledger, ledger_headers):
        """Should return all accounts for the ledger (19 seeded)."""
        resp = client.get(
            "/api/v1/accounts/",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 19
        codes = {a["code"] for a in data}
        assert "1001" in codes
        assert "1002" in codes
        assert "5001" in codes

    def test_list_accounts_sorted_by_code(self, client, auth_headers, ledger_headers):
        """Accounts should be returned sorted by code."""
        resp = client.get(
            "/api/v1/accounts/",
            headers={**auth_headers, **ledger_headers},
        )
        codes = [a["code"] for a in resp.json()]
        assert codes == sorted(codes)

    def test_list_accounts_requires_ledger_header(self, client, auth_headers):
        """Missing X-Ledger-Id should return 400."""
        resp = client.get(
            "/api/v1/accounts/",
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestCreateAccount:
    """Test POST /accounts/ — create a new account."""

    def test_create_top_level_account(self, client, auth_headers, ledger_headers):
        """Create a top-level account with explicit type and direction."""
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "code": "1701",
                "name": "无形资产",
                "account_type": "ASSET",
                "balance_direction": "DEBIT",
                "opening_balance": 0,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "1701"
        assert data["name"] == "无形资产"
        assert data["account_type"] == "ASSET"
        assert data["balance_direction"] == "DEBIT"

    def test_create_sub_account_inherits_parent(self, client, auth_headers, ledger, ledger_headers):
        """Sub-account inherits type and direction from parent."""
        # Find 6602 管理费用 as parent
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "code": "660201",
                "name": "管理费用-办公费",
                "parent_id": None,  # will need to set it
                "opening_balance": 0,
            },
            headers={**auth_headers, **ledger_headers},
        )
        # Find the parent by querying
        resp_list = client.get("/api/v1/accounts/", headers={**auth_headers, **ledger_headers})
        parent = next((a for a in resp_list.json() if a["code"] == "6602"), None)
        assert parent is not None

        resp = client.post(
            "/api/v1/accounts/",
            json={
                "code": "660201",
                "name": "管理费用-办公费",
                "parent_id": parent["id"],
                "opening_balance": 1000,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "660201"
        # Should inherit parent's type and direction
        assert data["account_type"] == "PROFIT_LOSS"
        assert data["balance_direction"] == "DEBIT"
        assert data["parent_id"] == parent["id"]

    def test_create_duplicate_code_rejected(self, client, auth_headers, ledger_headers):
        """Creating an account with an existing code returns 400."""
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "code": "1001",
                "name": "重复科目",
                "account_type": "ASSET",
                "balance_direction": "DEBIT",
                "opening_balance": 0,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_create_top_level_missing_type(self, client, auth_headers, ledger_headers):
        """Top-level account without type/direction should return 400."""
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "code": "9999",
                "name": "无类型科目",
                "opening_balance": 0,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 400
        assert "account_type" in resp.json()["detail"]

    def test_create_invalid_parent(self, client, auth_headers, ledger_headers):
        """Non-existent parent_id should return 404."""
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "code": "999901",
                "name": "无效子科目",
                "parent_id": 99999,
                "opening_balance": 0,
            },
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404


class TestUpdateAccount:
    """Test PUT /accounts/{id} — update account name or opening balance."""

    def test_update_name(self, client, auth_headers, ledger, db, ledger_headers):
        """Update the name of an existing account."""
        acc = db.query(Account).filter(Account.ledger_id == ledger.id, Account.code == "1001").first()

        resp = client.put(
            f"/api/v1/accounts/{acc.id}",
            json={"name": "库存现金-更新"},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "库存现金-更新"
        assert data["code"] == "1001"

    def test_update_opening_balance(self, client, auth_headers, ledger, db, ledger_headers):
        """Update the opening balance of an account."""
        acc = db.query(Account).filter(Account.ledger_id == ledger.id, Account.code == "1002").first()

        resp = client.put(
            f"/api/v1/accounts/{acc.id}",
            json={"opening_balance": 50000},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["opening_balance"]) == 50000.0

    def test_update_nonexistent_account(self, client, auth_headers, ledger_headers):
        """Updating a non-existent account returns 404."""
        resp = client.put(
            "/api/v1/accounts/99999",
            json={"name": "不存在"},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404


class TestTrialBalance:
    """Test GET /accounts/trial-balance — check debit/credit balance."""

    def test_trial_balance_all_zero(self, client, auth_headers, ledger, ledger_headers):
        """All zero opening balances → balanced."""
        resp = client.get(
            "/api/v1/accounts/trial-balance",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_debit"] == 0
        assert data["total_credit"] == 0
        assert data["is_balanced"] is True
        assert data["difference"] == 0

    def test_trial_balance_unbalanced(self, client, auth_headers, ledger, db, ledger_headers):
        """Non-zero opening balances that don't balance → is_balanced=False."""
        # Set opening balance on an asset account (debit) but no matching credit
        acc = db.query(Account).filter(Account.ledger_id == ledger.id, Account.code == "1001").first()
        acc.opening_balance = Decimal("10000")
        db.commit()

        resp = client.get(
            "/api/v1/accounts/trial-balance",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_debit"] == 10000
        assert data["total_credit"] == 0
        assert data["is_balanced"] is False
        assert data["difference"] == 10000

    def test_trial_balance_balanced(self, client, auth_headers, ledger, db, ledger_headers):
        """Equal debit and credit opening balances → balanced."""
        # Debit account (asset)
        acc1 = db.query(Account).filter(Account.ledger_id == ledger.id, Account.code == "1001").first()
        acc1.opening_balance = Decimal("10000")
        # Credit account (equity)
        acc2 = db.query(Account).filter(Account.ledger_id == ledger.id, Account.code == "4001").first()
        acc2.opening_balance = Decimal("10000")
        db.commit()

        resp = client.get(
            "/api/v1/accounts/trial-balance",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_balanced"] is True
        assert data["difference"] == 0


class TestDeleteAccount:
    """Test DELETE /accounts/{id} — delete an account."""

    def test_delete_leaf_account(self, client, auth_headers, ledger, db, ledger_headers):
        """Delete a leaf account with no children and no voucher entries."""
        # Create a temporary leaf account
        acc = Account(
            ledger_id=ledger.id,
            code="9998",
            name="临时科目",
            account_type=AccountType.ASSET,
            balance_direction=AccountDirection.DEBIT,
            opening_balance=0,
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)

        resp = client.delete(
            f"/api/v1/accounts/{acc.id}",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        assert "successfully deleted" in resp.json()["message"]

        # Verify it's gone
        db.expire_all()
        assert db.query(Account).filter(Account.id == acc.id).first() is None

    def test_delete_account_with_children(self, client, auth_headers, ledger_headers):
        """Cannot delete an account that has child accounts."""
        # The ledger fixture has 19 top-level accounts which are all leaf nodes.
        # We need to create a parent with a child.
        resp_list = client.get("/api/v1/accounts/", headers={**auth_headers, **ledger_headers})
        parent = next(a for a in resp_list.json() if a["code"] == "6602")

        # Create a child under 6602
        client.post(
            "/api/v1/accounts/",
            json={"code": "660299", "name": "测试子科目", "parent_id": parent["id"], "opening_balance": 0},
            headers={**auth_headers, **ledger_headers},
        )

        # Now try to delete the parent
        resp = client.delete(
            f"/api/v1/accounts/{parent['id']}",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 400
        assert "子科目" in resp.json()["detail"]

    def test_delete_account_with_entries(self, client, auth_headers, ledger, db, ledger_headers, posted_voucher):
        """Cannot delete an account referenced by voucher entries."""
        # 1002 was used in posted_voucher
        acc = db.query(Account).filter(Account.ledger_id == ledger.id, Account.code == "1002").first()

        resp = client.delete(
            f"/api/v1/accounts/{acc.id}",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 400
        assert "删除" in resp.json()["detail"] or "封锁" in resp.json()["detail"]

    def test_delete_nonexistent_account(self, client, auth_headers, ledger_headers):
        """Deleting a non-existent account returns 404."""
        resp = client.delete(
            "/api/v1/accounts/99999",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404
