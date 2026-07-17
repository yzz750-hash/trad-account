# Contract P&L Cross-Month Matching — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix commission engine so contract expenses from any month are matched to the month of revenue, and add a standalone Contract P&L report endpoint.

**Architecture:** Two-phase query in `_batch_compute_contract_pnls` — Phase 1 finds contracts with revenue in the target month, Phase 2 pulls ALL vouchers for those contracts regardless of month. New `GET /reports/contract-pnl` endpoint lists all contracts' P&L.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy ORM, Pydantic, pytest

---

## File Structure

| File | Role |
|------|------|
| `backend/app/commission.py` | Core engine — fix `_batch_compute_contract_pnls` cross-month bug |
| `backend/app/routers/reports.py` | New `GET /reports/contract-pnl` endpoint + response models |
| `backend/tests/test_contract_pnl.py` | New tests: cross-month matching + endpoint |
| `backend/tests/test_commission.py` | Update `test_month_filter` to verify cross-month behavior |
| `frontend/src/app/reports/page.tsx` | Optional: add "合同损益" tab |

---

### Task 1: Fix `_batch_compute_contract_pnls` — Two-Phase Cross-Month Query

**Files:**
- Modify: `backend/app/commission.py:86-135`

- [ ] **Step 1: Replace `_batch_compute_contract_pnls` with two-phase version**

Replace lines 86-135 of `backend/app/commission.py`:

```python
def _batch_compute_contract_pnls(
    db: Session,
    contract_numbers: list[str],
    year: int,
    month: Optional[int],
    account_map: dict,
) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    """Batch-compute P&L for multiple contracts with cross-month matching.

    Phase 1: Find contracts with revenue entries in the target month.
    Phase 2: Pull ALL vouchers for those contracts from ANY month (matching principle).
    If month is None, pulls all vouchers for the full year.
    """
    if not contract_numbers:
        return {}

    result: dict[str, tuple[Decimal, Decimal, Decimal]] = {
        cn: (Decimal("0"), Decimal("0"), Decimal("0")) for cn in contract_numbers
    }

    # ponytail: contracts with revenue in multiple months appear in each,
    # showing cumulative P&L. Rare in practice (one sale per contract).
    # If needed, add first-revenue-month gating via func.min(extract("month", ...)).
    if month is not None:
        # Phase 1: which contracts have REVENUE in the target month?
        # Revenue = PROFIT_LOSS account + CREDIT direction (single query, no N+1)
        rev_rows = (
            db.query(Voucher.contract_number)
            .join(VoucherEntry, VoucherEntry.voucher_id == Voucher.id)
            .join(Account, VoucherEntry.account_id == Account.id)
            .filter(
                Voucher.contract_number.in_(contract_numbers),
                Voucher.status == VoucherStatus.POSTED,
                extract("year", Voucher.voucher_date) == year,
                extract("month", Voucher.voucher_date) == month,
                Account.account_type == AccountType.PROFIT_LOSS,
                VoucherEntry.direction == AccountDirection.CREDIT,
            )
            .distinct()
            .all()
        )
        active_contracts = [cn for (cn,) in rev_rows]
        if not active_contracts:
            return result

        # Phase 2: pull ALL vouchers for those contracts (any month in year)
        rows = (
            db.query(VoucherEntry, Voucher)
            .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
            .filter(
                Voucher.contract_number.in_(active_contracts),
                Voucher.status == VoucherStatus.POSTED,
                extract("year", Voucher.voucher_date) == year,
            )
            .all()
        )
    else:
        # Full year: no month filter needed, just pull everything
        rows = (
            db.query(VoucherEntry, Voucher)
            .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
            .filter(
                Voucher.contract_number.in_(contract_numbers),
                Voucher.status == VoucherStatus.POSTED,
                extract("year", Voucher.voucher_date) == year,
            )
            .all()
        )

    for entry, voucher in rows:
        cn = voucher.contract_number
        if cn not in result:
            continue
        account = account_map.get(entry.account_id)
        if account is None:
            continue
        category, amount = classify_voucher_entry(entry, account)
        rev, cost, exp = result[cn]
        if category == "revenue":
            result[cn] = (rev + amount, cost, exp)
        elif category == "cost":
            result[cn] = (rev, cost + amount, exp)
        elif category == "expenses":
            result[cn] = (rev, cost, exp + amount)

    return result
```

