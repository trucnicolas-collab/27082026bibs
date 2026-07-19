"""Iter31 — Fusion des Zones Saisonnières + Flèches + Signalétique dans le stock du Suivi.

Vérifie que l'affichage stock consolide correctement :
- « SA 1.5 (Zone saisonnier) » et « SA 2.1 (Zone saisonnier) » dans les SA noirs
- Les lignes « Flèche » du brut dans « ES 1.5 (noir) »
- Les rails de signalétique (1187/1320/990/650/535/1240 mm) dans « ES 1.5 » par couleur

Les autres écrans (matériel/allée) conservent les désignations séparées pour la traçabilité.
"""


def _prod_agg_from_scenario(scenario):
    """Reproduit ce que fait _materiel_par_allee : agrège les raw_records par désignation."""
    agg = {}
    for it in scenario:
        dg = it["designation"]
        if dg not in agg:
            agg[dg] = {
                "designation": dg, "type": it.get("type", ""),
                "family": it.get("family"),
                "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0,
            }
        agg[dg]["prevu"] += it["prevu"]
    return agg


def _apply_stock_fusion(prod_agg):
    """Reproduit la logique de fusion appliquée dans suivi_deploy.py."""
    _RAILS_BONUS_COLORS = [
        ("1187 mm (noir)", "noir"), ("1187 mm (blanc)", "blanc"),
        ("1240 mm (noir)", "noir"), ("1320 mm (blanc)", "blanc"),
        ("1320 mm (noir)", "noir"), ("535 mm (noir)", "noir"),
        ("650 mm (noir)", "noir"), ("990 mm (blanc)", "blanc"),
        ("990 mm (noir)", "noir"),
    ]

    def _signaletique_color(dg):
        dl = (dg or "").lower()
        for pat, col in _RAILS_BONUS_COLORS:
            if pat in dl:
                return col
        return None

    def _is_fleche_line(dg, typ):
        import unicodedata
        for s in (dg, typ):
            n = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
            if "fleche" in n:
                return True
        return False

    def _find_target(prefix, color=None):
        pref_l = prefix.lower()
        for dg in prod_agg.keys():
            dgl = dg.lower()
            if not dgl.startswith(pref_l):
                continue
            if "saisonn" in dgl:
                continue
            if color and color not in dgl:
                continue
            return dg
        return None

    def _merge_into(src_desig, tgt_desig):
        src = prod_agg.pop(src_desig, None)
        if not src:
            return
        if tgt_desig in prod_agg:
            t = prod_agg[tgt_desig]
            t["prevu"] += src["prevu"]
            t["pose"] += src["pose"]
            t["restant_a_poser"] += src["restant_a_poser"]
        else:
            src["designation"] = tgt_desig
            prod_agg[tgt_desig] = src

    # 1) ZS
    for zs_desig, prefix in (("SA 1.5 (Zone saisonnier)", "sa 1.5"),
                             ("SA 2.1 (Zone saisonnier)", "sa 2.1")):
        if zs_desig in prod_agg:
            tgt = _find_target(prefix, color="noir") or f"{prefix.upper()} (noir)"
            _merge_into(zs_desig, tgt)

    # 2) Flèches
    fleche_desigs = [dg for dg, g in prod_agg.items() if _is_fleche_line(dg, g.get("type", ""))]
    target = _find_target("es 1.5", color="noir") or "ES 1.5 (noir)"
    for dg in fleche_desigs:
        _merge_into(dg, target)

    # 3) Signalétique
    signal_by_color = {"noir": [], "blanc": []}
    for dg in list(prod_agg.keys()):
        col = _signaletique_color(dg)
        if col:
            signal_by_color[col].append(dg)
    for col, desigs in signal_by_color.items():
        if not desigs:
            continue
        tgt = _find_target("es 1.5", color=col) or f"ES 1.5 ({col})"
        for dg in desigs:
            _merge_into(dg, tgt)

    return prod_agg


def test_zs_fusion_into_noir():
    agg = _prod_agg_from_scenario([
        {"designation": "ES 1.5 (noir)", "prevu": 1773},
        {"designation": "SA 1.5 (noir)", "prevu": 1693},
        {"designation": "SA 2.1 (noir)", "prevu": 5443},
        {"designation": "SA 1.5 (Zone saisonnier)", "prevu": 1200},
        {"designation": "SA 2.1 (Zone saisonnier)", "prevu": 4800},
    ])
    out = _apply_stock_fusion(agg)
    assert "SA 1.5 (Zone saisonnier)" not in out
    assert "SA 2.1 (Zone saisonnier)" not in out
    assert out["SA 1.5 (noir)"]["prevu"] == 1693 + 1200
    assert out["SA 2.1 (noir)"]["prevu"] == 5443 + 4800


def test_fleche_fusion_into_es15_noir():
    agg = _prod_agg_from_scenario([
        {"designation": "ES 1.5 (noir)", "prevu": 1773},
        {"designation": "Flèche noir", "prevu": 600, "type": "Flèche"},
    ])
    out = _apply_stock_fusion(agg)
    assert "Flèche noir" not in out
    assert out["ES 1.5 (noir)"]["prevu"] == 1773 + 600


def test_signaletique_fusion_by_color():
    agg = _prod_agg_from_scenario([
        {"designation": "ES 1.5 (noir)", "prevu": 1773},
        {"designation": "ES 1.5 (blanc)", "prevu": 8088},
        {"designation": "Rail 1187 mm (noir)", "prevu": 5000, "type": "Rail"},
        {"designation": "Rail 990 mm (blanc)", "prevu": 1025, "type": "Rail"},
        {"designation": "Rail 650 mm (noir)", "prevu": 4115, "type": "Rail"},
    ])
    out = _apply_stock_fusion(agg)
    # Toutes les signalétiques sont absorbées
    assert "Rail 1187 mm (noir)" not in out
    assert "Rail 990 mm (blanc)" not in out
    assert "Rail 650 mm (noir)" not in out
    assert out["ES 1.5 (noir)"]["prevu"] == 1773 + 5000 + 4115  # noir : 1187 + 650
    assert out["ES 1.5 (blanc)"]["prevu"] == 8088 + 1025


def test_no_target_creates_fallback():
    """Si la désignation cible n'existe pas dans le stock, on la crée."""
    agg = _prod_agg_from_scenario([
        {"designation": "SA 1.5 (Zone saisonnier)", "prevu": 1200},
    ])
    out = _apply_stock_fusion(agg)
    assert "SA 1.5 (Zone saisonnier)" not in out
    assert out["SA 1.5 (noir)"]["prevu"] == 1200


def test_other_products_unchanged():
    """Les autres désignations restent intactes (SA 2.1 Freezer, Support broche…)."""
    agg = _prod_agg_from_scenario([
        {"designation": "SA 2.1 Freezer", "prevu": 987},
        {"designation": "Support broche 3 positions", "prevu": 16733, "type": "Fixation"},
        {"designation": "ES 1.5 (noir)", "prevu": 1773},
        {"designation": "SA 1.5 (Zone saisonnier)", "prevu": 1200},
    ])
    out = _apply_stock_fusion(agg)
    assert out["SA 2.1 Freezer"]["prevu"] == 987
    assert out["Support broche 3 positions"]["prevu"] == 16733
    # ES 1.5 (noir) : pas de flèche/signalétique dans ce scénario, valeur préservée
    assert out["ES 1.5 (noir)"]["prevu"] == 1773
