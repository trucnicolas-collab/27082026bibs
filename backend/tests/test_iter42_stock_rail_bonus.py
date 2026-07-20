"""Iter42 — Bonus rails → ES 1.5 dans le stock du Suivi (règle commande).

Reproduit EXACTEMENT la règle du recap commande (server.build_recap_produits) :
1 rail (noir ou blanc parmi RAILS_BONUS_ES15) = +1 étiquette ES 1.5 de même
couleur. → chaque rail apparaît DEUX FOIS dans le stock : sur sa propre ligne,
ET son prévu/posé/restant à poser est ajouté à l'ES 1.5 de sa couleur.

Vérifie aussi que FLECHE_FIXED_ES15_NOIR (=600) est bien ajouté au prévu
d'ES 1.5 (noir) uniquement (pas au posé, pas au restant à poser).

Exemple utilisateur (Commande exemple.xlsx) :
- ES 1.5 (blanc) : brut 8088 + rails blanc 1025 = 9113
- ES 1.5 (noir)  : brut 1773 + flèche fixe 600 + rails noir 9115 = 11488
- Rails 1240 noir : 1420 (ligne propre)
- Rails 1320 noir : 7275 (ligne propre)
- etc. — les rails restent visibles avec leur quantité propre.
"""


def _prod_agg(items):
    """Construit prod_agg minimal reproduisant _stock_received_overview."""
    agg = {}
    for it in items:
        dg = it["designation"]
        if dg not in agg:
            agg[dg] = {
                "designation": dg, "type": it.get("type", ""),
                "family": it.get("family"),
                "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0,
            }
        agg[dg]["prevu"] += it.get("prevu", 0)
        agg[dg]["pose"] += it.get("pose", 0)
        agg[dg]["restant_a_poser"] += it.get("restant_a_poser", 0)
    return agg


