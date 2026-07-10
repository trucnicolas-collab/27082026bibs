"""Backend tests for the new terrain (public token) endpoints of /api/suivi + /api/suivi-terrain."""
import io
import os
import pytest
import requests
from openpyxl import load_workbook

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://go-lang-43.preview.emergentagent.com").rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"
UID = "1__A__R1"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@vusion.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def token(auth):
    r = auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/terrain-share", json={"enabled": True})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert tok
    return tok


# ---- terrain-share toggle -----------------------------------------------
def test_terrain_share_toggle_disable_and_reenable(auth):
    r = auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/terrain-share", json={"enabled": True})
    assert r.status_code == 200
    tok = r.json()["token"]
    # public accessible
    r = requests.get(f"{BASE_URL}/api/suivi-terrain/{tok}")
    assert r.status_code == 200
    # disable
    r = auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/terrain-share", json={"enabled": False})
    assert r.status_code == 200
    r = requests.get(f"{BASE_URL}/api/suivi-terrain/{tok}")
    assert r.status_code == 404
    # reenable
    r = auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/terrain-share", json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["token"] == tok


# ---- public state --------------------------------------------------------
def test_terrain_state_hides_terrain_key(token):
    r = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}")
    assert r.status_code == 200
    j = r.json()
    assert j["is_terrain"] is True
    assert "terrain" not in j
    assert "allees" in j and any(a["uid"] == UID for a in j["allees"])
    assert j.get("geo_keys") == ["rails_es", "sa_15", "sa_21_std", "sa_21_freezer"]


def test_terrain_state_invalid_token():
    r = requests.get(f"{BASE_URL}/api/suivi-terrain/deadbeefdeadbeefdeadbeefdeadbeef")
    assert r.status_code == 404


# ---- PATCH allee geoloc + comment ---------------------------------------
def test_terrain_patch_geo_gap_and_alert_explanation(token):
    # set reel=5, geo=3 → gap 2, no comment → needs_explanation True
    r = requests.patch(f"{BASE_URL}/api/suivi-terrain/{token}/allee",
                       json={"uid": UID, "rails_es_reel": 5, "rails_es_geo": 3,
                             "geoloc_comment": ""})
    assert r.status_code == 200

    j = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}").json()
    a = next(a for a in j["allees"] if a["uid"] == UID)
    assert a["reel"]["rails_es"] == 5
    assert a["geo"]["rails_es"] == 3
    assert a["geo_gap"].get("rails_es") == 2

    alerts_geo = [al for al in j["alerts"] if al.get("type") == "geoloc" and al.get("uid") == UID]
    assert alerts_geo, "expected geoloc alert"
    assert alerts_geo[0]["needs_explanation"] is True
    assert "Explication demandée" in alerts_geo[0]["message"] or "Explication demand" in alerts_geo[0]["message"]

    # add comment
    r = requests.patch(f"{BASE_URL}/api/suivi-terrain/{token}/allee",
                       json={"uid": UID, "geoloc_comment": "TEST_ explication automatique"})
    assert r.status_code == 200
    j = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}").json()
    alerts_geo = [al for al in j["alerts"] if al.get("type") == "geoloc" and al.get("uid") == UID]
    assert alerts_geo
    assert alerts_geo[0]["needs_explanation"] is False
    assert "TEST_ explication" in alerts_geo[0]["message"]


def test_terrain_patch_negative_geo_422(token):
    r = requests.patch(f"{BASE_URL}/api/suivi-terrain/{token}/allee",
                       json={"uid": UID, "rails_es_geo": -1})
    assert r.status_code == 422


# ---- Photos public ------------------------------------------------------
def test_terrain_photo_upload_get_delete(token):
    img_bytes = _tiny_png()
    files = {"file": ("test.png", img_bytes, "image/png")}
    data = {"uid": UID}
    r = requests.post(f"{BASE_URL}/api/suivi-terrain/{token}/allee-photo",
                      files=files, data=data)
    assert r.status_code == 200, r.text
    pid = r.json()["photo"]["id"]

    # GET returns bytes
    r = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}/photo/{pid}")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/")
    assert len(r.content) > 0

    # listed in state
    j = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}").json()
    a = next(a for a in j["allees"] if a["uid"] == UID)
    assert any(p["id"] == pid for p in a["photos"])

    # non-image upload → 400
    r = requests.post(f"{BASE_URL}/api/suivi-terrain/{token}/allee-photo",
                      files={"file": ("x.txt", b"hello", "text/plain")},
                      data={"uid": UID})
    assert r.status_code == 400

    # delete
    r = requests.delete(f"{BASE_URL}/api/suivi-terrain/{token}/photo/{pid}")
    assert r.status_code == 200
    j = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}").json()
    a = next(a for a in j["allees"] if a["uid"] == UID)
    assert not any(p["id"] == pid for p in a["photos"])


# ---- Photo authenticated variant ----------------------------------------
def test_auth_photo_endpoints(auth):
    img_bytes = _tiny_png()
    r = auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee-photo",
                  files={"file": ("test.png", img_bytes, "image/png")},
                  data={"uid": UID})
    assert r.status_code == 200, r.text
    pid = r.json()["photo"]["id"]
    r = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/photo/{pid}")
    assert r.status_code == 200
    assert len(r.content) > 0
    r = auth.delete(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/photo/{pid}")
    assert r.status_code == 200


# ---- Rapport terrain includes photos + geo columns ----------------------
def test_terrain_rapport_nuit_has_geo_and_images(token):
    # add a photo to embed
    img_bytes = _tiny_png()
    r = requests.post(f"{BASE_URL}/api/suivi-terrain/{token}/allee-photo",
                      files={"file": ("test.png", img_bytes, "image/png")},
                      data={"uid": UID})
    assert r.status_code == 200
    pid = r.json()["photo"]["id"]

    try:
        r = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}/rapport-nuit/2")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
        wb = load_workbook(io.BytesIO(r.content))
        ws = wb.active
        rows_texts = []
        for row in ws.iter_rows(values_only=True):
            rows_texts.append([str(c) if c is not None else "" for c in row])
        flat = "\n".join(" | ".join(r) for r in rows_texts)
        assert "Géoloc" in flat, "expected 'Géoloc' column header"
        assert "Explication géoloc" in flat, "expected 'Explication géoloc' header"
        # images embedded
        assert len(ws._images) >= 1, f"expected at least 1 embedded image, got {len(ws._images)}"
    finally:
        requests.delete(f"{BASE_URL}/api/suivi-terrain/{token}/photo/{pid}")


# ---- Incidents via terrain ----------------------------------------------
def test_terrain_incident_create_delete(token):
    r = requests.post(f"{BASE_URL}/api/suivi-terrain/{token}/incident",
                      json={"nuit": 2, "text": "TEST_terrain incident"})
    assert r.status_code == 200
    inc_id = r.json()["incident"]["id"]
    j = requests.get(f"{BASE_URL}/api/suivi-terrain/{token}").json()
    assert any(i["id"] == inc_id for i in j["incidents"])
    r = requests.delete(f"{BASE_URL}/api/suivi-terrain/{token}/incident/{inc_id}")
    assert r.status_code == 200


# ---------------------------------------------------------------- helpers
def _tiny_png():
    # 1x1 PNG
    return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
            b"\x00\x00\x00\x03\x00\x01[\x9f\x8c\x0c\x00\x00\x00\x00IEND\xaeB`\x82")
