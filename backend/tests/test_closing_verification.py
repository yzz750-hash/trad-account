"""Comprehensive monthly + year-end closing verification test.

Verifies:
- Monthly P&L carry-forward: revenue/expense accounts zeroed, 4103 = net profit
- Year-end carry-forward: 4103 zeroed, 4104 (Retained Earnings) = annual net profit
- Cross-report 勾稽 (articulation): balance sheet balances, net income matches
  the amount transferred to retained earnings, etc.

Run via:
    .\\venv\\Scripts\\python.exe tests\\test_closing_verification.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from decimal import Decimal
from typing import Any

import requests

API_BASE = "http://127.0.0.1:8004/api/v1"
TIMEOUT = 20

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


class Report:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.bugs: list[dict[str, Any]] = []

    def step(self, name: str, status: str, detail: str = "", data: Any = None) -> None:
        self.steps.append({"name": name, "status": status, "detail": detail, "data": data})
        color = GREEN if status == "PASS" else RED if status == "FAIL" else YELLOW
        print(f"  [{color}{status}{RESET}] {name}" + (f" — {detail}" if detail else ""))

    def bug(self, title: str, symptom: str, root_cause: str = "", fix: str = "") -> None:
        self.bugs.append({"title": title, "symptom": symptom, "root_cause": root_cause, "fix": fix})
        print(f"  {RED}{BOLD}BUG{RESET}: {title}")
        print(f"       symptom: {symptom}")

    def print_summary(self) -> None:
        print("\n" + "=" * 78)
        print(f"{BOLD}CLOSING VERIFICATION TEST SUMMARY{RESET}")
        print("=" * 78)
        pass_count = sum(1 for s in self.steps if s["status"] == "PASS")
        fail_count = sum(1 for s in self.steps if s["status"] == "FAIL")
        warn_count = sum(1 for s in self.steps if s["status"] == "WARN")
        print(f"Steps: {len(self.steps)} total | {GREEN}{pass_count} pass{RESET} | {RED}{fail_count} fail{RESET} | {YELLOW}{warn_count} warn{RESET}")
        print(f"Bugs found: {len(self.bugs)}")
        for b in self.bugs:
            print(f"  - {b['title']}")
        print("=" * 78)


REPORT = Report()


def http(method: str, path: str, token: str | None = None, ledger_id: int | None = None,
         **kwargs) -> requests.Response:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if ledger_id:
        headers["X-Ledger-Id"] = str(ledger_id)
    return requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)


def login() -> tuple[str, int]:
    r = http("POST", "/auth/login", json={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        REPORT.step("Login", "FAIL", f"HTTP {r.status_code}: {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]
    r = http("GET", "/ledgers", token=token)
    ledgers = r.json()
    ledger_id = ledgers[0]["id"]
    REPORT.step("Login + ledger discovery", "PASS",
                f"ledger_id={ledger_id}, name={ledgers[0].get('name')}")
    return token, ledger_id


def ensure_period_open(token: str, ledger_id: int, year: int, month: int) -> None:
    """Directly insert an AccountingPeriod row if it doesn't exist (test setup only)."""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if "DATABASE_URL" not in os.environ:
        # PG password must be provided via PG_PASSWORD env var to avoid
        # committing credentials to version control.
        os.environ["DATABASE_URL"] = f"postgresql+psycopg2://trad_user:{os.environ.get('PG_PASSWORD', 'SET_ME')}@localhost:5432/trad_account"
    from app.database import SessionLocal
    from app.models.financial import AccountingPeriod, PeriodStatus

    s = SessionLocal()
    try:
        existing = s.query(AccountingPeriod).filter(
            AccountingPeriod.ledger_id == ledger_id,
            AccountingPeriod.year == year,
            AccountingPeriod.month == month,
        ).first()
        if existing:
            print(f"  (setup) Period {year}-{month:02d} already exists ({existing.status.value})")
            return
        s.add(AccountingPeriod(
            ledger_id=ledger_id, year=year, month=month, status=PeriodStatus.OPEN,
        ))
        s.commit()
        print(f"  (setup) Created OPEN period {year}-{month:02d}")
    finally:
        s.close()


