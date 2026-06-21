"""Tests for user management CRUD endpoints (admin only)."""

from app.main import app


class TestUserCRUD:
    def test_list_users_admin(self, client, auth_headers):
        resp = client.get("/api/v1/users/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(u["username"] == "admin" for u in data)
        assert any(u["username"] == "accountant" for u in data)
        assert any(u["username"] == "auditor" for u in data)

    def test_list_users_requires_auth(self, client):
        from app.auth import get_current_user
        from fastapi import HTTPException
        def _raise_401():
            raise HTTPException(status_code=401, detail="Not authenticated")
        app.dependency_overrides[get_current_user] = _raise_401
        resp = client.get("/api/v1/users/")
        assert resp.status_code in (401, 403)

    def test_list_users_rejects_non_admin(self, client):
        from app.auth import get_current_user, CurrentUser
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=2, username="accountant", role="accountant")
        resp2 = client.get("/api/v1/users/")
        assert resp2.status_code == 403

    def test_create_user(self, client, auth_headers):
        resp = client.post(
            "/api/v1/users/",
            json={"username": "testuser", "password": "Test@1234pass", "role": "accountant"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["role"] == "accountant"
        assert data["is_active"] is True

    def test_create_duplicate_user_fails(self, client, auth_headers):
        resp = client.post(
            "/api/v1/users/",
            json={"username": "admin", "password": "Irrelevant@1A", "role": "accountant"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_create_user_invalid_role(self, client, auth_headers):
        resp = client.post(
            "/api/v1/users/",
            json={"username": "badrole", "password": "Test@1234pass", "role": "superadmin"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_create_user_requires_admin(self, client):
        from app.auth import get_current_user, CurrentUser
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=2, username="accountant", role="accountant")
        resp2 = client.post(
            "/api/v1/users/",
            json={"username": "hacker", "password": "Bad@pass12345", "role": "admin"},
        )
        assert resp2.status_code == 403

    def test_reset_password(self, client, auth_headers):
        # First create a user
        resp = client.post(
            "/api/v1/users/",
            json={"username": "resetme", "password": "Old@pass12345", "role": "auditor"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        user_id = resp.json()["id"]

        # Reset their password
        resp2 = client.put(
            f"/api/v1/users/{user_id}/reset-password",
            json={"new_password": "New@pass12345"},
            headers=auth_headers,
        )
        assert resp2.status_code == 200

        # Verify old password no longer works, new one does
        resp3 = client.post(
            "/api/v1/auth/login",
            json={"username": "resetme", "password": "Old@pass12345"},
        )
        assert resp3.status_code == 401

        resp4 = client.post(
            "/api/v1/auth/login",
            json={"username": "resetme", "password": "New@pass12345"},
        )
        assert resp4.status_code == 200

    def test_reset_password_nonexistent_user(self, client, auth_headers):
        resp = client.put(
            "/api/v1/users/99999/reset-password",
            json={"new_password": "Who@cares1234"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_deactivate_user(self, client, auth_headers):
        resp = client.post(
            "/api/v1/users/",
            json={"username": "deactivate_me", "password": "Test@1234pass", "role": "auditor"},
            headers=auth_headers,
        )
        user_id = resp.json()["id"]

        resp2 = client.put(
            f"/api/v1/users/{user_id}/deactivate",
            headers=auth_headers,
        )
        assert resp2.status_code == 200

        # Deactivated user cannot log in
        resp3 = client.post(
            "/api/v1/auth/login",
            json={"username": "deactivate_me", "password": "Test@1234pass"},
        )
        assert resp3.status_code == 401

    def test_activate_user(self, client, auth_headers):
        resp = client.post(
            "/api/v1/users/",
            json={"username": "reactivate_me", "password": "Test@1234pass", "role": "auditor"},
            headers=auth_headers,
        )
        user_id = resp.json()["id"]

        client.put(f"/api/v1/users/{user_id}/deactivate", headers=auth_headers)

        resp2 = client.put(
            f"/api/v1/users/{user_id}/activate",
            headers=auth_headers,
        )
        assert resp2.status_code == 200

        # Reactivated user can log in again
        resp3 = client.post(
            "/api/v1/auth/login",
            json={"username": "reactivate_me", "password": "Test@1234pass"},
        )
        assert resp3.status_code == 200

    def test_cannot_deactivate_admin(self, client, auth_headers):
        resp = client.get("/api/v1/users/", headers=auth_headers)
        admin_user = next(u for u in resp.json() if u["username"] == "admin")

        resp2 = client.put(
            f"/api/v1/users/{admin_user['id']}/deactivate",
            headers=auth_headers,
        )
        assert resp2.status_code == 400
        assert "admin" in resp2.json()["detail"].lower()
