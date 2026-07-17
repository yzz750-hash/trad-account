import sys
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import secrets
import json
import uuid
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.auth import get_current_user


def _decimal_json_default(obj):
    if isinstance(obj, Decimal):
        # Serialize financial amounts as exact strings to avoid IEEE 754 precision loss
        # on the frontend (e.g. 0.1+0.2=0.30000000000000004).
        return f"{obj:.4f}".rstrip("0").rstrip(".") if "." in f"{obj:.4f}" else str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class DecimalAwareJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=_decimal_json_default).encode("utf-8")
from sqlalchemy import text
from app.logging_config import setup_logging
from app.database import get_db
from sqlalchemy.orm import Session
from app.routers import ai_chat, reports, vouchers, closing, accounts, system, partners, ledgers, auth_router, export, user_router, tax_router, audit_router, backup_router
from app.routers.vouchers_crud import router as vouchers_crud_router
from app.routers.vouchers_ai import router as vouchers_ai_router
from app.routers.reconciliation import router as reconciliation_router
from app.routers.vouchers_upload import router as vouchers_upload_router

setup_logging()
logger = logging.getLogger("trad_account")

# Allow Next.js frontend to communicate with FastAPI
# Configure ALLOWED_ORIGINS env var as comma-separated list (e.g. "https://app.example.com,https://admin.example.com")
# NOTE: must be defined BEFORE the production safety check below references it.
_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001")
_allowed_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]

# Production safety check: refuse to boot if insecure defaults are still in use
_DEFAULT_PASSWORDS = {"admin123", "accountant1", "auditor123", "change-me-admin", "change-me-accountant", "change-me-auditor"}
_admin_pw = os.environ.get("ADMIN_PASSWORD", "")
_accountant_pw = os.environ.get("ACCOUNTANT_PASSWORD", "")
_auditor_pw = os.environ.get("AUDITOR_PASSWORD", "")
_PROHIBITED_JWT_KEYS = {"YOUR_JWT_SECRET_CHANGE_IN_PRODUCTION", "generate-a-real-64-char-hex-string", "test-jwt-secret-key-for-testing-only"}
_PLACEHOLDER_LLM_KEYS = {"", "sk-your-new-deepseek-key", "sk-your-deepseek-api-key", "sk-xxxxxxxx"}

if os.environ.get("ENVIRONMENT") == "production":
    if _admin_pw in _DEFAULT_PASSWORDS:
        raise RuntimeError("ADMIN_PASSWORD is set to a default value! Change it immediately.")
    if _accountant_pw in _DEFAULT_PASSWORDS:
        raise RuntimeError("ACCOUNTANT_PASSWORD is set to a default value! Change it immediately.")
    if _auditor_pw in _DEFAULT_PASSWORDS:
        raise RuntimeError("AUDITOR_PASSWORD is set to a default value! Change it immediately.")
    if os.environ.get("JWT_SECRET_KEY", "") in _PROHIBITED_JWT_KEYS:
        raise RuntimeError("JWT_SECRET_KEY is set to a placeholder value! Change it immediately.")
    if not os.environ.get("ENCRYPTION_KEY", "").strip():
        raise RuntimeError("ENCRYPTION_KEY must be set to a non-empty value in production.")
    if "*" in _allowed_origins:
        raise RuntimeError("ALLOWED_ORIGINS must not contain '*' in production. Specify exact origins.")
    if os.environ.get("DEEPSEEK_API_KEY", "") in _PLACEHOLDER_LLM_KEYS:
        logger.warning("DEEPSEEK_API_KEY is not configured — AI voucher / chat features will be unavailable.")
else:
    # Development mode: warn once at startup so the operator knows AI features are disabled.
    if os.environ.get("DEEPSEEK_API_KEY", "") in _PLACEHOLDER_LLM_KEYS:
        logger.warning("DEEPSEEK_API_KEY is a placeholder or empty — AI voucher OCR / chat will fail. Set a real key in .env to enable.")

