from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, Any
import logging

from app.database import get_db
from app.auth import require_write
from app.routers.ledgers import get_ledger_id
from app.models.financial import (
    Account,
    AccountBalance,
    Voucher,
    VoucherEntry,
    VoucherStatus,
    AccountDirection,
    AccountType,
    FixedAsset,
    AccountingPeriod,
    Currency,
    ExchangeRate,
    PeriodStatus,
)
from app.routers.vouchers import get_next_voucher_number
from app.models.financial import ClosingOperation

logger = logging.getLogger("trad_account")

router = APIRouter()


from app.idempotency import acquire_idempotency as _acquire_idempotency
from app.services.closing import (
    check_no_draft_vouchers,
    compute_period_balances,
    calculate_depreciation,
    calculate_fx_revaluation,
    calculate_profit_loss_carry_forward,
    PNL_CARRY_FORWARD_SOURCE_TYPE,
    YEAR_END_CARRY_FORWARD_SOURCE_TYPE,
)



@router.post("/depreciate")
def auto_depreciate_assets(year: int, month: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), current_user = Depends(require_write)):
    """
    一键计提当月所有固定资产折旧并自动生成记账凭证
    Uses straight-line method (直线法).
    """
    logger.info("Depreciation started for ledger %s, period %s-%s", ledger_id, year, month)
    proceed, op = _acquire_idempotency(db, ledger_id, "depreciate", year, month)
    if not proceed:
        return {"status": "success", "message": f"Depreciation already performed: {op.result_message}", "idempotent": True}
    check_no_draft_vouchers(db, ledger_id, year, month)

    total_depreciation, __, had_any = calculate_depreciation(db, ledger_id, year, month)
    if total_depreciation == 0:
        if not had_any:
            return {"status": "success", "message": "No active fixed assets found."}
        return {"status": "success", "message": "All assets are fully depreciated."}

    # Create Depreciation Voucher
    debit_acc = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "6602").first()
    credit_acc = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "1602").first()
    if not debit_acc:
        debit_acc = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "6601").first()
    if not debit_acc or not credit_acc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Depreciation accounts not found: {'6602/6601' if not debit_acc else ''}{' and ' if not debit_acc and not credit_acc else ''}{'1602' if not credit_acc else ''}."
        )

    import calendar as _cal
    _, _last_day = _cal.monthrange(year, month)
    v = Voucher(ledger_id=ledger_id, voucher_number=get_next_voucher_number(db, ledger_id),
        voucher_date=date(year, month, _last_day),
        status=VoucherStatus.DRAFT,
    )
    db.add(v)
    db.flush()

    db.add(VoucherEntry(
        voucher_id=v.id, account_id=debit_acc.id,
        summary="计提当月固定资产折旧", direction=AccountDirection.DEBIT,
        amount=total_depreciation,
    ))
    db.add(VoucherEntry(
        voucher_id=v.id, account_id=credit_acc.id,
        summary="计提当月固定资产折旧", direction=AccountDirection.CREDIT,
        amount=total_depreciation,
    ))

    op.voucher_id = v.id
    op.result_message = f"Depreciation voucher created with total {total_depreciation:.2f}"
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to create depreciation voucher for ledger %s, period %s-%s", ledger_id, year, month)
        raise HTTPException(status_code=500, detail="Failed to create depreciation voucher.")
    return {"status": "success", "message": f"Depreciation voucher created with total {total_depreciation:.2f}"}


