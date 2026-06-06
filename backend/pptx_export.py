"""
Génération du PowerPoint "CR VT et plan de phasage" à partir d'un template
et des données de l'application.

Le template contient 21 slides avec des placeholders texte, des tableaux
et des images (screenshots du phasage). Cette logique :
  - Remplit les zones de texte (nom magasin, code, dates, nombre de nuits)
  - Remplit les vrais tableaux PowerPoint (récap par nuit, détail caméras…)
  - Remplace les images "screenshots des tableaux" par des rendus PNG
    générés à partir des données actuelles de l'appli, avec une petite marge.

L'objectif est de ne RIEN toucher d'autre que ces placeholders, pour que
l'utilisateur conserve toute la mise en page Vusion d'origine.
"""
from __future__ import annotations

import io
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Emu, Inches, Pt
from pptx.dml.color import RGBColor
from lxml import etree

TEMPLATE_PATH = Path(__file__).parent / "templates" / "crvt_template.pptx"

# ---------------------------------------------------------------------------
# Polices (Linux container) ; on retombe sur la police par défaut PIL si KO.
# ---------------------------------------------------------------------------
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


# Palette identique à WEEK_NIGHT_PALETTE côté serveur
WEEK_PALETTE = ["#DBEAFE", "#FEF3C7", "#FEE2E2", "#DCFCE7"]
HEADER_BG = "#056839"       # Vert Carrefour (header tableaux)
HEADER_FG = "#FFFFFF"
GRID = "#D1D5DB"
TEXT = "#111827"
SUB_BG = "#F3F4F6"


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def night_position_in_week(nuit: int, weeks: list | None) -> int:
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


def _night_color(nuit: int, weeks: list | None) -> str:
    pos = night_position_in_week(nuit, weeks)
    if not pos:
        return "#FFFFFF"
    return WEEK_PALETTE[(pos - 1) % len(WEEK_PALETTE)]


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------
def _fmt_date_short(iso: Optional[str]) -> str:
    """ISO YYYY-MM-DD -> DD/MM/YY (chaîne vide si invalide)."""
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        return d.strftime("%d/%m/%y")
    except Exception:
        return ""


def _fmt_date_long(iso: Optional[str]) -> str:
    """ISO YYYY-MM-DD -> DD/MM/YYYY."""
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        return d.strftime("%d/%m/%Y")
    except Exception:
        return ""