app = FastAPI(
    title="Intelligent Foreign Trade Financial API",
    description="API for the China foreign trade financial software with Agnostic LLM and Multi-ledger.",
    version="1.0.0",
    default_response_class=DecimalAwareJSONResponse,
    # Disable automatic slash redirection. When the Next.js dev server proxies
    # /api/* requests via rewrites, a 307 redirect makes the proxy follow
    # server-side WITHOUT forwarding the browser's cookies → 401. With this
    # disabled, routes must match the exact path (collection routes use "" so
    # they live at /api/v1/foo, not /api/v1/foo/).
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "X-Ledger-Id", "X-Confirm-Restore"],
)

# Security headers middleware — must be outermost so all responses carry these headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# HTTPS enforcement middleware (checks reverse-proxy header)
# Must be early in the chain to reject plain HTTP before any business logic runs
class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        proto = request.headers.get("X-Forwarded-Proto", "https")
        if proto == "http":
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={"detail": "HTTPS required. Please use the secure endpoint."},
            )
        return await call_next(request)

app.add_middleware(HttpsRedirectMiddleware)

# Request ID middleware — assigns a unique ID to every request for log correlation
from app.logging_config import request_id_ctx

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id
        request_id_ctx.set(request_id)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

app.add_middleware(RequestIdMiddleware)