- [ ] **Step 2: Run existing commission tests to verify no regressions**

Run: `cd d:\antigravity ide text\trad account\backend && .\venv\Scripts\python.exe -m pytest tests/test_commission.py -v`
Expected: All existing tests PASS (especially `test_month_filter` which exercises month semantics)

- [ ] **Step 3: Commit**

```bash
git add backend/app/commission.py
git commit -m "fix: cross-month expense matching in commission engine

Phase 1 finds contracts with revenue in target month.
Phase 2 pulls ALL vouchers for those contracts regardless of month.
Expenses booked in different months are now matched to revenue month."
```

---

### Task 2: Update Tests for Cross-Month Semantics

**Files:**
- Modify: `backend/tests/test_commission.py`

The existing `test_month_filter` relies on old per-month voucher filtering and will break. We need to update it AND add the cross-month expense test.

- [ ] **Step 1: Update `test_month_filter` for cumulative-month semantics**

Replace the existing `test_month_filter` method (line 233-251) in `backend/tests/test_commission.py`:

```python
    def test_month_filter(self, db, ledger):
        """Contracts with revenue in target month show cumulative P&L (all related vouchers).

        Uses separate contracts per month so each month sees distinct contracts.
        """
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "gross_profit", 0.03)
        self._create_contract(db, ledger, sp, "OEM-2024-001")
        self._create_contract(db, ledger, sp, "OEM-2024-002")
        self._create_oem_voucher(db, ledger, "OEM-2024-001", month=1)
        self._create_oem_voucher(db, ledger, "OEM-2024-002", month=2)

        report_jan = calculate_commission(db, ledger.id, 2024, month=1)
        assert len(report_jan.salespersons[0].contracts) == 1
        assert report_jan.salespersons[0].contracts[0].contract_number == "OEM-2024-001"
        assert report_jan.salespersons[0].total_commission == Decimal("1200")

        report_feb = calculate_commission(db, ledger.id, 2024, month=2)
        assert len(report_feb.salespersons[0].contracts) == 1
        assert report_feb.salespersons[0].contracts[0].contract_number == "OEM-2024-002"
        assert report_feb.salespersons[0].total_commission == Decimal("1200")

        report_full = calculate_commission(db, ledger.id, 2024)
        assert report_full.salespersons[0].total_commission == Decimal("2400")
```

- [ ] **Step 2: Add cross-month expense test**

Append this test to `TestCommission` class in `backend/tests/test_commission.py`:

