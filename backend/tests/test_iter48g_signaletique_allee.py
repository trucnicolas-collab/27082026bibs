"""iter48g — ES 1.5 signalétique visibles par allée dans le suivi.

Contexte :
  L'outil de phasage calcule un bonus "signalétique" = 1 ES 1.5 par rail avec
  différenciation de couleur (noir/blanc). L'utilisateur veut voir ces ES 1.5
  comme ligne dédiée dans la saisie allée du suivi, pour :
    - dire explicitement « posée » ou « non posée »
    - décompter du stock global de manière précise

Choix utilisateur validés :
  Q1a : Ligne DISTINCTE « ES 1.5 signalétique (couleur) » dans l'allée
  Q2d : MÊME SKU que ES 1.5 standard → fusion au niveau stock global

Ce test vérifie :
  1. La ligne "ES 1.5 signalétique (noir)" apparaît dans les products d'une
     allée qui contient des rails noirs (ex. 990 mm noir)
  2. Sa quantité prévue = somme des rails de cette couleur dans l'allée
  3. Le stock global n'a PAS de ligne "ES 1.5 signalétique (X)" séparée
     (fusion avec "ES 1.5 (X)")
  4. Rétro-compat : quand le poseur a marqué le rail comme posé mais N'A PAS
     saisi la signalétique, la signalétique est comptée comme posée (comme
     l'ancien bonus rail auto).
  5. Anti-double-comptage : quand la signalétique est saisie EXPLICITEMENT,
     sa valeur prévaut (pas d'addition avec le rail posé).
"""
import io
import os
import openpyxl
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env", override=False)

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
UPLOAD_ID = "fd15443f-6d2a-4cef-bd72-c56bb29e9c42"
UID = "1__A__R1"  # phasée nuit 2, contient rails 990 mm noir
T = f"{BASE_URL}/api/suivi-terrain/{UPLOAD_ID}"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@vusion.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module", autouse=True)
def publish(auth):
    auth.post(f"{BASE_URL}/api/suivi/{UPLOAD_ID}/publish", json={"published": True})
    yield


def _find_product(allee: dict, desig: str) -> dict | None:
    return next((p for p in allee.get("products") or []
                 if p.get("designation") == desig), None)


def _get_allee(uid: str) -> dict:
    r = requests.get(T)
    assert r.status_code == 200, r.text
    for a in r.json().get("allees", []):
        if a["uid"] == uid:
            return a
    raise AssertionError(f"allee {uid} not found")


def test_ligne_signaletique_apparait_dans_allee():
    a = _get_allee(UID)
    ps = _find_product(a, "ES 1.5 signalétique (noir)")
    assert ps is not None, [p["designation"] for p in a["products"]]
    # Quantité prévue = nombre de rails noirs de l'allée
    rails_noir_total = 0.0
    for p in a["products"]:
        d = p["designation"].lower()
        if any(pat in d for pat in ("990 mm (noir)", "1187 mm (noir)",
                                    "1240 mm (noir)", "1320 mm (noir)",
                                    "535 mm (noir)", "650 mm (noir)")):
            rails_noir_total += float(p.get("plan") or 0)
    assert ps["plan"] == pytest.approx(rails_noir_total), (
        f"signalétique plan={ps['plan']} != rails noirs {rails_noir_total}")
    # Classée en family "es_15"
    assert ps["family"] == "es_15", ps


def test_reset_puis_pose_rail_incremente_signaletique_auto(auth):
    """Rétro-compat : le poseur saisit reel sur le RAIL, mais pas sur la
    signalétique. La signalétique doit être considérée comme posée."""
    # Reset
    requests.patch(f"{T}/allee", json={
        "uid": UID, "status": "a_faire",
        "products": [
            {"designation": "990 mm (noir)", "reel": None},
            {"designation": "ES 1.5 signalétique (noir)", "reel": None},
        ],
    })
    # Pose 5 rails 990 mm noir SANS toucher la signalétique
    requests.patch(f"{T}/allee", json={
        "uid": UID, "products": [{"designation": "990 mm (noir)", "reel": 5}],
    })
    a = _get_allee(UID)
    # ES 1.5 signalétique (noir) doit être 5 (fallback rétro-compat auto)
    ps = _find_product(a, "ES 1.5 signalétique (noir)")
    assert ps["reel"] == 5, ps


def test_saisie_explicite_signaletique_prime_sur_rail(auth):
    """Anti-double-comptage : quand le poseur saisit EXPLICITEMENT la
    signalétique, sa valeur prévaut sur le fallback rail."""
    # Reset
    requests.patch(f"{T}/allee", json={
        "uid": UID, "status": "a_faire",
        "products": [
            {"designation": "990 mm (noir)", "reel": None},
            {"designation": "ES 1.5 signalétique (noir)", "reel": None},
        ],
    })
    # Pose 5 rails + signalétique explicite = 3 (poseur en a posé 3, pas 5)
    requests.patch(f"{T}/allee", json={
        "uid": UID, "products": [
            {"designation": "990 mm (noir)", "reel": 5},
            {"designation": "ES 1.5 signalétique (noir)", "reel": 3},
        ],
    })
    a = _get_allee(UID)
    ps = _find_product(a, "ES 1.5 signalétique (noir)")
    assert ps["reel"] == 3, ps  # Pas 5, pas 8


def test_stock_global_pas_de_ligne_signaletique_separee(auth):
    """La ligne 'ES 1.5 signalétique (X)' doit être FUSIONNÉE avec
    'ES 1.5 (X)' au niveau stock global (Q2d : même SKU)."""
    r = requests.get(T)
    stock = r.json().get("stock") or []
    for s in stock:
        assert not s["designation"].startswith("ES 1.5 signalétique"), (
            f"ligne signalétique trouvée dans stock global : {s}")
    # ES 1.5 (noir) doit exister avec le prévu incluant les signalétiques
    es15_noir = next((s for s in stock if s["designation"] in ("ES 1.5 (noir)", "ES 1.5 noir")), None)
    assert es15_noir is not None, [s["designation"] for s in stock]
    assert es15_noir["prevu"] > 0


def test_excel_stock_sheet_no_signaletique_row(auth):
    """L'onglet Excel Stock ne doit pas non plus contenir de ligne signalétique
    séparée (cohérence avec le stock global JSON)."""
    r = requests.get(f"{T}/rapport-nuit/2")
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=False)
    ws = wb["Stock"]
    for row in ws.iter_rows(min_row=5):
        v = row[0].value
        if isinstance(v, str):
            assert not v.startswith("ES 1.5 signalétique"), (
                f"ligne signalétique orpheline dans Excel Stock : {v}")
    # Reset pour ne pas polluer d'autres tests
    requests.patch(f"{T}/allee", json={
        "uid": UID, "status": "a_faire",
        "products": [
            {"designation": "990 mm (noir)", "reel": None},
            {"designation": "ES 1.5 signalétique (noir)", "reel": None},
        ],
    })