def create_voucher(token: str, ledger_id: int, voucher_date: str, entries: list[dict]) -> dict | None:
    payload = {
        "voucher_date": voucher_date,
        "voucher_number": "AUTO",
        "attachments_count": 0,
        "entries": [
            {
                "account_code": e["account_code"],
                "summary": e.get("summary", ""),
                "direction": e["direction"],
                "amount": str(e["amount"]),
                "currency_code": e.get("currency_code", "CNY"),
                "exchange_rate": "1.0",
            }
            for e in entries
        ],
    }
    r = http("POST", "/vouchers", token=token, ledger_id=ledger_id, json=payload)
    if r.status_code not in (200, 201):
        REPORT.step(f"Create voucher {voucher_date}", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        return None
    voucher = r.json()
    vid = voucher["id"]
    r = http("POST", f"/vouchers/{vid}/post", token=token, ledger_id=ledger_id)
    if r.status_code not in (200, 201):
        REPORT.step(f"Post voucher #{vid}", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        return None
    return voucher


def get_account_balances(token: str, ledger_id: int, year: int, month: int) -> dict[str, dict]:
    """Return {account_code: balance_row}."""
    r = http("GET", f"/reports/account-balances?year={year}&month={month}",
             token=token, ledger_id=ledger_id)
    if r.status_code != 200:
        return {}
    data = r.json()
    if not isinstance(data, list):
        return {}
    return {a.get("account_code"): a for a in data}


def get_balance_sheet(token: str, ledger_id: int, as_of: str) -> dict:
    r = http("GET", f"/reports/balance-sheet?as_of_date={as_of}",
             token=token, ledger_id=ledger_id)
    if r.status_code != 200:
        return {}
    return r.json()


def get_income_statement(token: str, ledger_id: int, start: str, end: str) -> dict:
    r = http("GET", f"/reports/income-statement?start_date={start}&end_date={end}",
             token=token, ledger_id=ledger_id)
    if r.status_code != 200:
        return {}
    return r.json()


# ────────────────────────────────────────────────────────────────────────────
# PHASE A: MONTHLY CLOSING (2026-07)
# ────────────────────────────────────────────────────────────────────────────

def phase_a_create_vouchers(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[PHASE A1] Create test vouchers for 2026-07{RESET}")
    # Same 8 vouchers as previous E2E test
    vouchers = [
        ("2026-07-05", [("1002", "借", Decimal("1000000")), ("4001", "贷", Decimal("1000000"))], "V1 Capital"),
        ("2026-07-10", [("1405", "借", Decimal("500000")), ("1002", "贷", Decimal("500000"))], "V2 Purchase"),
        ("2026-07-15", [("1122", "借", Decimal("300000")), ("6001", "贷", Decimal("300000"))], "V3 Revenue"),
        ("2026-07-15", [("6401", "借", Decimal("180000")), ("1405", "贷", Decimal("180000"))], "V4 COGS"),
        ("2026-07-20", [("6602", "借", Decimal("20000")),  ("1002", "贷", Decimal("20000"))],  "V5 Admin"),
        ("2026-07-25", [("1002", "借", Decimal("300000")), ("1122", "贷", Decimal("300000"))], "V6 AR collect"),
        ("2026-07-28", [("1002", "借", Decimal("200000")), ("2202", "贷", Decimal("200000"))], "V7 AP"),
        ("2026-07-30", [("6403", "借", Decimal("30000")),  ("2221", "贷", Decimal("30000"))],  "V8 Tax"),
    ]
    for vdate, entries, label in vouchers:
        v = create_voucher(token, ledger_id, vdate, [
            {"account_code": code, "direction": direction, "amount": amt, "summary": label}
            for code, direction, amt in entries
        ])
        if v:
            REPORT.step(f"Create {label}", "PASS", f"voucher #{v['id']}")


def phase_a_pre_closing_reports(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[PHASE A2] Pre-closing report verification{RESET}")
    # Trial balance
    balances = get_account_balances(token, ledger_id, 2026, 7)
    total_debit = sum(Decimal(str(a.get("ending_debit", "0"))) for a in balances.values())
    total_credit = sum(Decimal(str(a.get("ending_credit", "0"))) for a in balances.values())
    if abs(total_debit - total_credit) <= Decimal("0.01"):
        REPORT.step("Pre-closing trial balance", "PASS",
                    f"debit={total_debit} == credit={total_credit}")
    else:
        REPORT.bug("Pre-closing trial balance unbalanced",
                   f"debit={total_debit} != credit={total_credit}")

    # Income statement
    inc = get_income_statement(token, ledger_id, "2026-07-01", "2026-07-31")
    net_income = Decimal(str(inc.get("net_income", "0")))
    if abs(net_income - Decimal("70000")) <= Decimal("0.01"):
        REPORT.step("Pre-closing income statement", "PASS",
                    f"net_income={net_income} (expected 70000)")
    else:
        REPORT.bug("Pre-closing income statement mismatch",
                   f"net_income={net_income}, expected 70000")

    # Balance sheet (must balance via P&L injection)
    bs = get_balance_sheet(token, ledger_id, "2026-07-31")
    is_balanced = bs.get("is_balanced", False)
    discrepancy = Decimal(str(bs.get("balance_discrepancy", "0")))
    if is_balanced and abs(discrepancy) <= Decimal("0.01"):
        REPORT.step("Pre-closing balance sheet", "PASS",
                    f"assets={bs.get('total_assets')} == liab+equity={Decimal(str(bs.get('total_liabilities',0)))+Decimal(str(bs.get('total_equity',0)))}")
    else:
        REPORT.bug("Pre-closing balance sheet unbalanced",
                   f"is_balanced={is_balanced}, discrepancy={discrepancy}")


def phase_a_monthly_closing(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[PHASE A3] Monthly closing — depreciation / FX / P&L transfer{RESET}")

    # A3.1: Depreciation (no fixed assets → expect skip message)
    r = http("POST", "/closing/depreciate?year=2026&month=7", token=token, ledger_id=ledger_id)
    if r.status_code in (200, 201):
        REPORT.step("Depreciation (no assets)", "PASS", f"msg={r.json().get('message', '')[:80]}")
    else:
        REPORT.step("Depreciation", "FAIL", f"HTTP {r.status_code}: {r.text[:200]}")

    # A3.2: FX revaluation (no foreign currency → expect skip)
    r = http("POST", "/closing/fx-revaluation?year=2026&month=7", token=token, ledger_id=ledger_id)
    if r.status_code in (200, 201):
        REPORT.step("FX revaluation (no FX)", "PASS", f"msg={r.json().get('message', '')[:80]}")
    else:
        REPORT.step("FX revaluation", "FAIL", f"HTTP {r.status_code}: {r.text[:200]}")

    # A3.3: P&L carry-forward
    r = http("POST", "/closing/profit-loss?year=2026&month=7", token=token, ledger_id=ledger_id)
    if r.status_code not in (200, 201):
        REPORT.step("P&L carry-forward", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        return
    data = r.json()
    voucher_id = data.get("voucher_id")
    REPORT.step("P&L carry-forward", "PASS",
                f"voucher_id={voucher_id}, net_profit_impact={data.get('net_profit_impact')}")

    # A3.4: POST the carry-forward voucher
    if voucher_id and data.get("voucher_status") == "DRAFT":
        r2 = http("POST", f"/vouchers/{voucher_id}/post", token=token, ledger_id=ledger_id)
        if r2.status_code in (200, 201):
            REPORT.step(f"POST P&L voucher #{voucher_id}", "PASS")
        else:
            REPORT.step(f"POST P&L voucher #{voucher_id}", "FAIL",
                        f"HTTP {r2.status_code}: {r2.text[:300]}")


def phase_a_post_closing_verify(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[PHASE A4] Post-monthly-closing verification{RESET}")
    balances = get_account_balances(token, ledger_id, 2026, 7)

    # P&L accounts must be zero
    pl_zero = True
    for code in ("6001", "6401", "6403", "6602"):
        a = balances.get(code, {})
        ed = Decimal(str(a.get("ending_debit", "0")))
        ec = Decimal(str(a.get("ending_credit", "0")))
        if abs(ed) > Decimal("0.01") or abs(ec) > Decimal("0.01"):
            pl_zero = False
            REPORT.bug(f"P&L account {code} not zeroed after monthly closing",
                       f"ending_debit={ed}, ending_credit={ec}")
    if pl_zero:
        REPORT.step("P&L accounts zeroed", "PASS", "6001/6401/6403/6602 all 0")

    # 4103 本年利润 must equal 70,000 (credit direction)
    profit = balances.get("4103", {})
    net_4103 = Decimal(str(profit.get("ending_credit", "0"))) - Decimal(str(profit.get("ending_debit", "0")))
    if abs(net_4103 - Decimal("70000")) <= Decimal("0.01"):
        REPORT.step("4103 net profit", "PASS", f"4103 net credit={net_4103}")
    else:
        REPORT.bug("4103 net profit mismatch",
                   f"4103 net={net_4103}, expected 70000")

    # Balance sheet must balance (equity includes 4103=70k, no P&L injection since P&L=0)
    bs = get_balance_sheet(token, ledger_id, "2026-07-31")
    is_balanced = bs.get("is_balanced", False)
    discrepancy = Decimal(str(bs.get("balance_discrepancy", "0")))
    if is_balanced and abs(discrepancy) <= Decimal("0.01"):
        REPORT.step("Post-closing balance sheet", "PASS",
                    f"assets={bs.get('total_assets')} = liab+equity={Decimal(str(bs.get('total_liabilities',0)))+Decimal(str(bs.get('total_equity',0)))}")
    else:
        REPORT.bug("Post-closing balance sheet unbalanced",
                   f"is_balanced={is_balanced}, discrepancy={discrepancy}")


def phase_a_close_period(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[PHASE A5] Close period 2026-07{RESET}")
    r = http("POST", "/closing/close?year=2026&month=7", token=token, ledger_id=ledger_id)
    if r.status_code in (200, 201):
        REPORT.step("Close period 2026-07", "PASS", r.json().get("message", ""))
    else:
        REPORT.step("Close period 2026-07", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")

    # Verify AccountBalance rows were generated
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if "DATABASE_URL" not in os.environ:
        # PG password must be provided via PG_PASSWORD env var to avoid
        # committing credentials to version control.
        os.environ["DATABASE_URL"] = f"postgresql+psycopg2://trad_user:{os.environ.get('PG_PASSWORD', 'SET_ME')}@localhost:5432/trad_account"
    from app.database import SessionLocal
    from app.models.financial import AccountBalance
    s = SessionLocal()
    try:
        count = s.query(AccountBalance).filter(
            AccountBalance.ledger_id == ledger_id,
            AccountBalance.year == 2026, AccountBalance.month == 7,
        ).count()
        if count > 0:
            REPORT.step("AccountBalance rows generated", "PASS", f"{count} rows for 2026-07")
        else:
            REPORT.bug("AccountBalance not generated", "0 rows after close_period")
    finally:
        s.close()


# ────────────────────────────────────────────────────────────────────────────
# PHASE B: YEAR-END CLOSING (2026-12)
# ────────────────────────────────────────────────────────────────────────────

def phase_b_year_end(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[PHASE B1] Year-end closing — 4103 → 4104{RESET}")

    # Pre-year-end: 4103 should be 70,000, 4104 should be 0
    balances = get_account_balances(token, ledger_id, 2026, 12)
    profit_4103 = balances.get("4103", {})
    retained_4104 = balances.get("4104", {})
    net_4103 = Decimal(str(profit_4103.get("ending_credit", "0"))) - Decimal(str(profit_4103.get("ending_debit", "0")))
    net_4104 = Decimal(str(retained_4104.get("ending_credit", "0"))) - Decimal(str(retained_4104.get("ending_debit", "0")))
    print(f"       Pre-year-end: 4103 net={net_4103}, 4104 net={net_4104}")

    # B2: Call year-end endpoint
    r = http("POST", "/closing/year-end?year=2026", token=token, ledger_id=ledger_id)
    if r.status_code not in (200, 201):
        REPORT.step("Year-end carry-forward", "FAIL", f"HTTP {r.status_code}: {r.text[:400]}")
        return
    data = r.json()
    voucher_id = data.get("voucher_id")
    if not voucher_id:
        REPORT.bug("Year-end response missing voucher_id",
                   f"response={data}",
                   root_cause="/closing/year-end endpoint return shape")
        REPORT.step("Year-end carry-forward", "WARN", "no voucher_id in response")
        return
    REPORT.step("Year-end carry-forward", "PASS",
                f"voucher_id={voucher_id}, net_profit={data.get('net_profit')}")

    # B3: POST the year-end voucher
    if data.get("voucher_status") == "DRAFT":
        r2 = http("POST", f"/vouchers/{voucher_id}/post", token=token, ledger_id=ledger_id)
        if r2.status_code in (200, 201):
            REPORT.step(f"POST year-end voucher #{voucher_id}", "PASS")
        else:
            REPORT.step(f"POST year-end voucher #{voucher_id}", "FAIL",
                        f"HTTP {r2.status_code}: {r2.text[:300]}")
            REPORT.bug("Year-end voucher POST failed",
                       f"HTTP {r2.status_code}: {r2.text[:200]}",
                       root_cause="Period 2026-12 may not be OPEN, or other posting issue")

    # B4: Post-year-end verification
    print(f"\n{CYAN}{BOLD}[PHASE B2] Post-year-end verification{RESET}")
    balances = get_account_balances(token, ledger_id, 2026, 12)
    profit_4103 = balances.get("4103", {})
    retained_4104 = balances.get("4104", {})
    net_4103 = Decimal(str(profit_4103.get("ending_credit", "0"))) - Decimal(str(profit_4103.get("ending_debit", "0")))
    net_4104 = Decimal(str(retained_4104.get("ending_credit", "0"))) - Decimal(str(retained_4104.get("ending_debit", "0")))
    print(f"       Post-year-end: 4103 net={net_4103}, 4104 net={net_4104}")

    # 4103 should be 0 (transferred out)
    if abs(net_4103) <= Decimal("0.01"):
        REPORT.step("4103 zeroed after year-end", "PASS", f"net={net_4103}")
    else:
        REPORT.bug("4103 not zeroed after year-end",
                   f"4103 net={net_4103}, expected 0")

    # 4104 should be 70,000 (received)
    if abs(net_4104 - Decimal("70000")) <= Decimal("0.01"):
        REPORT.step("4104 retained earnings", "PASS", f"net={net_4104}")
    else:
        REPORT.bug("4104 retained earnings mismatch",
                   f"4104 net={net_4104}, expected 70000")


# ────────────────────────────────────────────────────────────────────────────
# PHASE C: CROSS-REPORT ARTICULATION (勾稽)
# ────────────────────────────────────────────────────────────────────────────

def phase_c_articulation(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[PHASE C] Cross-report articulation (勾稽){RESET}")

    # C1: Full-year income statement
    inc = get_income_statement(token, ledger_id, "2026-01-01", "2026-12-31")
    net_income = Decimal(str(inc.get("net_income", "0")))
    total_revenue = Decimal(str(inc.get("total_revenue", "0")))
    total_expense = Decimal(str(inc.get("total_expense", "0")))
    print(f"       Income statement: revenue={total_revenue}, expense={total_expense}, net={net_income}")

    if abs(net_income - Decimal("70000")) <= Decimal("0.01"):
        REPORT.step("Full-year net income", "PASS", f"net={net_income}")
    else:
        REPORT.bug("Full-year net income mismatch",
                   f"net={net_income}, expected 70000")

    # C2: Balance sheet as of 2026-12-31
    bs = get_balance_sheet(token, ledger_id, "2026-12-31")
    total_assets = Decimal(str(bs.get("total_assets", "0")))
    total_liab = Decimal(str(bs.get("total_liabilities", "0")))
    total_equity = Decimal(str(bs.get("total_equity", "0")))
    is_balanced = bs.get("is_balanced", False)
    discrepancy = Decimal(str(bs.get("balance_discrepancy", "0")))
    print(f"       Balance sheet: assets={total_assets}, liab={total_liab}, equity={total_equity}, balanced={is_balanced}")

    if is_balanced and abs(discrepancy) <= Decimal("0.01"):
        REPORT.step("Year-end balance sheet balanced", "PASS",
                    f"assets={total_assets} = liab+equity={total_liab+total_equity}")
    else:
        REPORT.bug("Year-end balance sheet unbalanced",
                   f"is_balanced={is_balanced}, discrepancy={discrepancy}")

    # C3: 勾稽 — net income must equal retained earnings increase
    # 4104 = 70,000 should equal full-year net income
    balances = get_account_balances(token, ledger_id, 2026, 12)
    retained = balances.get("4104", {})
    net_4104 = Decimal(str(retained.get("ending_credit", "0"))) - Decimal(str(retained.get("ending_debit", "0")))
    if abs(net_4104 - net_income) <= Decimal("0.01"):
        REPORT.step("勾稽: 4104 = full-year net income", "PASS",
                    f"4104={net_4104} == net_income={net_income}")
    else:
        REPORT.bug("勾稽 mismatch: 4104 != net income",
                   f"4104={net_4104}, net_income={net_income}")

    # C4: 勾稽 — assets = liabilities + equity (basic accounting identity)
    if abs(total_assets - (total_liab + total_equity)) <= Decimal("0.01"):
        REPORT.step("勾稽: assets = liabilities + equity", "PASS",
                    f"{total_assets} = {total_liab} + {total_equity}")
    else:
        REPORT.bug("勾稽 mismatch: assets != liab + equity",
                   f"assets={total_assets}, liab+equity={total_liab+total_equity}")


def main() -> int:
    print(f"\n{BOLD}{CYAN}========================================")
    print(f"  CLOSING VERIFICATION TEST")
    print(f"  (Monthly + Year-End + 勾稽)")
    print(f"========================================{RESET}\n")

    # Setup: ensure 2026-12 period exists (needed for year-end voucher POST)
    print(f"{CYAN}[SETUP] Ensure periods exist{RESET}")
    # First login to get ledger_id
    token, ledger_id = login()
    ensure_period_open(token, ledger_id, 2026, 7)
    ensure_period_open(token, ledger_id, 2026, 12)

    # Phase A: Monthly closing
    phase_a_create_vouchers(token, ledger_id)
    phase_a_pre_closing_reports(token, ledger_id)
    phase_a_monthly_closing(token, ledger_id)
    phase_a_post_closing_verify(token, ledger_id)
    phase_a_close_period(token, ledger_id)

    # Phase B: Year-end closing
    phase_b_year_end(token, ledger_id)

    # Phase C: Cross-report articulation
    phase_c_articulation(token, ledger_id)

    REPORT.print_summary()
    return 0 if not REPORT.bugs else 1


if __name__ == "__main__":
    sys.exit(main())