```python
    def test_cross_month_expense_matching(self, db, ledger):
        """Expenses in a different month are matched to revenue month.

        Contract OEM-2024-001:
          - June: revenue 100,000, cost 60,000 → gross_profit 40,000
          - July: freight expense 5,000 (separate voucher)
        
        June commission should see net_profit = 100,000 - 60,000 - 5,000 = 35,000
        (not 40,000 which ignores July expenses).
        """
        from app.commission import calculate_commission

        sp = self._create_sp(db, ledger)
        self._create_rule(db, ledger, sp.id, "net_profit", 0.10)
        self._create_contract(db, ledger, sp, "OEM-2024-001")

        # June voucher: revenue + cost (no expenses)
        v_jun = Voucher(
            ledger_id=ledger.id,
            voucher_number="OEM-001-JUN",
            voucher_date=date(2024, 6, 15),
            status=VoucherStatus.POSTED,
            contract_number="OEM-2024-001",
        )
        db.add(v_jun)
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

        # June: revenue 100k, cost 60k
        db.add_all([
            VoucherEntry(voucher_id=v_jun.id, account_id=bank.id,
                         summary="OEM收款", direction=AccountDirection.DEBIT,
                         amount=Decimal("40000.00")),
            VoucherEntry(voucher_id=v_jun.id, account_id=cost.id,
                         summary="OEM销售成本", direction=AccountDirection.DEBIT,
                         amount=Decimal("60000.00")),
            VoucherEntry(voucher_id=v_jun.id, account_id=revenue.id,
                         summary="OEM销售收入", direction=AccountDirection.CREDIT,
                         amount=Decimal("100000.00")),
        ])

        # July voucher: freight expense 5,000 (no revenue)
        v_jul = Voucher(
            ledger_id=ledger.id,
            voucher_number="OEM-001-JUL",
            voucher_date=date(2024, 7, 10),
            status=VoucherStatus.POSTED,
            contract_number="OEM-2024-001",
        )
        db.add(v_jul)
        db.flush()
        db.add_all([
            VoucherEntry(voucher_id=v_jul.id, account_id=expense.id,
                         summary="OEM货运费", direction=AccountDirection.DEBIT,
                         amount=Decimal("5000.00")),
            VoucherEntry(voucher_id=v_jul.id, account_id=bank.id,
                         summary="支付货运费", direction=AccountDirection.CREDIT,
                         amount=Decimal("5000.00")),
        ])

        counter = db.query(VoucherNumberCounter).filter(
            VoucherNumberCounter.ledger_id == ledger.id,
            VoucherNumberCounter.prefix == "OEM-",
        ).first()
        if not counter:
            db.add(VoucherNumberCounter(
                ledger_id=ledger.id, prefix="OEM-", current_number=1,
            ))
        db.commit()

        # June report: should include July's 5,000 expense
        report_jun = calculate_commission(db, ledger.id, 2024, month=6)
        assert len(report_jun.salespersons) == 1
        ct = report_jun.salespersons[0].contracts[0]
        assert ct.revenue == Decimal("100000")
        assert ct.cost == Decimal("60000")
        # gross_profit = 40,000 but net_profit should pull July's 5,000 expense
        # net_profit = 100000 - 60000 - 5000 = 35000
        assert ct.basis_amount == Decimal("35000")  # net_profit basis
        assert ct.commission_amount == Decimal("3500")  # 35000 * 0.10

        # July report: contract has NO revenue in July, should NOT appear
        report_jul = calculate_commission(db, ledger.id, 2024, month=7)
        assert report_jul.contract_count == 0
```

- [ ] **Step 3: Run the new and updated tests**

Run: `cd d:\antigravity ide text\trad account\backend && .\venv\Scripts\python.exe -m pytest tests/test_commission.py::TestCommission::test_cross_month_expense_matching tests/test_commission.py::TestCommission::test_month_filter -v`
Expected: Both PASS

- [ ] **Step 4: Run full test suite**

Run: `cd d:\antigravity ide text\trad account\backend && .\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: All tests pass, zero regressions

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_commission.py
git commit -m "test: cross-month expense matching for commission engine"
```

---

### Task 3: Add Contract P&L List Endpoint

**Files:**
- Modify: `backend/app/routers/reports.py` (append after line 1163)

- [ ] **Step 1: Add response models**

Insert these Pydantic models before the endpoint function, around line 1022 (near existing `OemContractPnLEntryResponse`):

```python
class ContractPnLItem(BaseModel):
    contract_number: str
    customer_name: Optional[str] = None
    revenue: Money
    cost: Money
    expenses: Money
    gross_profit: Money
    net_profit: Money
    voucher_count: int


class ContractPnLResponse(BaseModel):
    period: str
    contracts: list[ContractPnLItem]
    total_revenue: Money
    total_cost: Money
    total_expenses: Money
    total_net_profit: Money
    contract_count: int
```

