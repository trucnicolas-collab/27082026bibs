"""Export PowerPoint — remplit le template `cr_vt_template.pptx` avec les
données d'une session. Les slides 1-7, 9, 10 ne sont pas modifiées.

Slides remplies :
- 8  : Tableau Commandes (split en 2 tables, 24×6 et 25×6)
- 11 : Tableau date global (5 × N nuits)
- 12 : Phasage EEG/Rails complet (N+2 × 8) — étend dynamiquement
- 13-16 : Phasage par semaine S1..S4 (2 tables chacune)
- 17 : Tableau date caméras (4 × N nuits cam)
- 18 : Phasage caméras (N+2 × 5)
- 19 : Détail caméras par allée (split en 2 tables, étend dynamiquement)
- 20 : Phasage full consolidé (N+3 × 10)

Style : couleurs par position de la nuit dans la semaine (cf. night_color_hex).
"""
from __future__ import annotations
import copy
import re
import copy
from datetime import datetime
from pathlib import Path
from io import BytesIO

from pptx import Presentation
from pptx.util import Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from lxml import etree

TEMPLATE_PATH = Path(__file__).parent / "templates" / "cr_vt_template.pptx"

# Marqueur de version pour debug deploy — incrémenter à chaque changement majeur.
# Visible dans le header HTTP `X-PPTX-Version` de la réponse d'export.
__PPTX_VERSION__ = "2026-02-27-v18-inclineur-short"

# Palette par position dans la semaine (alignée Excel)
WEEK_COLORS_HEX = ["#DBEAFE", "#FEF3C7", "#FECACA", "#D1FAE5"]
WHITE = "#FFFFFF"
HEADER_BG = "#1F2937"
SUBHEADER_BG = "#F3F4F6"


def _pos_in_week(nuit: int, weeks: list | None) -> int:
    if not nuit:
        return 0
    if not weeks:
        return int(nuit)
    remaining = int(nuit)
    for w in weeks:
        ww = int(w or 0)
        if remaining <= ww:
            return remaining
        remaining -= ww
    return remaining


def _color_for_night(n: int, weeks: list | None) -> str:
    if not n:
        return WHITE
    pos = _pos_in_week(n, weeks)
    if not pos:
        return WHITE
    return WEEK_COLORS_HEX[(pos - 1) % len(WEEK_COLORS_HEX)]


def _set_cell_text(cell, value, *, bold=False, italic=False, align="center", size=None, color=None, fill_rgb=None):
    """Remplace le contenu d'une cellule en préservant approximativement le
    style. On garde le premier paragraphe + run existants si présents.

    fill_rgb : tuple (r, g, b) optionnel pour la couleur de fond de la cellule.
    """
    if fill_rgb is not None:
        try:
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(*fill_rgb)
        except Exception:
            pass
    tf = cell.text_frame
    # Conserve les paragraphes/runs existants pour garder police/style si on
    # peut, sinon on rebuilde.
    if tf.paragraphs:
        p = tf.paragraphs[0]
        # Nettoie tous les autres paragraphes
        for extra_p in tf.paragraphs[1:]:
            extra_p._p.getparent().remove(extra_p._p)
        # Garde le 1er run si possible
        if p.runs:
            r = p.runs[0]
            # Supprime runs additionnels
            for extra_r in p.runs[1:]:
                extra_r._r.getparent().remove(extra_r._r)
            r.text = str(value) if value is not None else ""
        else:
            r = p.add_run()
            r.text = str(value) if value is not None else ""
        if bold:
            r.font.bold = True
        if italic:
            r.font.italic = True
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
        if align == "center":
            p.alignment = PP_ALIGN.CENTER
        elif align == "left":
            p.alignment = PP_ALIGN.LEFT
        elif align == "right":
            p.alignment = PP_ALIGN.RIGHT


def _set_cell_fill(cell, hex_color: str):
    """Définit la couleur de fond d'une cellule via XML direct (python-pptx
    n'expose pas table_cell.fill correctement pour les TableCells)."""
    if not hex_color or hex_color == WHITE:
        return
    tc = cell._tc
    tcPr = tc.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}tcPr')
    if tcPr is None:
        tcPr = etree.SubElement(tc, '{http://schemas.openxmlformats.org/drawingml/2006/main}tcPr')
    # Supprime les fills existants
    for child in list(tcPr):
        tag = etree.QName(child).localname
        if tag in ("solidFill", "noFill", "gradFill", "blipFill", "pattFill"):
            tcPr.remove(child)
    nsmap = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    fill = etree.SubElement(tcPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}solidFill')
    srgb = etree.SubElement(fill, '{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr')
    srgb.set("val", hex_color.lstrip("#").upper())
    _ = nsmap


def _clone_last_row(table):
    """Duplique la dernière ligne du tableau et l'insère à la fin.
    Permet d'étendre dynamiquement une table sans casser le style."""
    tbl = table._tbl
    rows = tbl.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}tr')
    if not rows:
        return None
    last = rows[-1]
    new = copy.deepcopy(last)
    # Vide le texte des cellules de la nouvelle ligne
    for tc in new.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}tc'):
        for p in tc.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}txBody/{http://schemas.openxmlformats.org/drawingml/2006/main}p'):
            for r in p.findall('{http://schemas.openxmlformats.org/drawingml/2006/main}r'):
                t = r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}t')
                if t is not None:
                    t.text = ""
    last.addnext(new)


def _ensure_table_size(table, n_rows: int):
    """Étend une table jusqu'à n_rows en clonant la dernière ligne."""
    while len(table.rows) < n_rows:
        _clone_last_row(table)


def _clone_last_col(table):
    """Duplique la dernière colonne du tableau (gridCol + tc dans chaque tr).
    Conserve les styles de la dernière colonne."""
    NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    tbl = table._tbl
    grid = tbl.find(f'{{{NS}}}tblGrid')
    if grid is None:
        return
    grid_cols = grid.findall(f'{{{NS}}}gridCol')
    if not grid_cols:
        return
    new_gc = copy.deepcopy(grid_cols[-1])
    grid.append(new_gc)
    for tr in tbl.findall(f'{{{NS}}}tr'):
        tcs = tr.findall(f'{{{NS}}}tc')
        if not tcs:
            continue
        new_tc = copy.deepcopy(tcs[-1])
        for p in new_tc.findall(f'.//{{{NS}}}txBody/{{{NS}}}p'):
            for r in p.findall(f'{{{NS}}}r'):
                t = r.find(f'{{{NS}}}t')
                if t is not None:
                    t.text = ""
        tr.append(new_tc)


