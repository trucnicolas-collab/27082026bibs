"""Iter28 — Fix Zone Saisonnière : sa_mag et all_nights.

Bugs :
1. Pour une Zone Saisonnière, `_aggregate_phasage_for_export` utilisait
   `node_sa_total(node)` qui retourne 0 pour les zones (car `is_seasonal=True`).
   Résultat : `sa_mag = 0` pour les nuits ZS-only → l'Excel affichait 2000/4000
   pour SA magasin, le PPTX slide 11 affichait 0/0.
2. `all_nights` dans l'adapter n'incluait pas les nuits au-delà de nb_nuits
   quand des Zones Saisonnières étaient placées dessus (ex: nb_nuits=16 mais
   ZS sur nuit 17-18).

Fix : dans l'aggregate, si `node.is_seasonal`, ajouter `node.seasonal_eeg`
à `sa_mag` (miroir du comportement Excel).
Fix : dans l'adapter, `max_night = max(nb_es_full, max_row_nuit, max(all_nights))`.
"""
import os
import server
from server import _aggregate_phasage_for_export


ADMIN_EMAIL = "admin@vusion.local"
ADMIN_PWD = "admin123"


def _fake_dataset(rows, zones_used=None):
    """Fabrique un dataset factice avec des allées ordinaires et des ZS."""
    zones_used = zones_used or []
    d = {
        "phasage": {
            "es": {
                "nb_nuits": 16,
                "rows": rows,
                "weeks": [4, 4, 4, 4],
            },
            "cam": {"nb_nuits": 0, "start_at_nuit": 1, "rows": []},
            "dates": {},
        },
        "recap_rows": [],
        "raw_records": [],
        "sa_install": {},
    }
    fake_summary = {
        "allees": [{"uid": "a1", "allee": "1", "es_15": 100, "es_21": 50,
                    "sa_15": 30, "sa_21": 20, "rails_es": 0, "cameras": 0}],
        "seasonal_zones": [
            {"id": "ZS1", "label": "Zone 1", "eeg": 2000, "is_seasonal": True},
            {"id": "ZS2", "label": "Zone 2", "eeg": 2000, "is_seasonal": True},
            {"id": "ZS3", "label": "Zone 3", "eeg": 2000, "is_seasonal": True},
        ],
        "store_mode": "magasin_1",
    }
    return d, fake_summary


def _run_aggregate(d, fake_summary):
    """Appelle _aggregate_phasage_for_export en monkey-patchant compute_phasage_summary."""
    orig = server.compute_phasage_summary
    server.compute_phasage_summary = lambda _d: fake_summary
    try:
        return _aggregate_phasage_for_export(d)
    finally:
        server.compute_phasage_summary = orig


def test_zone_saisonniere_populates_sa_mag_correctly():
    """Une Nuit avec 1 ZS doit avoir sa_mag=2000 (miroir du comportement Excel)."""
    rows = [{"allee": "ZS1", "nuit": 17}]
    d, s = _fake_dataset(rows)
    agg = _run_aggregate(d, s)
    b17 = agg["es_per_nuit"].get(17)
    assert b17 is not None, "Nuit 17 doit être dans es_per_nuit"
    assert b17["sa_mag"] == 2000, f"sa_mag Nuit 17 attendu 2000, obtenu {b17['sa_mag']}"


def test_zone_saisonniere_2zs_sums_sa_mag():
    """Nuit avec 2 ZS doit avoir sa_mag=4000."""
    rows = [{"allee": "ZS2", "nuit": 18}, {"allee": "ZS3", "nuit": 18}]
    d, s = _fake_dataset(rows)
    agg = _run_aggregate(d, s)
    b18 = agg["es_per_nuit"].get(18)
    assert b18["sa_mag"] == 4000, f"sa_mag Nuit 18 attendu 4000, obtenu {b18['sa_mag']}"


def test_zone_saisonniere_es_only_includes_zone_eeg():
    """La ZS contribue à eeg_only aussi (via es_21 = seasonal_eeg dans idx)."""
    rows = [{"allee": "ZS1", "nuit": 17}]
    d, s = _fake_dataset(rows)
    agg = _run_aggregate(d, s)
    b17 = agg["es_per_nuit"].get(17)
    assert b17["es_only"] == 2000, f"es_only Nuit 17 attendu 2000, obtenu {b17['es_only']}"


def test_nights_beyond_nb_nuits_are_present():
    """Nb_nuits=16 mais rows sur Nuit 17-18 → aggregate doit avoir 17, 18 dans es_per_nuit."""
    rows = [
        {"allee": "a1", "nuit": 1},
        {"allee": "ZS1", "nuit": 17},
        {"allee": "ZS2", "nuit": 18},
    ]
    d, s = _fake_dataset(rows)
    agg = _run_aggregate(d, s)
    keys = set(agg["es_per_nuit"].keys())
    assert 17 in keys and 18 in keys, f"Nuits 17-18 doivent être présentes, obtenu {sorted(keys)}"
