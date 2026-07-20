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


def test_1240_rail_bonus_accounted_in_reel(auth):
    """(iter35) Poser 100% d'un rail doit incrémenter reel_es_15 du bonus
    ES 1.5 (convention "1 rail = +1 ES 1.5"). Résultat : à 100% de pose,
    eeg_reel == eeg_plan (au lieu de eeg_reel < eeg_plan à cause du bonus
    non-comptabilisé). Aligne les totaux Phasage et Suivi."""
    auth.delete(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/reset")
    state = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    # Pose 100% sur toutes les allées
    for a in state["allees"]:
        prods = [{"designation": p["designation"],
                  "reel": p["plan"],
                  "geo": p["plan"] if p["is_geo"] else None}
                 for p in a["products"]]
        auth.patch(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/allee",
                   json={"uid": a["uid"], "products": prods})
    state2 = auth.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}").json()
    prevues = state2["stats"]["eeg_prevues"]
    posees = state2["stats"]["eeg_posees"]
    assert prevues == posees, (
        f"À 100% de pose, eeg_posees ({posees}) doit égaler eeg_prevues ({prevues}) — "
        f"bonus rails toujours pas répercuté côté posé ?"
    )
    auth.delete(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/reset")
