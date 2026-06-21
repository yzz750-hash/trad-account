"""Shared idempotency helper for period-end operations.

Used by closing.py and tax_router.py to prevent duplicate voucher generation
when the same operation is submitted concurrently.
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.financial import ClosingOperation

logger = logging.getLogger("trad_account.idempotency")


def acquire_idempotency(
    db: Session,
    ledger_id: int,
    operation_type: str,
    year: int,
    month: int,
) -> tuple[bool, ClosingOperation]:
    """Claim idempotency by inserting a closing-operation record.

    Returns (True, new_op) if this request should proceed with the work.
    Returns (False, existing_op) if another request already claimed it.

    The claim is committed inside a SAVEPOINT so it becomes visible to concurrent
    transactions immediately, closing the TOCTOU window. The caller's subsequent
    work runs in the outer transaction and can still be rolled back independently.
    """
    try:
        db.begin_nested()  # SAVEPOINT — isolates the claim from the caller's work
        op = ClosingOperation(
            ledger_id=ledger_id,
            operation_type=operation_type,
            year=year,
            month=month,
        )
        db.add(op)
        db.flush()
        db.commit()  # Release savepoint — claim is now visible to other transactions
        return True, op
    except IntegrityError:
        db.rollback()  # Roll back the savepoint
        existing = db.query(ClosingOperation).filter(
            ClosingOperation.ledger_id == ledger_id,
            ClosingOperation.operation_type == operation_type,
            ClosingOperation.year == year,
            ClosingOperation.month == month,
        ).first()
        if existing and existing.result_message is None:
            # Claim exists but work was never completed (crashed mid-flight).
            # Only re-use if no voucher was already created.
            if existing.voucher_id is not None:
                logger.warning(
                    "Orphaned claim already has voucher_id=%s — treating as completed",
                    existing.voucher_id,
                )
                return False, existing
            logger.warning(
                "Re-using orphaned idempotency claim for ledger=%s op=%s %s-%s",
                ledger_id, operation_type, year, month,
            )
            return True, existing
        return False, existing