def _add_days(iso: Optional[str], days: int) -> Optional[str]:
    if not iso:
        return None
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        return (d + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        return None


def _fmt_int(n) -> str:
    try:
        return f"{int(round(float(n))):,}".replace(",", " ")
    except (ValueError, TypeError):
        return "0"


# ---------------------------------------------------------------------------
# Agrégation phasage (similaire à _build_consolidated_nuit_data côté server)
# ---------------------------------------------------------------------------
def _aggregate(dataset: dict, summary: dict) -> dict:
    """Retourne :
       {
         "es_per_nuit": {nuit_glob: {allees:[label], es:n, rails_es:n, sa:n, es_15:n, es_21:n, sa_15:n, sa_21:n}},
         "cam_per_nuit": {nuit_glob: {allees:[label], cam:n, cam_elems:{allee:[el]}}},
         "weeks_es": [...],
         "weeks_cam": [...],
         "nb_nuits_es": int,
         "nb_nuits_cam": int,
         "cam_start_at": int,
         "dates": {str(n): iso},
         "totals": {...},
       }
    """
    phasage = dataset.get("phasage") or {}
    es_plan = phasage.get("es") or {}
    cam_plan = phasage.get("cam") or {}
    dates = phasage.get("dates") or {}

    nb_nuits_es = int(es_plan.get("nb_nuits") or 0)
    nb_nuits_cam = int(cam_plan.get("nb_nuits") or 0)
    cam_start_at = int(cam_plan.get("start_at_nuit") or 5)
    weeks_es = es_plan.get("weeks") or []
    weeks_cam = cam_plan.get("weeks") or []

    # Index uid -> noeud allée
    allees = summary.get("allees") or []
    seasonal = summary.get("seasonal_zones") or []
    idx = {str(a.get("uid") or a.get("allee")): a for a in allees}
    # Zones saisonnières : on les retrouve aussi par leur id (ZS1, ZS2…)
    for z in seasonal:
        idx[str(z.get("id"))] = {
            "uid": str(z.get("id")),
            "allee": str(z.get("id")),
            "es_15": 0, "es_21": 0, "sa": z.get("sa_21") or 0,
            "sa_15": 0, "sa_21": z.get("sa_21") or 0,
            "rails_es": 0, "cameras": 0, "camera_elems": [],
            "is_seasonal": True,
        }

    def _label(uid: str, node: dict) -> str:
        if node.get("is_seasonal"):
            return str(uid)
        num = str(node.get("allee") or "").strip()
        if node.get("is_dup"):
            return f"{num}-{node.get('dup_index', 1)}"
        return num

    es_per_nuit: dict[int, dict] = {}
    for r in es_plan.get("rows") or []:
        n = r.get("nuit")
        a_uid = str(r.get("allee") or "").strip()
        if not n or not a_uid:
            continue
        node = idx.get(a_uid)
        if not node:
            continue
        gn = int(n)
        bucket = es_per_nuit.setdefault(gn, {
            "allees": [], "es": 0, "rails_es": 0, "sa": 0,
            "es_15": 0, "es_21": 0, "sa_15": 0, "sa_21": 0,
        })
        bucket["allees"].append(_label(a_uid, node))
        bucket["es_15"] += float(node.get("es_15") or 0)
        bucket["es_21"] += float(node.get("es_21") or 0)
        bucket["es"] += float(node.get("es_15") or 0) + float(node.get("es_21") or 0)
        bucket["rails_es"] += float(node.get("rails_es") or 0)
        bucket["sa"] += float(node.get("sa") or 0)
        bucket["sa_15"] += float(node.get("sa_15") or 0)
        bucket["sa_21"] += float(node.get("sa_21") or 0)

    cam_per_nuit: dict[int, dict] = {}
    for r in cam_plan.get("rows") or []:
        n = r.get("nuit")
        a_uid = str(r.get("allee") or "").strip()
        if not n or not a_uid:
            continue
        node = idx.get(a_uid)
        if not node:
            continue
        gn = cam_start_at + int(n) - 1
        bucket = cam_per_nuit.setdefault(gn, {
            "allees": [], "cam": 0, "cam_elems_by_allee": {},
        })
        label = _label(a_uid, node)
        bucket["allees"].append(label)
        bucket["cam"] += float(node.get("cameras") or 0)
        # Détail éléments
        cam_elems = node.get("camera_elems") or []
        if cam_elems:
            bucket["cam_elems_by_allee"][label] = cam_elems

    totals_es = {
        "es": sum(b["es"] for b in es_per_nuit.values()),
        "es_15": sum(b["es_15"] for b in es_per_nuit.values()),
        "es_21": sum(b["es_21"] for b in es_per_nuit.values()),
        "rails_es": sum(b["rails_es"] for b in es_per_nuit.values()),
        "sa": sum(b["sa"] for b in es_per_nuit.values()),
    }
    totals_cam = {"cam": sum(b["cam"] for b in cam_per_nuit.values())}

    return {
        "es_per_nuit": es_per_nuit,
        "cam_per_nuit": cam_per_nuit,
        "weeks_es": weeks_es,
        "weeks_cam": weeks_cam,
        "nb_nuits_es": nb_nuits_es,
        "nb_nuits_cam": nb_nuits_cam,
        "cam_start_at": cam_start_at,
        "dates": dates,
        "totals_es": totals_es,
        "totals_cam": totals_cam,
    }


def _all_install_dates(agg: dict) -> tuple[Optional[str], Optional[str]]:
    """Min/Max des dates renseignées dans le Tableau Date (toutes nuits ES + Cam)."""
    dates = agg.get("dates") or {}
    iso_list = []
    for k, v in dates.items():
        if v:
            iso_list.append(str(v)[:10])
    if not iso_list:
        return None, None
    iso_list.sort()
    return iso_list[0], iso_list[-1]


# ---------------------------------------------------------------------------
# Rendu PNG d'une table de phasage (mode "ES" ou "CAM"), pour replace_image
# ---------------------------------------------------------------------------
def _render_phasage_image(
    *,
    title: str,
    mode: str,           # "es" | "cam"
    nights: list[int],   # nuits à afficher (déjà triées)
    agg: dict,
    width_px: int = 1600,
    target_height_px: Optional[int] = None,
) -> bytes:
    """Génère un PNG d'un tableau récap par nuit, façon "screenshot stylisé"
    du phasage. La largeur cible permet de respecter le ratio du slot image
    dans la slide.
    """
    if mode == "es":
        cols = ["Nuit", "Date", "Allées", "ES", "Rails ES", "SA"]
        col_w_ratio = [0.07, 0.10, 0.46, 0.10, 0.13, 0.14]
    else:
        cols = ["Nuit", "Date", "Allées", "Caméras"]
        col_w_ratio = [0.08, 0.12, 0.66, 0.14]

    # Marge & paddings
    margin = 24
    title_h = 56
    header_h = 44
    row_h = 36
    total_w = width_px

    # Largeurs colonnes
    inner_w = total_w - 2 * margin
    col_w = [int(inner_w * r) for r in col_w_ratio]
    # Corrige arrondi
    col_w[-1] = inner_w - sum(col_w[:-1])

    # Hauteur tableau
    n_rows = max(1, len(nights)) + 1  # +1 pour total
    tbl_h = header_h + n_rows * row_h
    total_h = margin + title_h + tbl_h + margin

    if target_height_px:
        # Si on doit caler dans une zone fixe, on ajuste row_h pour tenir
        avail = target_height_px - margin * 2 - title_h - header_h
        if avail > 0 and n_rows > 0:
            row_h = max(22, min(row_h, avail // n_rows))
            tbl_h = header_h + n_rows * row_h
            total_h = margin + title_h + tbl_h + margin

    img = Image.new("RGB", (total_w, total_h), "white")
    draw = ImageDraw.Draw(img)

    # Titre
    font_title = _font(28, bold=True)
    draw.text((margin, margin + 6), title, fill=_hex_to_rgb(TEXT), font=font_title)

    # Header tableau
    y0 = margin + title_h
    x = margin
    font_h = _font(16, bold=True)
    for i, c in enumerate(cols):
        draw.rectangle([x, y0, x + col_w[i], y0 + header_h],
                       fill=_hex_to_rgb(HEADER_BG), outline=_hex_to_rgb(GRID))
        # Texte centré
        bbox = draw.textbbox((0, 0), c, font=font_h)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((x + (col_w[i] - tw) // 2, y0 + (header_h - th) // 2 - 2),
                  c, fill=_hex_to_rgb(HEADER_FG), font=font_h)
        x += col_w[i]

    # Lignes
    font_cell = _font(14)
    font_cell_b = _font(14, bold=True)
    weeks = agg["weeks_es"] if mode == "es" else agg["weeks_cam"]
    per_nuit = agg["es_per_nuit"] if mode == "es" else agg["cam_per_nuit"]
    dates = agg["dates"] or {}

    total_es = total_rails = total_sa = total_cam = 0
    y = y0 + header_h
    for n in nights:
        bucket = per_nuit.get(n, {})
        bg = _night_color(n, weeks)
        x = margin
        # Nuit (colorée selon position dans semaine)
        draw.rectangle([x, y, x + col_w[0], y + row_h],
                       fill=_hex_to_rgb(bg), outline=_hex_to_rgb(GRID))
        nuit_lbl = f"Nuit {n}"
        bbox = draw.textbbox((0, 0), nuit_lbl, font=font_cell_b)
        tw = bbox[2] - bbox[0]
        draw.text((x + (col_w[0] - tw) // 2, y + 7), nuit_lbl,
                  fill=_hex_to_rgb(TEXT), font=font_cell_b)
        x += col_w[0]

        # Date
        date_iso = dates.get(str(n)) or ""
        date_lbl = _fmt_date_short(date_iso)
        draw.rectangle([x, y, x + col_w[1], y + row_h],
                       fill="white", outline=_hex_to_rgb(GRID))
        draw.text((x + 8, y + 8), date_lbl, fill=_hex_to_rgb(TEXT), font=font_cell)
        x += col_w[1]

        # Allées (concaténées avec ellipsis si > col_w[2])
        allees = ", ".join(str(a) for a in (bucket.get("allees") or []))
        # Ellipsis manuelle si trop long
        max_text_w = col_w[2] - 16
        text = allees
        while draw.textlength(text, font=font_cell) > max_text_w and len(text) > 3:
            text = text[:-2]
        if text != allees:
            text = text[:-1] + "…"
        draw.rectangle([x, y, x + col_w[2], y + row_h],
                       fill="white", outline=_hex_to_rgb(GRID))
        draw.text((x + 8, y + 8), text, fill=_hex_to_rgb(TEXT), font=font_cell)
        x += col_w[2]

        if mode == "es":
            es_v = int(round(bucket.get("es") or 0))
            rails_v = int(round(bucket.get("rails_es") or 0))
            sa_v = int(round(bucket.get("sa") or 0))
            total_es += es_v
            total_rails += rails_v
            total_sa += sa_v
            for idx_c, val in enumerate([es_v, rails_v, sa_v], start=3):
                draw.rectangle([x, y, x + col_w[idx_c], y + row_h],
                               fill="white", outline=_hex_to_rgb(GRID))
                txt = _fmt_int(val)
                bbox = draw.textbbox((0, 0), txt, font=font_cell)
                tw = bbox[2] - bbox[0]
                draw.text((x + col_w[idx_c] - tw - 8, y + 8),
                          txt, fill=_hex_to_rgb(TEXT), font=font_cell)
                x += col_w[idx_c]
        else:
            cam_v = int(round(bucket.get("cam") or 0))
            total_cam += cam_v
            draw.rectangle([x, y, x + col_w[3], y + row_h],
                           fill="white", outline=_hex_to_rgb(GRID))
            txt = _fmt_int(cam_v)
            bbox = draw.textbbox((0, 0), txt, font=font_cell)
            tw = bbox[2] - bbox[0]
            draw.text((x + col_w[3] - tw - 8, y + 8),
                      txt, fill=_hex_to_rgb(TEXT), font=font_cell)
            x += col_w[3]
        y += row_h

    # Ligne TOTAL
    x = margin
    for i, c in enumerate(cols):
        draw.rectangle([x, y, x + col_w[i], y + row_h],
                       fill=_hex_to_rgb(SUB_BG), outline=_hex_to_rgb(GRID))
        x += col_w[i]
    x = margin
    draw.text((x + 8, y + 8), "TOTAL", fill=_hex_to_rgb(TEXT), font=font_cell_b)
    x += col_w[0]
    # Date span
    if nights:
        date_min = _fmt_date_short(dates.get(str(nights[0])))
        date_max = _fmt_date_short(dates.get(str(nights[-1])))
        span = (f"{date_min} → {date_max}" if date_min and date_max
                else (date_min or date_max or ""))
        draw.text((x + 8, y + 8), span, fill=_hex_to_rgb(TEXT), font=font_cell)
    x += col_w[1]
    n_allees = sum(len(per_nuit.get(n, {}).get("allees") or []) for n in nights)
    draw.text((x + 8, y + 8),
              f"{n_allees} allée{'s' if n_allees > 1 else ''}",
              fill=_hex_to_rgb(TEXT), font=font_cell)
    x += col_w[2]
    if mode == "es":
        for idx_c, val in enumerate([total_es, total_rails, total_sa], start=3):
            txt = _fmt_int(val)
            bbox = draw.textbbox((0, 0), txt, font=font_cell_b)
            tw = bbox[2] - bbox[0]
            draw.text((x + col_w[idx_c] - tw - 8, y + 8),
                      txt, fill=_hex_to_rgb(TEXT), font=font_cell_b)
            x += col_w[idx_c]
    else:
        txt = _fmt_int(total_cam)
        bbox = draw.textbbox((0, 0), txt, font=font_cell_b)
        tw = bbox[2] - bbox[0]
        draw.text((x + col_w[3] - tw - 8, y + 8),
                  txt, fill=_hex_to_rgb(TEXT), font=font_cell_b)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helpers pour manipuler le PPTX
# ---------------------------------------------------------------------------
def _set_paragraph_text(p, new_text: str) -> None:
    """Remplace tout le texte d'un paragraphe en gardant le formatage du
    premier run existant (police, taille, couleur)."""
    runs = p.runs
    if runs:
        # On garde le 1er run, on vide les autres
        first = runs[0]
        first.text = new_text
        for r in runs[1:]:
            r.text = ""
    else:
        # Pas de run -> ajouter via add_run
        p.add_run().text = new_text


def _set_textframe_text(tf, new_text: str) -> None:
    """Idem mais sur tout le text_frame (cherche le 1er paragraphe non vide
    et remplace son contenu)."""
    if not tf.paragraphs:
        tf.text = new_text
        return
    # On remplace UNIQUEMENT le 1er paragraphe non vide, et on vide les autres
    done = False
    for p in tf.paragraphs:
        if not done and p.text.strip():
            _set_paragraph_text(p, new_text)
            done = True
        elif done:
            _set_paragraph_text(p, "")
    if not done:
        _set_paragraph_text(tf.paragraphs[0], new_text)


def _find_shape(slide, name: str):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
    return None


def _find_shapes_by_type(slide, shape_type):
    return [sh for sh in slide.shapes if sh.shape_type == shape_type]


def _replace_picture(slide, picture_shape, png_bytes: bytes, margin_inches: float = 0.06):
    """Supprime l'image existante et insère une nouvelle image PNG au même
    emplacement, en laissant une petite marge tout autour (par défaut ~0.06"
    soit ~1.5mm).
    """
    left = picture_shape.left
    top = picture_shape.top
    width = picture_shape.width
    height = picture_shape.height
    # Marge
    m = Inches(margin_inches)
    new_left = left + m
    new_top = top + m
    new_w = max(Inches(1), width - 2 * m)
    new_h = max(Inches(1), height - 2 * m)

    # On supprime l'élément <p:sp>/<p:pic> du XML parent
    sp = picture_shape._element
    sp.getparent().remove(sp)

    # On ajoute la nouvelle image
    slide.shapes.add_picture(io.BytesIO(png_bytes),
                             new_left, new_top, width=new_w, height=new_h)


def _set_table_cell(cell, text: str, *, bold: bool = False, font_size: int = 12,
                    color_hex: Optional[str] = None) -> None:
    """Remplace le texte d'une cellule en préservant le style du premier run
    si possible."""
    tf = cell.text_frame
    if not tf.paragraphs:
        p = tf.add_paragraph()
    else:
        p = tf.paragraphs[0]
        # Vider autres paragraphes
        for extra in list(tf.paragraphs[1:]):
            extra._p.getparent().remove(extra._p)
    if p.runs:
        run = p.runs[0]
        run.text = text
        # On vide les autres runs
        for r in p.runs[1:]:
            r.text = ""
    else:
        run = p.add_run()
        run.text = text
    try:
        run.font.bold = bold
        run.font.size = Pt(font_size)
        if color_hex:
            run.font.color.rgb = RGBColor.from_string(color_hex.lstrip("#"))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Génération principale
# ---------------------------------------------------------------------------
def generate_pptx(dataset: dict, summary: dict) -> bytes:
    """Charge le template, remplit les zones dynamiques, retourne le binaire .pptx."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template PPTX introuvable : {TEMPLATE_PATH}")

    prs = Presentation(str(TEMPLATE_PATH))
    agg = _aggregate(dataset, summary)

    # ----- Méta-infos magasin -----
    store_name = (dataset.get("store_name") or "").strip()
    store_city = (dataset.get("store_city") or "").strip()
    store_code = (dataset.get("store_code") or "").strip()
    store_address = (dataset.get("store_address") or "").strip()

    vt_start = (dataset.get("vt_start_date") or "").strip()
    vt_end = (dataset.get("vt_end_date") or "").strip() or _add_days(vt_start, 2)
    responsable_magasin = (dataset.get("responsable_magasin") or "").strip()
    responsable_vusion = (dataset.get("responsable_vusion") or "").strip()
    prestataire = (dataset.get("prestataire_install") or "").strip()
    plan_prevention = (dataset.get("plan_prevention_signe") or "").strip()
    doc_version = (dataset.get("doc_version") or "").strip()
    date_validation = (dataset.get("date_validation_carrefour") or "").strip()
    participants = (dataset.get("participants") or "").strip()

    install_start, install_end = _all_install_dates(agg)

    # Slide 1 (index 0) : sous-titre = ville + code magasin (ex: "Massy HA4CG")
    slide1 = prs.slides[0]
    sub1 = _find_shape(slide1, "Untertitel 2")
    if sub1 and sub1.has_text_frame:
        line = " ".join([x for x in [store_city or store_name, store_code] if x]).strip()
        _set_textframe_text(sub1.text_frame, line or " ")

    # Slide 4 (index 3) : "Date de VT: du XX au YY"
    slide4 = prs.slides[3]
    sub4 = _find_shape(slide4, "Sous-titre 4")
    if sub4 and sub4.has_text_frame:
        if vt_start and vt_end:
            txt = f"Date de VT: du {_fmt_date_short(vt_start)} au {_fmt_date_short(vt_end)}"
        elif vt_start:
            txt = f"Date de VT: {_fmt_date_short(vt_start)}"
        else:
            txt = "Date de VT: —"
        _set_textframe_text(sub4.text_frame, txt)

    # Slide 6 (index 5) : tableau "Informations générales"
    slide6 = prs.slides[5]
    info_tbl = _find_shape(slide6, "Tableau 5")
    if info_tbl and info_tbl.has_table:
        tbl = info_tbl.table
        # Mapping label -> valeur (lookup tolérant aux espaces)
        mapping = {
            "nom magasin": store_name,
            "code magasin": store_code,
            "adresse": store_address,
            "date de la visite technique (vt)":
                (f"du {_fmt_date_short(vt_start)} au {_fmt_date_short(vt_end)}"
                 if vt_start and vt_end else _fmt_date_short(vt_start)),
            "participants": participants,
            "responsable magasin présent": responsable_magasin,
            "responsable vusion/numéro de téléphone": responsable_vusion,
            "prestataire d'installation": prestataire,
            "plan de prévention signé": plan_prevention,
            "version du document": doc_version,
            "date de validation carrefour": _fmt_date_short(date_validation),
        }
        for row in tbl.rows:
            key = row.cells[0].text.strip().lower()
            if key in mapping and mapping[key]:
                _set_table_cell(row.cells[1], mapping[key])

    # Slide 9 (index 8) : "Date installation: du XX au YY"
    slide9 = prs.slides[8]
    sub9 = _find_shape(slide9, "Untertitel 2")
    if sub9 and sub9.has_text_frame:
        if install_start and install_end:
            txt = f"Date installation: du {_fmt_date_short(install_start)} au {_fmt_date_short(install_end)}"
        else:
            txt = "Date installation: —"
        _set_textframe_text(sub9.text_frame, txt)

    # Slide 10 (index 9) : zone de contenu - on met à jour les dates et nuits
    slide10 = prs.slides[9]
    content10 = _find_shape(slide10, "Espace réservé du contenu 2")
    nb_es = agg["nb_nuits_es"]
    nb_cam = agg["nb_nuits_cam"]
    if content10 and content10.has_text_frame:
        # On reconstruit complètement le texte d'info générale.
        tf = content10.text_frame
        date_range = (
            f"du {_fmt_date_short(install_start)} au {_fmt_date_short(install_end)}"
            if install_start and install_end else "—"
        )
        # On veut conserver le formatage existant. Stratégie : remplacer le
        # texte des paragraphes non vides en cascade.
        lines = [
            "Information générale:",
            f"Dates d'installation: {date_range}",
            f"Nombre de nuits ES/Rails : {nb_es}",
            f"Nombre de nuits caméras : {nb_cam} (à partir de la nuit {agg['cam_start_at']})",
        ]
        # On remplace les premiers paragraphes du tf
        existing = [p for p in tf.paragraphs]
        for i, line in enumerate(lines):
            if i < len(existing):
                _set_paragraph_text(existing[i], line)
            else:
                p = tf.add_paragraph()
                p.text = line
        # Vide les paragraphes suivants éventuels
        for j in range(len(lines), len(existing)):
            _set_paragraph_text(existing[j], "")

    # Slide 11 (index 10) : titre "(X nuits)" + image phasage complet ES
    slide11 = prs.slides[10]
    title11 = _find_shape(slide11, "Titre 1")
    if title11 and title11.has_text_frame:
        _set_textframe_text(
            title11.text_frame,
            f"Plan de phasage EEG et rails complet par nuit ({nb_es} nuits)"
        )
    # Remplace la grande image (Image 11)
    img11 = _find_shape(slide11, "Image 11")
    if img11 is not None and nb_es > 0:
        png = _render_phasage_image(
            title="Plan de phasage EEG et rails — Vue complète",
            mode="es",
            nights=list(range(1, nb_es + 1)),
            agg=agg,
            width_px=1900,
        )
        _replace_picture(slide11, img11, png)

    # Slide 12 (index 11) : "Tableau phasage EEG et rails par nuit (X nuits)"
    slide12 = prs.slides[11]
    title12 = _find_shape(slide12, "Titre 1")
    if title12 and title12.has_text_frame:
        _set_textframe_text(
            title12.text_frame,
            f"Tableau phasage EEG et rails par nuit ({nb_es} nuits)"
        )
    img12 = _find_shape(slide12, "Image 4")
    if img12 is not None and nb_es > 0:
        png = _render_phasage_image(
            title="Récap EEG et rails par nuit",
            mode="es",
            nights=list(range(1, nb_es + 1)),
            agg=agg,
            width_px=1700,
        )
        _replace_picture(slide12, img12, png)

    # Slides 13-17 (index 12-16) : semaines S1-S5
    _fill_week_slides(prs, agg)

    # Slide 18 (index 17) : Phasage caméras complet
    slide18 = prs.slides[17]
    title18_shape = _find_shape(slide18, "ZoneTexte 38")
    if title18_shape and title18_shape.has_text_frame:
        _set_textframe_text(
            title18_shape.text_frame,
            f"Plan de phasage caméras complet par nuit ({nb_cam} nuits)"
        )
    # Tableau dates nuits caméras
    tbl_cam_dates = _find_shape(slide18, "Tableau 29")
    if tbl_cam_dates and tbl_cam_dates.has_table:
        _fill_nuit_dates_table(tbl_cam_dates.table, agg,
                               nights=_cam_nights(agg))
    # Image caméras (Image 1 manquante au scan -> on cherche n'importe quelle Picture autre)
    for sh in slide18.shapes:
        if sh.shape_type == 13 and sh.name not in ("Image 8",):  # 13 = PICTURE
            if nb_cam > 0:
                png = _render_phasage_image(
                    title="Phasage caméras — Vue complète",
                    mode="cam",
                    nights=_cam_nights(agg),
                    agg=agg,
                    width_px=1700,
                )
                _replace_picture(slide18, sh, png)
            break

    # Slide 19 (index 18) : tableau "Récap par nuit" caméras
    slide19 = prs.slides[18]
    title19 = _find_shape(slide19, "Titre 1")
    if title19 and title19.has_text_frame:
        _set_textframe_text(
            title19.text_frame,
            f"Tableau phasage caméras par nuit ({nb_cam} nuits)"
        )
    cam_tbl = _find_shape(slide19, "Tableau 1")
    if cam_tbl and cam_tbl.has_table:
        _fill_cam_recap_table(cam_tbl.table, agg)

    # Slide 20 (index 19) : détail caméras par allée
    slide20 = prs.slides[19]
    _fill_cam_detail_tables(slide20, agg, summary)

    # Slide 21 (index 20) : tableau récap global
    slide21 = prs.slides[20]
    recap_tbl = _find_shape(slide21, "Tableau 4")
    if recap_tbl and recap_tbl.has_table:
        _fill_global_recap_table(recap_tbl.table, agg)

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _es_nights(agg: dict) -> list[int]:
    return list(range(1, agg["nb_nuits_es"] + 1))


def _cam_nights(agg: dict) -> list[int]:
    start = agg["cam_start_at"]
    return list(range(start, start + agg["nb_nuits_cam"]))


def _nights_by_week_es(agg: dict) -> list[list[int]]:
    """Retourne la liste des nuits regroupées par semaine selon agg['weeks_es'].
    Si pas de weeks définis, on retourne tout en une seule semaine.
    """
    weeks = agg["weeks_es"] or [agg["nb_nuits_es"]]
    out = []
    cursor = 1
    for w in weeks:
        ww = int(w or 0)
        if ww <= 0:
            continue
        out.append(list(range(cursor, cursor + ww)))
        cursor += ww
    return out


def _fill_nuit_dates_table(table, agg: dict, nights: list[int]) -> None:
    """Remplit un tableau 2 lignes x N colonnes :
       ligne 0 = "Nuit X", ligne 1 = date long format DD/MM/YYYY.
    Si trop de nuits par rapport aux colonnes du tableau, on garde les N premières.
    """
    n_cols = len(table.columns)
    n_show = min(len(nights), n_cols)
    dates = agg["dates"] or {}
    for j in range(n_cols):
        if j < n_show:
            n = nights[j]
            _set_table_cell(table.rows[0].cells[j], f"Nuit {n}", bold=True, font_size=11)
            _set_table_cell(table.rows[1].cells[j],
                            _fmt_date_long(dates.get(str(n))) or "—",
                            font_size=11)
        else:
            # Vide les colonnes excédentaires
            _set_table_cell(table.rows[0].cells[j], "", font_size=11)
            _set_table_cell(table.rows[1].cells[j], "", font_size=11)


def _fill_week_slides(prs, agg: dict) -> None:
    """Remplit les slides 13 à 17 (S1 à S5).
    - Slide 13 (idx 12) = S1 : Image 7 (image phasage) + pas de tableau date
    - Slides 14-17 (idx 13-16) = S2-S5 : Tableau 2/35/31/16 (dates) + Image 5/2/1/1
    """
    weeks = _nights_by_week_es(agg)

    # Pour chaque slide week, on associe (idx_slide, week_nights, title_shape_name, image_shape_name, date_table_name)
    mapping = [
        # idx_slide_0based, week_index, title_shape_names (candidates), image_shape_names, date_table_name
        (12, 0, ["Titre 1"], ["Image 7"], None),                       # S1
        (13, 1, ["Titre 1"], ["Image 5"], "Tableau 2"),               # S2
        (14, 2, ["Titre 1"], ["Image 2"], "Tableau 35"),              # S3
        (15, 3, ["ZoneTexte 38"], ["Image 1"], "Tableau 31"),         # S4
        (16, 4, ["ZoneTexte 38"], ["Image 1"], "Tableau 16"),         # S5
    ]
    for slide_idx, week_idx, title_names, img_names, date_tbl_name in mapping:
        slide = prs.slides[slide_idx]
        week_nights = weeks[week_idx] if week_idx < len(weeks) else []

        # Mise à jour titre (juste le numéro de semaine — Sx — garde le format)
        for tname in title_names:
            sh = _find_shape(slide, tname)
            if sh and sh.has_text_frame and week_nights:
                new = f"Plan de phasage EEG et rails par nuit – S{week_idx + 1}"
                _set_textframe_text(sh.text_frame, new)
                break

        # Tableau dates (s'il existe)
        if date_tbl_name:
            tbl_sh = _find_shape(slide, date_tbl_name)
            if tbl_sh and tbl_sh.has_table:
                _fill_nuit_dates_table(tbl_sh.table, agg, week_nights)

        # Image phasage semaine
        for iname in img_names:
            img_sh = _find_shape(slide, iname)
            if img_sh and week_nights:
                png = _render_phasage_image(
                    title=f"Semaine {week_idx + 1} — Nuit"
                    f"{'s' if len(week_nights) > 1 else ''} "
                    f"{week_nights[0]}{('–' + str(week_nights[-1])) if len(week_nights) > 1 else ''}",
                    mode="es",
                    nights=week_nights,
                    agg=agg,
                    width_px=1700,
                )
                _replace_picture(slide, img_sh, png)
                break


def _fill_cam_recap_table(table, agg: dict) -> None:
    """Slide 19 : table "Récap par nuit" (3 colonnes : Nuit | Allées | Caméras).
    On remplace les lignes existantes par les vraies données caméras.
    """
    cam_nights = _cam_nights(agg)
    n_rows = len(table.rows)
    if n_rows < 3:
        return

    # Ligne 0 = "Récap par nuit" merged, ligne 1 = en-têtes
    # Lignes 2..(n_rows-2) = données nuits, dernière ligne = TOTAL
    data_rows = n_rows - 3  # 2 lignes header + 1 TOTAL
    cam_per_nuit = agg["cam_per_nuit"]
    total_cam = 0
    used_allees = 0
    for i in range(data_rows):
        ri = 2 + i
        if i < len(cam_nights):
            n = cam_nights[i]
            bucket = cam_per_nuit.get(n, {"allees": [], "cam": 0})
            _set_table_cell(table.rows[ri].cells[0], f"Nuit {n}", font_size=10, bold=True)
            allees = ", ".join(str(a) for a in (bucket.get("allees") or []))
            _set_table_cell(table.rows[ri].cells[1], allees, font_size=10)
            cam_v = int(round(bucket.get("cam") or 0))
            _set_table_cell(table.rows[ri].cells[2], _fmt_int(cam_v), font_size=10)
            total_cam += cam_v
            used_allees += len(bucket.get("allees") or [])
        else:
            # Vide
            for j in range(3):
                _set_table_cell(table.rows[ri].cells[j], "", font_size=10)

    # Ligne TOTAL (dernière)
    last = n_rows - 1
    _set_table_cell(table.rows[last].cells[0], "TOTAL", bold=True, font_size=10)
    _set_table_cell(table.rows[last].cells[1],
                    f"{used_allees} allée{'s' if used_allees > 1 else ''} planifiée"
                    f"{'s' if used_allees > 1 else ''}",
                    bold=True, font_size=10)
    _set_table_cell(table.rows[last].cells[2], _fmt_int(total_cam),
                    bold=True, font_size=10)


def _fill_cam_detail_tables(slide, agg: dict, summary: dict) -> None:
    """Slide 20 : 2 tableaux "Détail caméras par allée" côte à côte (Tableau 6
    et Tableau 7). On y inscrit pour chaque allée : N° allée | éléments concernés.
    """
    # Collecte des allées caméras planifiées + leurs éléments
    cam_per_nuit = agg["cam_per_nuit"]
    allees_seen = []
    elems_by_allee: dict[str, list] = {}
    for n in sorted(cam_per_nuit.keys()):
        for a_lbl, elems in (cam_per_nuit[n].get("cam_elems_by_allee") or {}).items():
            if a_lbl not in elems_by_allee:
                elems_by_allee[a_lbl] = list(elems)
                allees_seen.append(a_lbl)

    # Récupère les 2 tableaux
    tables = []
    for nm in ("Tableau 6", "Tableau 7"):
        sh = _find_shape(slide, nm)
        if sh and sh.has_table:
            tables.append(sh.table)

    if not tables:
        return

    # Pour chaque table, on a un nombre de lignes (1 header "Détail" + 1 header
    # cols + N data lignes). On va répartir séquentiellement.
    idx = 0
    for ti, table in enumerate(tables):
        n_rows = len(table.rows)
        # Premier tableau : lignes 2..n_rows-1 sont data ; second tableau :
        # lignes 0..n_rows-1 sont data (pas d'entête car visuel continu)
        start_row = 2 if ti == 0 else 0
        for ri in range(start_row, n_rows):
            if idx < len(allees_seen):
                a = allees_seen[idx]
                elems = elems_by_allee.get(a, [])
                _set_table_cell(table.rows[ri].cells[0], str(a),
                                font_size=10, bold=True)
                _set_table_cell(table.rows[ri].cells[1],
                                ", ".join(str(e) for e in elems) if elems else " ",
                                font_size=9)
                idx += 1
            else:
                # Vide
                _set_table_cell(table.rows[ri].cells[0], "", font_size=10)
                _set_table_cell(table.rows[ri].cells[1], "", font_size=9)


def _fill_global_recap_table(table, agg: dict) -> None:
    """Slide 21 : grand tableau récap (7 colonnes) :
       Phasage étiquettes/rails | Nuit | Phasage caméras
       Allées | ES | Rails ES | SA | Nuit | Allées | Caméras
    On remplit ligne par ligne pour les nuits ES (1..nb_es).
    Les colonnes caméras sont remplies pour les nuits où il y a un planning cam.
    """
    nb_es = agg["nb_nuits_es"]
    es_per_nuit = agg["es_per_nuit"]
    cam_per_nuit = agg["cam_per_nuit"]

    n_rows = len(table.rows)
    if n_rows < 3:
        return
    # Lignes 0 et 1 = en-têtes (fusionnées) ; n_rows-1 = TOTAL
    data_count = n_rows - 3
    total_es = total_rails = total_sa = total_cam = 0
    for i in range(data_count):
        ri = 2 + i
        n_es = i + 1
        es = es_per_nuit.get(n_es, {})
        if n_es <= nb_es:
            es_allees = ", ".join(str(a) for a in (es.get("allees") or []))
            es_v = int(round(es.get("es") or 0))
            rails_v = int(round(es.get("rails_es") or 0))
            sa_v = int(round(es.get("sa") or 0))
            total_es += es_v
            total_rails += rails_v
            total_sa += sa_v
            _set_table_cell(table.rows[ri].cells[0], es_allees, font_size=9)
            _set_table_cell(table.rows[ri].cells[1], _fmt_int(es_v), font_size=9)
            _set_table_cell(table.rows[ri].cells[2], _fmt_int(rails_v), font_size=9)
            _set_table_cell(table.rows[ri].cells[3], _fmt_int(sa_v), font_size=9)
            _set_table_cell(table.rows[ri].cells[4], f"{n_es}", font_size=9, bold=True)
        else:
            for c in range(5):
                _set_table_cell(table.rows[ri].cells[c], "", font_size=9)

        # Colonnes caméras (5,6)
        if n_es in cam_per_nuit:
            cam = cam_per_nuit[n_es]
            cam_allees = ", ".join(str(a) for a in (cam.get("allees") or []))
            cam_v = int(round(cam.get("cam") or 0))
            total_cam += cam_v
            _set_table_cell(table.rows[ri].cells[5], cam_allees, font_size=9)
            _set_table_cell(table.rows[ri].cells[6], _fmt_int(cam_v), font_size=9)
        else:
            _set_table_cell(table.rows[ri].cells[5], "", font_size=9)
            _set_table_cell(table.rows[ri].cells[6], "", font_size=9)

    # Ligne TOTAL
    last = n_rows - 1
    _set_table_cell(table.rows[last].cells[0], "", font_size=9, bold=True)
    _set_table_cell(table.rows[last].cells[1], _fmt_int(total_es), font_size=9, bold=True)
    _set_table_cell(table.rows[last].cells[2], _fmt_int(total_rails), font_size=9, bold=True)
    _set_table_cell(table.rows[last].cells[3], _fmt_int(total_sa), font_size=9, bold=True)
    _set_table_cell(table.rows[last].cells[4], f"{nb_es} nuits", font_size=9, bold=True)
    _set_table_cell(table.rows[last].cells[5], f"{agg['nb_nuits_cam']} nuits cam",
                    font_size=9, bold=True)
    _set_table_cell(table.rows[last].cells[6], _fmt_int(total_cam), font_size=9, bold=True)
