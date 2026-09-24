"""
Test: une allée phaseée dont 100% du matériel est « à poser par le magasin »
(aucune ES, uniquement des SA non cochées dans sa_install) doit :
- apparaître dans la liste des nuits (`nuits`)
- être vide côté VT (`vusion_by_nuit`)
- être présente dans le bucket magasin (`carrefour_sa_by_nuit_by_allee`)
Cela valide que le phasage d'une allée 100% magasin reste utile : il permet
de planifier la nuit où le magasin devra poser sa marchandise.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import _split_materiel_by_recipient  # noqa: E402


def _dataset_allee_100pct_magasin():
    """Allée 7 phaseée nuit 1, ne contient QUE des SA 2.1 freezer.
    sa_install : freezer=False → 100% pour le magasin."""
    return {
        "raw_records": [
            {"Secteur": "PGC", "Rayon": "SURGELE", "N° allée": 7, "Type": "EEG",
             "Référence": "R-SA-FRZ", "Désignation": "SA 2.1 freezer noir",
             "Quantité": 25},
        ],
        "phasage": {
            "es": {"nb_nuits": 1, "rows": [{"id": "r1", "allee": "7", "nuit": 1}]},
            "cam": {"nb_nuits": 0, "rows": [], "start_at_nuit": 5},
        },
        "sa_install": {
            "enabled": True, "toutes": False, "sa_15": False, "sa_21": False,
            "freezer": False, "sa_42": False, "answered": True,
            "seasonal": {"all": True, "zones": {}},
        },
    }


def test_allee_100pct_magasin_apparait_dans_nuits():
    _, _, nuits, _, vt, magasin = _split_materiel_by_recipient(
        _dataset_allee_100pct_magasin())
    # La nuit doit être présente même si VT n'a rien à faire
    assert 1 in nuits


def test_allee_100pct_magasin_vt_est_vide():
    _, _, _, _, vt, _ = _split_materiel_by_recipient(
        _dataset_allee_100pct_magasin())
    # Aucun matériel VT pour cette nuit
    assert vt.get(1, {}) == {}


def test_allee_100pct_magasin_est_dans_bucket_magasin():
    _, _, _, _, _, magasin = _split_materiel_by_recipient(
        _dataset_allee_100pct_magasin())
    assert 1 in magasin
    entries = list(magasin[1].values())
    assert len(entries) == 1
    e = entries[0]
    assert e["allee"] == "7"
    assert e["secteur"] == "PGC" and e["rayon"] == "SURGELE"
    assert ("R-SA-FRZ", "SA 2.1 freezer noir") in e["items"]
    assert e["items"][("R-SA-FRZ", "SA 2.1 freezer noir")] == 25.0
