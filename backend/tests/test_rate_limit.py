"""Tests for the rate limiter — both unit (InMemoryRateLimiter) and integration (via TestClient)."""
import time
import pytest
from app.rate_limit import InMemoryRateLimiter, get_limit, DEFAULT_RPM, WINDOW_SECONDS


class TestInMemoryRateLimiter:
    def test_under_limit(self):
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            allowed, _ = limiter.check("127.0.0.1:/test", max_rpm=10)
            assert allowed

    def test_exceeds_limit(self):
        limiter = InMemoryRateLimiter()
        key = "127.0.0.1:/test"
        for _ in range(10):
            allowed, _ = limiter.check(key, max_rpm=10)
            assert allowed

        # 11th within the window should be denied
        allowed, retry = limiter.check(key, max_rpm=10)
        assert not allowed
        assert retry > 0

    def test_reset_clears_state(self):
        limiter = InMemoryRateLimiter()
        for _ in range(10):
            limiter.check("127.0.0.1:/test", max_rpm=10)
        limiter.reset()
        # After reset, should be allowed again
        for _ in range(10):
            allowed, _ = limiter.check("127.0.0.1:/test", max_rpm=10)
            assert allowed

    def test_different_keys_independent(self):
        limiter = InMemoryRateLimiter()
        # Exhaust key A
        for _ in range(10):
            limiter.check("A:/test", max_rpm=10)
        # Key B should still be allowed
        for _ in range(10):
            allowed, _ = limiter.check("B:/test", max_rpm=10)
            assert allowed

    def test_window_expiry(self):
        limiter = InMemoryRateLimiter()
        key = "127.0.0.1:/test"
        # Fill bucket
        for _ in range(10):
            limiter.check(key, max_rpm=10)
        # Override timestamps to simulate window passing
        old = time.time() - 120  # 2 minutes ago
        limiter._store[key] = [old] * 10
        # Now request should be allowed (old entries pruned)
        allowed, _ = limiter.check(key, max_rpm=10)
        assert allowed


class TestGetLimit:
    def test_login_endpoint(self):
        assert get_limit("/api/v1/auth/login") == 5

    def test_ai_endpoint(self):
        assert get_limit("/api/v1/ai/chat") == 60
        assert get_limit("/api/v1/ai/reconcile") == 60

    def test_default(self):
        assert get_limit("/api/v1/vouchers") == DEFAULT_RPM
        assert get_limit("/api/v1/reports/trial-balance") == DEFAULT_RPM
        assert get_limit("/health") == DEFAULT_RPM


class TestRateLimitIntegration:
    """Integration tests hitting the real app with the in-memory fallback (no Redis in CI)."""

    def test_normal_request_passes(self, client, ledger_headers):
        resp = client.get("/api/v1/vouchers", headers=ledger_headers)
        assert resp.status_code in (200, 404)  # 200 if vouchers exist, not 429

    def test_login_brute_force_blocked(self, client):
        # The login rate limit is 5 rpm. Sending 6 should trigger 429.
        for _ in range(5):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
            )
            assert resp.status_code != 429, f"Unexpected 429 on request {_}"

        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 429
        data = resp.json()
        assert "Rate limit exceeded" in data["detail"]
        assert data["retry_after"] > 0
        assert "Retry-After" in resp.headers

    def test_ai_endpoint_rate_limited(self, client):
        path = "/api/v1/ai/chat"
        key = f"testclient:{path}"

        from app.rate_limit import get_limiter
        limiter = get_limiter()
        for _ in range(60):
            limiter._fallback.check(key, max_rpm=60)

        resp = client.post(
            path,
            json={"message": "你好", "ledger_id": 1},
        )
        assert resp.status_code == 429
        data = resp.json()
        assert data["retry_after"] > 0

    def test_rate_limit_resets_between_tests(self, client):
        """Verify clean_db fixture resets the rate limiter so each test starts fresh."""
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        # Should NOT be 429 because clean_db reset the limiter
        assert resp.status_code != 429