@router.post("/profit-loss")
def carry_forward_profit_loss(year: int, month: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), current_user = Depends(require_write)):
    """
    月末自动将所有损益类科目结转至"本年利润"
    """
    logger.info("Profit-loss carry-forward started for ledger %s, period %s-%s", ledger_id, year, month)
    proceed, op = _acquire_idempotency(db, ledger_id, "profit_loss", year, month)
    if not proceed:
        return {"status": "success", "message": f"P&L carry-forward already performed: {op.result_message}", "idempotent": True}
    check_no_draft_vouchers(db, ledger_id, year, month)

    profit_account = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "4103").first()
    if not profit_account:
        raise HTTPException(status_code=400, detail="Account '本年利润' not found.")

    entries, total_profit_impact = calculate_profit_loss_carry_forward(db, ledger_id, year, month)

    if not entries:
        db.rollback()
        return {"status": "success", "message": "No profit/loss entries to carry forward."}

    import calendar as _cal
    _, _last_day = _cal.monthrange(year, month)
    voucher_date = date(year, month, _last_day)
    v = Voucher(ledger_id=ledger_id, voucher_number=get_next_voucher_number(db, ledger_id),
        voucher_date=voucher_date,
        status=VoucherStatus.DRAFT,
        source_type=PNL_CARRY_FORWARD_SOURCE_TYPE,
    )
    db.add(v)
    db.flush()

    for e in entries:
        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=e["account_id"],
            summary=e["summary"],
            direction=e["direction"],
            amount=e["amount"],
        ))

    # Create the balancing entry for '本年利润'
    profit_direction = AccountDirection.CREDIT if total_profit_impact >= 0 else AccountDirection.DEBIT
    db.add(VoucherEntry(
        voucher_id=v.id,
        account_id=profit_account.id,
        summary="结转本月损益",
        direction=profit_direction,
        amount=abs(total_profit_impact),
    ))

    op.voucher_id = v.id
    op.result_message = f"P&L carry-forward completed. Net profit impact: {total_profit_impact:.2f}"
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to carry forward profit/loss for ledger %s, period %s-%s", ledger_id, year, month)
        raise HTTPException(status_code=500, detail="Failed to carry forward profit/loss.")
    return {
        "status": "success",
        "message": f"P&L carry-forward completed. Net profit impact: {total_profit_impact:.2f}",
        "voucher_id": v.id,
        "voucher_status": v.status.value,
        "net_profit_impact": float(total_profit_impact),
        "note": "Voucher is created in DRAFT status. POST it via /api/v1/vouchers/{id}/post to finalize the carry-forward before period close.",
    }


@router.post("/year-end")
def carry_forward_year_end(year: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), current_user = Depends(require_write)):
    """
    年末结转：本年利润结转至未分配利润
    """
    logger.info("Year-end carry-forward started for ledger %s, year %s", ledger_id, year)
    proceed, op = _acquire_idempotency(db, ledger_id, "year_end", year, 12)
    if not proceed:
        return {"status": "success", "message": f"Year-end carry-forward already performed: {op.result_message}", "idempotent": True}
    check_no_draft_vouchers(db, ledger_id, year, 12)

    profit_account = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.code == "4103"
    ).first()
    retained_earnings = db.query(Account).filter(
        Account.ledger_id == ledger_id, Account.code == "4104"
    ).first()

    if not profit_account:
        raise HTTPException(status_code=400, detail="Account '本年利润' (4103) not found.")
    if not retained_earnings:
        raise HTTPException(status_code=400, detail="Account '利润分配' (4104) not found.")

    from sqlalchemy import extract

    entries = (
        db.query(
            VoucherEntry.direction,
            func.sum(VoucherEntry.amount),
        )
        .join(Voucher)
        .filter(
            Voucher.ledger_id == ledger_id,
            VoucherEntry.account_id == profit_account.id,
            Voucher.status == VoucherStatus.POSTED,
            extract("year", Voucher.voucher_date) == year,
        )
        .group_by(VoucherEntry.direction)
        .all()
    )

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for direction, amt in entries:
        if direction == AccountDirection.DEBIT:
            total_debit = Decimal(str(amt or 0))
        else:
            total_credit = Decimal(str(amt or 0))

    net_profit = total_credit - total_debit

    if net_profit == 0:
        return {"status": "success", "message": "本年利润余额为零，无需结转。"}

    v = Voucher(
        ledger_id=ledger_id,
        voucher_number=get_next_voucher_number(db, ledger_id),
        voucher_date=date(year, 12, 31),
        status=VoucherStatus.DRAFT,
        source_type=YEAR_END_CARRY_FORWARD_SOURCE_TYPE,
    )
    db.add(v)
    db.flush()

    if net_profit > 0:
        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=profit_account.id,
            summary="年末结转本年利润至未分配利润",
            direction=AccountDirection.DEBIT,
            amount=net_profit,
        ))
        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=retained_earnings.id,
            summary="年末结转本年利润至未分配利润",
            direction=AccountDirection.CREDIT,
            amount=net_profit,
        ))
    else:
        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=retained_earnings.id,
            summary="年末结转本年亏损至未分配利润",
            direction=AccountDirection.DEBIT,
            amount=abs(net_profit),
        ))
        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=profit_account.id,
            summary="年末结转本年亏损至未分配利润",
            direction=AccountDirection.CREDIT,
            amount=abs(net_profit),
        ))

    op.voucher_id = v.id
    op.result_message = f"Year-end carry-forward completed. Net profit/loss: {net_profit:.2f} transferred to Retained Earnings."
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to carry forward year-end profit/loss.")

    return {
        "status": "success",
        "message": f"Year-end carry-forward completed. Net profit/loss: {net_profit:.2f} transferred to Retained Earnings. [BUGFIX-v2]",
        "voucher_id": v.id,
        "voucher_status": v.status.value,
        "net_profit": float(net_profit),
        "note": "Voucher is created in DRAFT status. POST it via /api/v1/vouchers/{id}/post to finalize the year-end carry-forward.",
    }