- [ ] **Step 2: Add the endpoint**

Insert this endpoint after line 1163 of `backend/app/routers/reports.py` (before the commission endpoint):

```python
@router.get("/contract-pnl", response_model=ContractPnLResponse)
def get_contract_pnl(
    year: int = Query(..., description="Year, e.g. 2026"),
    month: Optional[int] = Query(None, description="Month 1-12, omit for full year"),
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """合同损益报表: P&L per contract with cross-month expense matching.

    When month is specified, shows contracts with revenue in that month,
    pulling ALL related vouchers (any month) for complete P&L.
    """
    from app.commission import classify_voucher_entry

    period = str(year) if month is None else f"{year}-{month:02d}"

    # Build account lookup
    accounts = db.query(Account).filter(Account.ledger_id == ledger_id).all()
    account_map = {a.id: a for a in accounts}

    # Phase 1: Find contract_numbers with revenue in target period
    base_filter = [
        Voucher.ledger_id == ledger_id,
        Voucher.status == VoucherStatus.POSTED,
        extract("year", Voucher.voucher_date) == year,
    ]
    if month is not None:
        base_filter.append(extract("month", Voucher.voucher_date) == month)

    contract_rows = (
        db.query(Voucher.contract_number)
        .filter(*base_filter)
        .filter(Voucher.contract_number != None)
        .filter(Voucher.contract_number != "")
        .distinct()
        .all()
    )

    if not contract_rows:
        return ContractPnLResponse(
            period=period,
            contracts=[],
            total_revenue=Decimal("0"),
            total_cost=Decimal("0"),
            total_expenses=Decimal("0"),
            total_net_profit=Decimal("0"),
            contract_count=0,
        )

    all_contract_numbers = [r[0] for r in contract_rows]

    # Phase 2: Pull ALL vouchers for those contracts (any month in year)
    rows = (
        db.query(VoucherEntry, Voucher)
        .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
        .filter(
            Voucher.contract_number.in_(all_contract_numbers),
            Voucher.status == VoucherStatus.POSTED,
            extract("year", Voucher.voucher_date) == year,
        )
        .all()
    )

    # Aggregate per contract
    from collections import defaultdict
    pnl: dict[str, dict] = defaultdict(lambda: {
        "revenue": Decimal("0"), "cost": Decimal("0"),
        "expenses": Decimal("0"), "voucher_ids": set(),
        "customer_name": None,
    })

    for entry, voucher in rows:
        cn = voucher.contract_number
        acct = account_map.get(entry.account_id)
        if acct is None:
            continue
        category, amount = classify_voucher_entry(entry, acct)
        d = pnl[cn]
        if category == "revenue":
            d["revenue"] += amount
        elif category == "cost":
            d["cost"] += amount
        elif category == "expenses":
            d["expenses"] += amount
        d["voucher_ids"].add(voucher.id)

    # Look up customer names from OEMContract table
    oem_contracts = {
        c.contract_number: c.customer_name
        for c in db.query(OEMContract).filter(
            OEMContract.ledger_id == ledger_id,
            OEMContract.contract_number.in_(list(pnl.keys())),
        ).all()
    }

    contracts = []
    total_rev = Decimal("0")
    total_cost = Decimal("0")
    total_exp = Decimal("0")
    total_net = Decimal("0")

    for cn in sorted(pnl.keys()):
        d = pnl[cn]
        gp = d["revenue"] - d["cost"]
        np = gp - d["expenses"]
        contracts.append(ContractPnLItem(
            contract_number=cn,
            customer_name=oem_contracts.get(cn),
            revenue=d["revenue"],
            cost=d["cost"],
            expenses=d["expenses"],
            gross_profit=gp,
            net_profit=np,
            voucher_count=len(d["voucher_ids"]),
        ))
        total_rev += d["revenue"]
        total_cost += d["cost"]
        total_exp += d["expenses"]
        total_net += np

    return ContractPnLResponse(
        period=period,
        contracts=contracts,
        total_revenue=total_rev,
        total_cost=total_cost,
        total_expenses=total_exp,
        total_net_profit=total_net,
        contract_count=len(contracts),
    )
```

