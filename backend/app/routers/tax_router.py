"""
VAT (增值税) and Export Tax Rebate (出口退税) module.
Implements China's foreign trade tax calculation including:
- Input VAT tracking (进项税额)
- Output VAT tracking (销项税额)
- Export tax rebate under 免抵退 method
- VAT payable summary and provisional entry generation
"""
from decimal import Decimal
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case

from app.database import get_db
from app.auth import require_write
from app.routers.ledgers import get_ledger_id
from app.models.financial import (
    TaxRate,
    VATRecord,
    Voucher,
    VoucherEntry,
    VoucherStatus,
    Account,
    AccountDirection,
    AccountType,
    ClosingOperation,
)
from app.routers.vouchers import get_next_voucher_number
from app.types import Money

router = APIRouter()

DEFAULT_VAT_RATE_INPUT = Decimal("0.13")
DEFAULT_VAT_RATE_OUTPUT = Decimal("0.13")
DEFAULT_EXPORT_REBATE_RATE = Decimal("0.13")


# ── Pydantic schemas ──────────────────────────────────────────────

class TaxRateCreate(BaseModel):
    tax_type: str  # "vat_input", "vat_output", "export_rebate"
    rate: Money
    description: str | None = None
    effective_from: date


class TaxRateResponse(BaseModel):
    id: int
    tax_type: str
    rate: Money
    description: str | None
    effective_from: date
    is_active: bool


class VATSummaryResponse(BaseModel):
    year: int
    month: int
    input_vat: Money       # 进项税额
    output_vat: Money      # 销项税额
    vat_payable: Money     # 应纳税额 = 销项 - 进项
    export_rebate_eligible: Money  # 可退税额 (计算值)
    carryover_input: Money  # 上期留抵税额
    net_payable: Money      # 最终应纳税额


class ExportRebateRequest(BaseModel):
    year: int
    month: int
    export_amount_fob: Money  # 当期出口离岸价 (人民币)
    domestic_sales: Money = Decimal("0")  # 当期国内销售额 (不含税)
    domestic_purchases: Money = Decimal("0")  # 当期国内采购额 (不含税，用于计算进项)
    taxfree_purchases: Money = Decimal("0")  # 免税购进原材料金额
    carryover_input: Money = Decimal("0")  # 上期留抵税额


class ExportRebateResponse(BaseModel):
    year: int
    month: int

    levy_rate: Money            # 征税率
    rebate_rate: Money          # 退税率
    rate_diff: Money            # 征退税差

    export_amount_fob: Money
    non_deductible: Money       # 当期不得免征和抵扣税额
    output_vat: Money           # 当期销项税额
    input_vat: Money            # 当期进项税额
    taxable_amount: Money       # 当期应纳税额 (负数=留抵)
    rebate_limit: Money         # 免抵退税额
    actual_rebate: Money        # 应退税额
    exemption_credit: Money     # 免抵税额


# ── Helpers ────────────────────────────────────────────────────────

def _get_active_rate(db: Session, ledger_id: int, tax_type: str) -> Decimal:
    """Return the active tax rate for a given type, or the default.

    只选取 effective_from <= today 的税率，避免未来生效的税率被提前使用。
    """
    today = date.today()
    rate_row = (
        db.query(TaxRate)
        .filter(
            TaxRate.ledger_id == ledger_id,
            TaxRate.tax_type == tax_type,
            TaxRate.is_active == True,
            TaxRate.effective_from <= today,
        )
        .order_by(TaxRate.effective_from.desc())
        .first()
    )
    if rate_row:
        return Decimal(str(rate_row.rate))
    defaults = {
        "vat_input": DEFAULT_VAT_RATE_INPUT,
        "vat_output": DEFAULT_VAT_RATE_OUTPUT,
        "export_rebate": DEFAULT_EXPORT_REBATE_RATE,
    }
    return defaults.get(tax_type, Decimal("0.13"))


