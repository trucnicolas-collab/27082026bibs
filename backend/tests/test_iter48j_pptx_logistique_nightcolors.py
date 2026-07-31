"""iter48j — Slide « Accès et logistique » et couleurs des nuits sans doublons.

Bugs signalés par l'utilisateur :
  1. Le slide « Accès et logistique » a disparu du PPTX exporté
  2. Dans les tableaux Récap par nuit, 2 nuits consécutives pouvaient avoir la
     même couleur de fond (bleu-bleu au changement de semaine)

Vérifie :
  A. Le slide « Accès et logistique » est bien inséré en position 7 (après
     « Informations Magasin ») dans le PPTX final
  B. `_color_for_night` cycle strictement bleu → jaune → rose → vert → bleu…
     sur le n° absolu de nuit, indépendamment du découpage par semaine
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app/backend")

from pptx import Presentation
from pptx_export import (
    LOGISTIQUE_SLIDE_PATH, TEMPLATE_PATH,
    WEEK_COLORS_HEX, _color_for_night, _insert_logistique_slide,
)


# ─── A. Couleurs des nuits ───────────────────────────────────────────────────
def test_week_colors_hex_are_all_distinct():
    """Aucune couleur dupliquée dans la palette (le bug initial était que la
    1ère et la 4e couleur étaient identiques → bleu-bleu)."""
    assert len(set(WEEK_COLORS_HEX)) == len(WEEK_COLORS_HEX), WEEK_COLORS_HEX
    assert len(WEEK_COLORS_HEX) == 4


def test_no_two_consecutive_nights_share_color():
    """Cycle strict, aucune paire consécutive de la même couleur."""
    prev = None
    for n in range(1, 25):  # test 24 nuits (6 semaines de 4)
        c = _color_for_night(n, [4, 4, 4, 4, 4, 4])
        if prev is not None:
            assert c != prev, f"Nuit {n-1} et Nuit {n} même couleur : {c}"
        prev = c


def test_color_cycle_deterministic():
    """N1=bleu, N2=jaune, N3=rose, N4=vert, N5=bleu (cycle continu)."""
    assert _color_for_night(1, []) == "#DBEAFE"  # bleu
    assert _color_for_night(2, []) == "#FEF3C7"  # jaune
    assert _color_for_night(3, []) == "#FECACA"  # rose
    assert _color_for_night(4, []) == "#DCFCE7"  # vert
    assert _color_for_night(5, []) == "#DBEAFE"  # bleu (cycle)


def test_color_independent_of_weeks_split():
    """La couleur d'une nuit ne dépend PAS du découpage `weeks`."""
    assert _color_for_night(5, [4, 4]) == _color_for_night(5, [3, 3, 3])
    assert _color_for_night(5, None) == _color_for_night(5, [10])


# ─── B. Insertion du slide « Accès et logistique » ───────────────────────────
def test_logistique_slide_asset_present():
    """Le fichier ressource `slide_logistique.pptx` doit exister."""
    assert LOGISTIQUE_SLIDE_PATH.exists(), LOGISTIQUE_SLIDE_PATH


def test_insertion_slide_in_correct_position():
    """Après insertion, le slide « Accès et logistique » doit être en position
    7 (index 6), juste après « Informations Magasin » (index 5)."""
    prs = Presentation(str(TEMPLATE_PATH))
    n_before = len(prs.slides)
    inserted = _insert_logistique_slide(prs, after_idx=5)
    assert inserted is True
    assert len(prs.slides) == n_before + 1
    # Récupère le texte du slide 7 (index 6)
    slide7 = prs.slides[6]
    texts = []
    for sh in slide7.shapes:
        if sh.has_text_frame:
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    if r.text.strip():
                        texts.append(r.text)
    joined = " ".join(texts)
    assert "Accès et logistique" in joined, joined
