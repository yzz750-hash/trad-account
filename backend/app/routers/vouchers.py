"""Voucher router — compatibility layer that aggregates sub-routers.

Routes are split across:
  vouchers_crud.py   — CRUD, batch, print
  vouchers_ai.py     — AI voucher generation from OCR docs
  reconciliation.py  — bank reconciliation
  vouchers_upload.py — PDF/CSV file upload
  voucher_utils.py   — shared schemas and helpers

All external imports (closing.py, ai_chat.py) continue to work via re-exports below.
"""

from fastapi import APIRouter

from app.routers.vouchers_crud import router as _crud_router
from app.routers.vouchers_ai import router as _ai_router
from app.routers.reconciliation import router as _recon_router
from app.routers.vouchers_upload import router as _upload_router

router = APIRouter()
router.include_router(_crud_router)
router.include_router(_ai_router)
router.include_router(_recon_router)
router.include_router(_upload_router)

# Re-exports for backward compatibility (used by closing.py and ai_chat.py)
from app.routers.voucher_utils import (  # noqa: F401, E402
    get_next_voucher_number,
    _get_llm_config_for_ledger,
    _batch_resolve_accounts,
    _build_3level_debit_account,
    _build_vendor_account,
    _infer_category,
    _call_llm_with_retry,
    VoucherEntrySchema,
    VoucherCreate,
    VoucherUpdate,
    VoucherResponse,
    VoucherEntryResponse,
    VoucherResponsePage,
    BatchVoucherRequest,
    BatchGenerateRequest,
    ReconciliationMatchRequest,
    AccountSchema,
    AIDebitEntrySchema,
    AIVoucherResponseSchema,
    MAX_VOUCHER_AMOUNT,
)
from app.routers.reconciliation import reconcile_suggestions  # noqa: F401, E402
