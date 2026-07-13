"""Iter21 backend tests — split Phasage EEG / Phasage Caméra + filtres SA/caméras."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@vusion.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def state(client):
    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}")
    assert r.status_code == 200, r.text
    return r.json()


def _has_cam_term(s):
    s = (s or "").lower()
    return "caméra" in s or "camera" in s or "captana" in s


# ---- Filtre côté EEG ----
def test_eeg_products_have_no_camera_or_captana(state):
    """state.allees[].products ne doit contenir aucun produit caméra/captana."""
    for a in state.get("allees", []):
        for p in a.get("products", []):
            desig = p.get("designation") or ""
            typ = p.get("type") or ""
            assert not _has_cam_term(desig), \
                f"Camera/captana product '{desig}' found in EEG allee {a.get('uid')}"
            assert not _has_cam_term(typ), \
                f"Camera type '{typ}' found in EEG allee {a.get('uid')}"
            assert p.get("family") != "cameras"


def test_eeg_products_have_no_zero_plan(state):
    """state.allees[].products ne doit contenir aucun produit avec plan=0."""
    for a in state.get("allees", []):
        for p in a.get("products", []):
            assert (p.get("plan") or 0) > 0, \
                f"Product '{p.get('designation')}' with plan=0 in allee {a.get('uid')}"


# ---- Structure Phasage Caméra ----
def test_cam_section_exists(state):
    """state.cam existe avec allees list."""
    cam = state.get("cam") or {}
    assert isinstance(cam.get("allees"), list)


def test_cam_allees_have_products_list(state):
    """Chaque cam_allee doit avoir un tableau products avec is_camera/is_fixation."""
    cam = state.get("cam") or {}
    for a in cam.get("allees", []):
        assert "products" in a, f"products missing on cam allee {a.get('uid')}"
        assert isinstance(a["products"], list)
        for p in a["products"]:
            assert "is_camera" in p
            assert "is_fixation" in p
            assert "plan" in p
            assert (p.get("plan") or 0) > 0
            # produit doit être un produit caméra
            assert _has_cam_term(p.get("designation") or "") or \
                   (p.get("type") or "").lower() in ("caméra", "camera")


# ---- Stock cam-side ----
def test_stock_includes_cam_products(state):
    """state.stock doit inclure les produits Captana (family=cameras ou désignation Captana)."""
    stock_desigs = [(s.get("designation") or "").lower() for s in state.get("stock", [])]
    # Le dataset de test contient au moins "Caméra noire"
    has_camera = any("caméra" in d or "camera" in d for d in stock_desigs)
    assert has_camera, f"Stock does not contain any camera product. Stock: {stock_desigs}"


def test_cam_stock_row_has_positive_prevu(state):
    """Les produits caméra dans le stock doivent avoir prevu > 0."""
    for s in state.get("stock", []):
        desig = (s.get("designation") or "").lower()
        if "caméra" in desig or "camera" in desig or "captana" in desig:
            assert (s.get("prevu") or 0) > 0, f"Cam product '{s.get('designation')}' prevu=0"


# ---- Régression : actions existantes fonctionnent ----
def test_patch_allee_still_works(client):
    """PATCH sur une allée EEG doit continuer à fonctionner."""
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                     json={"uid": "1__A__R1",
                           "products": [{"designation": "ES 1.5 noir", "reel": 95}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") or "state" in j or "allees" in j


def test_patch_cam_allee_still_works(client, state):
    """PATCH sur une cam_allee doit continuer à fonctionner."""
    cam_allees = (state.get("cam") or {}).get("allees") or []
    if not cam_allees:
        pytest.skip("No cam allees in test dataset")
    uid = cam_allees[0]["uid"]
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee-cam",
                     json={"uid": uid, "cameras_reel": 1})
    assert r.status_code in (200, 201), r.text
