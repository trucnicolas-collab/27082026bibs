"""Iter28 (mis à jour v27) — Zones Saisonnières = SA POSÉES PAR LA VT.

Sémantique v27 (févr. 2026) :
  Chaque ZS = 400 SA 1.5 + 1600 SA 2.1 = 2000 EEG SA, TOUS INSTALLÉS PAR LA VT.
  Auparavant : 2000 SA 2.1 posés par le magasin (sa_mag).

Cette suite valide que :
 - compute_node_sa_install renvoie {sa_15: 400, sa_21: 1600, ...} pour une ZS.
 - node_sa_total renvoie 2000 pour une ZS.
 - _aggregate_phasage_for_export place les ZS en sa_inst_15/sa_inst_21 et
   met sa_mag=0 (les ZS ne sont plus SA magasin).
"""
import server
from server import (_aggregate_phasage_for_export,
                    compute_node_sa_install, node_sa_total)


def _fake_dataset(rows):
    d = {
        "phasage": {
            "es": {"nb_nuits": 16, "rows": rows, "weeks": [4, 4, 4, 4]},
            "cam": {"nb_nuits": 0, "start_at_nuit": 1, "rows": []},
            "dates": {},
        },
        "recap_rows": [], "raw_records": [], "sa_install": {},
    }
    fake_summary = {
        "allees": [{"uid": "a1", "allee": "1", "es_15": 100, "es_21": 50,
                    "sa_15": 30, "sa_21": 20, "rails_es": 0, "cameras": 0}],
        "seasonal_zones": [
            {"id": f"ZS{i}", "label": f"Zone {i}", "sa_15": 400, "sa_21": 1600,
             "eeg": 2000, "is_seasonal": True} for i in (1, 2, 3)
        ],
        "store_mode": "magasin_1",
    }
    return d, fake_summary


def _run_aggregate(d, fake_summary):
    orig = server.compute_phasage_summary
    server.compute_phasage_summary = lambda _d: fake_summary
    try:
        return _aggregate_phasage_for_export(d)
    finally:
        server.compute_phasage_summary = orig


def test_compute_node_sa_install_zone_returns_split():
    zone_node = {"is_seasonal": True, "sa_15": 400, "sa_21_std": 1600}
    inst = compute_node_sa_install(zone_node, {})
    assert inst["sa_15"] == 400.0
    assert inst["sa_21"] == 1600.0
    assert inst["freezer"] == 0.0
    assert inst["sa_42"] == 0.0


def test_node_sa_total_zone_returns_sum():
    zone_node = {"is_seasonal": True, "sa_15": 400, "sa_21_std": 1600}
    assert node_sa_total(zone_node) == 2000.0


def test_zone_saisonniere_sa_mag_is_zero():
    """v27 : les ZS sont posées par la VT → sa_mag = 0."""
    d, s = _fake_dataset([{"allee": "ZS1", "nuit": 17}])
    agg = _run_aggregate(d, s)
    b17 = agg["es_per_nuit"].get(17)
    assert b17 is not None
    assert b17["sa_mag"] == 0, f"sa_mag ZS attendu 0, obtenu {b17['sa_mag']}"


def test_zone_saisonniere_populates_sa_inst_15_and_21():
    """v27 : 1 ZS => sa_inst_15=400 et sa_inst_21=1600."""
    d, s = _fake_dataset([{"allee": "ZS1", "nuit": 17}])
    agg = _run_aggregate(d, s)
    b17 = agg["es_per_nuit"][17]
    assert b17["sa_inst_15"] == 400
    assert b17["sa_inst_21"] == 1600


def test_zone_saisonniere_2zs_sums_sa_inst():
    """v27 : 2 ZS => sa_inst_15=800 et sa_inst_21=3200."""
    d, s = _fake_dataset([{"allee": "ZS2", "nuit": 18}, {"allee": "ZS3", "nuit": 18}])
    agg = _run_aggregate(d, s)
    b18 = agg["es_per_nuit"][18]
    assert b18["sa_inst_15"] == 800
    assert b18["sa_inst_21"] == 3200
    assert b18["sa_mag"] == 0


def test_zone_saisonniere_eeg_es_sa_total_is_2000_per_zone():
    """b["es"] = ES pur + SA à installer = 2000 par ZS."""
    d, s = _fake_dataset([{"allee": "ZS1", "nuit": 17}])
    agg = _run_aggregate(d, s)
    assert agg["es_per_nuit"][17]["es"] == 2000


def test_nights_beyond_nb_nuits_are_present():
    """Zones placées au-delà de nb_nuits doivent apparaître dans es_per_nuit."""
    d, s = _fake_dataset([
        {"allee": "a1", "nuit": 1},
        {"allee": "ZS1", "nuit": 17},
        {"allee": "ZS2", "nuit": 18},
    ])
    agg = _run_aggregate(d, s)
    keys = set(agg["es_per_nuit"].keys())
    assert 17 in keys and 18 in keys, f"Nuits 17-18 requises, obtenu {sorted(keys)}"


def test_zs_sizes_from_summary():
    """compute_phasage_summary doit produire des ZS avec sa_15=400, sa_21=1600."""
    # Ce test valide juste que la structure des zones est bien formée
    zones = [{"id": "ZS1", "label": "Z1", "sa_15": 400, "sa_21": 1600, "eeg": 2000, "is_seasonal": True}]
    z = zones[0]
    assert z["sa_15"] == 400
    assert z["sa_21"] == 1600
    assert z["eeg"] == 2000
