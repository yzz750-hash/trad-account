"""
Comprehensive financial feature E2E test script.

Tests the full flow via API:
1. Login + ledger/account discovery
2. Create income/expense/asset/liability vouchers
3. Query account balances
4. Generate financial reports (trial balance / income statement / balance sheet)
5. Tax calculation
6. Period-end closing (profit & loss transfer)
7. Verify post-closing report correctness

Prints a structured report at the end. Run via:
    .\\venv\\Scripts\\python.exe tests\\test_e2e_financial_flow.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import requests

# This file is a STANDALONE E2E script intended to be run directly against a
# live server (python tests/test_e2e_financial_flow.py), NOT under pytest.
# Its functions take (token, ledger_id) parameters that pytest cannot supply,
# so mark the whole module as skipped when collected by pytest to avoid
# spurious fixture errors in `pytest tests/` runs.
pytestmark = pytest.mark.skip(
    reason="Standalone E2E script — run via `python tests/test_e2e_financial_flow.py` against a live backend."
)

API_BASE = "http://127.0.0.1:8004/api/v1"
TIMEOUT = 15

# ANSI colors for terminal output
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
        print(f"{BOLD}TEST REPORT SUMMARY{RESET}")
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
    """Login as admin and return (token, ledger_id)."""
    r = http("POST", "/auth/login", json={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        REPORT.step("Login", "FAIL", f"HTTP {r.status_code}: {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]

    r = http("GET", "/ledgers", token=token)
    if r.status_code != 200:
        REPORT.step("Fetch ledgers", "FAIL", f"HTTP {r.status_code}: {r.text}")
        sys.exit(1)
    ledgers = r.json()
    if not ledgers:
        REPORT.step("Ledger discovery", "FAIL", "No ledgers found — run init_db.py first")
        sys.exit(1)
    ledger_id = ledgers[0]["id"]
    REPORT.step("Login + ledger discovery", "PASS",
                f"token len={len(token)}, ledger_id={ledger_id}, ledger_name={ledgers[0].get('name')}")
    return token, ledger_id


def fetch_accounts(token: str, ledger_id: int) -> dict[str, dict]:
    """Return code -> account dict."""
    r = http("GET", "/accounts", token=token, ledger_id=ledger_id)
    if r.status_code != 200:
        REPORT.step("Fetch accounts", "FAIL", f"HTTP {r.status_code}: {r.text}")
        sys.exit(1)
    accounts = r.json()
    by_code = {a["code"]: a for a in accounts}
    REPORT.step("Fetch accounts", "PASS", f"{len(accounts)} accounts loaded")
    return by_code


def create_voucher(token: str, ledger_id: int, voucher_date: str, entries: list[dict],
                   voucher_number: str = "AUTO") -> dict | None:
    """Create + post a voucher. Each entry: {account_code, summary, direction, amount, currency_code?}"""
    payload = {
        "voucher_date": voucher_date,
        "voucher_number": voucher_number,
        "attachments_count": 0,
        "entries": [
            {
                "account_code": e["account_code"],
                "summary": e.get("summary", ""),
                "direction": e["direction"],
                "amount": str(e["amount"]),
                "currency_code": e.get("currency_code", "CNY"),
                "original_amount": e.get("original_amount"),
                "exchange_rate": e.get("exchange_rate", "1.0"),
                "partner_id": e.get("partner_id"),
            }
            for e in entries
        ],
    }
    r = http("POST", "/vouchers", token=token, ledger_id=ledger_id, json=payload)
    if r.status_code not in (200, 201):
        REPORT.step(f"Create voucher {voucher_date}", "FAIL",
                    f"HTTP {r.status_code}: {r.text[:300]}")
        return None
    voucher = r.json()
    vid = voucher["id"]

    # Post (audit) the voucher so it affects account balances
    r = http("POST", f"/vouchers/{vid}/post", token=token, ledger_id=ledger_id)
    if r.status_code not in (200, 201):
        REPORT.step(f"Post voucher #{vid}", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        return None
    return voucher


def test_voucher_creation(token: str, ledger_id: int, accounts: dict[str, dict]) -> list[int]:
    """Create a comprehensive set of vouchers covering income/expense/asset/liability."""
    print(f"\n{CYAN}{BOLD}[STEP 2] Voucher creation — income/expense/asset/liability{RESET}")
    created_ids: list[int] = []

    # V1: Initial capital injection — Debit bank 1,000,000 / Credit paid-in capital 1,000,000
    v = create_voucher(token, ledger_id, "2026-07-05", [
        {"account_code": "1002", "summary": "收到股东投资款", "direction": "借", "amount": Decimal("1000000")},
        {"account_code": "4001", "summary": "实收资本", "direction": "贷", "amount": Decimal("1000000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V1 Capital injection 1,000,000", "PASS", f"voucher #{v['id']}")

    # V2: Purchase inventory — Debit inventory 500,000 / Credit bank 500,000
    v = create_voucher(token, ledger_id, "2026-07-10", [
        {"account_code": "1405", "summary": "采购商品", "direction": "借", "amount": Decimal("500000")},
        {"account_code": "1002", "summary": "银行付款", "direction": "贷", "amount": Decimal("500000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V2 Inventory purchase 500,000", "PASS", f"voucher #{v['id']}")

    # V3: Sales revenue — Debit AR 300,000 / Credit revenue 300,000
    # NOTE: 6001 = 主营业务收入 (PROFIT_LOSS, CREDIT). 5001 is 生产成本 (COST).
    v = create_voucher(token, ledger_id, "2026-07-15", [
        {"account_code": "1122", "summary": "销售商品应收款", "direction": "借", "amount": Decimal("300000")},
        {"account_code": "6001", "summary": "主营业务收入", "direction": "贷", "amount": Decimal("300000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V3 Sales revenue 300,000", "PASS", f"voucher #{v['id']}")

    # V4: COGS — Debit COGS 180,000 / Credit inventory 180,000
    # NOTE: 6401 = 主营业务成本 (PROFIT_LOSS, DEBIT). 5401 does not exist.
    v = create_voucher(token, ledger_id, "2026-07-15", [
        {"account_code": "6401", "summary": "结转销售成本", "direction": "借", "amount": Decimal("180000")},
        {"account_code": "1405", "summary": "出库", "direction": "贷", "amount": Decimal("180000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V4 COGS 180,000", "PASS", f"voucher #{v['id']}")

    # V5: Operating expense — Debit admin expense 20,000 / Credit bank 20,000
    v = create_voucher(token, ledger_id, "2026-07-20", [
        {"account_code": "6602", "summary": "支付办公费", "direction": "借", "amount": Decimal("20000")},
        {"account_code": "1002", "summary": "银行付款", "direction": "贷", "amount": Decimal("20000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V5 Operating expense 20,000", "PASS", f"voucher #{v['id']}")

    # V6: Receive AR payment — Debit bank 300,000 / Credit AR 300,000
    v = create_voucher(token, ledger_id, "2026-07-25", [
        {"account_code": "1002", "summary": "收到客户回款", "direction": "借", "amount": Decimal("300000")},
        {"account_code": "1122", "summary": "应收账款收回", "direction": "贷", "amount": Decimal("300000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V6 AR collection 300,000", "PASS", f"voucher #{v['id']}")

    # V7: Short-term loan — Debit bank 200,000 / Credit AP 200,000
    v = create_voucher(token, ledger_id, "2026-07-28", [
        {"account_code": "1002", "summary": "短期借款入账", "direction": "借", "amount": Decimal("200000")},
        {"account_code": "2202", "summary": "应付账款", "direction": "贷", "amount": Decimal("200000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V7 Short-term liability 200,000", "PASS", f"voucher #{v['id']}")

    # V8: Tax expense — Debit tax expense 30,000 / Credit tax payable 30,000
    # NOTE: 6403 = 税金及附加 (PROFIT_LOSS, DEBIT). 6603 is 财务费用 (also P&L).
    v = create_voucher(token, ledger_id, "2026-07-30", [
        {"account_code": "6403", "summary": "计提税金及附加", "direction": "借", "amount": Decimal("30000")},
        {"account_code": "2221", "summary": "应交税费", "direction": "贷", "amount": Decimal("30000")},
    ])
    if v:
        created_ids.append(v["id"])
        REPORT.step("V8 Tax accrual 30,000", "PASS", f"voucher #{v['id']}")

    return created_ids


def test_account_balances(token: str, ledger_id: int) -> None:
    """Query account balances / trial balance."""
    print(f"\n{CYAN}{BOLD}[STEP 3] Account balance query{RESET}")
    r = http("GET", "/reports/account-balances?year=2026&month=7&level=1", token=token, ledger_id=ledger_id)
    if r.status_code != 200:
        REPORT.step("Account balances", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        return
    data = r.json()
    if isinstance(data, list):
        nonzero = [a for a in data if Decimal(str(a.get("ending_debit", "0"))) > 0 or Decimal(str(a.get("ending_credit", "0"))) > 0]
        REPORT.step("Account balances", "PASS",
                    f"{len(data)} accounts, {len(nonzero)} non-zero")
        for a in nonzero[:15]:
            print(f"       {a.get('account_code','?'):>8} {a.get('account_name','')[:24]:<24} "
                  f"end_debit={a.get('ending_debit',0)} end_credit={a.get('ending_credit',0)}")
    else:
        REPORT.step("Account balances", "WARN", f"unexpected shape: {str(data)[:200]}")


def test_trial_balance(token: str, ledger_id: int) -> None:
    """Trial balance verification — sum of all debits must equal sum of all credits."""
    print(f"\n{CYAN}{BOLD}[STEP 4a] Trial balance (via account-balances){RESET}")
    r = http("GET", "/reports/account-balances?year=2026&month=7", token=token, ledger_id=ledger_id)
    if r.status_code != 200:
        REPORT.step("Trial balance", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        return
    data = r.json()
    if not isinstance(data, list):
        REPORT.step("Trial balance", "WARN", "unexpected shape")
        return
    total_debit = sum(Decimal(str(a.get("ending_debit", "0"))) for a in data)
    total_credit = sum(Decimal(str(a.get("ending_credit", "0"))) for a in data)
    if abs(total_debit - total_credit) <= Decimal("0.01"):
        REPORT.step("Trial balance", "PASS",
                    f"total_debit={total_debit} == total_credit={total_credit}")
    else:
        REPORT.bug(
            "Trial balance does not balance",
            f"total_debit={total_debit} != total_credit={total_credit} (diff={total_debit-total_credit})",
            root_cause="vouchers may have unbalanced entries or posting logic error",
        )


def test_income_statement(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[STEP 4b] Income statement{RESET}")
    r = http("GET", "/reports/income-statement?start_date=2026-07-01&end_date=2026-07-31",
             token=token, ledger_id=ledger_id)
    if r.status_code == 200:
        data = r.json()
        REPORT.step("Income statement", "PASS", f"keys={list(data.keys()) if isinstance(data, dict) else 'list'}")
        if isinstance(data, dict):
            for k, v in list(data.items())[:15]:
                print(f"       {k}: {v}")
    else:
        REPORT.step("Income statement", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")


def test_balance_sheet(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[STEP 4c] Balance sheet{RESET}")
    r = http("GET", "/reports/balance-sheet?as_of_date=2026-07-31",
             token=token, ledger_id=ledger_id)
    if r.status_code == 200:
        data = r.json()
        REPORT.step("Balance sheet", "PASS", f"keys={list(data.keys()) if isinstance(data, dict) else 'list'}")
        if isinstance(data, dict):
            for k, v in list(data.items())[:20]:
                print(f"       {k}: {v}")
    else:
        REPORT.step("Balance sheet", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")


def test_cash_flow(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[STEP 4d] Cash flow statement{RESET}")
    r = http("GET", "/reports/cash-flow?start_date=2026-07-01&end_date=2026-07-31",
             token=token, ledger_id=ledger_id)
    if r.status_code == 200:
        data = r.json()
        REPORT.step("Cash flow statement", "PASS", f"keys={list(data.keys()) if isinstance(data, dict) else 'list'}")
    else:
        REPORT.step("Cash flow statement", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")


def test_general_ledger(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[STEP 4e] General ledger{RESET}")
    r = http("GET", "/reports/general-ledger?year=2026&page=1&page_size=50", token=token, ledger_id=ledger_id)
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            REPORT.step("General ledger", "PASS", f"{len(data)} entries")
        elif isinstance(data, dict):
            items = data.get("items", data.get("data", []))
            REPORT.step("General ledger", "PASS", f"{len(items) if isinstance(items, list) else '?'} entries")
        else:
            REPORT.step("General ledger", "PASS", f"shape={type(data).__name__}")
    else:
        REPORT.step("General ledger", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")


def test_tax_calculation(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[STEP 5] Tax calculation{RESET}")
    # Try common tax endpoints
    paths = [
        "/tax/calculate?year=2026&month=7",
        "/tax/vat?year=2026&month=7",
        "/tax/cit?year=2026&month=7",
        "/tax?year=2026&month=7",
    ]
    found_any = False
    for path in paths:
        r = http("GET", path, token=token, ledger_id=ledger_id)
        if r.status_code == 200:
            data = r.json()
            REPORT.step(f"Tax {path.split('?')[0]}", "PASS", f"path={path}")
            if isinstance(data, dict):
                for k, v in list(data.items())[:8]:
                    print(f"       {k}: {v}")
            found_any = True
        elif r.status_code == 404:
            continue
        else:
            REPORT.step(f"Tax {path.split('?')[0]}", "WARN",
                        f"path={path} HTTP {r.status_code}: {r.text[:200]}")
    if not found_any:
        REPORT.step("Tax calculation", "WARN", "no tax endpoint found (feature may not be implemented)")


def test_period_end_closing(token: str, ledger_id: int) -> dict | None:
    print(f"\n{CYAN}{BOLD}[STEP 6] Period-end closing — profit/loss transfer{RESET}")
    r = http("POST", "/closing/profit-loss?year=2026&month=7", token=token, ledger_id=ledger_id)
    if r.status_code not in (200, 201):
        REPORT.step("P&L transfer closing", "FAIL",
                    f"HTTP {r.status_code}: {r.text[:400]}")
        return None
    data = r.json()
    REPORT.step("P&L transfer closing", "PASS", f"HTTP {r.status_code}")
    if isinstance(data, dict):
        for k, v in list(data.items())[:10]:
            print(f"       {k}: {v}")

    # The closing endpoint creates a DRAFT voucher (per CLAUDE.md constraint:
    # "System-generated vouchers must be DRAFT"). We must POST (audit) it before
    # it will affect account balances / be eligible for period close.
    voucher_id = data.get("voucher_id") if isinstance(data, dict) else None
    if not voucher_id:
        REPORT.bug(
            "P&L transfer response missing voucher_id",
            "Response did not include voucher_id; cannot POST the carry-forward voucher",
            root_cause="closing.py /profit-loss endpoint return shape",
        )
        return data

    if data.get("voucher_status") == "DRAFT":
        print(f"       {CYAN}POSTing carry-forward voucher #{voucher_id}...{RESET}")
        r2 = http("POST", f"/vouchers/{voucher_id}/post", token=token, ledger_id=ledger_id)
        if r2.status_code in (200, 201):
            REPORT.step(f"POST carry-forward voucher #{voucher_id}", "PASS")
        else:
            REPORT.step(f"POST carry-forward voucher #{voucher_id}", "FAIL",
                        f"HTTP {r2.status_code}: {r2.text[:300]}")
            REPORT.bug(
                "Carry-forward voucher POST failed",
                f"voucher_id={voucher_id} HTTP {r2.status_code}: {r2.text[:200]}",
            )
    else:
        print(f"       {CYAN}Voucher already POSTED (status={data.get('voucher_status')}){RESET}")

    return data


def test_post_closing_verification(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[STEP 7] Post-closing verification{RESET}")
    # After P&L transfer (and posting the carry-forward voucher), revenue/expense
    # accounts should be zero, and "本年利润" (4103) should equal net income.
    r = http("GET", "/reports/account-balances?year=2026&month=7", token=token, ledger_id=ledger_id)
    if r.status_code != 200:
        REPORT.step("Post-closing balances", "FAIL", f"HTTP {r.status_code}")
        return

    data = r.json()
    if not isinstance(data, list):
        REPORT.step("Post-closing balances", "WARN", f"unexpected shape: {type(data).__name__}")
        return

    by_code = {a.get("account_code"): a for a in data}
    # Correct account codes per init_db.py:
    #   6001 主营业务收入 (revenue, CREDIT)
    #   6401 主营业务成本 (COGS, DEBIT)
    #   6403 税金及附加 (tax surcharge, DEBIT)
    #   6602 管理费用 (admin expense, DEBIT)
    #   4103 本年利润 (current-year profit, CREDIT)
    revenue = by_code.get("6001", {})
    expense_cos = by_code.get("6401", {})
    expense_admin = by_code.get("6602", {})
    expense_tax = by_code.get("6403", {})
    profit_account = by_code.get("4103", {})

    # Expected: revenue 300k, COGS 180k, admin 20k, tax 30k → net profit = 70k
    expected_net = Decimal("70000")
    print(f"       revenue(6001) ending_debit={revenue.get('ending_debit', 'N/A')} ending_credit={revenue.get('ending_credit', 'N/A')}")
    print(f"       COGS(6401)    ending_debit={expense_cos.get('ending_debit', 'N/A')} ending_credit={expense_cos.get('ending_credit', 'N/A')}")
    print(f"       admin(6602)   ending_debit={expense_admin.get('ending_debit', 'N/A')} ending_credit={expense_admin.get('ending_credit', 'N/A')}")
    print(f"       tax(6403)     ending_debit={expense_tax.get('ending_debit', 'N/A')} ending_credit={expense_tax.get('ending_credit', 'N/A')}")
    print(f"       本年利润(4103) ending_debit={profit_account.get('ending_debit', 'N/A')} ending_credit={profit_account.get('ending_credit', 'N/A')}")
    print(f"       expected net profit: {expected_net}")

    # P&L accounts should be 0 (closed) — both ending_debit and ending_credit
    pl_zero = True
    for code in ("6001", "6401", "6602", "6403"):
        a = by_code.get(code, {})
        ed = Decimal(str(a.get("ending_debit", "0")))
        ec = Decimal(str(a.get("ending_credit", "0")))
        if abs(ed) > Decimal("0.01") or abs(ec) > Decimal("0.01"):
            pl_zero = False
            REPORT.bug(
                "P&L account not zeroed after closing",
                f"{code} ending_debit={ed} ending_credit={ec} (should both be 0)",
                root_cause="closing endpoint may not transfer all P&L account types",
            )
    if pl_zero:
        REPORT.step("P&L accounts zeroed", "PASS")

    # 本年利润 (4103, credit direction) ending_credit should equal expected net profit
    actual_profit = Decimal(str(profit_account.get("ending_credit", "0"))) - Decimal(str(profit_account.get("ending_debit", "0")))
    if abs(actual_profit - expected_net) <= Decimal("0.01"):
        REPORT.step("Net profit transfer", "PASS",
                    f"4103 net credit={actual_profit} == expected {expected_net}")
    else:
        REPORT.bug(
            "Net profit amount mismatch",
            f"4103 net credit={actual_profit}, expected={expected_net}",
            root_cause="P&L transfer may have miscalculated or skipped some accounts",
        )


def test_voucher_list(token: str, ledger_id: int) -> None:
    print(f"\n{CYAN}{BOLD}[STEP 1b] Voucher list query{RESET}")
    r = http("GET", "/vouchers?page=1&page_size=100", token=token, ledger_id=ledger_id)
    if r.status_code == 200:
        data = r.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        REPORT.step("Voucher list", "PASS", f"{len(items)} vouchers")
    else:
        REPORT.step("Voucher list", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")


def main() -> int:
    print(f"\n{BOLD}{CYAN}========================================")
    print(f"  COMPREHENSIVE FINANCIAL E2E TEST")
    print(f"========================================{RESET}\n")

    print(f"{CYAN}{BOLD}[STEP 1] Login + setup{RESET}")
    token, ledger_id = login()
    accounts = fetch_accounts(token, ledger_id)
    test_voucher_list(token, ledger_id)

    # Step 2: create vouchers
    test_voucher_creation(token, ledger_id, accounts)
    test_voucher_list(token, ledger_id)

    # Step 3: account balances
    test_account_balances(token, ledger_id)

    # Step 4: financial reports
    test_trial_balance(token, ledger_id)
    test_income_statement(token, ledger_id)
    test_balance_sheet(token, ledger_id)
    test_cash_flow(token, ledger_id)
    test_general_ledger(token, ledger_id)

    # Step 5: tax
    test_tax_calculation(token, ledger_id)

    # Step 6: period-end closing
    test_period_end_closing(token, ledger_id)

    # Step 7: verify
    test_post_closing_verification(token, ledger_id)

    REPORT.print_summary()
    return 0 if not REPORT.bugs else 1


if __name__ == "__main__":
    sys.exit(main())