def _ensure_table_cols(table, n_cols: int, label_cols: int = 1):
    """Étend une table jusqu'à n_cols en clonant la dernière colonne.
    Les `label_cols` premières conservent leur largeur ; les autres
    (data_cols) se partagent équitablement la somme des largeurs des
    anciennes data_cols pour rester dans la largeur totale d'origine."""
    NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    tbl = table._tbl
    grid = tbl.find(f'{{{NS}}}tblGrid')
    if grid is None:
        return
    grid_cols = grid.findall(f'{{{NS}}}gridCol')
    orig_n = len(grid_cols)
    if orig_n >= n_cols:
        return
    try:
        orig_data_total = sum(int(gc.get('w')) for gc in grid_cols[label_cols:])
    except (TypeError, ValueError):
        orig_data_total = None
    while len(table.columns) < n_cols:
        _clone_last_col(table)
    if orig_data_total is not None:
        new_grid_cols = grid.findall(f'{{{NS}}}gridCol')
        data_cols = new_grid_cols[label_cols:]
        if data_cols:
            new_w = orig_data_total // len(data_cols)
            for gc in data_cols:
                gc.set('w', str(new_w))


def _trim_table_cols(table, n_cols: int):
    """Supprime les colonnes au-delà de n_cols (gridCol + tc dans chaque tr).
    Sert à retirer les colonnes vides résiduelles du template (à droite)."""
    NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    tbl = table._tbl
    grid = tbl.find(f'{{{NS}}}tblGrid')
    if grid is None:
        return
    grid_cols = grid.findall(f'{{{NS}}}gridCol')
    if len(grid_cols) <= n_cols:
        return
    for gc in grid_cols[n_cols:]:
        grid.remove(gc)
    for tr in tbl.findall(f'{{{NS}}}tr'):
        tcs = tr.findall(f'{{{NS}}}tc')
        for tc in tcs[n_cols:]:
            tr.remove(tc)


def _remove_table_row(table, row_idx: int):
    """Supprime la ligne d'index row_idx (utile pour retirer un en-tête/bandeau)."""
    trs = table._tbl.findall(qn('a:tr'))
    if 0 <= row_idx < len(trs):
        trs[row_idx].getparent().remove(trs[row_idx])


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso


def _get_tables(slide):
    return [sh for sh in slide.shapes if sh.has_table]


def _set_col_widths_by_ratio(table, ratios: list[int]):
    """Répartit la largeur totale actuelle de la table selon `ratios`
    (un poids par colonne). Préserve la largeur totale d'origine."""
    try:
        total = sum(int(c.width) for c in table.columns)
    except (TypeError, ValueError):
        return
    s = sum(ratios) or 1
    for ci, w in enumerate(ratios):
        if ci < len(table.columns):
            table.columns[ci].width = Emu(int(total * w / s))


def _compact_layout(prs):
    """Post-traitement mise en page (gain de place) :
      - remonte le titre des slides qui contiennent un tableau,
      - réduit la police de la phrase d'avertissement / mention de bas de page
        sur toutes les slides où elle apparaît."""
    FOOT_KEYS = (
        "allées numérotées", "correspondantes sont à retrouver",
        "proprietary and confidential", "signalétique du magasin",
    )
    for slide in prs.slides:
        has_table = any(getattr(sh, "has_table", False) for sh in slide.shapes)
        try:
            title = slide.shapes.title
        except Exception:
            title = None
        for sh in slide.shapes:
            if not getattr(sh, "has_text_frame", False):
                continue
            low = (sh.text_frame.text or "").lower()
            if any(k in low for k in FOOT_KEYS):
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(7)
            if has_table and title is not None and sh == title:
                try:
                    sh.top = Emu(90000)
                except Exception:
                    pass


def _place_table(shape, left, top, width, row_h):
    """Repositionne/dimensionne le GraphicFrame d'une table pour compacter la
    mise en page (mesures reprises de la maquette de référence utilisateur) :
      - place le tableau (left, top) et fixe sa largeur totale `width`,
      - redistribue les colonnes proportionnellement pour remplir `width`,
      - applique une hauteur de ligne uniforme `row_h` (compacte).
    La hauteur totale s'adapte au nombre réel de lignes (donc au nb de nuits)."""
    try:
        shape.left = Emu(int(left))
        shape.top = Emu(int(top))
        shape.width = Emu(int(width))
        t = shape.table
        cols = list(t.columns)
        cur = [int(c.width) for c in cols]
        s = sum(cur) or 1
        for c, w in zip(cols, cur):
            c.width = Emu(int(width * w / s))
        trs = t._tbl.findall(qn('a:tr'))
        for tr in trs:
            tr.set('h', str(int(row_h)))
        shape.height = Emu(int(row_h * max(1, len(trs))))
    except Exception:
        pass


# En-têtes + ratios de largeur pour les tables "Phasage par nuit" (slide 12 +
# semaines) après éclatement de la colonne SA en SA 1.5 / 2.1 / frz (+ magasin)
# et retrait de la colonne Caméras (les caméras ont leurs propres slides).
def _phasage_headers(hide_sa_mag: bool) -> list[str]:
    base = ["Nuit", "Date", "Secteur/Rayon", "Allées", "EEG", "Rails ES",
            "SA 1.5", "SA 2.1", "SA 2.1 frz"]
    if not hide_sa_mag:
        base.append("SA magasin")
    return base


def _phasage_ratios(hide_sa_mag: bool) -> list[int]:
    base = [7, 9, 17, 20, 8, 8, 7, 7, 8]
    if not hide_sa_mag:
        base.append(8)
    return base




# ===================================================================
# Slide 8 — Commandes (split en 2 tables 24×6 et 25×6)
# ===================================================================
# Headers et largeurs pour les NOUVELLES tables 10-cols créées via add_table().
_RECAP_COL_HEADERS = [
    "Type", "Réf.", "Désignation", "Total", "Spare", "Flèche",
    "Signalétique", "Saisonnier", "Total", "Total + MOQ",
]
# Largeurs finalisées : Type 8% pour "Fixation" tienne sur une ligne partout.
_RECAP_COL_WEIGHTS = [8, 6, 28, 6, 6, 6, 11, 10, 7, 12]


def _set_recap_col_widths(table, total_emu: int):
    s = sum(_RECAP_COL_WEIGHTS)
    for ci, w in enumerate(_RECAP_COL_WEIGHTS):
        table.columns[ci].width = Emu(int(total_emu * w / s))


