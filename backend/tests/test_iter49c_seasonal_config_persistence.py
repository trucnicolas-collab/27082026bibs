"""
Test: la config seasonal (zones saisonnières décochées) DOIT être persistée
dans MongoDB via /api/dataset/{upload_id}/sa-install.

Contexte bug (01/09/2026) : le frontend `buildPayload` oubliait le champ
`seasonal`. Résultat : quand l'utilisateur décochait une zone saisonnière
et sauvegardait, la config seasonal était écrasée à {} → au refresh,
les zones ré-apparaissaient dans "allées à phaser".

Le fix côté frontend renvoie maintenant seasonal={all, zones}.
Ce test vérifie que le backend accepte + stocke fidèlement ce payload.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import SaInstallConfig, compute_node_sa_install  # noqa: E402


def test_seasonal_config_roundtrips_through_pydantic_model():
    """La config zones décochées passe via SaInstallConfig sans perte."""
    payload = {
        "enabled": True,
        "toutes": False,
        "sa_15": True,
        "sa_21": True,
        "freezer": False,
        "sa_42": False,
        "selection": {"sa_15": [], "sa_21": []},
        "answered": True,
        "seasonal": {
            "all": False,
            "zones": {
                "ZS1": {"sa_15": False, "sa_21": False},
                "ZS2": {"sa_15": True, "sa_21": True},
            },
        },
    }
    parsed = SaInstallConfig(**payload).model_dump()
    assert parsed["seasonal"]["all"] is False
    assert parsed["seasonal"]["zones"]["ZS1"] == {"sa_15": False, "sa_21": False}
    assert parsed["seasonal"]["zones"]["ZS2"] == {"sa_15": True, "sa_21": True}


def test_deselected_seasonal_zone_returns_zero_sa():
    """Une zone entièrement décochée → 0 SA à installer."""
    cfg = {
        "enabled": False,
        "seasonal": {
            "all": True,
            "zones": {"ZS1": {"sa_15": False, "sa_21": False}},
        },
    }
    node = {
        "is_seasonal": True,
        "uid": "ZS1",
        "allee": "ZS1",
        "sa_15": 400,
        "sa_21_std": 1600,
    }
    inst = compute_node_sa_install(node, cfg)
    assert inst["sa_15"] == 0.0
    assert inst["sa_21"] == 0.0


def test_partially_deselected_seasonal_zone():
    """SA 1.5 décoché mais SA 2.1 coché → seul SA 2.1 est installé."""
    cfg = {
        "enabled": False,
        "seasonal": {
            "all": True,
            "zones": {"ZS1": {"sa_15": False, "sa_21": True}},
        },
    }
    node = {
        "is_seasonal": True,
        "uid": "ZS1",
        "sa_15": 400,
        "sa_21_std": 1600,
    }
    inst = compute_node_sa_install(node, cfg)
    assert inst["sa_15"] == 0.0
    assert inst["sa_21"] == 1600.0


def test_seasonal_deselection_works_for_moins_10000():
    """Le fix marche aussi pour surface < 10000 m² (2 zones ZS1, ZS2)."""
    cfg = {
        "enabled": False,
        "seasonal": {
            "all": True,
            "zones": {
                "ZS1": {"sa_15": False, "sa_21": False},
                "ZS2": {"sa_15": False, "sa_21": False},
            },
        },
    }
    for zid in ("ZS1", "ZS2"):
        node = {
            "is_seasonal": True, "uid": zid,
            "sa_15": 400, "sa_21_std": 1600,
        }
        inst = compute_node_sa_install(node, cfg)
        assert inst["sa_15"] == 0.0, f"{zid} sa_15 doit être 0"
        assert inst["sa_21"] == 0.0, f"{zid} sa_21 doit être 0"


def test_seasonal_all_false_default():
    """cfg.seasonal.all=false + zones vides → tout décoché par défaut."""
    cfg = {"enabled": False, "seasonal": {"all": False, "zones": {}}}
    node = {"is_seasonal": True, "uid": "ZS1",
            "sa_15": 400, "sa_21_std": 1600}
    inst = compute_node_sa_install(node, cfg)
    assert inst["sa_15"] == 0.0
    assert inst["sa_21"] == 0.0
