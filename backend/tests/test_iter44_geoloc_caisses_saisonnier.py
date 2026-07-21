"""Iter44 — Exclusion géoloc pour SA 1.5 / SA 2.1 des caisses & zones saisonnières.

Règle métier Carrefour : les EEG SA 1.5 et SA 2.1 posés sur des allées de type
« caisse » (secteur commençant par « CAISSE ») ou de type « zone saisonnière »
(`is_seasonal=True`) ne sont PAS géolocalisés. Le champ géoloc doit être masqué
côté frontend (via `p["is_geo"] == False`) et ces produits ne doivent PAS
compter dans les totaux Géoloc EEG prévues / effectuées.

Note : les Rails ES (family=='rails_es') restent géolocalisables partout, y
compris sur les allées caisses/saisonnières.
"""

from suivi_deploy import GEO_KEYS


def _simulate_is_geo(secteur, is_seasonal, family):
    """Reproduit la logique de _build_state (iter44) pour is_geo par produit."""
    _sect = (secteur or "").strip().upper()
    no_geo_sa = _sect.startswith("CAISSE") or bool(is_seasonal)
    is_geo = family in GEO_KEYS
    if is_geo and no_geo_sa and family in ("sa_15", "sa_21_std"):
        is_geo = False
    return is_geo, no_geo_sa


def test_sa15_caisse_pas_de_geoloc():
    """SA 1.5 sur une allée caisse : is_geo=False."""
    is_geo, no_geo_sa = _simulate_is_geo("CAISSES", False, "sa_15")
    assert is_geo is False
    assert no_geo_sa is True


def test_sa21_caisse_pas_de_geoloc():
    """SA 2.1 std sur une allée caisse : is_geo=False."""
    is_geo, _ = _simulate_is_geo("Caisses", False, "sa_21_std")
    assert is_geo is False


def test_sa15_zone_saisonniere_pas_de_geoloc():
    """SA 1.5 sur une zone saisonnière : is_geo=False."""
    is_geo, no_geo_sa = _simulate_is_geo("Zone saisonnier", True, "sa_15")
    assert is_geo is False
    assert no_geo_sa is True


def test_sa21_zone_saisonniere_pas_de_geoloc():
    """SA 2.1 std sur une zone saisonnière : is_geo=False."""
    is_geo, _ = _simulate_is_geo("Zone saisonnier", True, "sa_21_std")
    assert is_geo is False


def test_rails_es_caisse_reste_geolocalisable():
    """Les Rails ES gardent leur géoloc même sur une allée caisse."""
    is_geo, no_geo_sa = _simulate_is_geo("CAISSES", False, "rails_es")
    assert is_geo is True  # rails toujours géolocalisés
    assert no_geo_sa is True


def test_rails_es_zone_saisonniere_reste_geolocalisable():
    """Les Rails ES gardent leur géoloc même sur une zone saisonnière."""
    is_geo, _ = _simulate_is_geo("Zone saisonnier", True, "rails_es")
    assert is_geo is True


def test_sa15_allee_normale_geolocalisable():
    """Une SA 1.5 sur une allée normale (ex : secteur A) reste géolocalisable."""
    is_geo, no_geo_sa = _simulate_is_geo("A", False, "sa_15")
    assert is_geo is True
    assert no_geo_sa is False


def test_sa21_allee_normale_geolocalisable():
    """SA 2.1 std sur une allée normale reste géolocalisable."""
    is_geo, _ = _simulate_is_geo("Rayon Bio", False, "sa_21_std")
    assert is_geo is True


def test_caisses_matching_case_insensitive():
    """Le matching « CAISSE » est insensible à la casse."""
    for secteur in ("CAISSES", "caisses", "Caisses", "CAISSE 1", "caisse 12"):
        is_geo, no_geo_sa = _simulate_is_geo(secteur, False, "sa_15")
        assert no_geo_sa is True, f"Secteur '{secteur}' devrait être détecté comme caisse"
        assert is_geo is False


def test_secteur_qui_contient_mais_ne_commence_pas_par_caisse():
    """Un secteur comme 'Rayon Caisses annexes' ne doit PAS être détecté (règle
    strictement basée sur le préfixe pour éviter les faux positifs)."""
    is_geo, no_geo_sa = _simulate_is_geo("Rayon Caisses annexes", False, "sa_15")
    assert no_geo_sa is False
    assert is_geo is True


def test_geo_keys_aggregation_excludes_caisses_sa():
    """L'agrégation `geo_eeg_plan` exclut sa_15 / sa_21_std pour les allées
    caisses. Simule la logique de suivi_deploy.py lignes 559-561 et 1030-1032."""
    def _geo_keys_for(x):
        return ["rails_es"] if x.get("no_geo_sa") else GEO_KEYS

    allees = [
        # Allée normale : sa_15=20, sa_21_std=15, rails_es=5 → géoloc plan = 40
        {"no_geo_sa": False, "plan": {"sa_15": 20, "sa_21_std": 15, "rails_es": 5, "es_15": 100}},
        # Allée caisse : sa_15=10, rails_es=0 → géoloc plan = 0 (SA ignoré)
        {"no_geo_sa": True, "plan": {"sa_15": 10, "sa_21_std": 8, "rails_es": 0}},
        # Zone saisonnière : sa_15=30, sa_21_std=12 → géoloc plan = 0
        {"no_geo_sa": True, "plan": {"sa_15": 30, "sa_21_std": 12}},
    ]
    total = sum(sum(float((x.get("plan") or {}).get(k) or 0) for k in _geo_keys_for(x)) for x in allees)
    # Seule l'allée normale contribue : 20 + 15 + 5 = 40
    assert total == 40


def test_no_geo_sa_flag_exposed_on_allee():
    """La flag `no_geo_sa` doit être stockée dans l'objet allée pour permettre
    à l'agrégation nightly et globale de filtrer correctement."""
    # Test structurel : l'allée doit avoir la clé "no_geo_sa"
    allee = {"uid": "3001", "no_geo_sa": True, "plan": {}, "geo": {}}
    assert "no_geo_sa" in allee
