"""
Test: la config sa_install DOIT filtrer identiquement le PHASAGE et le SUIVI
(matériel/stock/nuit). Bug initial (07/09/2026) : `_materiel_context` construisait
`by_uid` depuis phasage.es.rows (qui ne contient que {id, allee, nuit}), donc les
familles SA (freezer, sa_42, etc.) apparaissaient toujours dans le suivi même
quand elles étaient décochées côté phasage.

Fix : `_materiel_context` construit désormais by_uid depuis `summary.allees`,
même source que `_build_state`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import compute_node_sa_install  # noqa: E402


def _sa_families_off_for(a: dict, cfg: dict) -> set:
    """Reproduction locale de la fonction interne à suivi_deploy.py."""
    if (a or {}).get("is_seasonal"):
        return set()
    answered = bool((cfg or {}).get("answered"))
    enabled = bool((cfg or {}).get("enabled"))
    off = set()
    if answered and not enabled:
        for fam in ("sa_15", "sa_21_std", "sa_21_freezer", "sa_42"):
            val = a.get(fam)
            if fam == "sa_21_std" and (val is None or float(val or 0) == 0):
                val = a.get("sa_21")
            if float(val or 0) > 0:
                off.add(fam)
        return off
    if not enabled:
        return off
    inst = compute_node_sa_install(a, cfg)
    if not inst.get("sa_15") and float(a.get("sa_15") or 0) > 0:
        off.add("sa_15")
    if not inst.get("sa_21") and float(a.get("sa_21_std") or a.get("sa_21") or 0) > 0:
        off.add("sa_21_std")
    if not inst.get("freezer") and float(a.get("sa_21_freezer") or 0) > 0:
        off.add("sa_21_freezer")
    if not inst.get("sa_42") and float(a.get("sa_42") or 0) > 0:
        off.add("sa_42")
    return off


def _cfg_with(freezer=False, sa_15=False, sa_21=False, sa_42=False, toutes=False):
    return {
        "enabled": True, "toutes": toutes, "sa_15": sa_15, "sa_21": sa_21,
        "freezer": freezer, "sa_42": sa_42, "answered": True,
        "selection": {"sa_15": ["PGC|||PLS|||5"], "sa_21": ["PGC|||PLS|||5"]},
        "seasonal": {"all": True, "zones": {}},
    }


# ──────────────────────────────────────────────────────────────────────
# Bug initial : by_uid vide de quantités → freezer/sa_42 non filtrés
# ──────────────────────────────────────────────────────────────────────

def test_bug_by_uid_from_rows_misses_freezer():
    """Simule l'ancien comportement : by_uid depuis phasage.es.rows.
    Sans quantités SA, aucun filtrage → freezer apparaît."""
    a_from_rows = {"id": "5__PGC__PLS", "allee": "5", "nuit": 3}  # PAS de sa_21_freezer
    cfg = _cfg_with(freezer=False, sa_15=True, sa_21=True)
    off = _sa_families_off_for(a_from_rows, cfg)
    # BUG reproduit : off est vide
    assert "sa_21_freezer" not in off, "Le bug est censé être présent SANS quantités"


def test_fix_by_uid_from_summary_filters_freezer():
    """Le fix : by_uid depuis summary.allees a bien sa_21_freezer."""
    a_from_summary = {
        "uid": "5__PGC__PLS", "allee": "5", "secteur": "PGC", "rayon": "PLS",
        "sa_15": 50, "sa_21": 120, "sa_21_std": 100, "sa_21_freezer": 20, "sa_42": 0,
    }
    cfg = _cfg_with(freezer=False, sa_15=True, sa_21=True)
    off = _sa_families_off_for(a_from_summary, cfg)
    assert off == {"sa_21_freezer"}, f"Attendu sa_21_freezer, obtenu : {off}"


def test_fix_sa_42_deselected():
    """Même logique pour SA 4.2 non sélectionné."""
    a = {"uid": "9__PGC__PLS", "sa_15": 0, "sa_21_std": 0, "sa_21_freezer": 0, "sa_42": 30}
    cfg = _cfg_with(sa_42=False)
    off = _sa_families_off_for(a, cfg)
    assert off == {"sa_42"}


def test_fix_only_selected_families_installed():
    """SA 1.5 coché mais uniquement pour l'allée 5 → allée 7 doit être exclue."""
    a5 = {"uid": "5__PGC__PLS", "allee": "5", "secteur": "PGC", "rayon": "PLS",
          "sa_15": 40, "sa_21_std": 0, "sa_21_freezer": 0, "sa_42": 0}
    a7 = {"uid": "7__PGC__PLS", "allee": "7", "secteur": "PGC", "rayon": "PLS",
          "sa_15": 30, "sa_21_std": 0, "sa_21_freezer": 0, "sa_42": 0}
    cfg = {
        "enabled": True, "toutes": False, "sa_15": True, "sa_21": False,
        "freezer": False, "sa_42": False, "answered": True,
        "selection": {"sa_15": ["PGC|||PLS|||5"], "sa_21": []},
        "seasonal": {"all": True, "zones": {}},
    }
    off5 = _sa_families_off_for(a5, cfg)
    off7 = _sa_families_off_for(a7, cfg)
    assert off5 == set(), f"Allée 5 sélectionnée : rien à exclure. Got {off5}"
    assert "sa_15" in off7, f"Allée 7 non sélectionnée : SA 1.5 doit être exclu. Got {off7}"


def test_toutes_selected_filters_nothing():
    """Case 'Toutes cochée' → aucune famille filtrée."""
    a = {"uid": "5__PGC__PLS", "sa_15": 40, "sa_21_std": 60, "sa_21_freezer": 20, "sa_42": 10}
    cfg = _cfg_with(toutes=True)
    off = _sa_families_off_for(a, cfg)
    assert off == set()


def test_non_repondu_no_filter():
    """Utilisateur n'a pas encore répondu → pas de filtrage (comportement legacy)."""
    a = {"uid": "5__PGC__PLS", "sa_21_freezer": 20}
    cfg = {"answered": False, "enabled": False, "seasonal": {"all": True, "zones": {}}}
    off = _sa_families_off_for(a, cfg)
    assert off == set()


def test_non_j_installe_pas_filters_all_sa_present():
    """User a répondu 'Non, j'installe pas' → toutes les familles SA de l'allée sont filtrées."""
    a = {"uid": "5__PGC__PLS", "sa_15": 40, "sa_21_std": 60, "sa_21_freezer": 20, "sa_42": 0}
    cfg = {"enabled": False, "answered": True, "seasonal": {"all": True, "zones": {}}}
    off = _sa_families_off_for(a, cfg)
    assert off == {"sa_15", "sa_21_std", "sa_21_freezer"}  # sa_42 pas là car qty=0
