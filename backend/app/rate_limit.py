"""Redis-backed sliding window rate limiter.

Uses a sorted set per (IP, path) key for precise millisecond-granularity
windows. All check-and-increment logic runs inside a Lua script for atomicity.
When Redis is unavailable, falls back to an in-memory per-process store.
"""

import os
import time
import logging
from collections import defaultdict

logger = logging.getLogger("trad_account")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Lua script: atomic check + expire + insert
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])

-- Remove entries outside the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window_ms)

-- Count remaining
local count = redis.call('ZCARD', key)

if count >= max_req then
    -- Calculate retry-after in seconds
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if oldest and #oldest >= 2 then
        retry_after = math.ceil((tonumber(oldest[2]) + window_ms - now) / 1000)
    end
    if retry_after <= 0 then retry_after = 1 end
    return {0, retry_after}
end

-- Insert current request
redis.call('ZADD', key, now, now)
-- Set TTL slightly longer than window to clean up stale keys
redis.call('PEXPIRE', key, window_ms + 10000)

return {1, 0}
"""


class InMemoryRateLimiter:
    """Per-process fallback (not accurate under multiple workers)."""

    def __init__(self):
        self._store: dict[str, list[float]] = {}
        self._lock = __import__('threading').Lock()

    def check(self, key: str, max_rpm: int, window_s: float = 60.0) -> tuple[bool, float]:
        now = time.time()
        with self._lock:
            bucket = self._store.get(key)
            if bucket is None:
                bucket = []
                self._store[key] = bucket
            else:
                bucket[:] = [t for t in bucket if now - t < window_s]
                if not bucket:
                    del self._store[key]  # prevent unbounded memory growth
            if len(bucket) >= max_rpm:
                retry_after = bucket[0] + window_s - now if bucket else window_s
                return False, max(retry_after, 1.0)
            bucket.append(now)
            # Re-add to store in case this was a new bucket or was deleted above
            if key not in self._store:
                self._store[key] = bucket
            return True, 0.0

    def reset(self):
        with self._lock:
            self._store.clear()


class RedisRateLimiter:
    """Redis-backed sliding window rate limiter."""

    def __init__(self, redis_url: str = REDIS_URL):
        self._redis_url = redis_url
        self._redis = None
        self._script = None

    async def _ensure_connected(self) -> bool:
        if self._redis is not None:
            return True
        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(self._redis_url, decode_responses=False)
            self._script = self._redis.register_script(_SLIDING_WINDOW_SCRIPT)
            await self._redis.ping()
            logger.info("Redis rate limiter connected: %s", self._redis_url)
            return True
        except Exception as exc:
            logger.warning("Redis unavailable (%s), falling back to in-memory rate limiter", exc)
            self._redis = None
            self._script = None
            return False

    async def check(self, key: str, max_rpm: int, window_s: float = 60.0) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        if not await self._ensure_connected() or self._script is None:
            raise RuntimeError("Redis not available")

        now_ms = int(time.time() * 1000)
        window_ms = int(window_s * 1000)
        result = await self._script(keys=[key], args=[now_ms, window_ms, max_rpm])
        allowed = bool(result[0])
        retry_after = float(result[1])
        return allowed, retry_after


class HybridRateLimiter:
    """Tries Redis first; falls back to in-memory on failure.
    Periodically retries Redis reconnection after fallback.

    In production with REDIS_URL configured, refuses to fall back to in-memory
    — a Redis outage returns 429 rather than silently degrading to per-process
    limits that an attacker can bypass by spreading across workers.

    In development WITHOUT an explicit REDIS_URL, Redis is skipped entirely to
    avoid spamming the log with connection failures on every request.
    """

    def __init__(self, redis_url: str = REDIS_URL):
        self._fallback = InMemoryRateLimiter()
        self._redis_available = None  # tri-state: None=unknown, True, False
        self._last_retry_at: float = 0.0
        self._retry_interval: float = 60.0  # retry Redis every 60s after failure

        # Decide whether Redis should be attempted at all.
        _env = os.environ.get("ENVIRONMENT", "development")
        _redis_url_explicit = bool(os.environ.get("REDIS_URL"))
        self._skip_redis = (_env != "production") and (not _redis_url_explicit)

        if self._skip_redis:
            # Dev mode without Redis — go straight to in-memory, no connection noise.
            self._redis = None
            self._redis_available = False
            logger.info("Rate limiter: in-memory mode (dev, no REDIS_URL configured)")
        else:
            self._redis = RedisRateLimiter(redis_url)
            self._fail_closed = (
                _env == "production"
                and _redis_url_explicit
            )

    async def check(self, key: str, max_rpm: int, window_s: float = 60.0) -> tuple[bool, float]:
        if self._skip_redis:
            return self._fallback.check(key, max_rpm, window_s)

        if self._redis_available is not False:
            try:
                allowed, retry = await self._redis.check(key, max_rpm, window_s)
                self._redis_available = True
                return allowed, retry
            except Exception:
                self._redis_available = False
                self._last_retry_at = time.time()

        # Periodic retry of Redis connection
        if time.time() - self._last_retry_at > self._retry_interval:
            try:
                allowed, retry = await self._redis.check(key, max_rpm, window_s)
                self._redis_available = True
                logger.info("Redis rate limiter reconnected")
                return allowed, retry
            except Exception:
                self._last_retry_at = time.time()

        if self._fail_closed:
            logger.error("Redis unavailable in production — rejecting request (fail-closed)")
            return False, 1.0

        return self._fallback.check(key, max_rpm, window_s)

    def reset(self):
        self._fallback.reset()
        self._redis_available = None
        if self._skip_redis or self._redis is None:
            return
        # Also flush Redis rate-limit keys (sync client to avoid async in sync context)
        try:
            import redis
            r = redis.Redis.from_url(self._redis._redis_url, decode_responses=False)
            r.flushdb()
            r.close()
        except Exception:
            pass


# Mapping from path prefix to max requests per minute
RATE_LIMITS: list[tuple[str, int]] = [
    ("/api/v1/auth/login", 5),
    ("/api/v1/ai", 60),
]

DEFAULT_RPM = 200
WINDOW_SECONDS = 60.0


def get_limit(path: str) -> int:
    for prefix, rpm in RATE_LIMITS:
        if path.startswith(prefix):
            return rpm
    return DEFAULT_RPM


_limiter: HybridRateLimiter | None = None


def get_limiter() -> HybridRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = HybridRateLimiter()
    return _limiter


def _check_redis_health() -> bool:
    """Synchronous Redis health probe for the /health endpoint.

    Returns True if Redis is reachable and responsive, False otherwise.
    Uses a short-lived sync client so we don't depend on the async limiter's
    connection state (which may be in fallback mode).

    In dev mode without REDIS_URL configured, returns True (in-memory mode
    is the intended configuration, not a degraded state).
    """
    if os.environ.get("ENVIRONMENT", "development") != "production" and not os.environ.get("REDIS_URL"):
        return True  # dev mode intentionally has no Redis
    try:
        import redis
        client = redis.Redis.from_url(REDIS_URL, decode_responses=False, socket_timeout=1.0, socket_connect_timeout=1.0)
        try:
            client.ping()
            return True
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return False