# Rate limiting middleware — Redis sliding window with in-memory fallback
# Must run before Audit to prevent audit-log DoS flooding
from app.rate_limit import HybridRateLimiter, get_limit, WINDOW_SECONDS

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiter: 5 rpm login, 60 rpm /ai/, 200 rpm otherwise.

    Uses Redis sorted-set sliding window when REDIS_URL is configured.
    Falls back to per-process in-memory store when Redis is unavailable.
    """

    def __init__(self, app, limiter: HybridRateLimiter | None = None):
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip = request.client.host if request.client else "unknown"
        auth_header = request.headers.get("Authorization", "")
        user_tag = ""
        if auth_header.startswith("Bearer "):
            # Hash the token suffix so the key doesn't leak the full token into logs/metrics
            import hashlib
            token_suffix = auth_header[-16:] if len(auth_header) > 16 else auth_header[7:]
            user_tag = f":u{hashlib.sha256(token_suffix.encode()).hexdigest()[:8]}"
        key = f"{ip}:{path}{user_tag}"

        limit = get_limit(path)

        limiter = self._limiter
        if limiter is None:
            from app.rate_limit import get_limiter
            limiter = get_limiter()
            self._limiter = limiter

        allowed, retry_after = await limiter.check(key, limit, WINDOW_SECONDS)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded: {limit} req/min",
                    "retry_after": int(retry_after),
                },
                headers={"Retry-After": str(int(retry_after))},
            )

        return await call_next(request)

app.add_middleware(RateLimitMiddleware)

# Request body size limit — prevent memory exhaustion from oversized uploads
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    MAX_BODY_BYTES = 50 * 1024 * 1024  # 50 MB

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body exceeds {self.MAX_BODY_BYTES // (1024*1024)}MB limit"},
                    )
            except ValueError:
                pass
        return await call_next(request)

app.add_middleware(RequestSizeLimitMiddleware)

# Audit logging middleware (persists to DB)
# Runs after rate limiter to avoid logging floods; before CSRF to capture attack attempts
from app.audit import AuditMiddleware

app.add_middleware(AuditMiddleware)

# Schedule one-time audit log cleanup on startup (runs in background thread)
from app.audit import schedule_audit_cleanup
schedule_audit_cleanup()

# CSRF protection middleware (skips login which has no csrf cookie yet)
from app.auth import verify_csrf as _verify_csrf_fn

class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/api/v1/auth/login":
            return await call_next(request)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # Only enforce CSRF for requests that carry an auth cookie
            if not request.cookies.get("access_token"):
                return await call_next(request)
            # Bearer token + custom Authorization header provides CSRF protection
            # natively (browsers cannot set this header cross-origin without preflight).
            # If a valid Bearer token is present, skip CSRF validation.
            if request.headers.get("Authorization", "").startswith("Bearer "):
                return await call_next(request)
            csrf_cookie = request.cookies.get("csrf_token")
            csrf_header = request.headers.get("X-CSRF-Token")
            if not csrf_cookie or not csrf_header:
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=403, content={"detail": "CSRF token missing"})
            if not secrets.compare_digest(csrf_cookie, csrf_header):
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=403, content={"detail": "CSRF token mismatch"})
        return await call_next(request)

app.add_middleware(CsrfMiddleware)

_auth = [Depends(get_current_user)]

app.include_router(ai_chat.router, prefix="/api/v1/ai", tags=["AI Agent"], dependencies=_auth)
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"], dependencies=_auth)
app.include_router(vouchers_crud_router, prefix="/api/v1/vouchers", tags=["Vouchers"], dependencies=_auth)
app.include_router(vouchers_ai_router, prefix="/api/v1/vouchers", tags=["Vouchers"], dependencies=_auth)
app.include_router(reconciliation_router, prefix="/api/v1/vouchers", tags=["Vouchers"], dependencies=_auth)
app.include_router(vouchers_upload_router, prefix="/api/v1/vouchers", tags=["Vouchers"], dependencies=_auth)
app.include_router(closing.router, prefix="/api/v1/closing", tags=["Closing"], dependencies=_auth)
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["Accounts"], dependencies=_auth)
app.include_router(system.router, prefix="/api/v1/system", tags=["System"], dependencies=_auth)
app.include_router(partners.router, prefix="/api/v1/partners", tags=["Partners"], dependencies=_auth)
app.include_router(ledgers.router, prefix="/api/v1/ledgers", tags=["Ledgers"], dependencies=_auth)
app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(export.router, prefix="/api/v1/export", tags=["Export"], dependencies=_auth)
app.include_router(user_router.router, prefix="/api/v1/users", tags=["Users"], dependencies=_auth)
app.include_router(tax_router.router, prefix="/api/v1/tax", tags=["Tax"], dependencies=_auth)
app.include_router(audit_router.router, prefix="/api/v1", tags=["Audit"], dependencies=_auth)
app.include_router(backup_router.router, prefix="/api/v1/system", tags=["Backup"], dependencies=_auth)


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Composite health check for load balancer / orchestrator probes.

    Reports DB and Redis status separately so the LB can make informed
    routing decisions. A node with a dead DB is fully degraded (503);
    a node with a dead Redis is partially degraded (200 with degraded=true)
    since the rate limiter falls back to in-memory mode, so the node can
    still serve requests but should not be preferred over healthy nodes.
    """
    components: dict[str, str] = {}
    overall_ok = True

    # 1. Database — hard dependency. If DB is down, return 503.
    try:
        from app.database import _is_postgres
        if _is_postgres:
            db.execute(text("SET LOCAL statement_timeout = '2s'"))
        db.execute(text("SELECT 1"))
        components["db"] = "ok"
    except Exception as e:
        logger.error("Health check DB failed: %s", e)
        components["db"] = "error"
        overall_ok = False

    # 2. Redis — soft dependency in dev (rate limiter falls back to in-memory),
    # hard in production (without Redis, rate limiting is per-process and can
    # be trivially bypassed by spreading requests across workers). We still
    # report 200 if only Redis is down, but mark degraded=true so the LB can
    # deprioritize this node.
    redis_ok = True
    try:
        from app.rate_limit import _check_redis_health
        redis_ok = _check_redis_health()
        components["redis"] = "ok" if redis_ok else "error"
    except Exception as e:
        logger.warning("Health check Redis probe failed: %s", e)
        components["redis"] = "error"
        redis_ok = False

    degraded = overall_ok and not redis_ok
    if not overall_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "components": components},
        )
    return {
        "status": "degraded" if degraded else "ok",
        "components": components,
        "degraded": degraded,
    }


if __name__ == "__main__":
    import uvicorn
    _env = os.environ.get("ENVIRONMENT", "development")
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=(_env == "development"),
    )
