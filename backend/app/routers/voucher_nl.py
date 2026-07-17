"""Natural language to voucher handler for AI chat."""
import json
import logging
from decimal import Decimal

logger = logging.getLogger("trad_account")


VOUCHER_GEN_PROMPT = """你是一个中国外贸财务系统的会计 AI 助手。请根据用户描述的经济业务，生成对应的会计凭证分录。

可用科目列表（格式：编码 - 名称 - 类型 - 余额方向）：
{accounts}

当前日期：{today}
账套本位币：CNY

要求：
1. 根据业务描述选择最合适的科目（必须从上面的列表中选）
2. 借贷必须平衡（借方合计 = 贷方合计）
3. 金额保留两位小数
4. 每条分录的摘要要简洁明了
5. 如果涉及外币，请设置 currency_code、original_amount、exchange_rate
6. 如果用户没有指定日期，使用当前日期

返回 JSON 格式：
{{
  "voucher_date": "YYYY-MM-DD",
  "summary": "凭证摘要",
  "entries": [
    {{"account_code": "1002", "summary": "收XX货款", "direction": "借", "amount": "72000.00", "currency_code": "CNY"}},
    {{"account_code": "1122", "summary": "收XX货款", "direction": "贷", "amount": "72000.00", "currency_code": "CNY"}}
  ]
}}

用户描述：{description}
"""


async def _llm_json(prompt, config):
    """Call LLM with json_object response format, return parsed dict."""
    from app.llm import get_llm_response
    raw = get_llm_response(
        prompt=prompt, config=config,
        response_format={"type": "json_object"},
        max_tokens=2000, temperature=0.1, timeout=60.0,
    )
    return json.loads(raw)


