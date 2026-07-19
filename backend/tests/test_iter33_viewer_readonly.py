"""Backend tests for the read-only "viewer" access mode (/api/suivi-view).

Ces routes exposent UNIQUEMENT des GET protégés par un token global partagé.
Aucune route d'écriture n'existe : la sécurité repose sur la construction du router.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@vusion.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module", autouse=True)
def ensure_published(auth):
    r = auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/publish", json={"published": True})
    assert r.status_code == 200


@pytest.fixture(scope="module")
def viewer_token(auth):
    r = auth.get(f"{BASE_URL}/api/suivi/viewer-link")
    assert r.status_code == 200
    tk = r.json()["token"]
    assert tk and len(tk) > 20
    return tk


# ---- Token endpoint ---------------------------------------------------------
def test_viewer_link_requires_auth():
    r = requests.get(f"{BASE_URL}/api/suivi/viewer-link")
    assert r.status_code == 401


def test_viewer_link_idempotent(auth, viewer_token):
    r = auth.get(f"{BASE_URL}/api/suivi/viewer-link")
    assert r.status_code == 200
    # Le même token doit être retourné à chaque appel (pas de rotation implicite)
    assert r.json()["token"] == viewer_token


# ---- GET endpoints : refusent sans token, autorisent avec token -------------
def test_viewer_stores_without_token_denied():
    r = requests.get(f"{BASE_URL}/api/suivi-view/stores")
    # Sans token, FastAPI renvoie 422 (query param manquant)
    assert r.status_code in (401, 422)


def test_viewer_stores_bad_token_denied():
    r = requests.get(f"{BASE_URL}/api/suivi-view/stores", params={"token": "WRONG"})
    assert r.status_code == 401
    assert "invalide" in r.json().get("detail", "").lower()


def test_viewer_stores_ok(viewer_token):
    r = requests.get(f"{BASE_URL}/api/suivi-view/stores", params={"token": viewer_token})
    assert r.status_code == 200
    ids = [s["upload_id"] for s in r.json()["stores"]]
    assert UPLOAD_ID in ids


def test_viewer_state_ok(viewer_token):
    r = requests.get(f"{BASE_URL}/api/suivi-view/{UPLOAD_ID}", params={"token": viewer_token})
    assert r.status_code == 200
    j = r.json()
    assert "stats" in j
    assert "nights" in j
    assert "allees" in j


def test_viewer_state_bad_token(viewer_token):
    r = requests.get(f"{BASE_URL}/api/suivi-view/{UPLOAD_ID}", params={"token": "NOPE"})
    assert r.status_code == 401


def test_viewer_materiel_ok(viewer_token):
    r = requests.get(f"{BASE_URL}/api/suivi-view/{UPLOAD_ID}/materiel",
                     params={"token": viewer_token})
    assert r.status_code == 200
    assert "nights" in r.json()


def test_viewer_materiel_nuit_ok(viewer_token):
    r = requests.get(f"{BASE_URL}/api/suivi-view/{UPLOAD_ID}/materiel/1",
                     params={"token": viewer_token})
    assert r.status_code == 200


def test_viewer_rapport_ok(viewer_token):
    r = requests.get(f"{BASE_URL}/api/suivi-view/{UPLOAD_ID}/rapport-nuit/1",
                     params={"token": viewer_token})
    # Peut être 200 (fichier xlsx) ou 404 si nuit vide, mais jamais 401/403
    assert r.status_code in (200, 404)


# ---- WRITE endpoints : n'existent PAS (sécurité par construction) -----------
@pytest.mark.parametrize("method,path,payload", [
    ("PATCH", f"/api/suivi-view/{UPLOAD_ID}/allee", {"uid": "x"}),
    ("PATCH", f"/api/suivi-view/{UPLOAD_ID}/allee-cam", {"uid": "x"}),
    ("PATCH", f"/api/suivi-view/{UPLOAD_ID}/stock", {"designation": "x", "recu": 1}),
    ("POST", f"/api/suivi-view/{UPLOAD_ID}/incident", {"nuit": 1, "text": "x"}),
    ("POST", f"/api/suivi-view/{UPLOAD_ID}/publish", {"published": True}),
    ("POST", f"/api/suivi-view/{UPLOAD_ID}/replan", {"apply": True}),
    ("DELETE", f"/api/suivi-view/{UPLOAD_ID}/reset", None),
])
def test_viewer_no_write_routes(viewer_token, method, path, payload):
    """Ces routes ne DOIVENT PAS exister : 404/405 attendus même avec un token valide."""
    kwargs = {"params": {"token": viewer_token}}
    if payload is not None:
        kwargs["json"] = payload
    r = requests.request(method, f"{BASE_URL}{path}", **kwargs)
    assert r.status_code in (404, 405), (
        f"{method} {path} should not exist for viewer, got {r.status_code}: {r.text}"
    )


# ---- Rotation ---------------------------------------------------------------
def test_viewer_rotate_invalidates_old_token(auth, viewer_token):
    """Régénérer le token doit invalider les anciens liens partagés."""
    # Génère un nouveau token
    r = auth.post(f"{BASE_URL}/api/suivi/viewer-link/rotate")
    assert r.status_code == 200
    new_token = r.json()["token"]
    assert new_token != viewer_token

    # L'ancien token doit maintenant échouer
    r = requests.get(f"{BASE_URL}/api/suivi-view/stores", params={"token": viewer_token})
    assert r.status_code == 401

    # Le nouveau token doit fonctionner
    r = requests.get(f"{BASE_URL}/api/suivi-view/stores", params={"token": new_token})
    assert r.status_code == 200

    # Remettre l'ancien token pour ne pas casser les autres tests si ré-exécutés
    # (idempotent : la rotation créera un nouveau token la prochaine fois)
