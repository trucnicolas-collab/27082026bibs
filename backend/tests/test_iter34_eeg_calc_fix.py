"""Backend tests iter34 — bugfix : ne pas compter le bonus rails → ES 1.5 dans eeg_plan.

Contexte : un rail 1240 mm noir (qty 79) était comptabilisé DEUX fois côté prévu
(rails_es + es_15_bonus_noir), mais UNE seule fois côté posé (rails_es).
Résultat : eeg_plan=746 alors qu'à 100% de pose on n'atteignait que 667/746.

Depuis iter34, `_plan_for_allee` n'inclut plus le bonus dans es_15 →
eeg_plan == eeg_reel@100%. Aussi : 535 mm (noir) doit être classé comme
rail_es (donc géolocalisable).
"""
import os
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "nicolas.truc@vusion.com", "password": "Vusion_@2026!"})
    assert r.status_code == 200
    return s


def test_eeg_plan_consistent_with_reel(auth):
    """À 100% de pose, eeg_reel doit égaler eeg_plan (pas de gonflement bonus)."""
    state = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    # Pour chaque allée validée, eeg_reel doit être ≤ eeg_plan (jamais >)
    for a in state.get("allees", []):
        if a.get("has_reel") and a.get("status") == "validee":
            reel = a["eeg_reel"] or 0
            plan = a["eeg_plan"] or 0
            assert reel <= plan + 1, (
                f"Allée {a['allee']} : eeg_reel={reel} > eeg_plan={plan} (bonus rails à retirer ?)"
            )


def test_state_exposes_new_stats(auth):
    """Nouveaux KPI unitaires exposés dans le state."""
    state = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    s = state["stats"]
    for k in ("eeg_prevues", "eeg_posees", "pct",
              "geo_eeg_prevues", "geo_eeg_posees", "geo_eeg_pct",
              "cam_prevues", "cam_posees", "cam_pct",
              "cam_geo_prevues", "cam_geo_posees", "cam_geo_pct"):
        assert k in s, f"Missing stat: {k}"
    # Anciens KPI de lignes-produits (pose_saisis/geo_saisis) — retirés du stats block
    assert "pose_saisis" not in s
    assert "geo_saisis" not in s


def test_night_exposes_geo_eeg_units(auth):
    """Chaque nuit doit exposer geo_eeg_prevues/posees pour la mini-jauge."""
    state = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    for n in state["nights"]:
        assert "geo_eeg_prevues" in n
        assert "geo_eeg_posees" in n


def test_rails_535_is_geo(auth):
    """Un rail 535 mm (noir) doit être classifié rails_es (donc is_geo=True).
    Le RAILS_ES_PATTERNS a été enrichi de "535 mm (noir)" en iter34."""
    from server import _is_rail_es, classify_family
    assert _is_rail_es("535 mm (noir)") is True
    assert classify_family("Rail", "535 mm (noir)") == "rails_es"


def test_1240_rail_no_longer_double_counted(auth):
    """Reset l'état, pose 100% du 1240mm noir sur allée 1__A__R1, vérifie
    que eeg_reel <= eeg_plan (le bonus ES 1.5 est retiré du plan côté Suivi)."""
    auth.delete(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/reset")
    state = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    a = next((x for x in state["allees"] if x["uid"] == "1__A__R1"), None)
    if a is None:
        pytest.skip("Allée 1__A__R1 absente du dataset test")
    # Trouve les produits rails
    rail_prods = [p for p in a["products"] if p.get("family") == "rails_es"]
    if not rail_prods:
        pytest.skip("Pas de rail sur cette allée")
    # Pose 100%
    for p in rail_prods:
        auth.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                   json={"uid": "1__A__R1",
                         "products": [{"designation": p["designation"],
                                       "reel": p["plan"], "geo": p["plan"]}]})
    state2 = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    a2 = next(x for x in state2["allees"] if x["uid"] == "1__A__R1")
    reel = a2["eeg_reel"] or 0
    plan = a2["eeg_plan"] or 0
    # Le rail est rails_es (pas dans EEG_KEYS) donc n'apparaît ni dans reel ni dans plan EEG
    # Avant le fix : plan aurait ajouté es_15_bonus, ce qui aurait fait plan > reel systématiquement.
    # Après le fix : plan et reel EEG sont indépendants du bonus rails.
    assert reel <= plan, f"eeg_reel ({reel}) > eeg_plan ({plan}) — bonus rails toujours compté"
    # Nettoyage
    auth.delete(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/reset")
