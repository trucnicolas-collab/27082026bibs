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
__PPTX_VERSION__ = "2026-02-27-v10-tight"

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


def _set_cell_text(cell, value, *, bold=False, align="center", size=None, color=None, fill_rgb=None):
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


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso


def _get_tables(slide):
    return [sh for sh in slide.shapes if sh.has_table]


# ===================================================================
# Slide 8 — Commandes (split en 2 tables 24×6 et 25×6)
# ===================================================================
# Headers et largeurs pour les NOUVELLES tables 10-cols créées via add_table().
_RECAP_COL_HEADERS = [
    "Type", "Réf.", "Désignation", "Total", "Spare", "Flèche",
    "Signal.", "Saiso.", "Total", "Total+MOQ",
]
# Largeurs : Désignation plus étroite (18%), data cols plus larges pour éviter
# le wrap des headers ("Signalétique" raccourci en "Signal." pour la même raison).
_RECAP_COL_WEIGHTS = [9, 7, 18, 8, 8, 8, 11, 10, 9, 12]


def _set_recap_col_widths(table, total_emu: int):
    s = sum(_RECAP_COL_WEIGHTS)
    for ci, w in enumerate(_RECAP_COL_WEIGHTS):
        table.columns[ci].width = Emu(int(total_emu * w / s))


