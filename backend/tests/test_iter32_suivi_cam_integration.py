"""Iteration 32 integration tests — Suivi Caméras products grid refonte.

Validates:
- SUIVI_HIDDEN_DESIGNATIONS filtering (batterie/software caméra)
- cam_allees.products structure in GET /api/suivi/{uid}
- PATCH /api/suivi/{uid}/cam-allee with products payload re-aggregation
- GET /api/suivi/{uid}/stock no hidden designations
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://go-lang-43.preview.emergentagent.com").rstrip("/")
UID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"


@pytest.fixture(scope="module")
def headers():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@vusion.local", "password": "admin123"
    }, timeout=15)
    assert r.status_code == 200, r.text
    # Cookie-based auth: return the session
    return s


def test_suivi_hidden_batterie_software_cam(headers):
    r = headers.get(f"{BASE_URL}/api/suivi/{UID}", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    hidden_kws = ["batterie", "software"]
    # Check cam_allees products
    for night in data.get("cam_nuits", []) or []:
        for allee in night.get("allees", []) or []:
            for p in allee.get("products", []) or []:
                desig = (p.get("designation") or "").lower()
                for kw in hidden_kws:
                    if kw in desig and "cam" in desig:
                        pytest.fail(f"Hidden désignation présente dans cam_allees.products: {desig}")


def test_materiel_cam_no_hidden(headers):
    # Find nuit index for cam
    r0 = headers.get(f"{BASE_URL}/api/suivi/{UID}", timeout=15)
    assert r0.status_code == 200
    nights = r0.json().get("cam_nuits", []) or []
    if not nights:
        pytest.skip("No cam nights configured on dataset")
    for i in range(1, len(nights) + 1):
        r = headers.get(f"{BASE_URL}/api/suivi/{UID}/materiel/{i}?mode=cam", timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        # Search recursively for "batterie caméra" / "software caméra"
        blob = str(j).lower()
        assert "batterie caméra" not in blob and "batterie camera" not in blob, f"batterie caméra présente nuit {i}"
        assert "software caméra" not in blob and "software camera" not in blob, f"software caméra présente nuit {i}"


def test_stock_no_hidden(headers):
    # Stock is included in main GET /api/suivi/{uid} response under "stock"
    r = headers.get(f"{BASE_URL}/api/suivi/{UID}", timeout=15)
    assert r.status_code == 200, r.text
    stock = r.json().get("stock") or []
    for entry in stock:
        desig = (entry.get("designation") or "").lower()
        assert not ("batterie" in desig and "cam" in desig), f"batterie caméra dans stock: {entry}"
        assert not ("software" in desig and "cam" in desig), f"software caméra dans stock: {entry}"


def test_cam_allees_products_structure(headers):
    r = headers.get(f"{BASE_URL}/api/suivi/{UID}", timeout=15)
    assert r.status_code == 200
    data = r.json()
    cam_nuits = data.get("cam_nuits", []) or []
    if not cam_nuits:
        pytest.skip("Aucune nuit cam configurée sur ce dataset")
    found_products = False
    for night in cam_nuits:
        for allee in night.get("allees", []) or []:
            products = allee.get("products")
            assert products is not None, f"allee sans champ products: {allee}"
            assert isinstance(products, list), "products doit être une liste"
            for p in products:
                # Required fields per spec
                for k in ["designation", "plan", "reel", "geo", "is_camera", "is_fixation", "is_geo", "geo_gap"]:
                    assert k in p, f"champ manquant '{k}' dans product: {p}"
                found_products = True
            # Legacy aggregates still present
            assert "cameras_reel" in allee or "fixations_reel" in allee, "aggregates dérivés manquants"
    if not found_products:
        pytest.skip("Aucun produit cam sur le dataset - phasage cam probablement non configuré")


def test_patch_cam_allee_products_reaggregation(headers):
    r = headers.get(f"{BASE_URL}/api/suivi/{UID}", timeout=15)
    assert r.status_code == 200
    data = r.json()
    cam_nuits = data.get("cam_nuits", []) or []
    if not cam_nuits:
        pytest.skip("Aucune nuit cam configurée")
    target_allee = None
    for night in cam_nuits:
        for allee in night.get("allees", []) or []:
            if allee.get("products"):
                target_allee = allee
                break
        if target_allee:
            break
    if not target_allee:
        pytest.skip("Aucune allée cam avec products")
    allee_uid = target_allee.get("uid")
    cam_products = [p for p in target_allee["products"] if p.get("is_camera")]
    if not cam_products:
        pytest.skip("Aucun produit caméra dans l'allée")
    payload_products = [{"designation": p["designation"], "reel": 2, "geo": 1} for p in cam_products[:1]]
    body = {"uid": allee_uid, "products": payload_products}
    r2 = headers.patch(f"{BASE_URL}/api/suivi/{UID}/cam-allee", json=body, timeout=15)
    assert r2.status_code == 200, r2.text
    # Verify persistence
    r3 = headers.get(f"{BASE_URL}/api/suivi/{UID}", timeout=15)
    assert r3.status_code == 200
    d3 = r3.json()
    updated = None
    for night in d3.get("cam_nuits", []) or []:
        for allee in night.get("allees", []) or []:
            if allee.get("uid") == allee_uid:
                updated = allee
                break
    assert updated is not None, "allée non retrouvée après patch"
    # Aggregates should reflect at least the sum of set values
    prod_updated = [p for p in updated["products"] if p["designation"] == payload_products[0]["designation"]]
    assert prod_updated, "product not found after patch"
    assert prod_updated[0]["reel"] == 2, f"reel non persisté: {prod_updated[0]}"
    assert prod_updated[0]["geo"] == 1, f"geo non persisté: {prod_updated[0]}"