def _set_cell_margins_zero(cell):
    """Marges internes ultra-réduites pour maximiser l'espace texte ET
    minimiser la hauteur de ligne effective."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.set('marL', '36000')   # 0.04 inch L/R
    tcPr.set('marR', '36000')
    tcPr.set('marT', '0')       # 0 padding T/B → row height au plus près du texte
    tcPr.set('marB', '0')


def _fill_slide_8(slide, recap_rows: list):
    """27/02/2026 v9 — On SUPPRIME les 2 tables 6-cols du template et on CRÉE
    2 nouvelles tables 10-cols via slide.shapes.add_table(). Cela génère un
    XML 100 % compatible PowerPoint Desktop (comme un copier-coller Excel→PPT).
    """
    # 1) Localise les positions/tailles des 2 tables existantes pour les recréer
    old_tables = _get_tables(slide)
    if len(old_tables) < 2:
        return
    placements = []
    for gframe in old_tables[:2]:
        placements.append({
            "left": gframe.left, "top": gframe.top,
            "width": gframe.width, "height": gframe.height,
        })
    # 2) Supprime les anciennes tables
    for gframe in old_tables[:2]:
        sp = gframe._element
        sp.getparent().remove(sp)
    # 3) Filtre les lignes (exclut VCare et vides)
    rows = [r for r in recap_rows
            if r.get("kind") != "empty" and r.get("type") != "VCare"]
    # 4) Calcule la répartition rows → t1 / t2
    cap_per_table = 24
    n_t1 = min(len(rows), cap_per_table)
    rest = rows[n_t1:]
    # 5) Crée les 2 nouvelles tables — HAUTEUR = N rows × row_height_fixe
    # pour forcer des lignes très compactes (PowerPoint ignore le `h` sur tr
    # mais respecte la hauteur totale de la table).
    ROW_HEIGHT_EMU = 120000  # ≈ 0.13 inch — assez pour 7pt + padding 0
    n_rows_t1 = 1 + n_t1
    n_rows_t2 = max(1 + len(rest), 2)
    h_t1 = ROW_HEIGHT_EMU * n_rows_t1
    h_t2 = ROW_HEIGHT_EMU * n_rows_t2
    t1_shape = slide.shapes.add_table(n_rows_t1, 10,
                                       placements[0]["left"], placements[0]["top"],
                                       placements[0]["width"], h_t1)
    t2_shape = slide.shapes.add_table(n_rows_t2, 10,
                                       placements[1]["left"], placements[1]["top"],
                                       placements[1]["width"], h_t2)
    t1, t2 = t1_shape.table, t2_shape.table
    # 6) Largeurs proportionnelles
    _set_recap_col_widths(t1, placements[0]["width"])
    _set_recap_col_widths(t2, placements[1]["width"])
    # 7) Headers + data
    _write_recap_header(t1, 0)
    _write_recap_header(t2, 0)
    for i, r in enumerate(rows[:n_t1]):
        _write_recap_row(t1, i + 1, r)
    for i, r in enumerate(rest):
        _write_recap_row(t2, i + 1, r)
    # Hauteur de ligne FORCÉE — même valeur sur chaque tr ET sur la hauteur totale.
    for tbl in (t1, t2):
        for tr in tbl._tbl.findall(qn('a:tr')):
            tr.set('h', str(ROW_HEIGHT_EMU))


def _write_recap_header(table, row_idx: int):
    """Header gris/gras sur 10 cols."""
    for c, label in enumerate(_RECAP_COL_HEADERS):
        align = "left" if c < 3 else "right"
        cell = table.cell(row_idx, c)
        _set_cell_text(cell, label, bold=True, align=align, size=7,
                       fill_rgb=(0xE5, 0xE7, 0xEB))
        _set_cell_margins_zero(cell)


def _write_recap_row(table, row_idx, r):
    is_section = r.get("kind") == "section"
    if is_section:
        # Banner : on FUSIONNE les 10 cellules en une seule (comme un copier-coller
        # Excel), puis on remplit avec le nom de section + fond bleu clair.
        first = table.cell(row_idx, 0)
        last = table.cell(row_idx, 9)
        first.merge(last)
        _set_cell_text(first, (r.get("type") or ""),
                       bold=True, align="left", size=7,
                       fill_rgb=(0xDD, 0xEB, 0xF7))
        _set_cell_margins_zero(first)
        return
    vals = [
        (r.get("type", ""), "left", False),
        (r.get("reference", ""), "left", False),
        # Force la désignation "Inclineur" simple même si le dataset stocke
        # encore l'ancien texte long "Inclineur (1 par rail 1320/...)".
        ("Inclineur" if r.get("kind") == "inclineur" else r.get("designation", ""), "left", False),
        (_num(r.get("quantite")), "right", False),
        (_num(r.get("spare")), "right", False),
        (_num(r.get("fleche")), "right", False),
        (_num(r.get("signaletique")), "right", False),
        (_num(r.get("saisonnier")), "right", False),
        (_num(r.get("total_plus_spare")), "right", True),
        (("—" if r.get("total_moq") == "—" else _num(r.get("total_moq"))), "right", True),
    ]
    for c, (txt, align, bold) in enumerate(vals):
        cell = table.cell(row_idx, c)
        _set_cell_text(cell, txt, bold=bold, align=align, size=7)
        _set_cell_margins_zero(cell)


def _clear_row(table, row_idx):
    for c in range(len(table.columns)):
        _set_cell_text(table.cell(row_idx, c), "", size=8)


def _replace_nb_nuits_in_title(slide, nb_nuits: int):
    """Met à jour le titre d'une slide qui contient '(X nuits)' avec la
    bonne valeur de nb_nuits. Cherche le pattern '(<nombre> nuits)' dans
    tous les text-frames de la slide et le remplace tout en préservant
    le formatage (run par run).

    Ex: 'Tableau phasage EEG et rails par nuit (14 nuits)' →
        'Tableau phasage EEG et rails par nuit (12 nuits)' si nb_nuits=12.
    """
    if not nb_nuits or nb_nuits <= 0:
        return
    pattern = re.compile(r"\(\s*\d+\s+nuits?\s*\)")
    replacement = f"({nb_nuits} nuits)"
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        for para in sh.text_frame.paragraphs:
            # Concatène le texte du paragraphe pour détecter le pattern
            full = "".join(r.text or "" for r in para.runs)
            if not pattern.search(full):
                continue
            new_full = pattern.sub(replacement, full)
            if new_full == full:
                continue
            # On remet tout le texte sur le premier run en gardant son
            # formatage. Les runs suivants sont vidés.
            runs = list(para.runs)
            if runs:
                runs[0].text = new_full
                for r in runs[1:]:
                    r.text = ""


def _num(v):
    if v is None or v == "":
        return ""
    try:
        f = float(v)
        return f"{int(f)}" if f.is_integer() else f"{f:.2f}"
    except (ValueError, TypeError):
        return str(v)


# ===================================================================
# Slide 11 — Tableau date global (5 × N nuits)
# Lignes : [_, Date, EEG, Caméra, SA]   Colonnes : [label, Nuit 1, ..., Nuit N]
# ===================================================================
def _fill_slide_11(slide, totals_by_nuit, dates_map, weeks, all_nights: list[int]):
    tables = _get_tables(slide)
    if not tables:
        return
    _shape = tables[0]
    t = _shape.table
    # Étend/tronque le nb de colonnes pour couvrir TOUTES les nuits (plus de
    # troncature : les nuits 17-20 étaient perdues auparavant).
    needed_cols = 1 + len(all_nights)
    _ensure_table_cols(t, needed_cols, label_cols=1)
    _trim_table_cols(t, needed_cols)

    # Row 0 : header (Nuit X)
    _set_cell_text(t.cell(0, 0), "", bold=True, size=6)
    for i, n in enumerate(all_nights):
        _set_cell_text(t.cell(0, i + 1), f"Nuit {n}", bold=True, align="center", size=6)
        _set_cell_fill(t.cell(0, i + 1), _color_for_night(n, weeks))

    # Lignes : Date / EEG / SA (ligne « Caméra » retirée ; label « SA »).
    labels = ["Date", "EEG", "SA"]
    _ensure_table_size(t, 1 + len(labels))
    for li, lab in enumerate(labels):
        r = li + 1
        _set_cell_text(t.cell(r, 0), lab, bold=True, align="left", size=6)
        for i, n in enumerate(all_nights):
            tot = totals_by_nuit.get(n, {})
            if lab == "Date":
                val = _fmt_date(dates_map.get(str(n)))
            elif lab == "EEG":
                val = _num(tot.get("eeg", 0))
            else:
                val = _num(tot.get("sa", 0))
            _set_cell_text(t.cell(r, i + 1), val, size=6,
                           bold=(lab == "EEG"),
                           align="center")
            _set_cell_fill(t.cell(r, i + 1), _color_for_night(n, weeks))
    # Supprime les lignes résiduelles (ancienne ligne Caméra / SA en trop)
    while len(t.rows) > 1 + len(labels):
        last_tr = t._tbl.findall(qn('a:tr'))[-1]
        last_tr.getparent().remove(last_tr)
    # Position/dimensions compactes (bandeau fin en haut — maquette de référence)
    _place_table(_shape, 1822174, 574934, 8347544, 161670)


# ===================================================================
# Slide 12 — Phasage EEG/Rails complet (N+2 × 8) — étend
# ===================================================================
def _fill_slide_12(slide, nuit_es_data, weeks, hide_sa_mag=False):
    tables = _get_tables(slide)
    if not tables:
        return
    _shape = tables[0]
    t = _shape.table
    nights_sorted = sorted(nuit_es_data.keys())
    n_nights = len(nights_sorted)
    needed_rows = 2 + n_nights
    _ensure_table_size(t, needed_rows)
    # Colonnes cible (réf. utilisateur) : SA 1.5 gardée séparée, SA 2.1 + Freezer
    # fusionnées dans « SA 2.1 » ; colonne Caméras ajoutée. Pas de SA magasin.
    headers = ["Nuit", "Date", "Secteur/Rayon", "Allées", "EEG", "Rails ES", "SA 1.5", "SA 2.1", "Caméras"]
    ncols = len(headers)
    ratios = [13, 7, 20, 27, 7, 7, 6, 6, 7]
    _ensure_table_cols(t, ncols, label_cols=1)
    _trim_table_cols(t, ncols)
    _set_col_widths_by_ratio(t, ratios)
    _set_cell_text(t.cell(0, 0), "Récap par nuit", bold=True, align="center", size=11)
    for ci, h in enumerate(headers):
        _set_cell_text(t.cell(1, ci), h, bold=True, align="center", size=9)
    for i, n in enumerate(nights_sorted):
        r = i + 2
        d = nuit_es_data[n]
        sa_21_mix = (d.get("sa_inst_21", 0) or 0) + (d.get("sa_inst_freezer", 0) or 0)
        _set_cell_text(t.cell(r, 0), f"Nuit {n}", bold=True, size=9)
        _set_cell_text(t.cell(r, 1), _fmt_date(d.get("date")), size=9)
        _set_cell_text(t.cell(r, 2), d.get("sr", ""), align="left", size=8)
        _set_cell_text(t.cell(r, 3), d.get("allees_str", ""), align="left", size=8)
        _set_cell_text(t.cell(r, 4), _num(d.get("eeg", 0)), bold=True, size=9)
        _set_cell_text(t.cell(r, 5), _num(d.get("rails_es", 0)), size=9)
        _set_cell_text(t.cell(r, 6), _num(d.get("sa_inst_15", 0) or ""), size=9)
        _set_cell_text(t.cell(r, 7), _num(sa_21_mix or ""), size=9)
        _set_cell_text(t.cell(r, 8), _num(d.get("cam", 0) or ""), size=9)
        color = _color_for_night(n, weeks)
        for ci in range(ncols):
            _set_cell_fill(t.cell(r, ci), color)
    # Supprime les lignes vides finales (au-delà de needed_rows)
    while len(t.rows) > needed_rows:
        last_tr = t._tbl.findall(qn('a:tr'))[-1]
        last_tr.getparent().remove(last_tr)
    # Position/dimensions compactes (maquette de référence)
    _place_table(_shape, 666206, 983106, 10115008, 280000)


# ===================================================================
# Slides 13-16 — Par semaine : tableau détaillé (Nuit/Date/SR/Allées/EEG/
# Rails ES + colonnes SA à installer dynamiques) + ligne « Sous-total S{n} ».
# ===================================================================
def _fill_slide_week(slide, week_index: int, week_nights: list[int],
                     nuit_es_data, totals_by_nuit, dates_map, weeks, hide_sa_mag=False):
    tables = _get_tables(slide)
    if not tables:
        return
    # On garde la table détaillée (plus de colonnes) et on supprime l'éventuelle
    # petite table transposée du template.
    shapes_sorted = sorted(tables, key=lambda sh: len(sh.table.columns), reverse=True)
    t_shape = shapes_sorted[0]
    t = t_shape.table
    for sh in shapes_sorted[1:]:
        sh._element.getparent().remove(sh._element)
    _remove_table_row(t, 0)  # retire l'éventuel bandeau/en-tête noir du template

    # Colonnes SA à installer dynamiques PAR SEMAINE : on n'affiche que celles
    # qui ont des SA à poser sur les nuits de CETTE semaine. « SA » (magasin,
    # hors phasage) affichée pour info en italique si présente cette semaine.
    _wk = [nuit_es_data.get(n, {}) for n in week_nights]
    tot15 = sum((d.get("sa_inst_15") or 0) for d in _wk)
    tot21 = sum((d.get("sa_inst_21") or 0) for d in _wk)
    totfz = sum((d.get("sa_inst_freezer") or 0) for d in _wk)
    totmag = sum((d.get("sa_mag") or 0) for d in _wk)
    sa_cols = []  # (header, key, italic)
    if tot15 > 0:
        sa_cols.append(("SA 1.5", "sa_inst_15", False))
    if tot21 > 0:
        sa_cols.append(("SA 2.1", "sa_inst_21", False))
    if totfz > 0:
        sa_cols.append(("SA 2.1 frz", "sa_inst_freezer", False))
    if totmag > 0:
        sa_cols.append(("SA", "sa_mag", True))

    headers = ["Nuit", "Date", "Secteur/Rayon", "Allées", "EEG", "Rails ES"] + [c[0] for c in sa_cols]
    ncols = len(headers)
    ratios = [7, 9, 20, 22, 8, 8] + [7] * len(sa_cols)
    n_data = len(week_nights)
    needed = 1 + n_data + 1  # header + nuits + sous-total
    _ensure_table_size(t, needed)
    _ensure_table_cols(t, ncols, label_cols=1)
    _trim_table_cols(t, ncols)
    _set_col_widths_by_ratio(t, ratios)

    for ci, h in enumerate(headers):
        _set_cell_text(t.cell(0, ci), h, bold=True, align="center", size=9)

    sub = {"eeg": 0, "rails_es": 0}
    for c in sa_cols:
        sub[c[1]] = 0
    for i, n in enumerate(week_nights):
        r = i + 1
        d = nuit_es_data.get(n, {})
        _set_cell_text(t.cell(r, 0), f"Nuit {n}", bold=True, size=9)
        _set_cell_text(t.cell(r, 1), _fmt_date(d.get("date") or dates_map.get(str(n))), size=9)
        _set_cell_text(t.cell(r, 2), d.get("sr", ""), align="left", size=8)
        _set_cell_text(t.cell(r, 3), d.get("allees_str", ""), align="left", size=8)
        eeg = int(round(d.get("eeg", 0) or 0)); rails = int(round(d.get("rails_es", 0) or 0))
        _set_cell_text(t.cell(r, 4), _num(eeg), bold=True, size=9)
        _set_cell_text(t.cell(r, 5), _num(rails), size=9)
        sub["eeg"] += eeg; sub["rails_es"] += rails
        for j, (h, key, ital) in enumerate(sa_cols):
            v = int(round(d.get(key, 0) or 0))
            sub[key] += v
            _set_cell_text(t.cell(r, 6 + j), _num(v or ""), size=9, italic=ital,
                           color=("#6B7280" if ital else None))
        color = _color_for_night(n, weeks)
        for ci in range(ncols):
            _set_cell_fill(t.cell(r, ci), color)

    # Ligne « Sous-total S{n} »
    sr = 1 + n_data
    _set_cell_text(t.cell(sr, 0), f"Sous-total S{week_index}", bold=True, align="left", size=9)
    _set_cell_text(t.cell(sr, 1), "", size=9)
    _set_cell_text(t.cell(sr, 2), "", size=9)
    _set_cell_text(t.cell(sr, 3), "", size=9)
    _set_cell_text(t.cell(sr, 4), _num(sub["eeg"]), bold=True, size=9)
    _set_cell_text(t.cell(sr, 5), _num(sub["rails_es"]), bold=True, size=9)
    for j, (h, key, ital) in enumerate(sa_cols):
        _set_cell_text(t.cell(sr, 6 + j), _num(sub[key] or ""), bold=True, size=9, italic=ital,
                       color=("#6B7280" if ital else None))
    for ci in range(ncols):
        _set_cell_fill(t.cell(sr, ci), "F3F4F6")

    while len(t.rows) > needed:
        last_tr = t._tbl.findall(qn('a:tr'))[-1]
        last_tr.getparent().remove(last_tr)
    # Position/dimensions : bloc en haut à droite, compact (réf.)
    _place_table(t_shape, 5850000, 300000, 6050000, 215000)


# ===================================================================
# Slide 17 — Tableau date caméras (4 × N)
# ===================================================================
def _fill_slide_17(slide, totals_by_nuit, dates_map, cam_nights: list[int], weeks):
    tables = _get_tables(slide)
    if not tables:
        return
    _shape = tables[0]
    t = _shape.table
    # Étend dynamiquement le tableau pour accueillir toutes les nuits caméras
    # (1 colonne label + N colonnes nuits). Avant : tronqué à cur_cols-1 nuits.
    _ensure_table_cols(t, 1 + len(cam_nights))
    _trim_table_cols(t, 1 + len(cam_nights))
    cur_cols = len(t.columns)
    nights = cam_nights[: cur_cols - 1]
    _set_cell_text(t.cell(0, 0), "", size=11)
    for i, n in enumerate(nights):
        _set_cell_text(t.cell(0, i + 1), f"Nuit {n}", bold=True, align="center", size=12)
        _set_cell_fill(t.cell(0, i + 1), _color_for_night(n, weeks))
    # Lignes : Date / Caméra (ligne « EEG » retirée — réf. utilisateur).
    labels = ["Date", "Caméra"]
    _ensure_table_size(t, 1 + len(labels))
    for li, lab in enumerate(labels):
        r = li + 1
        _set_cell_text(t.cell(r, 0), lab, bold=True, align="left", size=11)
        for i, n in enumerate(nights):
            tot = totals_by_nuit.get(n, {})
            if lab == "Date":
                val = _fmt_date(dates_map.get(str(n)))
            else:
                val = _num(tot.get("cam", 0))
            _set_cell_text(t.cell(r, i + 1), val, align="center", size=11)
            _set_cell_fill(t.cell(r, i + 1), _color_for_night(n, weeks))
    # Supprime les lignes résiduelles du template (au-delà de 1 + labels)
    while len(t.rows) > 1 + len(labels):
        last_tr = t._tbl.findall(qn('a:tr'))[-1]
        last_tr.getparent().remove(last_tr)
    # Position/dimensions compactes (bandeau — maquette de référence)
    _place_table(_shape, 1952045, 624169, 7461250, 187000)


# ===================================================================
# Slide 18 — Phasage caméras (N+2 × 5)
# ===================================================================
def _fill_slide_18(slide, nuit_cam_data, weeks):
    tables = _get_tables(slide)
    if not tables:
        return
    _shape = tables[0]
    t = _shape.table
    nights = sorted(nuit_cam_data.keys())
    needed = 2 + len(nights)
    _ensure_table_size(t, needed)
    _trim_table_cols(t, 5)  # retire la colonne vide résiduelle à droite
    _set_cell_text(t.cell(0, 0), "Récap par nuit", bold=True, align="center", size=12)
    for ci, h in enumerate(["Nuit", "Date", "Secteur/Rayon", "Allées", "Caméras"]):
        _set_cell_text(t.cell(1, ci), h, bold=True, size=10)
    for i, n in enumerate(nights):
        r = i + 2
        d = nuit_cam_data[n]
        _set_cell_text(t.cell(r, 0), f"Nuit {n}", bold=True, size=10)
        _set_cell_text(t.cell(r, 1), _fmt_date(d.get("date")), size=10)
        _set_cell_text(t.cell(r, 2), d.get("sr", ""), align="left", size=9)
        _set_cell_text(t.cell(r, 3), d.get("allees_str", ""), align="left", size=9)
        _set_cell_text(t.cell(r, 4), _num(d.get("cam", 0)), bold=True, size=10)
        color = _color_for_night(n, weeks)
        for ci in range(5):
            _set_cell_fill(t.cell(r, ci), color)
    # Supprime les lignes résiduelles éventuelles + compactage/position (réf.)
    while len(t.rows) > needed:
        last_tr = t._tbl.findall(qn('a:tr'))[-1]
        last_tr.getparent().remove(last_tr)
    _place_table(_shape, 718456, 1403335, 9975669, 280000)


# ===================================================================
# Slide 19 — Détail caméras par allée (split en 2 tables 27×2)
# ===================================================================
def _fill_slide_19(slide, detail_rows, weeks=None):
    """Détail caméras par allée. Rows = list[(nuit, allee, elems_str)].
    Couleur de fond par nuit (cohérence visuelle avec le reste du PPTX).
    Pas de bandeau violet interne — le titre est déjà la title de slide."""
    tables = _get_tables(slide)
    if len(tables) < 2:
        return
    t1, t2 = tables[0].table, tables[1].table
    # On utilise row 0 de t1 comme HEADER (Allées | N° Elements), data depuis
    # row 1 — cohérent avec le rendu cible (pas de double titre).
    DATA_OFFSET_T1 = 1
    cap1 = len(t1.rows) - DATA_OFFSET_T1
    cap2 = len(t2.rows)
    needed = len(detail_rows)
    if needed > cap1 + cap2:
        _ensure_table_size(t2, needed - cap1)
        cap2 = len(t2.rows)
    # Header gris/gras à la place de l'ancien bandeau violet
    header_fill = (0xE5, 0xE7, 0xEB)
    _set_cell_text(t1.cell(0, 0), "Allées", bold=True, align="left",
                   size=8, fill_rgb=header_fill)
    _set_cell_text(t1.cell(0, 1), "N° Elements", bold=True, align="left",
                   size=8, fill_rgb=header_fill)

    def _row_color(n: int) -> str | None:
        if not n or n >= 9999 or not weeks:
            return None
        return _color_for_night(n, weeks)

    def _hex_to_rgb(hx: str):
        hx = hx.lstrip("#")
        return (int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16))

    for i in range(min(cap1, needed)):
        n, allee, elems = detail_rows[i]
        color = _row_color(n)
        fill = _hex_to_rgb(color) if color else None
        _set_cell_text(t1.cell(DATA_OFFSET_T1 + i, 0), allee,
                       bold=False, align="left", size=8, fill_rgb=fill)
        _set_cell_text(t1.cell(DATA_OFFSET_T1 + i, 1), elems,
                       align="left", size=7, fill_rgb=fill)
    rest = detail_rows[cap1:]
    for i in range(min(cap2, len(rest))):
        n, allee, elems = rest[i]
        color = _row_color(n)
        fill = _hex_to_rgb(color) if color else None
        _set_cell_text(t2.cell(i, 0), allee, bold=False, align="left",
                       size=8, fill_rgb=fill)
        _set_cell_text(t2.cell(i, 1), elems, align="left", size=7, fill_rgb=fill)
    # Vide les cellules non utilisées (sans fond)
    for i in range(max(0, needed - cap1), cap2):
        _set_cell_text(t2.cell(i, 0), "", size=8)
        _set_cell_text(t2.cell(i, 1), "", size=8)
    # Hauteur de ligne compacte uniforme
    for tbl in (t1, t2):
        for tr in tbl._tbl.findall(qn('a:tr')):
            tr.set('h', '180000')


# ===================================================================
# Slide 20 — Phasage full consolidé (N+3 × 10)
# ===================================================================
def _fill_slide_20(slide, nuit_es_data, nuit_cam_data, dates_map, weeks):
    tables = _get_tables(slide)
    if not tables:
        return
    t = tables[0].table
    all_n = sorted(set(nuit_es_data.keys()) | set(nuit_cam_data.keys()))
    # 3 lignes d'en-tête + N nuits + 1 ligne TOTAL
    needed = 3 + len(all_n) + 1
    _ensure_table_size(t, needed)
    _set_cell_text(t.cell(0, 0), "Phasage full — Planning consolidé EEG + Caméras",
                   bold=True, align="center", size=11)
    _set_cell_text(t.cell(1, 0), "Phasage étiquettes et rails", bold=True, align="center", size=9)
    _set_cell_text(t.cell(1, 5), "Nuit", bold=True, align="center", size=9)
    _set_cell_text(t.cell(1, 7), "Phasage caméras", bold=True, align="center", size=9)
    subs = ["Allées", "ES", "Rails ES", "SA posées", "Secteur/Rayon",
            "Nuit", "Date", "Secteur/Rayon", "Allées", "Caméras"]
    for ci, s in enumerate(subs):
        _set_cell_text(t.cell(2, ci), s, bold=True, size=8)
    # Data — police plus compacte pour faire tenir toutes les nuits dans la slide
    tot_es = tot_rails = tot_sa = tot_cam = 0
    for i, n in enumerate(all_n):
        r = i + 3
        es = nuit_es_data.get(n, {})
        cam = nuit_cam_data.get(n, {})
        _set_cell_text(t.cell(r, 0), es.get("allees_str", ""), align="left", size=7)
        _set_cell_text(t.cell(r, 1), _num(es.get("eeg", "")), size=8)
        _set_cell_text(t.cell(r, 2), _num(es.get("rails_es", "")), size=8)
        _set_cell_text(t.cell(r, 3), _num(es.get("sa", "")), size=8)
        _set_cell_text(t.cell(r, 4), es.get("sr", ""), align="left", size=7)
        _set_cell_text(t.cell(r, 5), str(n), bold=True, size=9)
        _set_cell_text(t.cell(r, 6), _fmt_date(dates_map.get(str(n))), size=8)
        _set_cell_text(t.cell(r, 7), cam.get("sr", ""), align="left", size=7)
        _set_cell_text(t.cell(r, 8), cam.get("allees_str", ""), align="left", size=7)
        _set_cell_text(t.cell(r, 9), _num(cam.get("cam", "")), size=8)
        color = _color_for_night(n, weeks)
        for ci in range(10):
            _set_cell_fill(t.cell(r, ci), color)
        # Cumul TOTAL
        for v, key in ((es.get("eeg"), "es"), (es.get("rails_es"), "rails"),
                       (es.get("sa"), "sa"), (cam.get("cam"), "cam")):
            try:
                f = float(v) if v not in (None, "") else 0
            except (ValueError, TypeError):
                f = 0
            if key == "es":
                tot_es += f
            elif key == "rails":
                tot_rails += f
            elif key == "sa":
                tot_sa += f
            else:
                tot_cam += f
    # Ligne TOTAL (réécrit la dernière row pour neutraliser les valeurs
    # héritées du template — bug 26/02/2026)
    total_row = 3 + len(all_n)
    _set_cell_text(t.cell(total_row, 0), "TOTAL", bold=True, align="left", size=9)
    _set_cell_text(t.cell(total_row, 1), _num(int(tot_es)), bold=True, size=9)
    _set_cell_text(t.cell(total_row, 2), _num(int(tot_rails)), bold=True, size=9)
    _set_cell_text(t.cell(total_row, 3), _num(int(tot_sa)), bold=True, size=9)
    _set_cell_text(t.cell(total_row, 4), "", size=9)
    _set_cell_text(t.cell(total_row, 5), f"{len(all_n)} nuits", bold=True, size=9)
    _set_cell_text(t.cell(total_row, 6), "", size=9)
    _set_cell_text(t.cell(total_row, 7), "", size=9)
    _set_cell_text(t.cell(total_row, 8), "", size=9)
    _set_cell_text(t.cell(total_row, 9), _num(int(tot_cam)), bold=True, size=9)
    # Vide les rows résiduelles éventuelles (si template a + de rows que prévu)
    for r in range(total_row + 1, len(t.rows)):
        for ci in range(10):
            _set_cell_text(t.cell(r, ci), "", size=8)
    # Force des hauteurs de ligne réduites pour faire tenir tout dans la slide
    # (cy en EMU : 240000 ≈ 0.25 inch ≈ ligne compacte)
    for tr in t._tbl.findall(qn('a:tr')):
        tr.set('h', '240000')


# ===================================================================
# Plans wifi — insertion d'images plein cadre dans la/les slide(s)
# "Plan wifi magasin" (jusqu'à 2 plans → 2 slides).
# ===================================================================
def _find_wifi_slide_indices(prs) -> list[int]:
    """Retourne les index de TOUTES les slides dont un texte contient 'plan wifi'.
    Le template contient 2 telles slides : la principale + une slide de réserve
    (en fin de deck) qui sera soit remplie (2e plan), soit supprimée."""
    out: list[int] = []
    for i, s in enumerate(prs.slides):
        for sh in s.shapes:
            try:
                if sh.has_text_frame and "plan wifi" in sh.text_frame.text.strip().lower():
                    out.append(i)
                    break
            except Exception:
                continue
    return out


def _fit_contain(img_w: int, img_h: int, box_w: int, box_h: int) -> tuple[int, int]:
    """Dimensions (w, h) pour contenir l'image dans la box en gardant le ratio."""
    if img_w <= 0 or img_h <= 0:
        return box_w, box_h
    scale = min(box_w / img_w, box_h / img_h)
    return int(img_w * scale), int(img_h * scale)


