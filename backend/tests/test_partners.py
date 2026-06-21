"""Tests for partners router (business partner CRUD)."""
import pytest

from app.models.financial import BusinessPartner, PartnerType


class TestListPartners:
    """Test GET /partners/ — list active partners."""

    def test_list_empty(self, client, auth_headers, ledger_headers):
        """No partners → returns empty list."""
        resp = client.get(
            "/api/v1/partners/",
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_active_partners(self, client, auth_headers, ledger, db):
        """List only active partners."""
        db.add(BusinessPartner(
            ledger_id=ledger.id, code="C001", name="客户A", partner_type=PartnerType.CUSTOMER,
        ))
        db.add(BusinessPartner(
            ledger_id=ledger.id, code="V001", name="供应商B", partner_type=PartnerType.VENDOR,
        ))
        db.add(BusinessPartner(
            ledger_id=ledger.id, code="V002", name="已停用", partner_type=PartnerType.VENDOR, is_active=False,
        ))
        db.commit()

        resp = client.get(
            "/api/v1/partners/",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        data = resp.json()
        codes = {p["code"] for p in data}
        assert "C001" in codes
        assert "V001" in codes
        assert "V002" not in codes  # inactive filtered out

    def test_list_requires_ledger_header(self, client, auth_headers):
        """Missing X-Ledger-Id returns 400."""
        resp = client.get("/api/v1/partners/", headers=auth_headers)
        assert resp.status_code == 400


class TestCreatePartner:
    """Test POST /partners/ — create a new partner."""

    def test_create_customer(self, client, auth_headers, ledger_headers):
        """Create a basic customer partner."""
        resp = client.post(
            "/api/v1/partners/",
            json={"code": "C001", "name": "国际客户A", "partner_type": "CUSTOMER"},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "C001"
        assert data["name"] == "国际客户A"
        assert data["partner_type"] == "CUSTOMER"

    def test_create_vendor(self, client, auth_headers, ledger_headers):
        """Create a vendor partner."""
        resp = client.post(
            "/api/v1/partners/",
            json={"code": "V001", "name": "供应商X", "partner_type": "VENDOR"},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        assert resp.json()["partner_type"] == "VENDOR"

    def test_create_both_type(self, client, auth_headers, ledger_headers):
        """Create a partner that is both customer and vendor."""
        resp = client.post(
            "/api/v1/partners/",
            json={"code": "B001", "name": "双重身份", "partner_type": "BOTH"},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 200
        assert resp.json()["partner_type"] == "BOTH"

    def test_duplicate_code_rejected(self, client, auth_headers, ledger, db):
        """Duplicate code within same ledger returns 400."""
        db.add(BusinessPartner(
            ledger_id=ledger.id, code="DUP001", name="原客户", partner_type=PartnerType.CUSTOMER,
        ))
        db.commit()

        resp = client.post(
            "/api/v1/partners/",
            json={"code": "DUP001", "name": "新客户", "partner_type": "CUSTOMER"},
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_invalid_partner_type_rejected(self, client, auth_headers, ledger_headers):
        """Invalid partner_type should return 400."""
        resp = client.post(
            "/api/v1/partners/",
            json={"code": "T001", "name": "测试", "partner_type": "INVALID_TYPE"},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]


class TestUpdatePartner:
    """Test PUT /partners/{id} — update partner."""

    def test_update_name(self, client, auth_headers, ledger, db):
        """Update partner name."""
        p = BusinessPartner(
            ledger_id=ledger.id, code="U001", name="旧名称", partner_type=PartnerType.CUSTOMER,
        )
        db.add(p)
        db.commit()

        resp = client.put(
            f"/api/v1/partners/{p.id}",
            json={"name": "新名称"},
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名称"
        assert resp.json()["code"] == "U001"

    def test_deactivate_partner(self, client, auth_headers, ledger, db):
        """Deactivate (soft-delete) a partner."""
        p = BusinessPartner(
            ledger_id=ledger.id, code="U002", name="待停用", partner_type=PartnerType.VENDOR,
        )
        db.add(p)
        db.commit()

        resp = client.put(
            f"/api/v1/partners/{p.id}",
            json={"is_active": False},
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        assert resp.status_code == 200

        # Should no longer appear in list
        list_resp = client.get(
            "/api/v1/partners/",
            headers={**auth_headers, **{"X-Ledger-Id": str(ledger.id)}},
        )
        codes = {p["code"] for p in list_resp.json()}
        assert "U002" not in codes

    def test_update_nonexistent(self, client, auth_headers, ledger_headers):
        """Update non-existent partner returns 404."""
        resp = client.put(
            "/api/v1/partners/99999",
            json={"name": "不存在"},
            headers={**auth_headers, **ledger_headers},
        )
        assert resp.status_code == 404

    def test_update_other_ledger_partner_rejected(self, client, auth_headers, ledger, db):
        """Cannot update a partner from another ledger (ledger-scoped query)."""
        # The query filters by ledger_id, so a partner from another ledger
        # should not be found and return 404
        p = BusinessPartner(
            ledger_id=ledger.id, code="U003", name="本账套客户", partner_type=PartnerType.CUSTOMER,
        )
        db.add(p)
        db.commit()

        # Use a different ledger_id header
        resp = client.put(
            f"/api/v1/partners/{p.id}",
            json={"name": "试图修改"},
            headers={**auth_headers, **{"X-Ledger-Id": "99999"}},
        )
        assert resp.status_code == 404