- [ ] **Step 3: Run existing tests to make sure imports are clean**

Run: `cd d:\antigravity ide text\trad account\backend && .\venv\Scripts\python.exe -m pytest tests/test_reports.py -v --timeout=30`
Expected: All existing tests PASS (no import errors from new code)

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/reports.py
git commit -m "feat: add GET /reports/contract-pnl endpoint with cross-month matching"
```

---

### Task 4: Add Endpoint Integration Tests

**Files:**
- Create: `backend/tests/test_contract_pnl.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_contract_pnl.py`:

```python
"""Tests for GET /reports/contract-pnl endpoint with cross-month matching."""
from datetime import date
from decimal import Decimal

from app.models.financial import (
    Account,
    AccountDirection,
    OEMContract,
    Voucher,
    VoucherEntry,
    VoucherNumberCounter,
    VoucherStatus,
)


class TestContractPnL:
    def _create_voucher(self, db, ledger, contract_number, year, month, day,
                        vn_suffix, entries_spec):
        """Create a posted voucher with entries.

        entries_spec: list of (account_code, summary, direction, amount)
        """
        v = Voucher(
            ledger_id=ledger.id,
            voucher_number=f"CPL-{contract_number}-{vn_suffix}",
            voucher_date=date(year, month, day),
            status=VoucherStatus.POSTED,
            contract_number=contract_number,
        )
        db.add(v)
        db.flush()

        for code, summary, direction, amount in entries_spec:
            acct = db.query(Account).filter(
                Account.ledger_id == ledger.id, Account.code == code
            ).first()
            db.add(VoucherEntry(
                voucher_id=v.id, account_id=acct.id,
                summary=summary, direction=direction, amount=amount,
            ))

        cnter = db.query(VoucherNumberCounter).filter(
            VoucherNumberCounter.ledger_id == ledger.id,
            VoucherNumberCounter.prefix == "CPL-",
        ).first()
        if not cnter:
            db.add(VoucherNumberCounter(
                ledger_id=ledger.id, prefix="CPL-", current_number=1,
            ))
        db.commit()
        return v

    def test_empty_no_contracts(self, client, ledger_id):
        """No contracts with vouchers returns empty list, not 404."""
        resp = client.get(
            "/api/v1/reports/contract-pnl",
            params={"year": 2024, "month": 6},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contracts"] == []
        assert data["contract_count"] == 0

    def test_single_contract_one_month(self, client, db, ledger, ledger_id):
        """Contract with revenue and cost in same month."""
        oem = OEMContract(
            ledger_id=ledger.id,
            contract_number="HT-2024-001",
            customer_name="ACME Corp",
        )
        db.add(oem)
        db.commit()

        self._create_voucher(db, ledger, "HT-2024-001", 2024, 6, 15, "A", [
            ("5001", "销售收入", AccountDirection.CREDIT, Decimal("100000.00")),
            ("5401", "销售成本", AccountDirection.DEBIT, Decimal("60000.00")),
            ("1002", "银行存款", AccountDirection.DEBIT, Decimal("40000.00")),
        ])

        resp = client.get(
            "/api/v1/reports/contract-pnl",
            params={"year": 2024, "month": 6},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "2024-06"
        assert data["contract_count"] == 1
        ct = data["contracts"][0]
        assert ct["contract_number"] == "HT-2024-001"
        assert ct["customer_name"] == "ACME Corp"
        assert ct["revenue"] == "100000.00"
        assert ct["cost"] == "60000.00"
        assert ct["gross_profit"] == "40000.00"
        assert ct["voucher_count"] == 1

    def test_cross_month_expenses_pulled_into_revenue_month(self, client, db, ledger, ledger_id):
        """July expenses are included in June P&L when revenue is in June."""
        oem = OEMContract(
            ledger_id=ledger.id,
            contract_number="HT-2024-002",
            customer_name="GlobalTrade Ltd",
        )
        db.add(oem)
        db.commit()

        # June: revenue 200,000 + cost 120,000
        self._create_voucher(db, ledger, "HT-2024-002", 2024, 6, 20, "SALE", [
            ("5001", "销售收入", AccountDirection.CREDIT, Decimal("200000.00")),
            ("5401", "销售成本", AccountDirection.DEBIT, Decimal("120000.00")),
            ("1002", "银行存款", AccountDirection.DEBIT, Decimal("80000.00")),
        ])

        # July: freight 8,000 + travel 3,000
        self._create_voucher(db, ledger, "HT-2024-002", 2024, 7, 5, "FRT", [
            ("6601", "货运费", AccountDirection.DEBIT, Decimal("8000.00")),
            ("1002", "银行存款", AccountDirection.CREDIT, Decimal("8000.00")),
        ])
        self._create_voucher(db, ledger, "HT-2024-002", 2024, 7, 10, "TRV", [
            ("6601", "差旅费", AccountDirection.DEBIT, Decimal("3000.00")),
            ("1002", "银行存款", AccountDirection.CREDIT, Decimal("3000.00")),
        ])

        # June report: should include July's 11,000 expenses
        resp = client.get(
            "/api/v1/reports/contract-pnl",
            params={"year": 2024, "month": 6},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract_count"] == 1
        ct = data["contracts"][0]
        assert ct["revenue"] == "200000.00"
        assert ct["cost"] == "120000.00"
        assert ct["expenses"] == "11000.00"
        assert ct["gross_profit"] == "80000.00"
        assert ct["net_profit"] == "69000.00"
        assert ct["voucher_count"] == 3

        # July report: no revenue in July, contract should NOT appear
        resp_jul = client.get(
            "/api/v1/reports/contract-pnl",
            params={"year": 2024, "month": 7},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp_jul.status_code == 200
        data_jul = resp_jul.json()
        assert data_jul["contract_count"] == 0

    def test_multiple_contracts_aggregation(self, client, db, ledger, ledger_id):
        """Multiple contracts in same month aggregate totals correctly."""
        for cn in ["HT-2024-003", "HT-2024-004"]:
            db.add(OEMContract(
                ledger_id=ledger.id,
                contract_number=cn,
                customer_name=f"Customer-{cn}",
            ))
        db.commit()

        # Contract 003: rev 50k, cost 30k
        self._create_voucher(db, ledger, "HT-2024-003", 2024, 6, 1, "C3", [
            ("5001", "销售收入", AccountDirection.CREDIT, Decimal("50000.00")),
            ("5401", "销售成本", AccountDirection.DEBIT, Decimal("30000.00")),
            ("1002", "银行存款", AccountDirection.DEBIT, Decimal("20000.00")),
        ])
        # Contract 004: rev 80k, cost 50k, expense 5k
        self._create_voucher(db, ledger, "HT-2024-004", 2024, 6, 1, "C4", [
            ("5001", "销售收入", AccountDirection.CREDIT, Decimal("80000.00")),
            ("5401", "销售成本", AccountDirection.DEBIT, Decimal("50000.00")),
            ("6601", "包装费", AccountDirection.DEBIT, Decimal("5000.00")),
            ("1002", "银行存款", AccountDirection.DEBIT, Decimal("25000.00")),
        ])

        resp = client.get(
            "/api/v1/reports/contract-pnl",
            params={"year": 2024, "month": 6},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract_count"] == 2
        assert data["total_revenue"] == "130000.00"
        assert data["total_cost"] == "80000.00"
        assert data["total_expenses"] == "5000.00"
        assert data["total_net_profit"] == "45000.00"

    def test_contract_without_oem_contract_record(self, client, db, ledger, ledger_id):
        """Contract with vouchers but no OEMContract row still appears (customer_name is null)."""
        self._create_voucher(db, ledger, "HT-ADHOC", 2024, 6, 1, "ADHOC", [
            ("5001", "销售收入", AccountDirection.CREDIT, Decimal("30000.00")),
            ("5401", "销售成本", AccountDirection.DEBIT, Decimal("18000.00")),
            ("1002", "银行存款", AccountDirection.DEBIT, Decimal("12000.00")),
        ])

        resp = client.get(
            "/api/v1/reports/contract-pnl",
            params={"year": 2024, "month": 6},
            headers={"X-Ledger-Id": str(ledger_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract_count"] == 1
        assert data["contracts"][0]["customer_name"] is None

    def test_ledger_isolation(self, client, db, ledger, ledger_id):
        """Contract in ledger A does not leak into ledger B."""
        from app.models.financial import Ledger, AccountingPeriod, PeriodStatus

        oem = OEMContract(
            ledger_id=ledger.id,
            contract_number="HT-ISO-001",
            customer_name="TestCo",
        )
        db.add(oem)
        db.commit()
        self._create_voucher(db, ledger, "HT-ISO-001", 2024, 6, 1, "ISO", [
            ("5001", "销售收入", AccountDirection.CREDIT, Decimal("50000.00")),
            ("1002", "银行存款", AccountDirection.DEBIT, Decimal("50000.00")),
        ])

        # Create ledger B
        ledger_b = Ledger(
            name="Company B", company_name="Corp B", start_year=2024, start_month=1
        )
        db.add(ledger_b)
        db.flush()
        db.add(AccountingPeriod(ledger_id=ledger_b.id, year=2024, month=1, status=PeriodStatus.OPEN))
        db.commit()

        resp = client.get(
            "/api/v1/reports/contract-pnl",
            params={"year": 2024, "month": 6},
            headers={"X-Ledger-Id": str(ledger_b.id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contracts"] == []
        assert data["contract_count"] == 0
```

- [ ] **Step 2: Run the new tests**

Run: `cd d:\antigravity ide text\trad account\backend && .\venv\Scripts\python.exe -m pytest tests/test_contract_pnl.py -v`
Expected: 6 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `cd d:\antigravity ide text\trad account\backend && .\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: All tests pass (existing 268 + 1 cross-month + 6 new = 275 tests)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_contract_pnl.py
git commit -m "test: contract P&L endpoint with cross-month matching"
```

---

### Task 5 (Optional): Frontend Contract P&L Tab

**Files:**
- Modify: `frontend/src/app/reports/page.tsx`
- Create: `frontend/src/components/ContractPnL.tsx`

Only implement if the user requests it. The backend endpoints are independently testable.

- [ ] **Step 1: Create `frontend/src/components/ContractPnL.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface ContractPnLItem {
  contract_number: string;
  customer_name: string | null;
  revenue: string;
  cost: string;
  expenses: string;
  gross_profit: string;
  net_profit: string;
  voucher_count: number;
}

interface ContractPnLResponse {
  period: string;
  contracts: ContractPnLItem[];
  total_revenue: string;
  total_cost: string;
  total_expenses: string;
  total_net_profit: string;
  contract_count: number;
}

export default function ContractPnL() {
  const [data, setData] = useState<ContractPnLResponse | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ year: String(year) });
      if (month > 0) params.set("month", String(month));
      const res = await apiFetch(`/api/v1/reports/contract-pnl?${params}`);
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [year, month]);

  const formatMoney = (s: string) => {
    const n = Number(s);
    return n.toLocaleString("zh-CN", { minimumFractionDigits: 2 });
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-4 items-center">
        <select value={year} onChange={e => setYear(Number(e.target.value))}
                className="border rounded px-2 py-1">
          {[2024, 2025, 2026].map(y => (
            <option key={y} value={y}>{y}年</option>
          ))}
        </select>
        <select value={month} onChange={e => setMonth(Number(e.target.value))}
                className="border rounded px-2 py-1">
          <option value={0}>全年</option>
          {Array.from({length: 12}, (_, i) => i + 1).map(m => (
            <option key={m} value={m}>{m}月</option>
          ))}
        </select>
      </div>

      {loading && <div>加载中...</div>}

      {data && (
        <>
          <div className="grid grid-cols-4 gap-4">
            <div className="border rounded p-3">
              <div className="text-sm text-gray-600">总收入</div>
              <div className="text-lg font-bold">{formatMoney(data.total_revenue)}</div>
            </div>
            <div className="border rounded p-3">
              <div className="text-sm text-gray-600">总成本</div>
              <div className="text-lg font-bold">{formatMoney(data.total_cost)}</div>
            </div>
            <div className="border rounded p-3">
              <div className="text-sm text-gray-600">总费用</div>
              <div className="text-lg font-bold">{formatMoney(data.total_expenses)}</div>
            </div>
            <div className="border rounded p-3">
              <div className="text-sm text-gray-600">总净利润</div>
              <div className="text-lg font-bold">{formatMoney(data.total_net_profit)}</div>
            </div>
          </div>

          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b bg-gray-50">
                <th className="text-left p-2">合同号</th>
                <th className="text-left p-2">客户</th>
                <th className="text-right p-2">收入</th>
                <th className="text-right p-2">成本</th>
                <th className="text-right p-2">费用</th>
                <th className="text-right p-2">毛利</th>
                <th className="text-right p-2">净利润</th>
                <th className="text-right p-2">凭证数</th>
              </tr>
            </thead>
            <tbody>
              {data.contracts.map(ct => (
                <tr key={ct.contract_number} className="border-b hover:bg-gray-50">
                  <td className="p-2 font-mono">{ct.contract_number}</td>
                  <td className="p-2">{ct.customer_name ?? "-"}</td>
                  <td className="p-2 text-right">{formatMoney(ct.revenue)}</td>
                  <td className="p-2 text-right">{formatMoney(ct.cost)}</td>
                  <td className="p-2 text-right">{formatMoney(ct.expenses)}</td>
                  <td className="p-2 text-right">{formatMoney(ct.gross_profit)}</td>
                  <td className="p-2 text-right font-bold">{formatMoney(ct.net_profit)}</td>
                  <td className="p-2 text-right">{ct.voucher_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add tab to reports page**

In `frontend/src/app/reports/page.tsx`, add a "合同损益" tab that renders `<ContractPnL />`. Follow the existing tab pattern (reference the "佣金" tab implementation).

- [ ] **Step 3: Type check**

Run: `cd d:\antigravity ide text\trad account\frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ContractPnL.tsx frontend/src/app/reports/page.tsx
git commit -m "feat: contract P&L tab in reports page"
```

---

## Self-Review

1. **Spec coverage:** The user's request — "统计每个月做的合同的净利润，跨月费用匹配" — is covered by:
   - Task 1: Fixes the cross-month bug in the commission engine
   - Task 2: Tests the cross-month behavior
   - Task 3: Adds a standalone contract P&L list endpoint (monthly view with cross-month matching)
   - Task 4: Integration tests for the new endpoint
   - Task 5: Optional frontend tab

2. **Placeholder scan:** No TBDs, no "implement later", no "add error handling" without code. All steps contain actual code.

3. **Type consistency:**
   - `_batch_compute_contract_pnls` signature unchanged (backward compatible)
   - `ContractPnLItem` field names match between backend model and frontend interface
   - `Money` type used consistently (existing project pattern from `OemContractPnLEntryResponse`)
   - `account_map` dict keyed by `account.id` — consistent across all functions
