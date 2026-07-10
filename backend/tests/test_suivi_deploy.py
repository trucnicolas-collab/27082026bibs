"""Backend tests for the /api/suivi router (Suivi de déploiement)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://go-lang-43.preview.emergentagent.com").rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"
UID = "1__A__R1"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@vusion.local", "password": "admin123"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return s


# ---- GET état complet ----------------------------------------------------
def test_get_suivi_state(client):
    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}")
    assert r.status_code == 200
    j = r.json()
    for k in ("allees", "nights", "stock", "alerts", "stats", "incidents"):
        assert k in j, f"missing {k}"
    assert any(a["uid"] == UID for a in j["allees"])
    a = next(a for a in j["allees"] if a["uid"] == UID)
    assert a["plan"]["es_15"] == 105
    assert a["plan"]["es_21"] == 50
    assert a["plan"]["rails_es"] == 5
    assert a["nuit_plan"] == 2


# ---- PATCH allée : réel + statut ----------------------------------------
def test_patch_allee_reel(client):
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                     json={"uid": UID, "es_15_reel": 100, "status": "validee"})
    assert r.status_code == 200
    j = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    a = next(a for a in j["allees"] if a["uid"] == UID)
    assert a["reel"]["es_15"] == 100
    assert a["delta"]["es_15"] == -5
    assert a["status"] == "validee"
    assert j["stats"]["eeg_posees"] >= 100


# ---- PATCH allée : nuit_reelle move --------------------------------------
def test_patch_allee_nuit_reelle_move_and_reset(client):
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                     json={"uid": UID, "nuit_reelle": 3})
    assert r.status_code == 200
    j = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    a = next(a for a in j["allees"] if a["uid"] == UID)
    assert a["nuit_eff"] == 3
    # reset
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                     json={"uid": UID, "nuit_reelle": 0})
    assert r.status_code == 200
    j = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    a = next(a for a in j["allees"] if a["uid"] == UID)
    assert a["nuit_eff"] == 2
    assert a["nuit_reelle"] in (None, 0)


# ---- PATCH stock : alerte rupture ---------------------------------------
def test_patch_stock_rupture_and_reset(client):
    # Ensure there is remaining to poser: mark allee not-yet validated first
    client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                 json={"uid": UID, "status": "a_faire"})
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/stock",
                     json={"family": "es_15", "recu": 50})
    assert r.status_code == 200
    j = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    alerts_es15 = [a for a in j["alerts"] if a.get("type") == "rupture" and a.get("family") == "es_15"]
    assert alerts_es15, f"expected rupture alert, got alerts={j['alerts']}"
    assert alerts_es15[0]["manque"] > 0
    # reset (null -> theorique)
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/stock",
                     json={"family": "es_15", "recu": None})
    assert r.status_code == 200
    j = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    st = next(s for s in j["stock"] if s["family"] == "es_15")
    assert st["recu_theorique"] is True
    # restore validee for later tests
    client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                 json={"uid": UID, "status": "validee", "es_15_reel": 100})


def test_patch_stock_bad_family(client):
    r = client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/stock",
                     json={"family": "xxx", "recu": 10})
    assert r.status_code == 400


# ---- Incidents ----------------------------------------------------------
def test_incident_create_and_delete(client):
    r = client.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/incident",
                    json={"nuit": 2, "text": "TEST_incident automatique"})
    assert r.status_code == 200
    inc_id = r.json()["incident"]["id"]
    j = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    assert any(i["id"] == inc_id for i in j["incidents"])
    r = client.delete(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/incident/{inc_id}")
    assert r.status_code == 200
    j = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    assert not any(i["id"] == inc_id for i in j["incidents"])


def test_incident_empty_text(client):
    r = client.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/incident",
                    json={"nuit": 2, "text": "   "})
    assert r.status_code == 400


# ---- Rapport Excel -------------------------------------------------------
def test_rapport_nuit_ok(client):
    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/rapport-nuit/2")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "spreadsheet" in ct or "officedocument" in ct
    assert len(r.content) > 500
    # xlsx magic: PK zip header
    assert r.content[:2] == b"PK"


def test_rapport_nuit_404(client):
    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/rapport-nuit/99")
    assert r.status_code == 404


# ---- Replan --------------------------------------------------------------
def test_replan_400_when_all_validated(client):
    # ensure validated
    client.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                 json={"uid": UID, "status": "validee", "es_15_reel": 100})
    r = client.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/replan", json={"apply": False})
    # Either 400 (all validated / no remaining) — expected as documented
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"


# ---- Regression : main app phasage-summary works ------------------------
def test_regression_phasage_summary(client):
    r = client.get(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/phasage-summary")
    assert r.status_code == 200
