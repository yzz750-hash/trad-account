"""Tests for audit logging middleware and query endpoint."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app


class TestAuditLogging:
    """Verify audit logs are created for API requests."""

    def test_audit_log_created_on_login(self, client, db):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200

        # Audit writes are async — wait briefly for the background thread
        import time
        time.sleep(0.3)

        # Check audit_logs table via the test DB (middleware writes to the real DB,
        # but we can verify the pattern by checking the login itself succeeded)
        from app.database import SessionLocal
        audit_db = SessionLocal()
        try:
            logs = audit_db.execute(
                text("SELECT * FROM audit_logs WHERE path = '/api/v1/auth/login' ORDER BY id DESC LIMIT 1")
            ).fetchall()
            assert len(logs) > 0
            entry = logs[0]
            # Columns: id, username, ledger_id, method, path, status_code, detail, ip_address, duration_ms, created_at
            assert entry[4] == "/api/v1/auth/login"
            assert entry[3] == "POST"
        finally:
            audit_db.close()

    def test_audit_log_created_on_auth_request(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/reports/dashboard-summary",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200

        # Audit writes are async — wait briefly for the background thread
        import time
        time.sleep(0.3)

        from app.database import SessionLocal
        audit_db = SessionLocal()
        try:
            logs = audit_db.execute(
                text("SELECT * FROM audit_logs WHERE path LIKE '/api/v1/reports/%' ORDER BY id DESC LIMIT 1")
            ).fetchall()
            assert len(logs) > 0
            entry = logs[0]
            assert entry[3] == "GET"
            assert entry[1] == "admin"  # username
        finally:
            audit_db.close()


class TestAuditLogQuery:
    """Test admin-only audit log query endpoint."""

    def test_admin_can_list_audit_logs(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1

    def test_non_admin_cannot_access(self, client, ledger_headers):
        from app.auth import get_current_user, CurrentUser
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=2, username="accountant", role="accountant")
        resp = client.get("/api/v1/audit-logs", headers=ledger_headers)
        assert resp.status_code == 403

    def test_unauthorized_without_auth(self, client):
        from app.auth import get_current_user
        from fastapi import HTTPException
        def _raise_401():
            raise HTTPException(status_code=401, detail="Not authenticated")
        app.dependency_overrides[get_current_user] = _raise_401
        resp = client.get("/api/v1/audit-logs")
        assert resp.status_code in (401, 403)

    def test_pagination(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs?page=1&page_size=10",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 10

    def test_filter_by_method(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs?method=POST",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["method"] == "POST"

    def test_filter_by_username(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs?username=admin",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["username"] == "admin"

    def test_filter_by_status_code(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs?status_code=200",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status_code"] == 200

    def test_filter_by_date_range(self, client, auth_headers, ledger_headers):
        from datetime import date
        today = date.today().isoformat()
        resp = client.get(
            f"/api/v1/audit-logs?date_from={today}&date_to={today}",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200

    def test_filter_by_path(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs?path_contains=login",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert "login" in item["path"]

    def test_invalid_page_rejected(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs?page=0",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 422

    def test_page_size_capped(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/audit-logs?page_size=999",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 422  # exceeds max 200
