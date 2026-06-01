"""
Backend tests for PATCH /api/dataset/{upload_id}/surface — règle SA 2.1 (noir) :
- Le delta (+6000 ou +4000) s'ajoute UNIQUEMENT à total_plus_spare
- quantite et spare RESTENT à la valeur de base (pas de spare additionnel)
- La désignation reçoit le suffixe ' — rajout de X SA sans spare'
- Le retour à null restitue exactement la ligne d'origine
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    try:
        with open('/app/frontend/.env') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    BASE_URL = line.split('=', 1)[1].strip().rstrip('/')
    except Exception:
        pass

SAMPLE_PATH = "/tmp/sample.xlsx"


@pytest.fixture(scope="module")
def upload_id():
    if not os.path.exists(SAMPLE_PATH):
        pytest.skip(f"Sample file missing at {SAMPLE_PATH}")
    with open(SAMPLE_PATH, "rb") as f:
        files = {"file": ("sample.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = requests.post(f"{BASE_URL}/api/upload-excel", files=files, timeout=180)
    assert r.status_code == 200, f"Upload failed: {r.status_code} - {r.text[:500]}"
    return r.json()["upload_id"]


def _find_sa21(rows):
    """Trouve la ligne SA 2.1 (noir) du recap (avec ou sans suffixe ' — rajout de…')."""
    for r in rows:
        des = (r.get("designation") or "").strip()
        # Strip le suffixe éventuel
        i = des.find(" — rajout de ")
        base = des[:i] if i != -1 else des
        if base.lower() == "sa 2.1 (noir)" and r.get("kind") == "product":
            return r
    return None


def _patch_surface(uid, category):
    r = requests.patch(
        f"{BASE_URL}/api/dataset/{uid}/surface",
        json={"category": category},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_surface_plus_10000_adds_6000_to_total_only(upload_id):
    # Etat initial : récupère la ligne SA 2.1 (noir)
    _patch_surface(upload_id, None)
    res0 = _patch_surface(upload_id, None)
    row0 = _find_sa21(res0["rows"])
    assert row0 is not None, "Ligne SA 2.1 (noir) absente du recap"
    base_q = row0["quantite"]
    base_s = row0["spare"]
    base_t = row0["total_plus_spare"]

    # Active +10 000 m² → +6000 sur total_plus_spare seulement
    res = _patch_surface(upload_id, "plus_10000")
    assert res["category"] == "plus_10000"
    row = _find_sa21(res["rows"])
    assert row is not None
    assert row["quantite"] == base_q, f"quantite a changé: {row['quantite']} vs {base_q}"
    assert row["spare"] == base_s, f"spare a changé: {row['spare']} vs {base_s}"
    base_t_num = float(base_t) if base_t not in ("", None) else 0.0
    assert float(row["total_plus_spare"]) == base_t_num + 6000, \
        f"total_plus_spare attendu {base_t_num + 6000}, reçu {row['total_plus_spare']}"
    assert "rajout de 6000 SA sans spare" in row["designation"], row["designation"]


def test_surface_moins_10000_adds_4000_to_total_only(upload_id):
    res = _patch_surface(upload_id, "moins_10000")
    assert res["category"] == "moins_10000"
    row = _find_sa21(res["rows"])
    assert row is not None
    assert "rajout de 4000 SA sans spare" in row["designation"]
    # Le delta doit être 4000 et pas 6000 (pas de cumul)
    # On peut le vérifier en revenant à null puis en remettant moins_10000
    res_null = _patch_surface(upload_id, None)
    row_null = _find_sa21(res_null["rows"])
    base_t_num = float(row_null["total_plus_spare"]) if row_null["total_plus_spare"] not in ("", None) else 0.0

    res2 = _patch_surface(upload_id, "moins_10000")
    row2 = _find_sa21(res2["rows"])
    assert float(row2["total_plus_spare"]) == base_t_num + 4000, \
        f"Attendu {base_t_num + 4000}, reçu {row2['total_plus_spare']}"


def test_surface_null_restores_original(upload_id):
    # Va vers plus_10000 puis revient à null → la ligne doit redevenir identique à l'origine
    _patch_surface(upload_id, "plus_10000")
    res = _patch_surface(upload_id, None)
    assert res["category"] is None
    row = _find_sa21(res["rows"])
    assert row is not None
    assert "rajout de" not in (row.get("designation") or ""), row.get("designation")


def test_surface_no_double_add(upload_id):
    # Appel "plus_10000" deux fois de suite ne doit PAS doubler (pas de cumul)
    res1 = _patch_surface(upload_id, "plus_10000")
    row1 = _find_sa21(res1["rows"])
    t1 = float(row1["total_plus_spare"])

    res2 = _patch_surface(upload_id, "plus_10000")
    row2 = _find_sa21(res2["rows"])
    t2 = float(row2["total_plus_spare"])

    assert t1 == t2, f"Double-apply a doublé total_plus_spare: {t1} -> {t2}"


def test_surface_switch_categories(upload_id):
    # plus_10000 → moins_10000 → plus_10000 : la base doit rester stable
    _patch_surface(upload_id, None)
    r0 = _find_sa21(_patch_surface(upload_id, None)["rows"])
    base_t = float(r0["total_plus_spare"]) if r0["total_plus_spare"] not in ("", None) else 0.0

    p = _find_sa21(_patch_surface(upload_id, "plus_10000")["rows"])
    assert float(p["total_plus_spare"]) == base_t + 6000

    m = _find_sa21(_patch_surface(upload_id, "moins_10000")["rows"])
    assert float(m["total_plus_spare"]) == base_t + 4000

    p2 = _find_sa21(_patch_surface(upload_id, "plus_10000")["rows"])
    assert float(p2["total_plus_spare"]) == base_t + 6000