@router.post("/fx-revaluation")
def fx_revaluation(year: int, month: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), current_user = Depends(require_write)):
    """
    自动期末调汇
    计算本期所有外币科目的汇兑损益，并生成凭证
    """
    logger.info("FX revaluation started for ledger %s, period %s-%s", ledger_id, year, month)
    proceed, op = _acquire_idempotency(db, ledger_id, "fx_revaluation", year, month)
    if not proceed:
        return {"status": "success", "message": f"FX revaluation already performed: {op.result_message}", "idempotent": True}
    check_no_draft_vouchers(db, ledger_id, year, month)

    fx_account = db.query(Account).filter(Account.ledger_id == ledger_id, Account.code == "6603").first()
    if not fx_account:
        raise HTTPException(status_code=400, detail="未找到 6603 财务费用 科目")

    from app.services.closing import FX_REVALUATION_SOURCE_TYPE

    entries, total_gain_loss = calculate_fx_revaluation(db, ledger_id, year, month)

    if not entries:
        return {"status": "success", "message": "当前期间无外币发生额，无需调汇"}
    if total_gain_loss == 0:
        return {"status": "success", "message": "汇率无变化或无外币余额，无需生成调汇凭证"}

    v_num = get_next_voucher_number(db, ledger_id, prefix="期末调汇-")
    import calendar
    _, last_day = calendar.monthrange(year, month)
    # Use DRAFT status so the FX revaluation voucher goes through the normal
    # review/post workflow instead of bypassing segregation of duties. The
    # source_type tag lets subsequent runs exclude it from the FX baseline.
    v = Voucher(ledger_id=ledger_id, voucher_number=v_num,
        voucher_date=date(year, month, last_day),
        attachments_count=0,
        status=VoucherStatus.DRAFT,
        source_type=FX_REVALUATION_SOURCE_TYPE,
    )
    db.add(v)
    db.flush()

    for e in entries:
        eid = e["account_id"]
        if eid is None:
            eid = fx_account.id
        db.add(VoucherEntry(
            voucher_id=v.id,
            account_id=eid,
            summary=e["summary"],
            direction=e["direction"],
            amount=e["amount"],
            currency_code=e["currency_code"],
        ))

    op.voucher_id = v.id
    op.result_message = f"成功生成期末调汇凭证 {v_num}，调整总额 {total_gain_loss:.2f}"
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to create FX revaluation voucher for ledger %s, period %s-%s", ledger_id, year, month)
        raise HTTPException(status_code=500, detail="Failed to create FX revaluation voucher.")
    return {"status": "success", "message": f"FX revaluation completed. Voucher: {v_num}, total adjustment: {total_gain_loss:.2f}"}



@router.post("/close")
def close_period(year: int, month: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), current_user = Depends(require_write)):
    """月末结账：锁定当月期间，禁止再修改凭证
    Uses SELECT FOR UPDATE on the period row for cross-process mutual exclusion.
    """
    logger.info("Period closing started for ledger %s, period %s-%s", ledger_id, year, month)
    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == year,
        AccountingPeriod.month == month,
    ).with_for_update().first()
    if not period:
        raise HTTPException(status_code=404, detail="Period not found.")
    if period.status == PeriodStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Period is already closed.")
    # Require previous period to be closed first (balance chain integrity)
    if month > 1:
        prev_year, prev_month = year, month - 1
    else:
        prev_year, prev_month = year - 1, 12
    prev_period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == prev_year,
        AccountingPeriod.month == prev_month,
    ).first()
    if prev_period and prev_period.status != PeriodStatus.CLOSED:
        raise HTTPException(
            status_code=400,
            detail=f"Previous period {prev_year}-{prev_month:02d} must be closed before closing {year}-{month:02d}.",
        )
    draft_vouchers = db.query(Voucher).filter(
        Voucher.ledger_id == ledger_id,
        func.extract('year', Voucher.voucher_date) == year,
        func.extract('month', Voucher.voucher_date) == month,
        Voucher.status == VoucherStatus.DRAFT,
    ).count()
    if draft_vouchers > 0:
        raise HTTPException(status_code=400, detail="Cannot close period. There are unposted vouchers.")
    period.status = PeriodStatus.CLOSED
    compute_period_balances(db, ledger_id, year, month)
    db.commit()
    return {"status": "success", "message": f"Period {year}-{month} closed successfully."}

