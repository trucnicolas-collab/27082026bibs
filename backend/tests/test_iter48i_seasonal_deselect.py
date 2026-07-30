"""iter48i — Désélection des Zones Saisonnières dans « Étiquettes SA à poser ».

Contexte :
  L'utilisateur veut pouvoir décocher les Zones Saisonnières (ZS1/ZS2/ZS3)
  dans le panneau SaInstallPanel du phasage. Deux niveaux :
    - case globale « Zone(s) saisonnière(s) » (all)
    - par zone + par type (sa_15, sa_21)

Config stockée dans `sa_install.seasonal` :
  {
    "all": bool,         // case globale (défaut True = retro-compat)
    "zones": {           // détail par zone
      "ZS1": {"sa_15": bool, "sa_21": bool},
      ...
    }
  }

Miroir Python de la logique frontend : `compute_node_sa_install` dans server.py.
"""
import pytest
from server import compute_node_sa_install


def _zs_node(zid: str, sa_15: float = 400, sa_21: float = 1600) -> dict:
    return {
        "uid": zid, "allee": zid, "is_seasonal": True,
        "sa_15": sa_15, "sa_21_std": sa_21, "sa_21": sa_21,
        "sa_21_freezer": 0, "sa_42": 0,
    }


def test_retrocompat_pas_de_config_toutes_zs_posees():
    """Sans config seasonal, comportement historique : ZS entièrement posée."""
    n = _zs_node("ZS1")
    res = compute_node_sa_install(n, {})
    assert res == {"sa_15": 400, "sa_21": 1600, "freezer": 0, "sa_42": 0}


def test_case_globale_decochee_rien_pose():
    """all=False sans override par zone → aucune SA ZS posée."""
    n = _zs_node("ZS1")
    res = compute_node_sa_install(n, {"seasonal": {"all": False, "zones": {}}})
    assert res == {"sa_15": 0, "sa_21": 0, "freezer": 0, "sa_42": 0}


def test_desactivation_zs_specifique():
    """all=True par défaut, mais ZS2 explicitement décochée (les deux types)."""
    cfg = {"seasonal": {"all": True, "zones": {
        "ZS2": {"sa_15": False, "sa_21": False},
    }}}
    assert compute_node_sa_install(_zs_node("ZS1"), cfg)["sa_15"] == 400  # gardée
    assert compute_node_sa_install(_zs_node("ZS2"), cfg)["sa_15"] == 0    # décochée
    assert compute_node_sa_install(_zs_node("ZS2"), cfg)["sa_21"] == 0
    assert compute_node_sa_install(_zs_node("ZS3"), cfg)["sa_21"] == 1600  # gardée


def test_desactivation_par_type_uniquement():
    """ZS1 : SA 1.5 décochée, SA 2.1 gardée."""
    cfg = {"seasonal": {"all": True, "zones": {"ZS1": {"sa_15": False, "sa_21": True}}}}
    r = compute_node_sa_install(_zs_node("ZS1"), cfg)
    assert r["sa_15"] == 0
    assert r["sa_21"] == 1600


def test_all_false_avec_override_partiel():
    """all=False mais ZS1 remise explicitement à True sur SA 1.5."""
    cfg = {"seasonal": {"all": False, "zones": {"ZS1": {"sa_15": True}}}}
    r = compute_node_sa_install(_zs_node("ZS1"), cfg)
    assert r["sa_15"] == 400
    # sa_21 non spécifié → suit le défaut all=False
    assert r["sa_21"] == 0


def test_config_normale_hors_zs_intacte():
    """La config seasonal n'affecte PAS les nodes non-saisonniers."""
    n = {"uid": "1__A__R1", "allee": "1", "secteur": "A", "rayon": "R1",
         "sa_15": 50, "sa_21_std": 100, "sa_21_freezer": 20, "sa_42": 10}
    # Sans enabled → aucune SA posée (hors ZS)
    cfg = {"enabled": False, "seasonal": {"all": False}}
    r = compute_node_sa_install(n, cfg)
    assert r == {"sa_15": 0, "sa_21": 0, "freezer": 0, "sa_42": 0}
    # Avec enabled + toutes → toutes posées, indépendamment de seasonal
    cfg2 = {"enabled": True, "toutes": True, "seasonal": {"all": False}}
    r2 = compute_node_sa_install(n, cfg2)
    assert r2["sa_15"] == 50
    assert r2["sa_21"] == 100
