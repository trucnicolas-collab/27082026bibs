"""Backend tests for the new CAM + MATERIEL endpoints of /api/suivi and /api/suivi-terrain."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"
CAM_UID = "1__A__R1"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@vusion.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module", autouse=True)
def ensure_published(auth):
    """Terrain routes now key on upload_id + published=true."""
    r = auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/publish", json={"published": True})
    assert r.status_code == 200, r.text
    yield
    auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/publish", json={"published": True})


# ---------- CAM section in state --------------------------------------------
def test_state_has_cam_section(auth):
    r = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}")
    assert r.status_code == 200
    j = r.json()
    assert "cam" in j, "missing cam section"
    cam = j["cam"]
    for k in ("start_at_nuit", "nb_nuits", "nights", "allees"):
        assert k in cam, f"missing cam.{k}"
    # allée cam test uid
    a = next((x for x in cam["allees"] if x["uid"] == CAM_UID), None)
    assert a is not None, f"cam allée {CAM_UID} not found; got uids={[x['uid'] for x in cam['allees'][:5]]}"
    for k in ("uid", "plan", "reel", "geo", "geo_gap", "elements", "status", "nuit_abs"):
        assert k in a
    assert a["plan"] == 2
    assert 12 in a.get("elements", []) or "12" in [str(e) for e in a.get("elements", [])]
    # night entries
    n1 = next((n for n in cam["nights"] if n["nuit"] == 1), None)
    assert n1 is not None
    for k in ("nuit", "nuit_abs", "nb_allees", "cam_plan", "cam_reel", "complete"):
        assert k in n1


# ---------- PATCH allee-cam (auth) ------------------------------------------
def test_patch_allee_cam_auth_geo_gap_alert(auth):
    r = auth.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee-cam",
                   json={"uid": CAM_UID, "cameras_reel": 2, "cameras_geo": 1, "geoloc_comment": ""})
    assert r.status_code == 200

    j = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    a = next(x for x in j["cam"]["allees"] if x["uid"] == CAM_UID)
    assert a["reel"] == 2
    assert a["geo"] == 1
    assert a["geo_gap"] == 1

    geo_alerts = [al for al in j["alerts"]
                  if al.get("type") == "geoloc" and al.get("family") == "cameras" and al.get("uid") == CAM_UID]
    assert geo_alerts, f"expected cam geoloc alert, alerts={j['alerts']}"
    assert geo_alerts[0]["needs_explanation"] is True


def test_patch_allee_cam_add_comment_clears_needs_explanation(auth):
    r = auth.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee-cam",
                   json={"uid": CAM_UID, "geoloc_comment": "TEST_cam explication"})
    assert r.status_code == 200
    j = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    geo_alerts = [al for al in j["alerts"]
                  if al.get("type") == "geoloc" and al.get("family") == "cameras" and al.get("uid") == CAM_UID]
    assert geo_alerts
    assert geo_alerts[0]["needs_explanation"] is False


def test_patch_allee_cam_negative_422(auth):
    r = auth.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee-cam",
                   json={"uid": CAM_UID, "cameras_geo": -1})
    assert r.status_code == 422


def test_patch_allee_cam_bad_status_400(auth):
    r = auth.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee-cam",
                   json={"uid": CAM_UID, "status": "not_a_status"})
    assert r.status_code == 400


def test_patch_allee_cam_validate_marks_night_complete(auth):
    # Force set reel = plan and validate — a night with only 1 allée should then be complete
    r = auth.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee-cam",
                   json={"uid": CAM_UID, "cameras_reel": 2, "cameras_geo": 2,
                         "status": "validee", "geoloc_comment": ""})
    assert r.status_code == 200
    j = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    a = next(x for x in j["cam"]["allees"] if x["uid"] == CAM_UID)
    assert a["status"] == "validee"
    n = next(x for x in j["cam"]["nights"] if x["nuit"] == 1)
    # night 1 has this single allée → complete after its validation
    if n["nb_allees"] == 1:
        assert n["complete"] is True


# ---------- PATCH allee-cam terrain -----------------------------------------
def test_patch_allee_cam_terrain_public():
    r = requests.patch(f"{BASE_URL}/api/suivi-terrain/{UPLOAD_ID}/allee-cam",
                       json={"uid": CAM_UID, "cameras_reel": 2, "cameras_geo": 1, "geoloc_comment": ""})
    assert r.status_code == 200, r.text
    j = requests.get(f"{BASE_URL}/api/suivi-terrain/{UPLOAD_ID}").json()
    a = next(x for x in j["cam"]["allees"] if x["uid"] == CAM_UID)
    assert a["geo_gap"] == 1
    geo_alerts = [al for al in j["alerts"]
                  if al.get("type") == "geoloc" and al.get("family") == "cameras" and al.get("uid") == CAM_UID]
    assert geo_alerts and geo_alerts[0]["needs_explanation"] is True


def test_patch_allee_cam_terrain_negative_422():
    r = requests.patch(f"{BASE_URL}/api/suivi-terrain/{UPLOAD_ID}/allee-cam",
                       json={"uid": CAM_UID, "cameras_reel": -2})
    assert r.status_code == 422


# ---------- MATERIEL overview ------------------------------------------------
def test_materiel_overview_auth(auth):
    r = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/materiel")
    assert r.status_code == 200
    j = r.json()
    assert "nights" in j and "unassigned" in j
    # Night 2 should contain around 7 products
    n2 = next((n for n in j["nights"] if n["nuit"] == 2), None)
    assert n2 is not None, f"night 2 missing; got nights={[n['nuit'] for n in j['nights']]}"
    designations = {p["designation"]: p["qty"] for p in n2["products"]}
    # spec expects roughly these designations present
    expected_subs = ["ES 1.5", "ES 2.1", "SA 1.5", "SA 2.1", "990", "Caméra"]
    found = [s for s in expected_subs if any(s in d for d in designations)]
    assert len(found) >= 5, f"expected most of {expected_subs} in night2 products; found={found}, designations={list(designations.keys())}"
    # unassigned present
    assert "products" in j["unassigned"]
    assert j["unassigned"]["nb_allees"] >= 1


def test_materiel_overview_terrain():
    r = requests.get(f"{BASE_URL}/api/suivi-terrain/{UPLOAD_ID}/materiel")
    assert r.status_code == 200
    j = r.json()
    assert "nights" in j and "unassigned" in j


# ---------- MATERIEL nuit drill-down ----------------------------------------
def test_materiel_nuit_auth(auth):
    r = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/materiel/2")
    assert r.status_code == 200
    j = r.json()
    assert "allees" in j
    assert len(j["allees"]) >= 1
    a1 = j["allees"][0]
    for k in ("uid", "products", "elements"):
        assert k in a1
    # elements list should have entries with numero + products
    if a1["elements"]:
        el = a1["elements"][0]
        # Accept both 'numero' and 'element' keys
        key = "numero" if "numero" in el else "element"
        assert key in el and "products" in el
    # Element '12' contains 'Caméra noire' qty 2
    all_els = []
    for a in j["allees"]:
        all_els.extend(a["elements"])
    def _num(e):
        return str(e.get("numero", e.get("element", "")))
    el12 = next((e for e in all_els if _num(e) == "12"), None)
    assert el12 is not None, f"element 12 not found; got numeros={[_num(e) for e in all_els]}"
    cam = next((p for p in el12["products"] if "Caméra" in p["designation"]), None)
    assert cam is not None, f"expected Caméra in element 12; got products={el12['products']}"
    assert cam["qty"] == 2
    # (sans élément) bucket
    labels = [_num(e) for a in j["allees"] for e in a["elements"]]
    assert any("sans" in lab.lower() for lab in labels), f"expected '(sans élément)' bucket; got labels={labels}"


def test_materiel_nuit_terrain():
    r = requests.get(f"{BASE_URL}/api/suivi-terrain/{UPLOAD_ID}/materiel/2")
    assert r.status_code == 200


def test_materiel_nuit_404(auth):
    r = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/materiel/99")
    assert r.status_code == 404


# ---------- Regression: previous 20 tests must still pass -------------------
# (executed as separate pytest invocation)
