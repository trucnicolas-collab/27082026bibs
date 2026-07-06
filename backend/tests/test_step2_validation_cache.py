"""Tests for Step 2 validation cache-consistency bug fix.
Validates that PATCH /surface and PATCH /dongles are immediately reflected
in GET /step2-validation (multi-replica cache coherence via load_dataset refresh).
"""
import io
import os
import pytest
import requests
import openpyxl

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://go-lang-43.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@vusion.local"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    # Auth via HTTP-only cookie set by backend
    return s


@pytest.fixture(scope="module")
def headers(session):
    # Backward-compat alias: return the session as the "headers" fixture
    return session


def _make_min_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Secteur", "Rayon", "N° allée", "Type", "Référence", "Désignation", "Quantité"])
    ws.append(["S1", "R1", "1", "EEG", "15024", "ES 1.5 (noir)", 10])
    ws.append(["S1", "R1", "1", "Rail", "16957", "Rail 1187mm noir", 5])
    ws.append(["S1", "R1", "2", "Caméra", "11892", "Caméra (noire)", 2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def upload_id(headers):
    files = {"file": ("TEST_step2.xlsx", _make_min_xlsx(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = headers.post(f"{BASE_URL}/api/upload-excel", files=files, timeout=60)
    assert r.status_code == 200, f"Upload failed: {r.status_code} {r.text[:400]}"
    uid = r.json()["upload_id"]
    yield uid
    try:
        headers.delete(f"{BASE_URL}/api/dataset/{uid}", timeout=15)
    except Exception:
        pass


class TestStep2Validation:
    def test_initial_state_blocks(self, headers, upload_id):
        """Fresh dataset: no surface, no dongles → must block with correct codes."""
        r = headers.get(f"{BASE_URL}/api/dataset/{upload_id}/step2-validation",
                          timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        codes = {i["code"] for i in data["issues"]}
        assert "surface_missing" in codes
        assert "dongles_missing" in codes
        assert data["surface_category"] is None
        assert data["dongles_quantity"] == 0

    def test_patch_surface_then_get_immediately_reflects(self, headers, upload_id):
        """PATCH surface → GET step2-validation must immediately see plus_10000."""
        r = headers.patch(f"{BASE_URL}/api/dataset/{upload_id}/surface",
                            json={"category": "plus_10000"}, timeout=30)
        assert r.status_code == 200, r.text
        # Immediate GET (simulates cross-replica case: cache should refresh flat fields)
        r2 = headers.get(f"{BASE_URL}/api/dataset/{upload_id}/step2-validation",
                           timeout=15)
        assert r2.status_code == 200
        d = r2.json()
        assert d["surface_category"] == "plus_10000", d
        codes = {i["code"] for i in d["issues"]}
        assert "surface_missing" not in codes

    def test_patch_dongles_then_get_immediately_reflects(self, headers, upload_id):
        """PATCH dongles=22 → GET step2-validation must immediately see 22."""
        r = headers.patch(f"{BASE_URL}/api/dataset/{upload_id}/dongles",
                            json={"quantity": 22}, timeout=30)
        assert r.status_code == 200, r.text
        r2 = headers.get(f"{BASE_URL}/api/dataset/{upload_id}/step2-validation",
                           timeout=15)
        assert r2.status_code == 200
        d = r2.json()
        assert d["dongles_quantity"] == 22, d
        codes = {i["code"] for i in d["issues"]}
        assert "dongles_missing" not in codes

    def test_full_step2_ok_after_both_patches(self, headers, upload_id):
        """With surface + dongles set, validation should be ok=True (assuming no bad refs)."""
        r = headers.get(f"{BASE_URL}/api/dataset/{upload_id}/step2-validation",
                          timeout=15)
        assert r.status_code == 200
        d = r.json()
        # Le fichier test n'a pas de lignes AUTRE, donc pas d'unprocessed_refs
        assert d["surface_category"] == "plus_10000"
        assert d["dongles_quantity"] == 22
        assert d["ok"] is True, f"Expected ok=True, got issues={d.get('issues')}"

    def test_surface_moins_10000_also_reflects(self, headers, upload_id):
        """Toggling to moins_10000 should also be immediately visible."""
        r = headers.patch(f"{BASE_URL}/api/dataset/{upload_id}/surface",
                            json={"category": "moins_10000"}, timeout=30)
        assert r.status_code == 200
        r2 = headers.get(f"{BASE_URL}/api/dataset/{upload_id}/step2-validation",
                           timeout=15)
        assert r2.json()["surface_category"] == "moins_10000"

    def test_dongles_zero_blocks_again(self, headers, upload_id):
        """Setting dongles=0 must re-block validation with dongles_missing."""
        r = headers.patch(f"{BASE_URL}/api/dataset/{upload_id}/dongles",
                            json={"quantity": 0}, timeout=30)
        assert r.status_code == 200
        r2 = headers.get(f"{BASE_URL}/api/dataset/{upload_id}/step2-validation",
                           timeout=15)
        d = r2.json()
        assert d["dongles_quantity"] == 0
        codes = {i["code"] for i in d["issues"]}
        assert "dongles_missing" in codes
        assert d["ok"] is False
