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

    The claim is committed as its own transaction so it becomes visible to
    concurrent transactions immediately, closing the TOCTOU window. The
    caller's subsequent work runs in a fresh transaction (SQLAlchemy re-begins
    automatically on next query) and can still be rolled back independently.

    NOTE: callers must NOT have uncommitted in-flight work in `db` when calling
    this — any such work will be committed alongside the claim. All current
    callers (closing router endpoints) invoke this as their first DB-mutating
    step, after only read-only queries, so the constraint is satisfied.
    """
    op = ClosingOperation(
        ledger_id=ledger_id,
        operation_type=operation_type,
        year=year,
        month=month,
    )
    db.add(op)
    try:
        db.commit()  # Commit the claim so it's visible to other transactions
    except IntegrityError:
        # Unique constraint (ledger_id, operation_type, year, month) violated:
        # another request already claimed this operation. Roll back the failed
        # INSERT to restore the session to a usable state, then read the
        # existing claim. We do NOT use begin_nested() here because the claim
        # must be cross-transaction visible — a SAVEPOINT would not suffice.
        db.rollback()
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
    return True, op
