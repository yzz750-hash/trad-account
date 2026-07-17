"""
Audit logging middleware: persists every API request to audit_logs table.
Extracts identity from JWT httpOnly cookie without hitting the database.
Uses a background thread to avoid blocking API responses on audit I/O.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from jose import jwt, JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.auth import SECRET_KEY, ALGORITHM
from app.database import SessionLocal
from app.models.financial import AuditLog

logger = logging.getLogger("trad_account.audit")

# Single-thread executor for audit writes — keeps ordering without blocking API
_audit_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audit")

# Maximum pending audit writes before dropping events (backpressure protection).
# With a single worker, this bounds memory when the DB is slower than request rate.
_MAX_PENDING_AUDITS = 10000  # Increased from 2000 for high-traffic resilience

# Number of dropped audit events since startup (for monitoring)
_audit_dropped_count = 0

# Paths excluded from audit logging to reduce noise
EXCLUDED_PREFIXES = ("/health",)

# Paths excluded from request body capture (passwords, tokens, secrets)
BODY_CAPTURE_EXCLUDED = (
    "/api/v1/auth/login",
    "/api/v1/auth/password",
    "/api/v1/users",
)

# Retention: delete audit logs older than this many days (0 = keep forever)
AUDIT_RETENTION_DAYS = int(__import__('os').environ.get("AUDIT_RETENTION_DAYS", "90"))

# Background cleanup executor
_cleanup_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audit_cleanup")


def cleanup_old_audit_logs() -> int:
    """Delete audit logs older than AUDIT_RETENTION_DAYS. Returns count of deleted rows."""
    if AUDIT_RETENTION_DAYS <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=AUDIT_RETENTION_DAYS)
    try:
        db = SessionLocal()
        try:
            # Check table existence first — on a fresh install migrations may not have
            # created audit_logs yet. Silence the noise instead of WARNING every boot.
            from sqlalchemy import inspect as _inspect
            if not _inspect(db.bind).has_table(AuditLog.__tablename__):
                logger.debug("Audit log cleanup skipped: table '%s' does not exist yet.", AuditLog.__tablename__)
                return 0
            deleted = db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete()
            db.commit()
            if deleted:
                logger.info("Audit log cleanup: deleted %d rows older than %s", deleted, cutoff.isoformat())
            return deleted
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Audit log cleanup failed: %s", exc)
        return 0


def schedule_audit_cleanup():
    """Schedule a one-time background cleanup of old audit logs.

    A short delay is added so that on a cold start the Alembic migrations have
    a chance to create the audit_logs table before we try to clean it.
    """
    import os as _os
    if _os.environ.get("ENVIRONMENT") == "ci" or _os.environ.get("PYTEST_CURRENT_TEST"):
        return

    def _deferred():
        time.sleep(3)
        cleanup_old_audit_logs()

    _cleanup_executor.submit(_deferred)


def _extract_identity(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        # Fallback to Authorization header for non-browser API consumers
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], audience="trad-account")
        return payload.get("sub")
    except JWTError:
        try:
            unverified = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False}, audience="trad-account")
            return unverified.get("sub")
        except Exception:
            return None


class AuditMiddleware(BaseHTTPMiddleware):
    """Persist all API requests to audit_logs table."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in EXCLUDED_PREFIXES):
            return await call_next(request)

        username = _extract_identity(request)
        ledger_id = request.headers.get("X-Ledger-Id")
        ip = request.client.host if request.client else None

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Capture request body for detail (limited to 4KB to avoid bloat)
        # Skip body capture for auth endpoints to avoid logging passwords/tokens
        detail = None
        if request.method not in ("GET", "HEAD", "OPTIONS") and not any(path.startswith(p) for p in BODY_CAPTURE_EXCLUDED):
            try:
                body = await request.body()
                if body and len(body) <= 4096:
                    import json
                    detail = json.loads(body)
            except Exception:
                pass

        request_id = getattr(request.state, "request_id", None)

        # Fire-and-forget audit write to a background thread (with backpressure)
        global _audit_dropped_count
        pending = _audit_executor._work_queue.qsize() if hasattr(_audit_executor._work_queue, 'qsize') else 0
        if pending >= _MAX_PENDING_AUDITS:
            _audit_dropped_count += 1
            if _audit_dropped_count % 1000 == 1:
                logger.error(
                    "Audit backpressure: dropped %d events (pending=%d, max=%d)",
                    _audit_dropped_count, pending, _MAX_PENDING_AUDITS,
                )
        else:
            _audit_executor.submit(
                _write_audit_log,
                username,
                ledger_id,
                request.method,
                path,
                response.status_code,
                ip,
                duration_ms,
                detail,
                request_id,
            )

        return response


def _write_audit_log(username, ledger_id, method, path, status_code, ip, duration_ms, detail=None, request_id=None):
    """Write a single audit log entry in a background thread."""
    try:
        db = SessionLocal()
        try:
            if request_id and detail is None:
                detail = {"_request_id": request_id}
            elif request_id and isinstance(detail, dict):
                detail["_request_id"] = request_id

            log_entry = AuditLog(
                username=username,
                ledger_id=int(ledger_id) if ledger_id and ledger_id.isdigit() else None,
                method=method,
                path=path,
                status_code=status_code,
                ip_address=ip,
                duration_ms=duration_ms,
                detail=detail,
            )
            db.add(log_entry)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        logger.exception("Audit log write failed")