def _set_cell_margins_zero(cell):
    """Réduit les marges internes pour maximiser la largeur dispo du texte."""
    from pptx.oxml.ns import qn as _qn
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.set('marL', '36000')   # 0.04 inch
    tcPr.set('marR', '36000')
    tcPr.set('marT', '18000')
    tcPr.set('marB', '18000')


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
    # 5) Crée les 2 nouvelles tables (1 header + N data rows chacune)
    n_rows_t1 = 1 + n_t1
    n_rows_t2 = max(1 + len(rest), 2)
    t1_shape = slide.shapes.add_table(n_rows_t1, 10,
                                       placements[0]["left"], placements[0]["top"],
                                       placements[0]["width"], placements[0]["height"])
    t2_shape = slide.shapes.add_table(n_rows_t2, 10,
                                       placements[1]["left"], placements[1]["top"],
                                       placements[1]["width"], placements[1]["height"])
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
    # 8) Hauteur de ligne compacte
    for tbl in (t1, t2):
        for tr in tbl._tbl.findall(qn('a:tr')):
            tr.set('h', '180000')


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
        section_fill = (0xDD, 0xEB, 0xF7)
        for c in range(10):
            txt = (r.get("type") or "") if c == 0 else ""
            cell = table.cell(row_idx, c)
            _set_cell_text(cell, txt, bold=(c == 0), align="left",
                           size=8, fill_rgb=section_fill)
            _set_cell_margins_zero(cell)
        return
    vals = [
        (r.get("type", ""), "left", False),
        (r.get("reference", ""), "left", False),
        (r.get("designation", ""), "left", False),
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
    t = tables[0].table
    # cols template = 1 + max_nights. On étend si besoin.
    needed_cols = 1 + len(all_nights)
    cur_cols = len(t.columns)
    if needed_cols > cur_cols:
        # Pas de clone de colonne facile dans python-pptx — on tronque à cur_cols-1
        all_nights = all_nights[: cur_cols - 1]

    # Row 0 : header (Nuit X)
    _set_cell_text(t.cell(0, 0), "", bold=True, size=10)
    for i, n in enumerate(all_nights):
        _set_cell_text(t.cell(0, i + 1), f"Nuit {n}", bold=True, align="center", size=10)
        _set_cell_fill(t.cell(0, i + 1), _color_for_night(n, weeks))
    # Vide les colonnes restantes
    for i in range(len(all_nights) + 1, cur_cols):
        _set_cell_text(t.cell(0, i), "", size=10)

    labels = ["Date", "EEG", "Caméra", "SA"]
    for li, lab in enumerate(labels):
        r = li + 1
        _set_cell_text(t.cell(r, 0), lab, bold=True, align="left", size=10)
        for i, n in enumerate(all_nights):
            tot = totals_by_nuit.get(n, {})
            if lab == "Date":
                val = _fmt_date(dates_map.get(str(n)))
            elif lab == "EEG":
                val = _num(tot.get("eeg", 0))
            elif lab == "Caméra":
                val = _num(tot.get("cam", 0))
            else:
                val = _num(tot.get("sa", 0))
            _set_cell_text(t.cell(r, i + 1), val, size=10,
                           bold=(lab == "EEG"),
                           align="center")
            _set_cell_fill(t.cell(r, i + 1), _color_for_night(n, weeks))


# ===================================================================
# Slide 12 — Phasage EEG/Rails complet (N+2 × 8) — étend
# ===================================================================
def _fill_slide_12(slide, nuit_es_data, weeks):
    tables = _get_tables(slide)
    if not tables:
        return
    t = tables[0].table
    nights_sorted = sorted(nuit_es_data.keys())
    n_nights = len(nights_sorted)
    needed_rows = 2 + n_nights
    _ensure_table_size(t, needed_rows)
    _set_cell_text(t.cell(0, 0), "Récap par nuit", bold=True, align="center", size=11)
    headers = ["Nuit", "Date", "Secteur/Rayon", "Allées", "EEG", "Rails ES", "SA", "Caméras"]
    for ci, h in enumerate(headers):
        _set_cell_text(t.cell(1, ci), h, bold=True, align="center", size=9)
    for i, n in enumerate(nights_sorted):
        r = i + 2
        d = nuit_es_data[n]
        _set_cell_text(t.cell(r, 0), f"Nuit {n}", bold=True, size=9)
        _set_cell_text(t.cell(r, 1), _fmt_date(d.get("date")), size=9)
        _set_cell_text(t.cell(r, 2), d.get("sr", ""), align="left", size=8)
        _set_cell_text(t.cell(r, 3), d.get("allees_str", ""), align="left", size=8)
        _set_cell_text(t.cell(r, 4), _num(d.get("eeg", 0)), bold=True, size=9)
        _set_cell_text(t.cell(r, 5), _num(d.get("rails_es", 0)), size=9)
        _set_cell_text(t.cell(r, 6), _num(d.get("sa", 0)), size=9)
        _set_cell_text(t.cell(r, 7), _num(d.get("cam", 0) or ""), size=9)
        color = _color_for_night(n, weeks)
        for ci in range(8):
            _set_cell_fill(t.cell(r, ci), color)
    # Supprime les lignes vides finales (au-delà de needed_rows)
    while len(t.rows) > needed_rows:
        last_tr = t._tbl.findall(qn('a:tr'))[-1]
        last_tr.getparent().remove(last_tr)
    # Hauteurs compactes
    for tr in t._tbl.findall(qn('a:tr')):
        tr.set('h', '280000')


# ===================================================================
# Slides 13-16 — Par semaine (2 tables : phasage 7×8 + tableau date 5×5)
# ===================================================================
def _fill_slide_week(slide, week_index: int, week_nights: list[int],
                     nuit_es_data, totals_by_nuit, dates_map, weeks):
    tables = _get_tables(slide)
    if len(tables) < 2:
        return
    # Identifie laquelle est la grande (8 cols) vs la petite (5 cols)
    t_phasage = None
    t_date = None
    for sh in tables:
        if len(sh.table.columns) == 8:
            t_phasage = sh.table
        elif len(sh.table.columns) <= 7:
            t_date = sh.table
    if t_phasage is None or t_date is None:
        return

    # === Phasage EEG/Rails (7×8) ===
    n_data = len(week_nights)
    needed = 2 + n_data
    _ensure_table_size(t_phasage, needed)
    # Le template a déjà un titre fusionné en row 0 — on n'écrase PAS le fond
    # foncé existant, on écrit juste un titre clair. Si c'était une bandeau noire
    # involontaire, l'utilisateur peut la supprimer manuellement du template.
    _set_cell_text(t_phasage.cell(0, 0),
                   f"Semaine {week_index} (Nuits {week_nights[0]} → {week_nights[-1]})",
                   bold=True, align="center", size=11)
    headers = ["Nuit", "Date", "Secteur/Rayon", "Allées", "EEG", "Rails ES", "SA", "Caméras"]
    for ci, h in enumerate(headers):
        _set_cell_text(t_phasage.cell(1, ci), h, bold=True, align="center", size=9)
    for i, n in enumerate(week_nights):
        r = i + 2
        d = nuit_es_data.get(n, {})
        _set_cell_text(t_phasage.cell(r, 0), f"Nuit {n}", bold=True, size=9)
        _set_cell_text(t_phasage.cell(r, 1), _fmt_date(d.get("date") or dates_map.get(str(n))), size=9)
        _set_cell_text(t_phasage.cell(r, 2), d.get("sr", ""), align="left", size=8)
        _set_cell_text(t_phasage.cell(r, 3), d.get("allees_str", ""), align="left", size=8)
        _set_cell_text(t_phasage.cell(r, 4), _num(d.get("eeg", 0)), bold=True, size=9)
        _set_cell_text(t_phasage.cell(r, 5), _num(d.get("rails_es", 0)), size=9)
        _set_cell_text(t_phasage.cell(r, 6), _num(d.get("sa", 0)), size=9)
        _set_cell_text(t_phasage.cell(r, 7), _num(d.get("cam", 0) or ""), size=9)
        color = _color_for_night(n, weeks)
        for ci in range(8):
            _set_cell_fill(t_phasage.cell(r, ci), color)
    # Supprime les lignes vides finales (au-delà de 2 + n_data)
    while len(t_phasage.rows) > needed:
        last_tr = t_phasage._tbl.findall(qn('a:tr'))[-1]
        last_tr.getparent().remove(last_tr)

    # === Tableau date (5 × N) ===
    cur_cols = len(t_date.columns)
    nights_in_date = week_nights[: cur_cols - 1]
    _set_cell_text(t_date.cell(0, 0), "", size=10)
    for i, n in enumerate(nights_in_date):
        _set_cell_text(t_date.cell(0, i + 1), f"Nuit {n}", bold=True, size=10)
        _set_cell_fill(t_date.cell(0, i + 1), _color_for_night(n, weeks))
    # Vide colonnes restantes
    for i in range(len(nights_in_date) + 1, cur_cols):
        _set_cell_text(t_date.cell(0, i), "", size=10)
    labels = ["Date", "EEG", "Caméra", "SA"]
    for li, lab in enumerate(labels):
        r = li + 1
        _set_cell_text(t_date.cell(r, 0), lab, bold=True, align="left", size=10)
        for i, n in enumerate(nights_in_date):
            tot = totals_by_nuit.get(n, {})
            if lab == "Date":
                val = _fmt_date(dates_map.get(str(n)))
            elif lab == "EEG":
                val = _num(tot.get("eeg", 0))
            elif lab == "Caméra":
                val = _num(tot.get("cam", 0))
            else:
                val = _num(tot.get("sa", 0))
            _set_cell_text(t_date.cell(r, i + 1), val,
                           bold=(lab == "EEG"), size=10)
            _set_cell_fill(t_date.cell(r, i + 1), _color_for_night(n, weeks))
        for i in range(len(nights_in_date) + 1, cur_cols):
            _set_cell_text(t_date.cell(r, i), "", size=10)


# ===================================================================
# Slide 17 — Tableau date caméras (4 × N)
# ===================================================================
def _fill_slide_17(slide, totals_by_nuit, dates_map, cam_nights: list[int], weeks):
    tables = _get_tables(slide)
    if not tables:
        return
    t = tables[0].table
    # Étend dynamiquement le tableau pour accueillir toutes les nuits caméras
    # (1 colonne label + N colonnes nuits). Avant : tronqué à cur_cols-1 nuits.
    _ensure_table_cols(t, 1 + len(cam_nights))
    cur_cols = len(t.columns)
    nights = cam_nights[: cur_cols - 1]
    _set_cell_text(t.cell(0, 0), "", size=10)
    for i, n in enumerate(nights):
        _set_cell_text(t.cell(0, i + 1), f"Nuit {n}", bold=True, size=10)
        _set_cell_fill(t.cell(0, i + 1), _color_for_night(n, weeks))
    labels = ["Date", "EEG", "Caméra"]
    for li, lab in enumerate(labels):
        r = li + 1
        _set_cell_text(t.cell(r, 0), lab, bold=True, align="left", size=10)
        for i, n in enumerate(nights):
            tot = totals_by_nuit.get(n, {})
            if lab == "Date":
                val = _fmt_date(dates_map.get(str(n)))
            elif lab == "EEG":
                val = _num(tot.get("eeg", 0))
            else:
                val = _num(tot.get("cam", 0))
            _set_cell_text(t.cell(r, i + 1), val,
                           bold=(lab == "EEG"), size=10)
            _set_cell_fill(t.cell(r, i + 1), _color_for_night(n, weeks))


# ===================================================================
# Slide 18 — Phasage caméras (N+2 × 5)
# ===================================================================
def _fill_slide_18(slide, nuit_cam_data, weeks):
    tables = _get_tables(slide)
    if not tables:
        return
    t = tables[0].table
    nights = sorted(nuit_cam_data.keys())
    needed = 2 + len(nights)
    _ensure_table_size(t, needed)
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
    subs = ["Allées", "ES", "Rails ES", "SA", "Secteur/Rayon",
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
# Public entry point
# ===================================================================
def build_pptx(d: dict, *, aggregate_fn, recap_rows: list, summary: dict | None = None,
               detail_cam_rows: list[tuple[int, str, str]] | None = None) -> bytes:
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
        _fill_slide_12(slides[12], agg["nuit_es"], agg["weeks"])
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
                             agg["dates_map"], weeks_list)
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
    # Suppression des slides semaines non utilisées (en ordre décroissant pour
    # préserver les indices). Si magasin = 3 semaines → slide S4 supprimée.
    # Si 2 semaines → S3 et S4 supprimées. Etc.
    unused = sorted([idx for idx in WEEK_SLIDE_INDICES if idx not in used_week_slides], reverse=True)
    for idx in unused:
        if idx < len(slides):
            _delete_slide(prs, idx)
    # Sauvegarde en bytes
    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


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
