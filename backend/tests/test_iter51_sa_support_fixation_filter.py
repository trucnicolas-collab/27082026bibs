"""
Test: si une allée n'a pas d'EEG SA à poser (toutes SA filtrées ou = 0),
les supports & fixations SA doivent aussi être masqués du suivi.

Règle métier (07/09/2026) : "Si dans une allée il n'y a pas d'EEG SA il
ne faut pas mettre les support et fixation SA dans cette allée car nous
n'allons pas les poser."
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from suivi_deploy import is_sa_support_fixation  # noqa: E402


# ── Identification des produits Support/Fixation SA ─────────────────────

def test_rail_minimal_adhesif_is_sa_support():
    assert is_sa_support_fixation("Rail minimal adhésif 900 mm", "Rail") is True
    assert is_sa_support_fixation("Rail minimal adh 500 mm", "") is True


def test_rail_no_easylock_is_sa_support():
    assert is_sa_support_fixation("Rail no easylock 600 mm", "Rail") is True


def test_support_individuel_alu_sa():
    assert is_sa_support_fixation("Support individuel alu SA", "") is True
    assert is_sa_support_fixation("Support alu SA blanc", "") is True


def test_vis_fixation_sa():
    assert is_sa_support_fixation("Vis fixation SA", "Fixation") is True


def test_support_broche_3_positions_is_sa_support():
    assert is_sa_support_fixation("Support broche 3 positions", "") is True


def test_pic_a_glace_is_sa_support():
    assert is_sa_support_fixation("Pic à glace", "") is True
    assert is_sa_support_fixation("Pic a glace", "") is True  # sans accent


def test_plaque_pour_pic_a_glace_is_sa_support():
    assert is_sa_support_fixation("Plaque pour pic à glace", "") is True
    assert is_sa_support_fixation("Plaque pour pic a glace", "") is True


def test_clip_vertical_is_sa_support():
    assert is_sa_support_fixation("Clip vertical", "") is True


def test_crochet_suspension_is_sa_support():
    assert is_sa_support_fixation("Crochet suspension", "") is True


def test_support_individuel_tablette_verre_is_sa_support():
    assert is_sa_support_fixation("Support individuel tablette verre", "") is True


def test_support_labels_are_case_insensitive():
    assert is_sa_support_fixation("CLIP VERTICAL", "") is True
    assert is_sa_support_fixation("  Crochet Suspension  ", "") is True


def test_rail_edgesense_is_not_sa_support():
    """Les rails EdgeSense (ES) ne doivent PAS être filtrés."""
    assert is_sa_support_fixation("Rail 900 mm noir", "Rail") is False
    assert is_sa_support_fixation("Face arrière 900 mm", "") is False
    assert is_sa_support_fixation("Vis fixation", "Fixation") is False


def test_camera_support_is_not_sa_support():
    """Les supports caméras (Captana) ne doivent PAS être classés en SA."""
    assert is_sa_support_fixation("Support mobilier captana (blanc)", "") is False
    assert is_sa_support_fixation("Support ajustable adhésif captana", "") is False


def test_eeg_products_are_not_sa_support():
    """Les EEG eux-mêmes ne sont pas des supports."""
    assert is_sa_support_fixation("ES 1.5 (noir)", "EEG") is False
    assert is_sa_support_fixation("SA 1.5 (noir)", "EEG") is False
    assert is_sa_support_fixation("SA 2.1 freezer noir", "EEG") is False


# ── Comportement dans _filter_materiel_node ─────────────────────────────

def _make_node(desigs_qty: dict, types_map: dict = None):
    return {
        "uid": "5__PGC__PLS", "allee": "5", "secteur": "PGC", "rayon": "PLS",
        "totals": dict(desigs_qty),
        "types": dict(types_map or {}),
        "elements": {},
    }


def test_filter_removes_sa_support_when_no_sa_eeg():
    """L'allée n'a pas de SA EEG (via cfg qui filtre tout) → supports SA retirés."""
    # Simule la logique du filtre in-line (pour ne pas monter tout FastAPI)
    from suivi_deploy import is_sa_support_fixation as _is_sa
    node_totals = {
        "ES 1.5 (noir)": 10,
        "Rail 900 mm noir": 4,
        "Rail minimal adhésif 900 mm": 2,   # ← doit être retiré
        "Support individuel alu SA": 1,      # ← doit être retiré
    }
    # Allée avec 0 SA (has_sa_eeg=False)
    has_sa_eeg = False
    new_totals = {}
    for desig, qty in node_totals.items():
        if not has_sa_eeg and _is_sa(desig, ""):
            continue
        new_totals[desig] = qty
    assert "ES 1.5 (noir)" in new_totals
    assert "Rail 900 mm noir" in new_totals
    assert "Rail minimal adhésif 900 mm" not in new_totals
    assert "Support individuel alu SA" not in new_totals


def test_filter_keeps_sa_support_when_sa_eeg_present():
    """L'allée a du SA EEG (has_sa_eeg=True) → supports SA conservés."""
    from suivi_deploy import is_sa_support_fixation as _is_sa
    node_totals = {
        "SA 2.1 (noir)": 8,
        "Rail minimal adhésif 900 mm": 2,
        "Support individuel alu SA": 1,
    }
    has_sa_eeg = True
    new_totals = {}
    for desig, qty in node_totals.items():
        if not has_sa_eeg and _is_sa(desig, ""):
            continue
        new_totals[desig] = qty
    assert len(new_totals) == 3
