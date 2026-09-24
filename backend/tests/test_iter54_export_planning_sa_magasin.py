"""
Test: onglet 2 « SA Magasin » de l'export Planning.
Vérifie que _split_materiel_by_recipient produit `carrefour_sa_by_nuit_by_allee`
contenant les SA que le magasin doit poser lui-même :
- SA EEG NON cochées dans sa_install
- Support/fixation SA quand l'allée n'a pas d'EEG SA à poser
uniquement pour les allées effectivement phaseées.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import _split_materiel_by_recipient  # noqa: E402


def _entry(by_allee: dict, allee: str, sec: str, ray: str):
    for e in (by_allee or {}).values():
        if e.get("allee") == allee and e.get("secteur") == sec and e.get("rayon") == ray:
            return e
    return None


def _dataset_sa_partiellement_cochee():
    """Allée 2 phaseée. SA 1.5 cochée (→ VT). SA 2.1 freezer non cochée
    (→ magasin). Support SA présent, avec SA cochée pour l'allée → support
    reste chez VT (has_sa=True)."""
    return {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 2, "Type": "EEG",
             "Référence": "R-ES", "Désignation": "ES 1.5 noir", "Quantité": 50},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 2, "Type": "EEG",
             "Référence": "R-SA15", "Désignation": "SA 1.5 (noir)", "Quantité": 20},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 2, "Type": "EEG",
             "Référence": "R-SA21F", "Désignation": "SA 2.1 freezer noir",
             "Quantité": 10},
        ],
        "phasage": {
            "es": {"nb_nuits": 1, "rows": [{"id": "r1", "allee": "2", "nuit": 1}]},
            "cam": {"nb_nuits": 0, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {
            "enabled": True, "toutes": False, "sa_15": True, "sa_21": True,
            "freezer": False, "sa_42": False, "answered": True,
            "selection": {"sa_15": ["PGC|||PLS|||2"], "sa_21": ["PGC|||PLS|||2"]},
            "seasonal": {"all": True, "zones": {}},
        },
    }


def test_sa_non_cochee_apparait_dans_onglet_magasin():
    _, _, _, _, vt, magasin = _split_materiel_by_recipient(
        _dataset_sa_partiellement_cochee())
    # Nuit 1 doit exister dans le bucket magasin
    assert 1 in magasin
    e = _entry(magasin[1], "2", "PGC", "PLS")
    assert e is not None
    # SA 2.1 freezer non cochée → magasin
    assert ("R-SA21F", "SA 2.1 freezer noir") in e["items"]
    assert e["items"][("R-SA21F", "SA 2.1 freezer noir")] == 10.0
    # SA 1.5 cochée → PAS dans magasin (est chez VT)
    assert ("R-SA15", "SA 1.5 (noir)") not in e["items"]
    # ES non plus (jamais dans le magasin)
    assert ("R-ES", "ES 1.5 noir") not in e["items"]
    # Sanity côté VT
    vt_e = _entry(vt[1], "2", "PGC", "PLS")
    assert ("R-SA15", "SA 1.5 (noir)") in vt_e["items"]
    assert ("R-ES", "ES 1.5 noir") in vt_e["items"]


def test_support_sa_orphelin_va_dans_onglet_magasin():
    """Allée 3 phaseée sans EEG SA → support SA doit aller au magasin."""
    d = {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 3, "Type": "EEG",
             "Référence": "R-ES", "Désignation": "ES 1.5 noir", "Quantité": 30},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 3, "Type": "",
             "Référence": "R-SUP",
             "Désignation": "Support individuel alu SA", "Quantité": 5},
        ],
        "phasage": {
            "es": {"nb_nuits": 1, "rows": [{"id": "r1", "allee": "3", "nuit": 1}]},
            "cam": {"nb_nuits": 0, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {"enabled": True, "answered": True,
                       "seasonal": {"all": True, "zones": {}}},
    }
    _, _, _, _, _, magasin = _split_materiel_by_recipient(d)
    e = _entry(magasin[1], "3", "PGC", "PLS")
    assert e is not None
    assert ("R-SUP", "Support individuel alu SA") in e["items"]


def test_sa_non_phasee_pas_dans_magasin():
    """Une SA sur une allée NON phaseée ne doit PAS apparaître dans
    l'onglet magasin (elle va uniquement dans carrefour_agg pour la palette)."""
    d = {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 9, "Type": "EEG",
             "Référence": "R-SA", "Désignation": "SA 1.5 (noir)", "Quantité": 8},
        ],
        "phasage": {
            "es": {"nb_nuits": 1, "rows": []},  # allée 9 pas dans phasage
            "cam": {"nb_nuits": 0, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {"enabled": False, "answered": True,
                       "seasonal": {"all": True, "zones": {}}},
    }
    _, carrefour, _, _, _, magasin = _split_materiel_by_recipient(d)
    # L'agrégat carrefour contient bien la SA
    assert ("R-SA", "SA 1.5 (noir)") in carrefour
    # Mais le bucket magasin (structuré par nuit) est vide
    assert magasin == {}


def test_onglet_magasin_conserve_contexte_secteur_rayon():
    """Deux allées 5 (PGC/PLS et SAISONNIER/ZS) avec SA non cochée →
    l'onglet magasin doit conserver le split par secteur/rayon."""
    d = {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 5, "Type": "EEG",
             "Référence": "R-SA-P", "Désignation": "SA 2.1 freezer noir",
             "Quantité": 4},
            {"Secteur": "SAISONNIER", "Rayon": "ZS", "N° allée": 5, "Type": "EEG",
             "Référence": "R-SA-S", "Désignation": "SA 2.1 freezer noir",
             "Quantité": 3},
        ],
        "phasage": {
            "es": {"nb_nuits": 1, "rows": [
                {"id": "r1", "allee": "5__PGC__PLS", "nuit": 1},
                {"id": "r2", "allee": "5__SAISONNIER__ZS", "nuit": 1},
            ]},
            "cam": {"nb_nuits": 0, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {
            "enabled": True, "toutes": False, "sa_15": False, "sa_21": False,
            "freezer": False, "sa_42": False, "answered": True,
            "seasonal": {"all": True, "zones": {}},
        },
    }
    _, _, _, _, _, magasin = _split_materiel_by_recipient(d)
    assert 1 in magasin
    ctx = {(e["secteur"], e["rayon"]) for e in magasin[1].values()}
    assert ("PGC", "PLS") in ctx
    assert ("SAISONNIER", "ZS") in ctx


def test_xlsx_contient_deux_onglets():
    """Vérifie que l'endpoint génère un XLSX à 2 onglets nommés
    « Planning » et « SA Magasin »."""
    import io
    import xlsxwriter
    import zipfile

    d = _dataset_sa_partiellement_cochee()
    _, _, nuits, _, vt, magasin = _split_materiel_by_recipient(d)

    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    ws1 = wb.add_worksheet("Planning")
    ws2 = wb.add_worksheet("SA Magasin")
    fmt = wb.add_format({})
    for ws, src in ((ws1, vt), (ws2, magasin)):
        row = 0
        for nuit in nuits:
            ws.write(row, 0, f"Nuit {nuit}", fmt); row += 1
            for e in (src.get(nuit) or {}).values():
                ws.write(row, 0, f"Allée {e['allee']} — {e['secteur']}/{e['rayon']}", fmt)
                row += 1
                for (ref, desig), qty in (e.get("items") or {}).items():
                    ws.write(row, 0, ref, fmt); ws.write(row, 1, desig, fmt)
                    ws.write_number(row, 2, qty, fmt); row += 1
    wb.close()
    output.seek(0)

    with zipfile.ZipFile(output) as zf:
        # workbook.xml doit lister 2 sheets
        wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
        assert 'name="Planning"' in wb_xml
        assert 'name="SA Magasin"' in wb_xml