@router.post("/unclose")
def unclose_period(year: int, month: int, db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id), current_user = Depends(require_write)):
    """
    反结账：解锁期间。

    会级联清理：
    1. 当月及后续所有期间的期末凭证（折旧/损益结转/FX 调汇/年末结转）；
       通过 voucher_id 反查 ClosingOperation，定位系统生成的期末凭证。
    2. 对应的 ClosingOperation 幂等记录（否则下次无法重做期末操作）。
    3. 当月及后续所有期间的 AccountBalance（余额链已断，必须重算）。
    4. 重开当月及后续已 CLOSED 的 AccountingPeriod。
    用户在期间内手工录入的凭证不受影响。
    """
    logger.info("Period unclosing started for ledger %s, period %s-%s", ledger_id, year, month)
    period = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.year == year,
        AccountingPeriod.month == month,
    ).with_for_update().first()
    if not period:
        raise HTTPException(status_code=404, detail="Period not found.")

    if period.status == PeriodStatus.OPEN:
        raise HTTPException(status_code=400, detail="Period is already open.")

    # Identify the boundary: (year, month) and everything after.
    # Use a SQL OR so we cover both same-year-future-months and later years.
    from sqlalchemy import or_ as _or

    def _period_filter(col_year, col_month):
        return _or(
            (col_year == year) & (col_month >= month),
            col_year > year,
        )

    # 1. Collect voucher_ids of all ClosingOperations for this period and later.
    closing_ops = (
        db.query(ClosingOperation)
        .filter(
            ClosingOperation.ledger_id == ledger_id,
            _period_filter(ClosingOperation.year, ClosingOperation.month),
        )
        .all()
    )
    closing_voucher_ids = [op.voucher_id for op in closing_ops if op.voucher_id is not None]

    # 2. Delete the system-generated closing vouchers (entries cascade via FK or
    #    ORM relationship). User-authored vouchers in the period are preserved.
    deleted_voucher_count = 0
    if closing_voucher_ids:
        # Delete VoucherEntry rows first to avoid FK violations on Voucher delete.
        db.query(VoucherEntry).filter(
            VoucherEntry.voucher_id.in_(closing_voucher_ids)
        ).delete(synchronize_session="fetch")
        db.query(Voucher).filter(
            Voucher.id.in_(closing_voucher_ids),
            Voucher.ledger_id == ledger_id,
        ).delete(synchronize_session="fetch")
        deleted_voucher_count = len(closing_voucher_ids)

    # 3. Drop the idempotency claims so the operations can be re-run.
    for op in closing_ops:
        db.delete(op)

    # 4. Invalidate AccountBalance rows for this period and all subsequent ones.
    #    The balance chain is broken once a period is reopened.
    subsequent_balances = db.query(AccountBalance).filter(
        AccountBalance.ledger_id == ledger_id,
        _period_filter(AccountBalance.year, AccountBalance.month),
    ).all()
    if subsequent_balances:
        logger.warning(
            "Unclosing %s-%s: cascade-deleting %d AccountBalance rows (this period + subsequent). "
            "These periods must be re-closed in chronological order.",
            year, month, len(subsequent_balances),
        )
        for sb in subsequent_balances:
            db.delete(sb)

    # 5. Reopen subsequent CLOSED periods (their balances are now invalid).
    subs_periods = db.query(AccountingPeriod).filter(
        AccountingPeriod.ledger_id == ledger_id,
        AccountingPeriod.status == PeriodStatus.CLOSED,
        _period_filter(AccountingPeriod.year, AccountingPeriod.month),
    ).all()
    for sp in subs_periods:
        sp.status = PeriodStatus.OPEN
        logger.warning("Unclose cascade: reopened period %s-%s", sp.year, sp.month)

    # 6. Finally reopen the requested period itself.
    period.status = PeriodStatus.OPEN

    logger.info(
        "Unclose %s-%s complete: deleted %d closing voucher(s), %d closing op(s), "
        "%d balance row(s), reopened %d subsequent period(s).",
        year, month, deleted_voucher_count, len(closing_ops),
        len(subsequent_balances), len(subs_periods),
    )
    db.commit()
    return {
        "status": "success",
        "message": (
            f"Period {year}-{month:02d} reopened. "
            f"Deleted {deleted_voucher_count} system voucher(s) and {len(closing_ops)} idempotency record(s)."
        ),
    }
