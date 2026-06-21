"""Tests for backup/restore endpoints."""
import io
import os
import zipfile

import pytest
from app.main import app


class TestBackupCreate:
    """Test backup creation endpoint."""

    def test_admin_can_create_backup(self, client, auth_headers, ledger_headers):
        resp = client.post(
            "/api/v1/system/backups",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("backup_")
        assert data["filename"].endswith(".zip")
        assert data["size_bytes"] > 0
        assert "db_checksum" in data

    def test_non_admin_cannot_create(self, client, ledger_headers):
        from app.auth import get_current_user, CurrentUser
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=2, username="accountant", role="accountant")
        resp = client.post("/api/v1/system/backups", headers=ledger_headers)
        assert resp.status_code == 403


class TestBackupList:
    """Test backup listing endpoint."""

    def test_admin_can_list_backups(self, client, auth_headers, ledger_headers):
        # Create a backup first so we have something to list
        client.post(
            "/api/v1/system/backups",
            headers={**auth_headers, **ledger_headers},
        )
        resp = client.get(
            "/api/v1/system/backups",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["backups"], list)
        assert len(data["backups"]) >= 1

    def test_non_admin_cannot_list(self, client, ledger_headers):
        from app.auth import get_current_user, CurrentUser
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=2, username="accountant", role="accountant")
        resp = client.get("/api/v1/system/backups", headers=ledger_headers)
        assert resp.status_code == 403


class TestBackupDownload:
    """Test backup download endpoint."""

    def test_admin_can_download_backup(self, client, auth_headers, ledger_headers):
        create_resp = client.post(
            "/api/v1/system/backups",
            headers={**auth_headers, **ledger_headers},
        )
        backup_id = create_resp.json()["id"]

        resp = client.get(
            f"/api/v1/system/backups/{backup_id}/download",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        # Verify it's a valid zip with expected contents
        content = resp.read()
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            assert "financial.db" in names
            assert "manifest.json" in names

    def test_download_nonexistent_backup(self, client, auth_headers, ledger_headers):
        resp = client.get(
            "/api/v1/system/backups/nonexistent/download",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404


class TestBackupRestore:
    """Test backup restore endpoint."""

    RESTORE_CONFIRM = "I understand this will overwrite all current data"

    def test_restore_missing_confirmation(self, client, auth_headers, ledger_headers):
        """Restore without confirmation header must fail."""
        create_resp = client.post(
            "/api/v1/system/backups",
            headers={**auth_headers, **ledger_headers},
        )
        backup_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/system/backups/{backup_id}/restore",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 422  # missing required header

    def test_restore_wrong_confirmation(self, client, auth_headers, ledger_headers):
        """Restore with wrong confirmation text must fail."""
        create_resp = client.post(
            "/api/v1/system/backups",
            headers={**auth_headers, **ledger_headers},
        )
        backup_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/system/backups/{backup_id}/restore",
            headers={
                **auth_headers,
                **ledger_headers,
                "X-Confirm-Restore": "yes",
            },
        )
        assert resp.status_code == 400

    def test_restore_nonexistent_backup(self, client, auth_headers, ledger_headers):
        resp = client.post(
            "/api/v1/system/backups/nonexistent/restore",
            headers={
                **auth_headers,
                **ledger_headers,
                "X-Confirm-Restore": self.RESTORE_CONFIRM,
            },
        )
        assert resp.status_code == 404

    def test_restore_success(self, client, auth_headers, ledger_headers):
        """Full backup and restore cycle."""
        # Create a backup of current state
        create_resp = client.post(
            "/api/v1/system/backups",
            headers={**auth_headers, **ledger_headers},
        )
        assert create_resp.status_code == 200
        backup_id = create_resp.json()["id"]

        # Restore it
        resp = client.post(
            f"/api/v1/system/backups/{backup_id}/restore",
            headers={
                **auth_headers,
                **ledger_headers,
                "X-Confirm-Restore": self.RESTORE_CONFIRM,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "safety_backup" in data

        # After restore, the system should still work
        health = client.get("/health")
        assert health.status_code == 200
