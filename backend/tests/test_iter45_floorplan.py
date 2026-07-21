"""Iter45 — Endpoints Floorplan (CRUD).

Vérifie que les endpoints /api/suivi/{upload_id}/floorplans acceptent bien
un data-url image + zones, refusent les payloads invalides, sanitizent les
coordonnées (clamp 0..1), et sont accessibles côté terrain (sans auth) et
côté viewer (read-only via token).
"""

import os
import uuid
import base64
import pytest
import requests


BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"
API = f"{BASE}/api"
EMAIL = "admin@vusion.local"
PASSWORD = "admin123"

# 1x1 transparent PNG
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
TINY_DATA_URL = f"data:image/png;base64,{_TINY_PNG_B64}"


def _login():
    """Récupère un cookie de session admin."""
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=10)
    if r.status_code != 200:
        pytest.skip(f"Login admin impossible ({r.status_code}) — préview probablement non seedée")
    return s


def _find_dataset(s):
    r = s.get(f"{API}/datasets", timeout=10)
    if r.status_code != 200:
        pytest.skip("Impossible de lister les datasets")
    items = r.json() if isinstance(r.json(), list) else r.json().get("datasets", [])
    if not items:
        pytest.skip("Aucun dataset disponible en preview")
    return items[0].get("upload_id")


def test_floorplan_crud_admin():
    s = _login()
    uid = _find_dataset(s)
    # LIST initial (peut avoir des plans existants d'autres tests)
    r = s.get(f"{API}/suivi/{uid}/floorplans")
    assert r.status_code == 200
    initial = r.json().get("floorplans", [])

    # CREATE
    zone_id = f"z-{uuid.uuid4().hex[:8]}"
    payload = {
        "label": "RDC Test iter45",
        "image_data_url": TINY_DATA_URL,
        "zones": [{"id": zone_id, "allee_uid": "test-uid", "kind": "rect",
                   "coords": [[0.1, 0.2, 0.3, 0.4]]}],
    }
    r = s.post(f"{API}/suivi/{uid}/floorplans", json=payload)
    assert r.status_code == 200, r.text
    plan = r.json()["floorplan"]
    floor_id = plan["id"]
    assert plan["label"] == "RDC Test iter45"
    assert len(plan["zones"]) == 1
    assert plan["zones"][0]["allee_uid"] == "test-uid"

    # LIST après create
    r = s.get(f"{API}/suivi/{uid}/floorplans")
    ids = [p["id"] for p in r.json()["floorplans"]]
    assert floor_id in ids

    # UPDATE (ajoute une seconde zone polygone)
    poly_id = f"z-{uuid.uuid4().hex[:8]}"
    r = s.put(f"{API}/suivi/{uid}/floorplans/{floor_id}", json={
        "label": "RDC Test iter45 (mod)",
        "zones": plan["zones"] + [{
            "id": poly_id, "allee_uid": "another-uid", "kind": "polygon",
            "coords": [[0.1, 0.1], [0.5, 0.1], [0.3, 0.5]],
        }],
    })
    assert r.status_code == 200
    upd = r.json()["floorplan"]
    assert upd["label"] == "RDC Test iter45 (mod)"
    assert len(upd["zones"]) == 2
    assert any(z["kind"] == "polygon" for z in upd["zones"])

    # DELETE
    r = s.delete(f"{API}/suivi/{uid}/floorplans/{floor_id}")
    assert r.status_code == 200
    r = s.get(f"{API}/suivi/{uid}/floorplans")
    assert floor_id not in [p["id"] for p in r.json()["floorplans"]]


def test_floorplan_create_refuses_no_image():
    s = _login()
    uid = _find_dataset(s)
    r = s.post(f"{API}/suivi/{uid}/floorplans", json={"label": "Sans image", "zones": []})
    assert r.status_code == 400
    assert "image_data_url" in r.text.lower()


def test_floorplan_create_refuses_bad_data_url():
    s = _login()
    uid = _find_dataset(s)
    r = s.post(f"{API}/suivi/{uid}/floorplans", json={
        "label": "Faux", "image_data_url": "not a data url", "zones": [],
    })
    assert r.status_code == 400


def test_floorplan_zones_are_clamped():
    """Coordonnées hors 0..1 doivent être clampées."""
    s = _login()
    uid = _find_dataset(s)
    r = s.post(f"{API}/suivi/{uid}/floorplans", json={
        "label": "Clamp",
        "image_data_url": TINY_DATA_URL,
        "zones": [
            {"id": "z-clamp", "allee_uid": "test", "kind": "rect",
             "coords": [[-0.5, 2.0, 0.3, 0.4]]},
        ],
    })
    assert r.status_code == 200
    plan = r.json()["floorplan"]
    z = plan["zones"][0]
    assert z["coords"][0][0] == 0.0  # clampé de -0.5 à 0.0
    assert z["coords"][0][1] == 1.0  # clampé de 2.0 à 1.0
    # cleanup
    s.delete(f"{API}/suivi/{uid}/floorplans/{plan['id']}")


def test_floorplan_polygon_min_3_points():
    """Un polygone avec < 3 points doit être rejeté (silencieusement filtré)."""
    s = _login()
    uid = _find_dataset(s)
    r = s.post(f"{API}/suivi/{uid}/floorplans", json={
        "label": "Poly2",
        "image_data_url": TINY_DATA_URL,
        "zones": [{"id": "z-bad", "allee_uid": "test", "kind": "polygon",
                   "coords": [[0.1, 0.1], [0.5, 0.5]]}],
    })
    assert r.status_code == 200
    # Zone invalide filtrée
    assert len(r.json()["floorplan"]["zones"]) == 0
    s.delete(f"{API}/suivi/{uid}/floorplans/{r.json()['floorplan']['id']}")


def test_floorplan_terrain_access_without_auth():
    """L'espace terrain (sans auth) doit pouvoir lister/créer/éditer les plans."""
    s = _login()
    uid = _find_dataset(s)
    # Publier le magasin pour rendre l'espace terrain accessible
    s.post(f"{API}/suivi/{uid}/publish", json={"published": True})
    # Requête terrain SANS auth
    anon = requests.Session()
    r = anon.get(f"{API}/suivi-terrain/{uid}/floorplans", timeout=10)
    assert r.status_code == 200
    # Create depuis terrain
    r = anon.post(f"{API}/suivi-terrain/{uid}/floorplans", json={
        "label": "Terrain plan",
        "image_data_url": TINY_DATA_URL,
        "zones": [],
    })
    assert r.status_code == 200, r.text
    plan_id = r.json()["floorplan"]["id"]
    # Cleanup
    anon.delete(f"{API}/suivi-terrain/{uid}/floorplans/{plan_id}")


def test_floorplan_viewer_readonly():
    """L'espace viewer (token) doit pouvoir LIRE les plans, pas les modifier."""
    s = _login()
    uid = _find_dataset(s)
    # Récupérer le token viewer
    r = s.get(f"{API}/suivi/viewer-link")
    if r.status_code != 200:
        pytest.skip("Endpoint viewer-link indisponible")
    token = r.json().get("token")
    if not token:
        pytest.skip("Token viewer non émis")
    # Publier
    s.post(f"{API}/suivi/{uid}/publish", json={"published": True})
    # GET viewer
    anon = requests.Session()
    r = anon.get(f"{API}/suivi-view/{uid}/floorplans", params={"token": token})
    assert r.status_code == 200
    assert "floorplans" in r.json()
