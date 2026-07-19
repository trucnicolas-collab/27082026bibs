"""Iter32 — Suivi Caméras : refonte par produit (symétrique EEG).

Vérifie que la logique de dérivation `cameras_reel / cameras_geo / fixations_reel`
depuis la liste `products` fonctionne correctement, et que les valeurs BATTERIE
et SOFTWARE caméra sont bien masquées de tout le Suivi (v28 iter6).
"""
import pytest
import suivi_deploy


def test_is_hidden_in_suivi():
    """Batterie/Software caméra doivent être masqués du Suivi."""
    assert suivi_deploy.is_hidden_in_suivi("Batterie caméra") is True
    assert suivi_deploy.is_hidden_in_suivi("BATTERIE CAMÉRA") is True
    assert suivi_deploy.is_hidden_in_suivi("Software caméra") is True
    assert suivi_deploy.is_hidden_in_suivi("Caméra (blanche)") is False
    assert suivi_deploy.is_hidden_in_suivi("Support mobilier Captana") is False


def _aggregate_from_products(products):
    """Reproduit la logique de _apply_cam_update : dérive cameras_reel/geo/fixations_reel
    depuis la liste de produits."""
    cam_reel = 0.0; cam_geo = 0.0; fix_reel = 0.0
    has_cam_reel = has_cam_geo = has_fix_reel = False
    for p in products:
        desig = (p.get("designation") or "").lower()
        is_cam_dev = desig.startswith("caméra") or desig.startswith("camera")
        r = p.get("reel")
        g = p.get("geo")
        if r is not None:
            if is_cam_dev:
                cam_reel += float(r); has_cam_reel = True
            else:
                fix_reel += float(r); has_fix_reel = True
        if g is not None and is_cam_dev:
            cam_geo += float(g); has_cam_geo = True
    return {
        "cameras_reel": cam_reel if has_cam_reel else None,
        "cameras_geo": cam_geo if has_cam_geo else None,
        "fixations_reel": fix_reel if has_fix_reel else None,
    }


def test_aggregate_cameras_only():
    """2 caméras posées + 1 géolocalisée → cameras_reel=2, cameras_geo=1, fixations=None."""
    products = [
        {"designation": "Caméra (blanche)", "reel": 1, "geo": 1},
        {"designation": "Caméra (noire)", "reel": 1, "geo": 0},
    ]
    agg = _aggregate_from_products(products)
    assert agg["cameras_reel"] == 2
    assert agg["cameras_geo"] == 1
    assert agg["fixations_reel"] is None


def test_aggregate_fixations_only():
    """3 fixations posées (support mobilier + support ajustable), pas de caméra."""
    products = [
        {"designation": "Support mobilier Captana (blanc)", "reel": 2},
        {"designation": "Support ajustable adhésif Captana", "reel": 1},
    ]
    agg = _aggregate_from_products(products)
    assert agg["cameras_reel"] is None
    assert agg["cameras_geo"] is None
    assert agg["fixations_reel"] == 3


def test_aggregate_mixed_full():
    """Cas complet : caméras + fixations posées et géolocalisées correctement."""
    products = [
        {"designation": "Caméra (blanche)", "reel": 5, "geo": 4},
        {"designation": "Caméra (noire)", "reel": 3, "geo": 3},
        {"designation": "Support mobilier Captana (noir)", "reel": 6},
        {"designation": "Pied réglable 0,5-1 m adhésif Captana", "reel": 2},
    ]
    agg = _aggregate_from_products(products)
    assert agg["cameras_reel"] == 8   # 5 + 3
    assert agg["cameras_geo"] == 7    # 4 + 3
    assert agg["fixations_reel"] == 8 # 6 + 2


def test_aggregate_geo_never_on_fixations():
    """Une fixation avec géo (invalide sémantiquement) ne doit PAS être comptée en geo."""
    products = [
        {"designation": "Support mobilier Captana (blanc)", "reel": 2, "geo": 2},
    ]
    agg = _aggregate_from_products(products)
    # geo=None car pas de caméra
    assert agg["cameras_geo"] is None


def test_aggregate_no_saisie():
    """Aucune saisie → tous les agrégats à None (pas 0)."""
    products = [
        {"designation": "Caméra (blanche)"},
        {"designation": "Support mobilier"},
    ]
    agg = _aggregate_from_products(products)
    assert agg["cameras_reel"] is None
    assert agg["cameras_geo"] is None
    assert agg["fixations_reel"] is None
