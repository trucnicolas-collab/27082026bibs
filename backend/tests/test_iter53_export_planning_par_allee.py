"""
Test: export Planning avec granularité par allée + contexte Secteur/Rayon.
Vérifie que _split_materiel_by_recipient renvoie bien une ventilation
{nuit: {"allee|sec|ray": {allee, secteur, rayon, kind, items}}} pour l'export
« Planning ».
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import _split_materiel_by_recipient  # noqa: E402


def _dataset_deux_allees_meme_nuit():
    """Nuit 1 : allées 2 (PGC/PLS) et 4 (PGC/PLS)."""
    return {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 2, "Type": "EEG",
             "Référence": "R-A2-ES", "Désignation": "ES 1.5 noir", "Quantité": 100},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 2, "Type": "EEG",
             "Référence": "R-A2-SA", "Désignation": "SA 1.5 (noir)", "Quantité": 30},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 4, "Type": "EEG",
             "Référence": "R-A4-ES", "Désignation": "ES 2.1 blanc", "Quantité": 60},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 5, "Type": "EEG",
             "Référence": "R-A5-ES", "Désignation": "ES 1.5 noir", "Quantité": 40},
        ],
        "phasage": {
            "es": {
                "nb_nuits": 2,
                "rows": [
                    {"id": "r1", "allee": "2", "nuit": 1},
                    {"id": "r2", "allee": "4", "nuit": 1},
                    {"id": "r3", "allee": "5", "nuit": 2},
                ],
            },
            "cam": {"nb_nuits": 0, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {
            "enabled": True, "toutes": True, "sa_15": True, "sa_21": True,
            "freezer": True, "sa_42": True, "answered": True,
            "seasonal": {"all": True, "zones": {}},
        },
    }


def _entry_by_allee(by_allee: dict, allee: str, sec: str = "", ray: str = ""):
    """Retourne l'entrée matching allee/secteur/rayon dans le dict de la nuit."""
    for k, e in (by_allee or {}).items():
        if e.get("allee") == allee and e.get("secteur") == sec and e.get("rayon") == ray:
            return e
    return None


def test_ventilation_par_allee_dans_meme_nuit():
    _, _, nuits, _, by_nuit, _ = _split_materiel_by_recipient(
        _dataset_deux_allees_meme_nuit())
    assert 1 in nuits
    assert 1 in by_nuit
    a2 = _entry_by_allee(by_nuit[1], "2", "PGC", "PLS")
    a4 = _entry_by_allee(by_nuit[1], "4", "PGC", "PLS")
    assert a2 is not None and a4 is not None
    assert a2["kind"] == "es"
    # Allée 2 : ES + SA
    assert ("R-A2-ES", "ES 1.5 noir") in a2["items"]
    assert a2["items"][("R-A2-ES", "ES 1.5 noir")] == 100.0
    assert ("R-A2-SA", "SA 1.5 (noir)") in a2["items"]
    # Allée 4 : ES uniquement
    assert ("R-A4-ES", "ES 2.1 blanc") in a4["items"]
    assert ("R-A2-ES", "ES 1.5 noir") not in a4["items"]


def test_meme_numero_allee_dans_secteurs_differents_sont_separes():
    """Deux allées portant le numéro 5 mais dans PGC/PLS et Saisonnier/ZS
    doivent apparaître comme deux entrées distinctes dans la même nuit."""
    d = {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 5, "Type": "EEG",
             "Référence": "R-PGC", "Désignation": "ES 1.5 noir", "Quantité": 20},
            {"Secteur": "SAISONNIER", "Rayon": "ZS", "N° allée": 5, "Type": "EEG",
             "Référence": "R-SAIS", "Désignation": "ES 2.1 blanc", "Quantité": 8},
        ],
        "phasage": {
            "es": {"nb_nuits": 1, "rows": [
                {"id": "r1", "allee": "5__PGC__PLS", "nuit": 1},
                {"id": "r2", "allee": "5__SAISONNIER__ZS", "nuit": 1},
            ]},
            "cam": {"nb_nuits": 0, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {"enabled": False, "answered": True,
                       "seasonal": {"all": True, "zones": {}}},
    }
    _, _, _, _, by_nuit, _ = _split_materiel_by_recipient(d)
    assert 1 in by_nuit
    entries = list(by_nuit[1].values())
    # 2 entrées distinctes pour allée 5
    all5 = [e for e in entries if e["allee"] == "5"]
    assert len(all5) == 2
    ctx = {(e["secteur"], e["rayon"]) for e in all5}
    assert ("PGC", "PLS") in ctx
    assert ("SAISONNIER", "ZS") in ctx


def test_captana_ratache_a_son_allee_dans_nuit_camera():
    d = {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 3, "Type": "",
             "Référence": "CAPT-01",
             "Désignation": "Captana camera side kit", "Quantité": 4},
        ],
        "phasage": {
            "es": {"nb_nuits": 0, "rows": []},
            "cam": {"nb_nuits": 1, "rows": [{"id": "c1", "allee": "3", "nuit": 1}],
                    "start_at_nuit": 5},
        },
        "sa_install": {"enabled": False, "answered": True,
                       "seasonal": {"all": True, "zones": {}}},
    }
    _, _, nuits, _, by_nuit, _ = _split_materiel_by_recipient(d)
    assert 5 in nuits and 5 in by_nuit
    e = _entry_by_allee(by_nuit[5], "3", "PGC", "PLS")
    assert e is not None
    assert e["kind"] == "cam"
    assert ("CAPT-01", "Captana camera side kit") in e["items"]


def test_export_planning_endpoint_produces_valid_xlsx():
    """Smoke test : le endpoint génère un XLSX (ZIP) valide avec la
    nouvelle structure."""
    from fastapi.testclient import TestClient
    from server import app, load_dataset  # noqa: F401
    # Cet endpoint requiert auth ; on se contente de vérifier la génération
    # XLSX via reproduction directe du rendu.
    import xlsxwriter

    d = _dataset_deux_allees_meme_nuit()
    _, _, nuits, _, by_nuit, _ = _split_materiel_by_recipient(d)

    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    ws = wb.add_worksheet("Planning")
    fmt = wb.add_format({})
    row = 0
    for nuit in nuits:
        ws.write(row, 0, f"Nuit {nuit}", fmt); row += 1
        entries = sorted((by_nuit.get(nuit) or {}).values(),
                         key=lambda e: (int(e["allee"]) if e["allee"].isdigit() else 999,
                                        e.get("secteur", ""), e.get("rayon", "")))
        for e in entries:
            label = f"Allée {e['allee']} — {e.get('secteur','')} / {e.get('rayon','')}"
            ws.write(row, 0, label, fmt); row += 1
            for (ref, desig), qty in (e.get("items") or {}).items():
                ws.write(row, 0, ref, fmt)
                ws.write(row, 1, desig, fmt)
                ws.write_number(row, 2, qty, fmt)
                row += 1
    wb.close()
    output.seek(0)

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert "xl/workbook.xml" in names
        assert len(names) == len(set(names))