def _add_picture_fullframe(slide, image_bytes: bytes, slide_w: int, slide_h: int) -> None:
    """Ajoute l'image centrée, mise à l'échelle pour occuper au maximum la zone
    sous le titre (plein cadre, ratio préservé)."""
    try:
        from PIL import Image
        with Image.open(BytesIO(image_bytes)) as im:
            iw, ih = im.size
    except Exception:
        iw, ih = 0, 0
    margin = 228600           # ~0.25 pouce
    top_area = 1737360        # sous le titre "Plan wifi magasin"
    box_w = int(slide_w - 2 * margin)
    box_h = int(slide_h - top_area - margin)
    w, h = _fit_contain(iw, ih, box_w, box_h)
    left = int((slide_w - w) / 2)
    top = int(top_area + (box_h - h) / 2)
    slide.shapes.add_picture(BytesIO(image_bytes), left, top, width=w, height=h)


def _move_slide(prs, from_idx: int, to_idx: int) -> None:
    """Déplace une slide EXISTANTE (par réordonnancement du sldIdLst).
    N'ajoute aucune partie → aucun risque de collision de nom (contrairement à
    add_slide après suppression de slides)."""
    xml_slides = prs.slides._sldIdLst
    ids = list(xml_slides)
    el = ids[from_idx]
    xml_slides.remove(el)
    xml_slides.insert(to_idx, el)


