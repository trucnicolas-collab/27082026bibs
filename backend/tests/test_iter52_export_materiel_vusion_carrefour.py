"""
Test: nouvel export "Matériel Vusion / Matériel Carrefour"
Vérifie que la ventilation matériel par nuit respecte les règles :
- EEG ES/rails/caméras planifiés → Vusion (dans la nuit correspondante)
- SA sélectionnée dans sa_install → Vusion
- SA NON sélectionnée → Carrefour
- Support/Fixation SA → Vusion si allée a du SA, sinon Carrefour
- Allée pas dans phasage.es.rows → Carrefour
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import _split_materiel_by_recipient  # noqa: E402


def _minimal_dataset(**overrides):
    d = {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "EEG",
             "Référence": "R001", "Désignation": "ES 1.5 noir", "Quantité": 100},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "EEG",
             "Référence": "R002", "Désignation": "SA 1.5 (noir)", "Quantité": 50},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "EEG",
             "Référence": "R003", "Désignation": "SA 2.1 freezer noir", "Quantité": 20},
            {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "",
             "Référence": "R005", "Désignation": "Support individuel alu SA", "Quantité": 5},
        ],
        "phasage": {
            "es": {"nb_nuits": 2, "rows": [{"id": "r1", "allee": "1", "nuit": 1}]},
            "cam": {"nb_nuits": 1, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {
            "enabled": True, "toutes": False, "sa_15": True, "sa_21": True,
            "freezer": False, "sa_42": False, "answered": True,
            "selection": {"sa_15": ["PGC|||PLS|||1"], "sa_21": ["PGC|||PLS|||1"]},
            "seasonal": {"all": True, "zones": {}},
        },
    }
    d.update(overrides)
    return d


def test_es_produit_va_dans_vusion_nuit_correspondante():
    v, c, nuits = _split_materiel_by_recipient(_minimal_dataset())
    assert 1 in nuits
    assert ("R001", "ES 1.5 noir") in v[1]
    assert v[1][("R001", "ES 1.5 noir")] == 100.0


def test_sa_selectionnee_va_dans_vusion():
    v, c, _ = _split_materiel_by_recipient(_minimal_dataset())
    assert ("R002", "SA 1.5 (noir)") in v[1]


def test_sa_non_selectionnee_va_dans_carrefour():
    """SA 2.1 freezer non cochée → Carrefour."""
    v, c, _ = _split_materiel_by_recipient(_minimal_dataset())
    assert ("R003", "SA 2.1 freezer noir") in c
    assert c[("R003", "SA 2.1 freezer noir")] == 20.0
    # Ne doit PAS être dans Vusion
    for nuit_bucket in v.values():
        assert ("R003", "SA 2.1 freezer noir") not in nuit_bucket


def test_support_sa_va_dans_vusion_si_sa_installe():
    """Allée avec SA 1.5 sélectionnée → Support alu SA suit."""
    v, _, _ = _split_materiel_by_recipient(_minimal_dataset())
    assert ("R005", "Support individuel alu SA") in v[1]


def test_support_sa_va_dans_carrefour_si_aucun_sa():
    """Allée sans SA (rien coché) → Support alu SA va chez Carrefour."""
    d = _minimal_dataset()
    d["sa_install"] = {
        "enabled": True, "toutes": False, "sa_15": False, "sa_21": False,
        "freezer": False, "sa_42": False, "answered": True,
        "selection": {"sa_15": [], "sa_21": []},
        "seasonal": {"all": True, "zones": {}},
    }
    v, c, _ = _split_materiel_by_recipient(d)
    assert ("R005", "Support individuel alu SA") in c
    for nuit_bucket in v.values():
        assert ("R005", "Support individuel alu SA") not in nuit_bucket


def test_allee_hors_phasage_va_dans_carrefour():
    """Une allée non phaseée (pas dans es.rows) → tout va chez Carrefour."""
    d = _minimal_dataset()
    d["raw_records"].append({
        "Secteur": "PGC", "Rayon": "PLS", "N° allée": 99, "Type": "EEG",
        "Référence": "R099", "Désignation": "ES 2.1 noir", "Quantité": 30,
    })
    v, c, _ = _split_materiel_by_recipient(d)
    assert ("R099", "ES 2.1 noir") in c
    for nuit_bucket in v.values():
        assert ("R099", "ES 2.1 noir") not in nuit_bucket


def test_camera_skipped_completely():
    """Caméras (Captana) → EXCLUES des 2 onglets (suivies dans le flux dédié)."""
    d = _minimal_dataset()
    d["raw_records"].append({
        "Secteur": "PGC", "Rayon": "PLS", "N° allée": 2, "Type": "Caméra",
        "Référence": "R010", "Désignation": "Caméra noir", "Quantité": 10,
    })
    d["phasage"]["cam"] = {"nb_nuits": 1, "rows": [{"id": "c1", "allee": "2", "nuit": 1}], "start_at_nuit": 5}
    v, c, _ = _split_materiel_by_recipient(d)
    # Ne doit apparaître nulle part
    assert ("R010", "Caméra noir") not in c
    for nuit_bucket in v.values():
        assert ("R010", "Caméra noir") not in nuit_bucket


def test_captana_support_skipped():
    """Les supports Captana (Support mobilier, Support ajustable) → exclus aussi."""
    d = _minimal_dataset()
    d["raw_records"].extend([
        {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "",
         "Référence": "R100", "Désignation": "Support mobilier captana (blanc)", "Quantité": 3},
        {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "Fixation",
         "Référence": "R101", "Désignation": "Support ajustable adhésif captana", "Quantité": 2},
    ])
    v, c, _ = _split_materiel_by_recipient(d)
    for key in [("R100", "Support mobilier captana (blanc)"),
                 ("R101", "Support ajustable adhésif captana")]:
        assert key not in c, f"{key} devrait être exclu de Carrefour"
        for nuit_bucket in v.values():
            assert key not in nuit_bucket, f"{key} devrait être exclu de Vusion"


def test_aggregation_meme_reference_desig():
    """2 raw_records avec (ref, désig) identique + même allée → somme."""
    d = _minimal_dataset()
    d["raw_records"] = [
        {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "EEG",
         "Référence": "R001", "Désignation": "ES 1.5 noir", "Quantité": 30},
        {"Secteur": "PGC", "Rayon": "PLS", "N° allée": 1, "Type": "EEG",
         "Référence": "R001", "Désignation": "ES 1.5 noir", "Quantité": 70},
    ]
    v, _, _ = _split_materiel_by_recipient(d)
    assert v[1][("R001", "ES 1.5 noir")] == 100.0