def _apply_bonus(prod_agg):
    """Applique les sections 4 (bonus rails) + 5 (flèche fixe) sur prod_agg,
    en reproduisant la logique de suivi_deploy._stock_received_overview."""
    _RAILS_BONUS_COLORS = [
        ("1187 mm (noir)", "noir"), ("1187 mm (blanc)", "blanc"),
        ("1240 mm (noir)", "noir"), ("1320 mm (blanc)", "blanc"),
        ("1320 mm (noir)", "noir"), ("535 mm (noir)", "noir"),
        ("650 mm (noir)", "noir"), ("990 mm (blanc)", "blanc"),
        ("990 mm (noir)", "noir"),
    ]

    def _color(dg):
        dl = (dg or "").lower()
        for pat, col in _RAILS_BONUS_COLORS:
            if pat in dl:
                return col
        return None

    def _find_target(prefix, color):
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

    # Section 4 : bonus rails → ES 1.5 (couleur) — aligné phasage
    bonus_by_color = {
        "noir": {"prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0},
        "blanc": {"prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0},
    }
    for dg, g in prod_agg.items():
        typ_g = (g.get("type") or "").strip().lower()
        fam_g = g.get("family")
        # Aligné phasage : rail = (type=="rail") OU family=="rails_es"
        if typ_g != "rail" and fam_g != "rails_es":
            continue
        col = _color(dg)
        if col not in bonus_by_color:
            continue
        bonus_by_color[col]["prevu"] += g["prevu"]
        bonus_by_color[col]["pose"] += g["pose"]
        bonus_by_color[col]["restant_a_poser"] += g["restant_a_poser"]

    for col, b in bonus_by_color.items():
        if b["prevu"] <= 0 and b["pose"] <= 0:
            continue
        tgt_dg = _find_target("es 1.5", col) or f"ES 1.5 ({col})"
        tgt = prod_agg.get(tgt_dg)
        if tgt is None:
            tgt = {"designation": tgt_dg, "type": "", "family": "es_15",
                   "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0}
            prod_agg[tgt_dg] = tgt
        tgt["prevu"] += b["prevu"]
        tgt["pose"] += b["pose"]
        tgt["restant_a_poser"] += b["restant_a_poser"]

    # Section 5 : flèche fixe
    from server import FLECHE_FIXED_ES15_NOIR
    if FLECHE_FIXED_ES15_NOIR > 0:
        tgt_dg = _find_target("es 1.5", "noir") or "ES 1.5 (noir)"
        tgt = prod_agg.get(tgt_dg)
        if tgt is None:
            tgt = {"designation": tgt_dg, "type": "", "family": "es_15",
                   "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0}
            prod_agg[tgt_dg] = tgt
        tgt["prevu"] += FLECHE_FIXED_ES15_NOIR

    return prod_agg


def test_commande_example_es15_blanc():
    """ES 1.5 (blanc) prévu = 8088 (brut) + 1025 (rail 990 blanc) = 9113."""
    agg = _prod_agg([
        {"designation": "ES 1.5 (blanc)", "prevu": 8088, "family": "es_15"},
        {"designation": "990 mm (blanc)", "prevu": 1025, "family": "rails_es"},
    ])
    out = _apply_bonus(agg)
    assert out["ES 1.5 (blanc)"]["prevu"] == 9113
    # Rail conservé en ligne propre
    assert out["990 mm (blanc)"]["prevu"] == 1025


def test_commande_example_es15_noir_full():
    """ES 1.5 (noir) prévu = 1773 + 600 (flèche fixe) + 9115 (rails noir) = 11488.
    Somme des rails noir : 24 + 1420 + 7275 + 47 + 94 + 255 = 9115."""
    agg = _prod_agg([
        {"designation": "ES 1.5 (noir)", "prevu": 1773, "family": "es_15"},
        {"designation": "1187 mm (noir)", "prevu": 24, "family": "rails_es"},
        {"designation": "1240 mm (noir)", "prevu": 1420, "family": "rails_es"},
        {"designation": "1320 mm (noir)", "prevu": 7275, "family": "rails_es"},
        {"designation": "535 mm (noir)", "prevu": 47, "family": "rails_es"},
        {"designation": "650 mm (noir)", "prevu": 94, "family": "rails_es"},
        {"designation": "990 mm (noir)", "prevu": 255, "family": "rails_es"},
    ])
    out = _apply_bonus(agg)
    assert out["ES 1.5 (noir)"]["prevu"] == 11488
    # Tous les rails conservés en ligne propre avec leur quantité brute
    assert out["1187 mm (noir)"]["prevu"] == 24
    assert out["1240 mm (noir)"]["prevu"] == 1420
    assert out["1320 mm (noir)"]["prevu"] == 7275
    assert out["535 mm (noir)"]["prevu"] == 47
    assert out["650 mm (noir)"]["prevu"] == 94
    assert out["990 mm (noir)"]["prevu"] == 255


def test_bonus_propagates_to_pose_and_restant():
    """La pose et le reste à poser des rails s'ajoutent aussi à l'ES 1.5."""
    agg = _prod_agg([
        {"designation": "ES 1.5 (noir)", "prevu": 100, "pose": 30, "restant_a_poser": 70, "family": "es_15"},
        {"designation": "1240 mm (noir)", "prevu": 200, "pose": 80, "restant_a_poser": 120, "family": "rails_es"},
    ])
    out = _apply_bonus(agg)
    # prévu : 100 + 200 (rail) + 600 (flèche fixe) = 900
    assert out["ES 1.5 (noir)"]["prevu"] == 900
    # pose : 30 + 80 = 110 (pas de bonus flèche sur la pose)
    assert out["ES 1.5 (noir)"]["pose"] == 110
    # restant à poser : 70 + 120 = 190 (pas de bonus flèche)
    assert out["ES 1.5 (noir)"]["restant_a_poser"] == 190


def test_rails_es_creates_es15_target_if_missing():
    """Si l'ES 1.5 (couleur) n'existe pas dans le stock mais qu'il y a des rails
    de cette couleur, on crée la ligne cible avec le bonus."""
    agg = _prod_agg([
        {"designation": "990 mm (blanc)", "prevu": 500, "family": "rails_es"},
    ])
    out = _apply_bonus(agg)
    assert "ES 1.5 (blanc)" in out
    assert out["ES 1.5 (blanc)"]["prevu"] == 500
    assert out["990 mm (blanc)"]["prevu"] == 500  # rail conservé


def test_fleche_fixe_ajoutee_meme_sans_rails():
    """Sans aucun rail, ES 1.5 (noir) reçoit quand même les +600 flèche fixe."""
    agg = _prod_agg([
        {"designation": "ES 1.5 (noir)", "prevu": 1000, "family": "es_15"},
    ])
    out = _apply_bonus(agg)
    assert out["ES 1.5 (noir)"]["prevu"] == 1600
    # Le posé et le restant à poser ne sont PAS affectés par la flèche fixe
    assert out["ES 1.5 (noir)"]["pose"] == 0
    assert out["ES 1.5 (noir)"]["restant_a_poser"] == 0


def test_rail_1187_blanc_counted_by_type_even_if_not_rails_es_family():
    """(alignement phasage) « 1187 mm (blanc) » est dans RAILS_BONUS_ES15 mais
    PAS dans RAILS_ES_PATTERNS, donc son family=None. Le phasage l'inclut quand
    même dans es_15_bonus_blanc via `typ.lower() == 'rail'`. Le stock du Suivi
    doit faire pareil : filtrage sur type=='rail' OR family=='rails_es'."""
    agg = _prod_agg([
        {"designation": "ES 1.5 (blanc)", "prevu": 1000, "family": "es_15"},
        # type=rail mais pas dans RAILS_ES_PATTERNS → family serait None en prod
        {"designation": "1187 mm (blanc)", "prevu": 300, "type": "Rail", "family": None},
    ])
    out = _apply_bonus(agg)
    # ES 1.5 (blanc) prévu = 1000 + 300 (rail 1187 blanc bonus) = 1300
    assert out["ES 1.5 (blanc)"]["prevu"] == 1300
    # Le rail 1187 blanc reste visible sur sa propre ligne
    assert out["1187 mm (blanc)"]["prevu"] == 300


def test_non_rail_matching_color_pattern_not_counted():
    """Un produit dont la désignation matche accidentellement un pattern couleur
    mais qui n'est PAS un rail (type != 'rail' et family != 'rails_es') ne doit
    PAS être compté dans le bonus."""
    agg = _prod_agg([
        {"designation": "ES 1.5 (noir)", "prevu": 1000, "family": "es_15"},
        # Un produit dont le nom contient "1187 mm (noir)" mais type=Fixation
        {"designation": "Face arrière 1187 mm (noir)", "prevu": 500,
         "type": "Fixation", "family": None},
    ])
    out = _apply_bonus(agg)
    # Pas de bonus rail (uniquement flèche fixe +600)
    assert out["ES 1.5 (noir)"]["prevu"] == 1600
