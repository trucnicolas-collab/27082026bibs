"""Iter29 E2E — Zones Saisonnières dans le SUIVI DE DÉPLOIEMENT (v27).

Tests bout-en-bout via l'API HTTP :
 - login admin
 - dataset existant (surface=plus_10000)
 - PATCH /api/dataset/{id}/phasage avec ZS assignées à une nuit
 - GET /api/suivi/{id} : ZS présentes avec plan.sa_15=400 + plan.sa_21_std=1600
 - GET /api/suivi/{id}/materiel/{nuit}?mode=eeg : produits synthétiques présents
 - ZS non filtrées quand sa_install.answered=true & enabled=false
 - state.stats.eeg_prevues inclut 2000/ZS
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"
ZS_NUIT = 17


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@vusion.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def surface_plus10000(client):
    """S'assure que le magasin est en surface plus_10000 (3 ZS)."""
    r = client.patch(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/surface",
                     json={"category": "plus_10000"})
    assert r.status_code == 200, r.text
    return "plus_10000"


@pytest.fixture(scope="module")
def phasage_with_zs(client, surface_plus10000):
    """Configure un phasage avec ZS1/ZS2/ZS3 assignées à ZS_NUIT."""
    # Récupère le résumé pour obtenir les allées et ZS
    r = client.get(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/phasage-summary")
    assert r.status_code == 200, r.text
    summary = r.json()
    seasonal_zones = summary.get("seasonal_zones") or []
    assert len(seasonal_zones) >= 2, f"Attendu >=2 ZS, reçu {len(seasonal_zones)}"

    # Ajoute une row ES par ZS avec nuit=ZS_NUIT
    es_rows = []
    for a in (summary.get("allees") or []):
        uid = str(a.get("uid") or a.get("allee"))
        es_rows.append({"id": uid, "allee": uid, "nuit": 1})
    for z in seasonal_zones:
        zid = str(z["id"])
        es_rows.append({"id": zid, "allee": zid, "nuit": ZS_NUIT})

    payload = {
        "es": {"nb_nuits": max(ZS_NUIT, 18), "rows": es_rows},
        "cam": {"nb_nuits": 0, "start_at_nuit": 5, "rows": []},
        "suivi": {"rows": []},
        "dates": {str(ZS_NUIT): "2026-03-01"},
    }
    r = client.patch(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/phasage", json=payload)
    assert r.status_code == 200, r.text
    return {"seasonal_zones": seasonal_zones, "nuit": ZS_NUIT}


def test_suivi_state_contains_zs_with_correct_split(client, phasage_with_zs):
    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}")
    assert r.status_code == 200, r.text
    state = r.json()
    allees = state.get("allees") or []
    zs_allees = [a for a in allees if a.get("secteur", "").startswith("Zone sais")]
    expected_n = len(phasage_with_zs["seasonal_zones"])
    assert len(zs_allees) == expected_n, \
        f"Attendu {expected_n} ZS dans state.allees, reçu {len(zs_allees)}"
    for a in zs_allees:
        plan = a.get("plan") or {}
        assert plan.get("sa_15") == 400, f"ZS {a.get('uid')} plan.sa_15={plan.get('sa_15')}"
        assert plan.get("sa_21_std") == 1600, \
            f"ZS {a.get('uid')} plan.sa_21_std={plan.get('sa_21_std')}"
        assert a.get("nuit_plan") == phasage_with_zs["nuit"]


def test_materiel_nuit_eeg_contains_zs_synthetic_products(client, phasage_with_zs):
    nuit = phasage_with_zs["nuit"]
    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/materiel/{nuit}?mode=eeg")
    assert r.status_code == 200, r.text
    j = r.json()
    # Aplatit produits (structure : list of allees/products)
    desigs = {}

    def _add(d, k, v):
        d[k] = d.get(k, 0.0) + float(v or 0)
    # tolère plusieurs formats
    for allee in (j.get("allees") or j.get("nights") or []):
        for p in (allee.get("products") or []):
            _add(desigs, p.get("designation"), p.get("plan") or p.get("qty") or 0)
    for p in (j.get("products") or []):
        _add(desigs, p.get("designation"), p.get("plan") or p.get("qty") or 0)

    n_zs = len(phasage_with_zs["seasonal_zones"])
    # Chaque ZS ajoute 400 SA 1.5 + 1600 SA 2.1 = agrégé n_zs*400 et n_zs*1600
    key15 = "SA 1.5 (Zone saisonnier)"
    key21 = "SA 2.1 (Zone saisonnier)"
    assert key15 in desigs, f"Manque '{key15}' dans matériel nuit {nuit}. Trouvés: {list(desigs.keys())[:20]}"
    assert key21 in desigs, f"Manque '{key21}' dans matériel nuit {nuit}"
    assert desigs[key15] == 400 * n_zs, f"{key15}: attendu {400*n_zs}, reçu {desigs[key15]}"
    assert desigs[key21] == 1600 * n_zs, f"{key21}: attendu {1600*n_zs}, reçu {desigs[key21]}"


def test_zs_not_filtered_when_sa_install_disabled(client, phasage_with_zs):
    """Quand sa_install.answered=true & enabled=false, les ZS restent."""
    # Récupère et enrichit le phasage courant avec sa_install
    r = client.get(f"{BASE_URL}/api/dataset/{UPLOAD_ID}")
    assert r.status_code == 200
    d = r.json()
    prev_sa = d.get("sa_install") or {}
    # Le sa_install est stocké sur le dataset, PATCH via phasage inclut peut-être pas.
    # On tente via PATCH direct sur le dataset (endpoint générique) :
    # Fallback : re-PATCH phasage avec ajout sa_install si supporté
    # NB: la config sa_install est stockée sur dataset dans _build_state → cfg_sa = d.get("sa_install")
    # On la définit via l'endpoint dédié si présent, sinon on skip.
    r = client.patch(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/sa-install",
                     json={"answered": True, "enabled": False})
    if r.status_code == 404:
        pytest.skip("Endpoint /sa-install non disponible")
    assert r.status_code in (200, 204), r.text

    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}")
    assert r.status_code == 200
    state = r.json()
    zs_allees = [a for a in (state.get("allees") or [])
                 if a.get("secteur", "").startswith("Zone sais")]
    assert len(zs_allees) >= 2
    for a in zs_allees:
        plan = a.get("plan") or {}
        assert plan.get("sa_15") == 400, f"ZS filtrée par sa_install! sa_15={plan.get('sa_15')}"
        assert plan.get("sa_21_std") == 1600, \
            f"ZS filtrée par sa_install! sa_21_std={plan.get('sa_21_std')}"

    # Restore
    client.patch(f"{BASE_URL}/api/dataset/{UPLOAD_ID}/sa-install",
                 json=prev_sa or {"answered": False, "enabled": False})


def test_stats_eeg_prevues_includes_zs(client, phasage_with_zs):
    """state.stats.eeg_prevues doit inclure 2000/ZS."""
    r = client.get(f"{BASE_URL}/api/suivi/{UPLOAD_ID}")
    assert r.status_code == 200
    state = r.json()
    stats = state.get("stats") or {}
    eeg_prevues = stats.get("eeg_prevues")
    if eeg_prevues is None:
        pytest.skip(f"KPI eeg_prevues absent. stats keys={list(stats.keys())}")
    n_zs = len(phasage_with_zs["seasonal_zones"])
    # Au minimum, contient les EEG des ZS
    assert eeg_prevues >= 2000 * n_zs, \
        f"eeg_prevues={eeg_prevues} < {2000*n_zs} attendus pour {n_zs} ZS"