def _seed_default_tax_rates(db: Session, ledger_id: int):
    """Ensure default tax rates exist for a ledger."""
    today = date.today()
    for tax_type, desc, default_rate in [
        ("vat_input", "增值税进项税率", DEFAULT_VAT_RATE_INPUT),
        ("vat_output", "增值税销项税率", DEFAULT_VAT_RATE_OUTPUT),
        ("export_rebate", "出口退税率", DEFAULT_EXPORT_REBATE_RATE),
        ("income_tax", "企业所得税率", Decimal("0.25")),
    ]:
        exists = (
            db.query(TaxRate)
            .filter(
                TaxRate.ledger_id == ledger_id,
                TaxRate.tax_type == tax_type,
                TaxRate.is_active == True,
            )
            .first()
        )
        if not exists:
            db.add(
                TaxRate(
                    ledger_id=ledger_id,
                    tax_type=tax_type,
                    rate=default_rate,
                    description=desc,
                    effective_from=today,
                )
            )
    db.commit()


from app.idempotency import acquire_idempotency as _acquire_idempotency


# ── Tax Rate Management ────────────────────────────────────────────

@router.get("/rates", response_model=List[TaxRateResponse])
def list_tax_rates(
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """List all tax rates configured for this ledger."""
    _seed_default_tax_rates(db, ledger_id)
    rates = (
        db.query(TaxRate)
        .filter(TaxRate.ledger_id == ledger_id)
        .order_by(TaxRate.tax_type, TaxRate.effective_from.desc())
        .all()
    )
    return [
        TaxRateResponse(
            id=r.id,
            tax_type=r.tax_type,
            rate=r.rate,
            description=r.description,
            effective_from=r.effective_from,
            is_active=r.is_active,
        )
        for r in rates
    ]


@router.post("/rates", response_model=TaxRateResponse)
def set_tax_rate(
    data: TaxRateCreate,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    current_user = Depends(require_write),
):
    """Set a new tax rate (deactivates previous rate of same type)."""
    if data.tax_type not in ("vat_input", "vat_output", "export_rebate", "income_tax"):
        raise HTTPException(status_code=400, detail="Invalid tax_type")

    # Deactivate previous active rate for this type
    db.query(TaxRate).filter(
        TaxRate.ledger_id == ledger_id,
        TaxRate.tax_type == data.tax_type,
        TaxRate.is_active == True,
    ).update({"is_active": False})

    new_rate = TaxRate(
        ledger_id=ledger_id,
        tax_type=data.tax_type,
        rate=data.rate,
        description=data.description,
        effective_from=data.effective_from,
        is_active=True,
    )
    db.add(new_rate)
    db.commit()
    db.refresh(new_rate)
    return TaxRateResponse(
        id=new_rate.id,
        tax_type=new_rate.tax_type,
        rate=new_rate.rate,
        description=new_rate.description,
        effective_from=new_rate.effective_from,
        is_active=new_rate.is_active,
    )


# ── VAT Summary ────────────────────────────────────────────────────

@router.get("/vat-summary", response_model=VATSummaryResponse)
def get_vat_summary(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """
    Calculate VAT summary for a given period.
    进项税额 + 销项税额 → 应纳税额
    """
    _seed_default_tax_rates(db, ledger_id)

    # 1. Sum input VAT (进项税额) from VAT records and voucher entries
    vat_input = (
        db.query(func.coalesce(func.sum(VATRecord.vat_amount), 0))
        .filter(
            VATRecord.ledger_id == ledger_id,
            VATRecord.vat_type == "input",
            extract("year", VATRecord.voucher_date) == year,
            extract("month", VATRecord.voucher_date) == month,
        )
        .scalar()
    ) or Decimal("0")

    # Also sum from voucher_entries with vat_amount set
    entry_input = (
        db.query(func.coalesce(func.sum(VoucherEntry.vat_amount), 0))
        .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
        .filter(
            Voucher.ledger_id == ledger_id,
            VoucherEntry.vat_amount.isnot(None),
            VoucherEntry.direction == AccountDirection.DEBIT,
            extract("year", Voucher.voucher_date) == year,
            extract("month", Voucher.voucher_date) == month,
            Voucher.status == VoucherStatus.POSTED,
        )
        .scalar()
    ) or Decimal("0")

    total_input_vat = Decimal(str(vat_input)) + Decimal(str(entry_input))

    # 2. Sum output VAT (销项税额)
    vat_output = (
        db.query(func.coalesce(func.sum(VATRecord.vat_amount), 0))
        .filter(
            VATRecord.ledger_id == ledger_id,
            VATRecord.vat_type == "output",
            extract("year", VATRecord.voucher_date) == year,
            extract("month", VATRecord.voucher_date) == month,
        )
        .scalar()
    ) or Decimal("0")

    entry_output = (
        db.query(func.coalesce(func.sum(VoucherEntry.vat_amount), 0))
        .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
        .filter(
            Voucher.ledger_id == ledger_id,
            VoucherEntry.vat_amount.isnot(None),
            VoucherEntry.direction == AccountDirection.CREDIT,
            extract("year", Voucher.voucher_date) == year,
            extract("month", Voucher.voucher_date) == month,
            Voucher.status == VoucherStatus.POSTED,
        )
        .scalar()
    ) or Decimal("0")

    total_output_vat = Decimal(str(vat_output)) + Decimal(str(entry_output))

    # 3. Get carryover from previous period
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    prev_input = (
        db.query(func.coalesce(func.sum(VATRecord.vat_amount), 0))
        .filter(
            VATRecord.ledger_id == ledger_id,
            VATRecord.vat_type == "input",
            extract("year", VATRecord.voucher_date) == prev_year,
            extract("month", VATRecord.voucher_date) == prev_month,
        )
        .scalar()
    ) or Decimal("0")
    prev_output = (
        db.query(func.coalesce(func.sum(VATRecord.vat_amount), 0))
        .filter(
            VATRecord.ledger_id == ledger_id,
            VATRecord.vat_type == "output",
            extract("year", VATRecord.voucher_date) == prev_year,
            extract("month", VATRecord.voucher_date) == prev_month,
        )
        .scalar()
    ) or Decimal("0")

    carryover = max(Decimal(str(prev_input)) - Decimal(str(prev_output)), Decimal("0"))

    # 4. Export rebate estimate
    export_records = (
        db.query(func.coalesce(func.sum(VATRecord.export_amount_fob), 0))
        .filter(
            VATRecord.ledger_id == ledger_id,
            VATRecord.is_export == True,
            extract("year", VATRecord.voucher_date) == year,
            extract("month", VATRecord.voucher_date) == month,
        )
        .scalar()
    ) or Decimal("0")

    rebate_rate = _get_active_rate(db, ledger_id, "export_rebate")
    export_rebate_eligible = Decimal(str(export_records)) * rebate_rate

    # 5. VAT payable
    vat_payable = total_output_vat - total_input_vat
    net_payable = max(vat_payable - carryover, Decimal("0"))

    return VATSummaryResponse(
        year=year,
        month=month,
        input_vat=round(total_input_vat, 2),
        output_vat=round(total_output_vat, 2),
        vat_payable=round(vat_payable, 2),
        export_rebate_eligible=round(export_rebate_eligible, 2),
        carryover_input=round(carryover, 2),
        net_payable=round(net_payable, 2),
    )


# ── Export Tax Rebate Calculation (出口退税 / 免抵退) ──────────────

@router.post("/export-rebate", response_model=ExportRebateResponse)
def calculate_export_rebate(
    req: ExportRebateRequest,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    current_user = Depends(require_write),
):
    """
    Calculate export tax rebate using China's 免抵退 (exemption-credit-refund) method.

    免抵退计算公式:
      当期不得免征和抵扣税额 = (出口离岸价 - 免税购进原材料) × (征税率 - 退税率)
      当期应纳税额 = 销项税额 - (进项税额 - 不得免征和抵扣税额) - 上期留抵
      免抵退税额 = 出口离岸价 × 退税率
      应退税额 = min(期末留抵税额, 免抵退税额)
      免抵税额 = 免抵退税额 - 应退税额
    """
    _seed_default_tax_rates(db, ledger_id)

    levy_rate = _get_active_rate(db, ledger_id, "vat_output")
    rebate_rate = _get_active_rate(db, ledger_id, "export_rebate")

    if levy_rate < rebate_rate:
        raise HTTPException(
            status_code=400,
            detail=f"退税率({rebate_rate:.1%})不能高于征税率({levy_rate:.1%})",
        )

    rate_diff = levy_rate - rebate_rate

    # Step 1: 当期不得免征和抵扣税额
    export_fob = req.export_amount_fob
    taxfree_purchases = req.taxfree_purchases
    non_deductible = max((export_fob - taxfree_purchases) * rate_diff, Decimal("0"))

    # Step 2: 当期销项税额 (from domestic sales)
    output_vat = req.domestic_sales * levy_rate

    # Step 3: 当期进项税额 (from domestic purchases)
    input_vat = req.domestic_purchases * levy_rate

    # Step 4: 当期应纳税额 = 销项 - (进项 - 不得免征和抵扣) - 上期留抵
    taxable = output_vat - (input_vat - non_deductible) - req.carryover_input

    # Step 5: 免抵退税额
    rebate_limit = export_fob * rebate_rate

    # Step 6: 应退税额 = min(期末留抵绝对值, 免抵退税额) when 应纳税额 < 0
    if taxable < 0:
        actual_rebate = min(abs(taxable), rebate_limit)
        exemption_credit = rebate_limit - actual_rebate
    else:
        actual_rebate = Decimal("0")
        exemption_credit = rebate_limit

    return ExportRebateResponse(
        year=req.year,
        month=req.month,
        levy_rate=levy_rate,
        rebate_rate=rebate_rate,
        rate_diff=rate_diff,
        export_amount_fob=export_fob,
        non_deductible=round(non_deductible, 2),
        output_vat=round(output_vat, 2),
        input_vat=round(input_vat, 2),
        taxable_amount=round(taxable, 2),
        rebate_limit=round(rebate_limit, 2),
        actual_rebate=round(actual_rebate, 2),
        exemption_credit=round(exemption_credit, 2),
    )


# ── VAT Payable Provisional Entry ──────────────────────────────────

class CreateVATVoucherRequest(BaseModel):
    year: int
    month: int


@router.post("/create-vat-voucher")
def create_vat_payable_voucher(
    req: CreateVATVoucherRequest,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    current_user = Depends(require_write),
):
    """
    Generate a provisional entry for VAT payable at period end.
    Debit: 应交税费-应交增值税(转出未交增值税)
    Credit: 应交税费-未交增值税
    """
    proceed, op = _acquire_idempotency(db, ledger_id, "vat_provision", req.year, req.month)
    if not proceed:
        return {
            "status": "success",
            "message": f"VAT provision already performed: {op.result_message}",
            "idempotent": True,
        }

    # Get VAT summary
    summary = get_vat_summary(req.year, req.month, db, ledger_id)

    if summary.net_payable <= 0:
        return {"status": "success", "message": "当期无应缴增值税，无需生成凭证"}

    # Find VAT accounts
    vat_payable_acc = db.query(Account).filter(
        Account.ledger_id == ledger_id,
        Account.code == "2221",
    ).first()
    vat_unpaid_acc = db.query(Account).filter(
        Account.ledger_id == ledger_id,
        Account.name.like("%未交增值税%"),
    ).first()

    if not vat_payable_acc:
        raise HTTPException(status_code=400, detail="未找到 2221 应交税费 科目")
    if not vat_unpaid_acc:
        # Create the sub-account with hierarchical code (parent.code + "01", etc.)
        siblings = db.query(Account).filter(
            Account.ledger_id == ledger_id,
            Account.parent_id == vat_payable_acc.id,
        ).all()
        max_suffix = 0
        for sib in siblings:
            try:
                suffix = int(sib.code[len(vat_payable_acc.code):])
                if suffix > max_suffix:
                    max_suffix = suffix
            except (ValueError, IndexError):
                pass
        new_code = vat_payable_acc.code + str(max_suffix + 1).zfill(2)
        vat_unpaid_acc = Account(
            ledger_id=ledger_id,
            code=new_code,
            name="未交增值税",
            account_type=AccountType.LIABILITY,
            balance_direction=AccountDirection.CREDIT,
            parent_id=vat_payable_acc.id,
        )
        db.add(vat_unpaid_acc)
        db.flush()

    # 使用月末最后一天作为凭证日期，避免漏算 29-31 号
    import calendar as _cal
    _, _last_day = _cal.monthrange(req.year, req.month)
    v = Voucher(
        ledger_id=ledger_id,
        voucher_number=get_next_voucher_number(db, ledger_id, "税-"),
        voucher_date=date(req.year, req.month, _last_day),
        status=VoucherStatus.DRAFT,
    )
    db.add(v)
    db.flush()

    db.add(VoucherEntry(
        voucher_id=v.id,
        account_id=vat_payable_acc.id,
        summary=f"{req.year}-{req.month:02d} 转出未交增值税",
        direction=AccountDirection.DEBIT,
        amount=summary.net_payable,
    ))
    db.add(VoucherEntry(
        voucher_id=v.id,
        account_id=vat_unpaid_acc.id,
        summary=f"{req.year}-{req.month:02d} 未交增值税",
        direction=AccountDirection.CREDIT,
        amount=summary.net_payable,
    ))

    op.voucher_id = v.id
    op.result_message = f"VAT provision voucher created: 应交增值税 {summary.net_payable:.2f}"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create VAT voucher")

    return {"status": "success", "message": f"VAT provision voucher created: 应交增值税 {summary.net_payable:.2f}", "voucher_id": v.id}


# ── VAT Record CRUD ────────────────────────────────────────────────

class VATRecordCreate(BaseModel):
    voucher_id: int
    voucher_date: date
    vat_type: str  # "input" or "output"
    invoice_code: str | None = None
    invoice_number: str | None = None
    counterpart_name: str | None = None
    taxable_amount: Money
    vat_rate: Money = DEFAULT_VAT_RATE_INPUT
    vat_amount: Money
    total_amount: Money
    is_export: bool = False
    export_amount_fob: Money | None = None
    export_currency: str | None = None
    export_rebate_rate: Money | None = None


@router.post("/records")
def add_vat_record(
    data: VATRecordCreate,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    current_user = Depends(require_write),
):
    """Record a VAT invoice (进项 or 销项) for tax tracking."""
    if data.vat_type not in ("input", "output"):
        raise HTTPException(status_code=400, detail="vat_type must be 'input' or 'output'")

    # Verify voucher exists in this ledger
    v = db.query(Voucher).filter(
        Voucher.ledger_id == ledger_id,
        Voucher.id == data.voucher_id,
    ).first()
    if not v:
        raise HTTPException(status_code=404, detail="Voucher not found")

    record = VATRecord(
        ledger_id=ledger_id,
        voucher_id=data.voucher_id,
        voucher_date=data.voucher_date,
        vat_type=data.vat_type,
        invoice_code=data.invoice_code,
        invoice_number=data.invoice_number,
        counterpart_name=data.counterpart_name,
        taxable_amount=data.taxable_amount,
        vat_rate=data.vat_rate,
        vat_amount=data.vat_amount,
        total_amount=data.total_amount,
        is_export=data.is_export,
        export_amount_fob=data.export_amount_fob,
        export_currency=data.export_currency,
        export_rebate_rate=data.export_rebate_rate,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "success", "id": record.id}


@router.get("/records")
def list_vat_records(
    year: int,
    month: int | None = None,
    vat_type: str | None = None,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
):
    """List VAT records for a period."""
    q = db.query(VATRecord).filter(
        VATRecord.ledger_id == ledger_id,
        extract("year", VATRecord.voucher_date) == year,
    )
    if month:
        q = q.filter(extract("month", VATRecord.voucher_date) == month)
    if vat_type:
        q = q.filter(VATRecord.vat_type == vat_type)

    records = q.order_by(VATRecord.voucher_date.desc()).all()
    return [
        {
            "id": r.id,
            "voucher_id": r.voucher_id,
            "voucher_date": str(r.voucher_date),
            "vat_type": r.vat_type,
            "invoice_code": r.invoice_code,
            "invoice_number": r.invoice_number,
            "counterpart_name": r.counterpart_name,
            "taxable_amount": r.taxable_amount,
            "vat_rate": r.vat_rate,
            "vat_amount": r.vat_amount,
            "total_amount": r.total_amount,
            "is_export": r.is_export,
            "export_amount_fob": r.export_amount_fob,
        }
        for r in records
    ]
