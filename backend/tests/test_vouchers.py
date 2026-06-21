"""Tests for voucher CRUD, posting, reversal, and validation."""

from datetime import date
from decimal import Decimal

from app.models.financial import (
    Voucher, VoucherEntry, VoucherStatus,
    Account, AccountDirection,
)


class TestCreateVoucher:
    def test_create_draft_voucher(self, client, ledger_id):
        resp = client.post(
            "/api/v1/vouchers/",
            json={
                "voucher_date": "2024-01-15",
                "entries": [
                    {
                        "account_code": "1002",
                        "summary": "测试借方",
                        "direction": "借",
                        "amount": 1000.0,
                    },
                    {
                        "account_code": "4001",
                        "summary": "测试贷方",
                        "direction": "贷",
                        "amount": 1000.0,
                    },
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "DRAFT"
        assert data["voucher_number"].startswith("记-")

    def test_debit_credit_must_balance(self, client, ledger_id):
        resp = client.post(
            "/api/v1/vouchers/",
            json={
                "voucher_date": "2024-01-15",
                "entries": [
                    {"account_code": "1002", "summary": "借", "direction": "借", "amount": 1000.0},
                    {"account_code": "4001", "summary": "贷", "direction": "贷", "amount": 500.0},
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 400
        assert "equal" in resp.json()["detail"]

    def test_must_have_at_least_2_entries(self, client, ledger_id):
        resp = client.post(
            "/api/v1/vouchers/",
            json={
                "voucher_date": "2024-01-15",
                "entries": [
                    {"account_code": "1002", "summary": "借", "direction": "借", "amount": 1000.0},
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 400

    def test_invalid_direction_rejected(self, client, ledger_id):
        resp = client.post(
            "/api/v1/vouchers/",
            json={
                "voucher_date": "2024-01-15",
                "entries": [
                    {"account_code": "1002", "summary": "坏", "direction": "坏", "amount": 1000.0},
                    {"account_code": "4001", "summary": "坏", "direction": "好", "amount": 1000.0},
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 422  # Pydantic validation error

    def test_zero_amount_rejected(self, client, ledger_id):
        resp = client.post(
            "/api/v1/vouchers/",
            json={
                "voucher_date": "2024-01-15",
                "entries": [
                    {"account_code": "1002", "summary": "零", "direction": "借", "amount": 0},
                    {"account_code": "4001", "summary": "零", "direction": "贷", "amount": 0},
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 422

    def test_invalid_account_rejected(self, client, ledger_id):
        resp = client.post(
            "/api/v1/vouchers/",
            json={
                "voucher_date": "2024-01-15",
                "entries": [
                    {"account_code": "9999", "summary": "不存在", "direction": "借", "amount": 1000.0},
                    {"account_code": "4001", "summary": "贷", "direction": "贷", "amount": 1000.0},
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]


class TestVoucherLifecycle:
    def test_post_draft_voucher(self, client, db, ledger, ledger_id):
        """Draft -> POSTED."""
        v = Voucher(
            ledger_id=ledger_id,
            voucher_number="记-post",
            voucher_date=date(2024, 1, 10),
            status=VoucherStatus.DRAFT,
        )
        db.add(v)
        db.flush()
        bank = db.query(Account).filter(
            Account.ledger_id == ledger_id, Account.code == "1002"
        ).first()
        capital = db.query(Account).filter(
            Account.ledger_id == ledger_id, Account.code == "4001"
        ).first()
        db.add(VoucherEntry(voucher_id=v.id, account_id=bank.id, summary="test",
            direction=AccountDirection.DEBIT, amount=100.0))
        db.add(VoucherEntry(voucher_id=v.id, account_id=capital.id, summary="test",
            direction=AccountDirection.CREDIT, amount=100.0))
        db.commit()

        resp = client.post(
            f"/api/v1/vouchers/{v.id}/post",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "POSTED"

    def test_cannot_post_already_posted(self, client, db, ledger, ledger_id):
        v = Voucher(
            ledger_id=ledger_id,
            voucher_number="记-posted",
            voucher_date=date(2024, 1, 10),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()
        bank = db.query(Account).filter(
            Account.ledger_id == ledger_id, Account.code == "1002"
        ).first()
        db.add(VoucherEntry(voucher_id=v.id, account_id=bank.id, summary="x",
            direction=AccountDirection.DEBIT, amount=100.0))
        db.add(VoucherEntry(voucher_id=v.id, account_id=bank.id, summary="x",
            direction=AccountDirection.CREDIT, amount=100.0))
        db.commit()

        resp = client.post(
            f"/api/v1/vouchers/{v.id}/post",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 400

    def test_unpost_voucher(self, client, db, ledger, ledger_id):
        v = Voucher(
            ledger_id=ledger_id,
            voucher_number="记-posted2",
            voucher_date=date(2024, 1, 10),
            status=VoucherStatus.POSTED,
        )
        db.add(v)
        db.flush()
        bank = db.query(Account).filter(
            Account.ledger_id == ledger_id, Account.code == "1002"
        ).first()
        db.add(VoucherEntry(voucher_id=v.id, account_id=bank.id, summary="x",
            direction=AccountDirection.DEBIT, amount=100.0))
        db.add(VoucherEntry(voucher_id=v.id, account_id=bank.id, summary="x",
            direction=AccountDirection.CREDIT, amount=100.0))
        db.commit()

        resp = client.post(
            f"/api/v1/vouchers/{v.id}/unpost",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        assert "draft" in resp.json()["message"].lower()


class TestReverseVoucher:
    def test_reverse_uses_opposite_direction(self, client, db, ledger, ledger_id, posted_voucher):
        """Reversal should create entries with opposite direction and same amount."""
        from app.models.financial import AccountingPeriod, PeriodStatus
        from datetime import date as dt_date
        today = dt_date.today()
        if not db.query(AccountingPeriod).filter(
            AccountingPeriod.ledger_id == ledger_id,
            AccountingPeriod.year == today.year,
            AccountingPeriod.month == today.month,
        ).first():
            db.add(AccountingPeriod(ledger_id=ledger_id, year=today.year, month=today.month, status=PeriodStatus.OPEN))
            db.commit()

        resp = client.post(
            f"/api/v1/vouchers/{posted_voucher.id}/reverse",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200

        # Verify the reversal voucher exists in DB
        # The router creates a sequential number (记-2, 记-3, etc.) and marks source_type
        reversal = (
            db.query(Voucher)
            .filter(Voucher.source_type == f"REVERSAL of {posted_voucher.voucher_number}")
            .first()
        )
        assert reversal is not None, f"Reversal voucher not found for {posted_voucher.voucher_number}"
        assert reversal.status == VoucherStatus.DRAFT

        # Check entry directions are reversed
        for entry in reversal.entries:
            assert float(entry.amount) > 0  # no negative amounts
            # Original was DEBIT, reversal should be CREDIT (or vice versa)
            original_entries = [
                e for e in posted_voucher.entries
                if e.account_id == entry.account_id
            ]
            if original_entries:
                assert entry.direction != original_entries[0].direction


class TestUpdateDraftVoucher:
    def test_cannot_update_posted_voucher(self, client, db, ledger, ledger_id, posted_voucher):
        resp = client.put(
            f"/api/v1/vouchers/{posted_voucher.id}",
            json={
                "entries": [
                    {"account_code": "1002", "summary": "改", "direction": "借", "amount": 500.0},
                    {"account_code": "4001", "summary": "改", "direction": "贷", "amount": 500.0},
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 400
        assert "DRAFT" in resp.json()["detail"]

    def test_update_draft_succeeds(self, client, db, ledger, ledger_id):
        v = Voucher(
            ledger_id=ledger_id,
            voucher_number="记-draft-upd",
            voucher_date=date(2024, 1, 10),
            status=VoucherStatus.DRAFT,
        )
        db.add(v)
        db.commit()

        resp = client.put(
            f"/api/v1/vouchers/{v.id}",
            json={
                "entries": [
                    {"account_code": "1002", "summary": "新摘要", "direction": "借", "amount": 500.0},
                    {"account_code": "4001", "summary": "新摘要", "direction": "贷", "amount": 500.0},
                ],
            },
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200


class TestLedgerIsolation:
    def test_list_vouchers_isolated_by_ledger(self, client, db, ledger_id):
        """Vouchers from one ledger must not leak into another."""
        from app.models.financial import (
            Ledger, AccountingPeriod, PeriodStatus,
            Voucher, VoucherEntry, VoucherStatus,
            Account, AccountType, AccountDirection,
        )

        ledger2 = Ledger(
            name="Other Company", company_name="Other Corp",
            base_currency="USD", start_year=2024, start_month=1,
        )
        db.add(ledger2)
        db.commit()
        db.refresh(ledger2)

        period2 = AccountingPeriod(
            ledger_id=ledger2.id, year=2024, month=1, status=PeriodStatus.OPEN
        )
        db.add(period2)
        db.commit()

        acc = Account(
            ledger_id=ledger2.id, code="1001", name="Cash",
            account_type=AccountType.ASSET, balance_direction=AccountDirection.DEBIT,
        )
        db.add(acc)
        db.commit()

        v2 = Voucher(
            ledger_id=ledger2.id, voucher_number="记-iso",
            voucher_date=date(2024, 6, 15), status=VoucherStatus.DRAFT,
        )
        db.add(v2)
        db.flush()
        db.add(VoucherEntry(voucher_id=v2.id, account_id=acc.id, summary="x",
            direction=AccountDirection.DEBIT, amount=50.0))
        db.add(VoucherEntry(voucher_id=v2.id, account_id=acc.id, summary="x",
            direction=AccountDirection.CREDIT, amount=50.0))
        db.commit()

        resp = client.get(
            "/api/v1/vouchers/",
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        ledger2_ids = [v["id"] for v in resp.json()["items"] if v["id"] == v2.id]
        assert len(ledger2_ids) == 0, "Voucher from another ledger leaked into list"


class TestBatchReview:
    def test_batch_review_all_draft(self, client, db, ledger, ledger_id):
        """Batch review should post all DRAFT vouchers."""
        from app.models.financial import AccountingPeriod, PeriodStatus

        v1 = Voucher(ledger_id=ledger_id, voucher_number="记-br-1", voucher_date=date(2024, 1, 10), status=VoucherStatus.DRAFT)
        v2 = Voucher(ledger_id=ledger_id, voucher_number="记-br-2", voucher_date=date(2024, 1, 10), status=VoucherStatus.DRAFT)
        db.add_all([v1, v2])
        db.flush()
        for v in [v1, v2]:
            bank = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "1002").first()
            db.add(VoucherEntry(voucher_id=v.id, account_id=bank.id, summary="x", direction=AccountDirection.DEBIT, amount=100.0))
            db.add(VoucherEntry(voucher_id=v.id, account_id=bank.id, summary="x", direction=AccountDirection.CREDIT, amount=100.0))
        db.commit()

        resp = client.post(
            "/api/v1/vouchers/batch-review",
            json={"voucher_ids": [v1.id, v2.id]},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reviewed_count"] == 2
        assert data["failed_count"] == 0
        assert data["errors"] == []

    def test_batch_review_mixed_status(self, client, db, ledger, ledger_id, posted_voucher):
        """Batch review with mixed DRAFT + POSTED should partially succeed."""
        v_draft = Voucher(ledger_id=ledger_id, voucher_number="记-br-draft", voucher_date=date(2024, 1, 10), status=VoucherStatus.DRAFT)
        db.add(v_draft)
        db.flush()
        bank = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "1002").first()
        db.add(VoucherEntry(voucher_id=v_draft.id, account_id=bank.id, summary="x", direction=AccountDirection.DEBIT, amount=100.0))
        db.add(VoucherEntry(voucher_id=v_draft.id, account_id=bank.id, summary="x", direction=AccountDirection.CREDIT, amount=100.0))
        db.commit()

        resp = client.post(
            "/api/v1/vouchers/batch-review",
            json={"voucher_ids": [v_draft.id, posted_voucher.id]},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reviewed_count"] == 1
        assert data["failed_count"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["id"] == posted_voucher.id

    def test_batch_review_empty_list(self, client, ledger_id):
        """Empty voucher_ids should be rejected (422)."""
        resp = client.post(
            "/api/v1/vouchers/batch-review",
            json={"voucher_ids": []},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 422


class TestBatchUnpost:
    def test_batch_unpost_all_posted(self, client, db, ledger, ledger_id, posted_voucher):
        """Batch unpost should return all POSTED vouchers to DRAFT."""
        v2 = Voucher(ledger_id=ledger_id, voucher_number="记-bu-2", voucher_date=date(2024, 1, 10), status=VoucherStatus.POSTED)
        db.add(v2)
        db.flush()
        bank = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "1002").first()
        db.add(VoucherEntry(voucher_id=v2.id, account_id=bank.id, summary="x", direction=AccountDirection.DEBIT, amount=100.0))
        db.add(VoucherEntry(voucher_id=v2.id, account_id=bank.id, summary="x", direction=AccountDirection.CREDIT, amount=100.0))
        db.commit()

        resp = client.post(
            "/api/v1/vouchers/batch-unpost",
            json={"voucher_ids": [posted_voucher.id, v2.id]},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["unposted_count"] == 2
        assert data["failed_count"] == 0

    def test_batch_unpost_already_draft(self, client, db, ledger, ledger_id, posted_voucher):
        """Batch unpost with a DRAFT voucher should report it as failed."""
        v_draft = Voucher(ledger_id=ledger_id, voucher_number="记-bu-draft", voucher_date=date(2024, 1, 10), status=VoucherStatus.DRAFT)
        db.add(v_draft)
        db.flush()
        bank = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "1002").first()
        db.add(VoucherEntry(voucher_id=v_draft.id, account_id=bank.id, summary="x", direction=AccountDirection.DEBIT, amount=100.0))
        db.add(VoucherEntry(voucher_id=v_draft.id, account_id=bank.id, summary="x", direction=AccountDirection.CREDIT, amount=100.0))
        db.commit()

        resp = client.post(
            "/api/v1/vouchers/batch-unpost",
            json={"voucher_ids": [posted_voucher.id, v_draft.id]},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["unposted_count"] == 1
        assert data["failed_count"] == 1
        assert data["errors"][0]["id"] == v_draft.id

    def test_batch_unpost_empty_list(self, client, ledger_id):
        """Empty voucher_ids should be rejected (422)."""
        resp = client.post(
            "/api/v1/vouchers/batch-unpost",
            json={"voucher_ids": []},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 422
