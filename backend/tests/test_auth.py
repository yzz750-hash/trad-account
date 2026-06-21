"""Tests for JWT authentication and RBAC."""

import pytest
import base64
import json


class TestLogin:
    def test_admin_login(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["role"] == "admin"

    def test_accountant_login(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "accountant", "password": "accountant1"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "accountant"

    def test_auditor_login(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "auditor", "password": "auditor123"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "auditor"

    def test_wrong_password(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "WrongPass123"},
        )
        assert resp.status_code == 401

    def test_nonexistent_user(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "Whatever123"},
        )
        assert resp.status_code == 401


class TestTokenStructure:
    def test_token_contains_claims(self, client):
        """Token should contain sub, role, exp claims."""
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = resp.json()["access_token"]

        # Decode payload (without verification) to check claims
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64))
        assert "exp" in payload
        assert payload["sub"] == "admin"
        assert payload["role"] == "admin"

    def test_token_is_jwt_format(self, client):
        """Token should be a 3-part JWT."""
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = resp.json()["access_token"]
        parts = token.split(".")
        assert len(parts) == 3


class TestRBAC:
    def test_health_no_auth_required(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_reports_require_ledger_id(self, client):
        """Reports should fail without X-Ledger-Id header."""
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]

        resp = client.get(
            "/api/v1/reports/dashboard-summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "X-Ledger-Id" in resp.json()["detail"]