def _insert_wifi_plans(prs, wifi_plans: list | None) -> None:
    """Insère 0, 1 ou 2 plans wifi (images) dans la/les slide(s) 'Plan wifi
    magasin'. Le template fournit 2 slides wifi (principale + réserve en fin) :
      - 0 plan  → supprime la réserve (slide principale laissée vide)
      - 1 plan  → remplit la principale, supprime la réserve
      - 2 plans → remplit les deux, la réserve est déplacée juste après la principale
    On ne crée JAMAIS de slide à l'exécution (uniquement remplir/déplacer/supprimer)."""
    plans = [p for p in (wifi_plans or []) if p][:2]
    idxs = _find_wifi_slide_indices(prs)
    if not idxs:
        return
    slide_w, slide_h = int(prs.slide_width), int(prs.slide_height)
    primary = idxs[0]
    reserve = idxs[-1] if len(idxs) >= 2 else None
    n = len(plans)
    if n >= 1:
        _add_picture_fullframe(prs.slides[primary], plans[0], slide_w, slide_h)
    if n >= 2 and reserve is not None:
        _add_picture_fullframe(prs.slides[reserve], plans[1], slide_w, slide_h)
        _move_slide(prs, reserve, primary + 1)
    elif reserve is not None:
        # 0 ou 1 plan → on retire la slide de réserve inutilisée
        _delete_slide(prs, reserve)



