"""E2E tests for the new store-info / activity / export-pptx endpoints.

Auth via cookie-based JWT (admin@vusion.local / admin123).
Uses the existing dataset upload_id provided by the main agent.
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://auto-tab-counter.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@vusion.local"
ADMIN_PASSWORD = "admin123"
UPLOAD_ID = "aa7d9aa6-ec7d-4f27-968e-b2a5228b0065"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
               timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    # Check auth me works
    me = s.get(f"{BASE_URL}/api/auth/me", timeout=10)
    assert me.status_code == 200
    assert me.json().get("email") == ADMIN_EMAIL
    return s


@pytest.fixture(scope="module")
def upload_id(session):
    # Make sure dataset exists and belongs to admin
    r = session.get(f"{BASE_URL}/api/dataset/{UPLOAD_ID}", timeout=15)
    if r.status_code == 404:
        pytest.skip(f"Test dataset {UPLOAD_ID} not found - skipping e2e")
    assert r.status_code == 200, f"Dataset not accessible: {r.status_code} {r.text[:200]}"
    return UPLOAD_ID


# ---------------- Activity endpoint ----------------

class TestActivity:
    def test_activity_returns_200(self, session, upload_id):
        r = session.get(f"{BASE_URL}/api/dataset/{upload_id}/activity", timeout=15)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "activity" in data
        assert "count" in data
        assert isinstance(data["activity"], list)
        assert isinstance(data["count"], int)

    def test_activity_unauthenticated(self):
        # No cookies -> should 401
        r = requests.get(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/activity", timeout=10)
        assert r.status_code in (401, 403), f"Expected 401/403 got {r.status_code}"

    def test_activity_unknown_dataset(self, session):
        r = session.get(f"{BASE_URL}/api/dataset/does-not-exist-xyz/activity", timeout=10)
        assert r.status_code == 404


# ---------------- Store-info PATCH ----------------

class TestStoreInfo:
    def test_patch_persists_all_fields(self, session, upload_id):
        payload = {
            "store_name": "Carrefour Test",
            "store_city": "TestCity",
            "store_code": "T0001",
            "store_address": "1 rue de Test",
            "vt_start_date": "2026-04-27",
            "vt_end_date": "2026-04-29",
            "participants": "Alice, Bob",
            "responsable_magasin": "M. Dupont",
            "responsable_vusion": "Mme Martin",
            "prestataire_install": "ACME",
            "plan_prevention_signe": "Oui",
            "doc_version": "v1.0",
            "date_validation_carrefour": "2026-04-20",
        }
        r = session.patch(f"{BASE_URL}/api/dataset/{upload_id}/store-info",
                          json=payload, timeout=15)
        assert r.status_code == 200, f"PATCH failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is True
        # Server returns the persisted fields too
        for k, v in payload.items():
            assert body.get(k) == v, f"PATCH echo mismatch for {k}: {body.get(k)} != {v}"

        # GET dataset -> values persisted
        g = session.get(f"{BASE_URL}/api/dataset/{upload_id}", timeout=15)
        assert g.status_code == 200
        d = g.json()
        for k, v in payload.items():
            assert d.get(k) == v, f"Persistence mismatch for {k}: {d.get(k)} != {v}"

    def test_patch_invalid_vt_start_date(self, session, upload_id):
        r = session.patch(f"{BASE_URL}/api/dataset/{upload_id}/store-info",
                          json={"vt_start_date": "pas-une-date"}, timeout=10)
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text[:200]}"
        # French error message
        detail = r.json().get("detail", "").lower()
        assert "date" in detail or "invalide" in detail

    def test_patch_invalid_date_format_2(self, session, upload_id):
        r = session.patch(f"{BASE_URL}/api/dataset/{upload_id}/store-info",
                          json={"vt_start_date": "2026-13-99"}, timeout=10)
        assert r.status_code == 400

    def test_patch_empty_payload(self, session, upload_id):
        r = session.patch(f"{BASE_URL}/api/dataset/{upload_id}/store-info",
                          json={}, timeout=10)
        # Should reject (no modification provided)
        assert r.status_code == 400

    def test_patch_unauthenticated(self):
        r = requests.patch(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/store-info",
                           json={"store_name": "Hacker"}, timeout=10)
        assert r.status_code in (401, 403)


# ---------------- Export PPTX ----------------

class TestExportPptx:
    def test_pptx_download_ok(self, session, upload_id):
        # Make sure store info is set so filename is meaningful
        session.patch(f"{BASE_URL}/api/dataset/{upload_id}/store-info",
                      json={"store_name": "Carrefour Test", "store_code": "T0001"},
                      timeout=15)
        r = session.get(f"{BASE_URL}/api/dataset/{upload_id}/export-pptx",
                        timeout=120, stream=False)
        assert r.status_code == 200, f"Status: {r.status_code} body: {r.text[:300]}"
        ctype = r.headers.get("content-type", "")
        assert "presentationml.presentation" in ctype, f"Bad CT: {ctype}"
        # File size > 1 MB (template is 39 MB)
        assert len(r.content) > 1_000_000, f"PPTX too small: {len(r.content)} bytes"
        # Filename pattern
        cd = r.headers.get("content-disposition", "")
        assert "CR_VT_Phasage" in cd, f"Bad filename: {cd}"
        # Magic bytes of a PPTX (zip)
        assert r.content[:2] == b"PK", "Not a valid zip/pptx"

    def test_pptx_unauthenticated(self):
        r = requests.get(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/export-pptx", timeout=30)
        assert r.status_code in (401, 403)

    def test_pptx_unknown_dataset(self, session):
        r = session.get(f"{BASE_URL}/api/dataset/does-not-exist-xyz/export-pptx", timeout=15)
        assert r.status_code == 404