async def create_voucher_suggestion(db, ledger_id, config, user_msg):
    """Generate voucher suggestion from natural language description.

    Yields SSE data lines for the AI chat stream.
    """
    from app.models.financial import Account
    from datetime import date

    accounts = db.query(Account).filter(
        Account.ledger_id == ledger_id,
        Account.is_active == True,
    ).order_by(Account.code).all()

    if not accounts:
        err = json.dumps({"type": "error", "text": "当前账套没有可用科目，请先在科目设置中创建科目。"}, ensure_ascii=False)
        yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Format the account list for the prompt: 编码 - 名称 - 类型 - 余额方向
    type_names = {
        "ASSET": "资产", "LIABILITY": "负债", "EQUITY": "权益",
        "COST": "成本", "PROFIT_LOSS": "损益",
    }
    dir_names = {"DEBIT": "借", "CREDIT": "贷"}

    def _enum_val(v):
        return v.value if hasattr(v, "value") else str(v)

    acct_lines = []
    for a in accounts:
        t = type_names.get(_enum_val(a.account_type), str(a.account_type))
        d = dir_names.get(_enum_val(a.balance_direction), str(a.balance_direction))
        acct_lines.append(f"{a.code} - {a.name} - {t} - {d}")
    accounts_text = "\n".join(acct_lines)

    today = date.today().isoformat()
    prompt = VOUCHER_GEN_PROMPT.format(
        accounts=accounts_text, today=today, description=user_msg,
    )

    # Call LLM to generate the voucher structure
    try:
        result = await _llm_json(prompt, config)
    except Exception as e:
        logger.error("Voucher generation LLM call failed: %s", e)
        err = json.dumps({"type": "error", "text": "AI 生成凭证失败，请稍后重试。"}, ensure_ascii=False)
        yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"
        return

    entries = result.get("entries") or []
    if not entries:
        err = json.dumps({"type": "error", "text": "AI 未能生成凭证分录，请提供更详细的业务描述。"}, ensure_ascii=False)
        yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Resolve account codes to Account objects (all must exist in this ledger)
    codes = {str(e.get("account_code", "")).strip() for e in entries if e.get("account_code")}
    code_to_acct = {}
    if codes:
        code_to_acct = {
            a.code: a for a in db.query(Account).filter(
                Account.ledger_id == ledger_id, Account.code.in_(codes),
            ).all()
        }

    missing = sorted(c for c in codes if c not in code_to_acct)
    if missing:
        err = json.dumps(
            {"type": "error", "text": f"AI 选择的科目不存在：{', '.join(missing)}。请先在科目设置中创建对应科目。"},
            ensure_ascii=False,
        )
        yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Validate double-entry balance (借方合计 == 贷方合计)
    def _to_decimal(v):
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal("0")

    def _normalize_direction(v):
        """Normalize LLM-returned direction to '借' or '贷'.

        VoucherEntrySchema only accepts '借'/'贷'; LLM may return
        DEBIT/CREDIT/借方/贷方 etc.
        """
        s = str(v).strip()
        if s in ("借", "DEBIT", "debit", "借方", "dr", "Dr"):
            return "借"
        if s in ("贷", "CREDIT", "credit", "贷方", "cr", "Cr"):
            return "贷"
        return ""

    def _validate_date(v):
        """Validate YYYY-MM-DD; return None if invalid."""
        if not v:
            return None
        try:
            from datetime import date as _date
            return _date.fromisoformat(str(v)[:10]).isoformat()
        except (ValueError, TypeError):
            return None

    debit_total = Decimal("0")
    credit_total = Decimal("0")
    for e in entries:
        amt = _to_decimal(e.get("amount", "0"))
        direction = _normalize_direction(e.get("direction", ""))
        if direction == "借":
            debit_total += amt
        elif direction == "贷":
            credit_total += amt

    # Quantize to 2dp to avoid sub-cent drift when comparing
    debit_total_q = debit_total.quantize(Decimal("0.01"))
    credit_total_q = credit_total.quantize(Decimal("0.01"))
    if debit_total_q != credit_total_q:
        err = json.dumps(
            {"type": "error", "text": f"借贷不平衡：借方 {debit_total_q}，贷方 {credit_total_q}，请重新描述业务。"},
            ensure_ascii=False,
        )
        yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Build the suggestion payload. The voucher number is assigned at creation
    # time — the suggestion is a preview only, so we do not consume a number
    # from the counter here.
    voucher_summary = str(result.get("summary", "")).strip()
    suggestion_entries = []
    for e in entries:
        code = str(e.get("account_code", "")).strip()
        acct = code_to_acct.get(code)
        direction = _normalize_direction(e.get("direction", ""))
        amount = _to_decimal(e.get("amount", "0")).quantize(Decimal("0.01"))
        # Ensure summary non-empty (VoucherEntrySchema requires min_length=1);
        # fall back to the voucher-level summary, then the account name.
        entry_summary = str(e.get("summary", "")).strip() or voucher_summary or (acct.name if acct else code)
        suggestion_entries.append({
            "account_id": acct.id if acct else None,
            "account_code": code,
            "account_name": acct.name if acct else "",
            "summary": entry_summary,
            "direction": direction,
            "amount": str(amount),
            "currency_code": e.get("currency_code", "CNY") or "CNY",
            "original_amount": e.get("original_amount"),
            "exchange_rate": e.get("exchange_rate", "1.0000"),
        })

    # Validate voucher_date format (LLM may return '2026年7月17日' etc.)
    raw_date = result.get("voucher_date")
    voucher_date = _validate_date(raw_date) or today

    payload = {
        "type": "meta",
        "action_type": "SUGGEST_VOUCHER",
        "action_payload": {
            "voucher_date": voucher_date,
            "voucher_number": "",
            "summary": voucher_summary,
            "entries": suggestion_entries,
            "debit_total": str(debit_total_q),
            "credit_total": str(credit_total_q),
        },
        "text": f"我已为您生成凭证建议（共 {len(suggestion_entries)} 条分录，金额 {debit_total_q} 元），请确认是否录入？",
    }
    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