# ===================================================================
# Public entry point
# ===================================================================
def build_pptx(d: dict, *, aggregate_fn, recap_rows: list, summary: dict | None = None,
               detail_cam_rows: list[tuple[int, str, str]] | None = None,
               wifi_plans: list | None = None) -> bytes:
    """Génère le PowerPoint complet à partir des données.

    aggregate_fn(d) → dict avec clés : nuit_es (n -> {date, sr, allees_str, eeg, rails_es, sa, cam}),
    nuit_cam, dates_map, weeks, totals_by_nuit (n -> {eeg, cam, sa}), all_nights, cam_nights.
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template PowerPoint introuvable : {TEMPLATE_PATH}")
    agg = aggregate_fn(d)
    prs = Presentation(str(TEMPLATE_PATH))
    slides = prs.slides
    # NOTE (16/06/2026) : insertion de la slide "Accès et logistique" en
    # position 7 → toutes les slides à remplir sont décalées de +1.
    # Slide 9 (ex-8) = Commandes / 12 (ex-11) = Tableau date global / etc.
    # NOTE (17/06/2026) : la slide 7 a été re-liée au layout
    # `CONTENT 1 Column - Color` (FDF6E3) directement dans le template,
    # pour matcher exactement le rendu PPTX fourni par l'utilisateur
    # (fond crème, titre noir, pas de formes dorées).
    # Slide 9 (index 8)
    if len(slides) >= 9:
        _fill_slide_8(slides[8], recap_rows)
    # Nb nuits dynamiques pour les titres "(N nuits)"
    nb_nuits_eeg = len(agg.get("all_nights") or [])
    nb_nuits_cam = len(agg.get("cam_nights") or [])
    # Slide 12 (index 11)
    if len(slides) >= 12:
        _replace_nb_nuits_in_title(slides[11], nb_nuits_eeg)
        _fill_slide_11(slides[11], agg["totals_by_nuit"], agg["dates_map"],
                       agg["weeks"], agg["all_nights"])
    # Slide 13 (index 12)
    if len(slides) >= 13:
        _replace_nb_nuits_in_title(slides[12], nb_nuits_eeg)
        _fill_slide_12(slides[12], agg["nuit_es"], agg["weeks"],
                       hide_sa_mag=agg.get("hide_sa_mag", False))
    # Slides 14-17 (ex-13-16) = semaines S1..S4
    weeks_list = agg["weeks"] or []
    # Indices des slides semaine dans le template (0-based)
    WEEK_SLIDE_INDICES = [13, 14, 15, 16]  # S1, S2, S3, S4
    cursor = 1
    used_week_slides = set()
    for wi, w in enumerate(weeks_list[:4]):
        ww = int(w or 0)
        if ww <= 0:
            continue
        week_nights = list(range(cursor, cursor + ww))
        cursor += ww
        slide_idx = WEEK_SLIDE_INDICES[wi]
        if slide_idx < len(slides):
            _fill_slide_week(slides[slide_idx], wi + 1, week_nights,
                             agg["nuit_es"], agg["totals_by_nuit"],
                             agg["dates_map"], weeks_list,
                             hide_sa_mag=agg.get("hide_sa_mag", False))
            used_week_slides.add(slide_idx)
    # Slide 18 (index 17) = Tableau date caméras
    if len(slides) >= 18 and agg["cam_nights"]:
        _replace_nb_nuits_in_title(slides[17], nb_nuits_cam)
        _fill_slide_17(slides[17], agg["totals_by_nuit"], agg["dates_map"],
                       agg["cam_nights"], weeks_list)
    # Slide 19 (index 18) = Phasage caméras
    if len(slides) >= 19:
        _replace_nb_nuits_in_title(slides[18], nb_nuits_cam)
        _fill_slide_18(slides[18], agg["nuit_cam"], weeks_list)
    # Slide 20 (index 19) = Détail caméras par allée
    if len(slides) >= 20 and detail_cam_rows:
        _fill_slide_19(slides[19], detail_cam_rows, weeks=weeks_list)
    # Slide 21 (index 20) = Phasage full consolidé
    if len(slides) >= 21:
        _fill_slide_20(slides[20], agg["nuit_es"], agg["nuit_cam"],
                       agg["dates_map"], weeks_list)
    # Semaines au-delà de 4 (jusqu'à 20 nuits = 5 semaines de 4) : on clone la
    # dernière slide semaine du template (index 16) pour créer les slides
    # manquantes, insérées juste après. Fait APRÈS les fills à index fixe pour
    # ne pas décaler les slides caméras/full déjà remplies.
    if len(weeks_list) > 4 and len(slides) >= 17:
        cursor2 = sum(int(w or 0) for w in weeks_list[:4]) + 1
        for j, w in enumerate(weeks_list[4:]):
            ww = int(w or 0)
            if ww <= 0:
                continue
            week_nights = list(range(cursor2, cursor2 + ww))
            cursor2 += ww
            new_slide = _duplicate_slide(prs, 16, 17 + j)
            _fill_slide_week(new_slide, 5 + j, week_nights,
                             agg["nuit_es"], agg["totals_by_nuit"],
                             agg["dates_map"], weeks_list,
                             hide_sa_mag=agg.get("hide_sa_mag", False))
    # Suppression des slides semaines non utilisées (en ordre décroissant pour
    # préserver les indices). Si magasin = 3 semaines → slide S4 supprimée.
    # Si 2 semaines → S3 et S4 supprimées. Etc.
    unused = sorted([idx for idx in WEEK_SLIDE_INDICES if idx not in used_week_slides], reverse=True)
    for idx in unused:
        if idx < len(slides):
            _delete_slide(prs, idx)
    # Insertion des plans wifi (0, 1 ou 2 images) dans la/les slide(s)
    # "Plan wifi magasin". Fait EN DERNIER pour ne pas décaler les index des
    # slides remplies ci-dessus.
    try:
        _insert_wifi_plans(prs, wifi_plans)
    except Exception:
        pass
    # Titres remontés + phrase de bas de page réduite (sur toutes les slides).
    try:
        _compact_layout(prs)
    except Exception:
        pass
    # Sauvegarde en bytes
    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _duplicate_slide(prs, src_index: int, dest_index: int):
    """Clone la slide `src_index` (deep-copy des formes) et la déplace en
    position `dest_index`. Utilisé pour créer une 5e slide "semaine" quand le
    phasage dépasse 4 semaines (jusqu'à 20 nuits = 5 semaines de 4)."""
    src = prs.slides[src_index]
    new_slide = prs.slides.add_slide(src.slide_layout)
    # Retire les placeholders hérités du layout
    for shp in list(new_slide.shapes):
        shp._element.getparent().remove(shp._element)
    # Deep-copy des formes de la slide source (tables + textes ; pas d'images)
    for shp in src.shapes:
        new_slide.shapes._spTree.append(copy.deepcopy(shp._element))
    # Réordonne : déplace la nouvelle slide (en dernier) vers dest_index
    xml_slides = prs.slides._sldIdLst
    ids = list(xml_slides)
    new_id = ids[-1]
    xml_slides.remove(new_id)
    xml_slides.insert(dest_index, new_id)
    return new_slide


def _delete_slide(prs, slide_idx: int):
    """Supprime la slide à l'index donné du PowerPoint en nettoyant aussi
    sa référence et sa relation dans la présentation."""
    xml_slides = prs.slides._sldIdLst
    slides_list = list(xml_slides)
    if slide_idx >= len(slides_list):
        return
    slide_id_elem = slides_list[slide_idx]
    rId = slide_id_elem.get(qn('r:id'))
    # Supprime de la liste sldIdLst
    xml_slides.remove(slide_id_elem)
    # Drop la relation pour que python-pptx oublie la slide
    if rId:
        prs.part.drop_rel(rId)
