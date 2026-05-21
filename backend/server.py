"""
Backend FastAPI pour l'application d'inventaire d'étiquettes électroniques.
Reçoit un fichier Excel, le traite et génère :
- Onglet "Données" : données brutes
- Onglet "Récapitulatif produits" : totaux par Type+Référence, Spare (+5%), Inclineur, 3 lignes vides
- Onglet "Par Secteur/Allée" : comptage EEG (ES/SA), Rails, Caméras
"""
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import math
import logging
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Union, Any
from pydantic import BaseModel

import pandas as pd

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

# In-memory store of processed datasets keyed by upload_id (data too large for Mongo doc)
DATASTORE: dict[str, dict] = {}

# Longueurs de rails qui comptent pour 1 inclineur
INCLINEUR_LENGTHS = ["1320mm", "1240mm", "990mm", "1187mm", "908mm", "650mm", "535mm"]

# Colonnes attendues (le fichier peut avoir des variantes)
EXPECTED_COLS = {
    "secteur": ["Secteur"],
    "rayon": ["Rayon"],
    "allee": ["N° allée", "N° allee", "Allée", "Allee"],
    "type": ["Type"],
    "reference": ["Référence", "Reference"],
    "designation": ["Désignation", "Designation"],
    "quantite": ["Quantité", "Quantite"],
}


def find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    # fallback insensible à la casse
    lower_map = {col.lower(): col for col in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def detect_columns(df: pd.DataFrame) -> dict:
    detected = {}
    for key, candidates in EXPECTED_COLS.items():
        col = find_col(df, candidates)
        if col is None:
            raise HTTPException(status_code=400, detail=f"Colonne manquante : {candidates[0]}")
        detected[key] = col
    return detected


def is_inclineur_rail(designation: str) -> bool:
    """Retourne True si le rail compte 1 inclineur (contient une longueur listée)."""
    if not isinstance(designation, str):
        return False
    for length in INCLINEUR_LENGTHS:
        # match number suivi de "mm" insensible à la casse, avec ou sans espace
        num = length.replace("mm", "")
        pattern = rf"\b{num}\s*mm\b"
        if re.search(pattern, designation, re.IGNORECASE):
            return True
    return False


def classify_eeg(designation: str) -> Optional[str]:
    """Retourne 'ES' ou 'SA' selon le préfixe de la désignation EEG."""
    if not isinstance(designation, str):
        return None
    s = designation.strip().upper()
    if s.startswith("ES"):
        return "ES"
    if s.startswith("SA"):
        return "SA"
    return None


def build_recap_produits(df: pd.DataFrame, cols: dict) -> list[dict]:
    """
    Construit le récapitulatif :
      Pour chaque Type (EEG, Fixation, Rail, Caméra) :
        - Ligne header "TOTAL <Type>"
        - Une ligne par (Référence, Désignation) avec somme Quantité
        - Ligne "SPARE (+5%)" = 5% du grand total du Type
        - Ligne "INCLINEUR" calculée (seulement pour Rail)
      + 3 lignes vides en fin
    """
    rows: list[dict] = []
    type_col = cols["type"]
    ref_col = cols["reference"]
    desig_col = cols["designation"]
    qty_col = cols["quantite"]

    # Ordre fixe des types (ceux trouvés + autres)
    preferred_order = ["EEG", "Fixation", "Rail", "Caméra", "Camera"]
    types_in_data = list(df[type_col].dropna().unique())
    ordered_types = [t for t in preferred_order if t in types_in_data] + [
        t for t in types_in_data if t not in preferred_order
    ]

    for tp in ordered_types:
        sub = df[df[type_col] == tp].copy()
        sub[qty_col] = pd.to_numeric(sub[qty_col], errors="coerce").fillna(0)
        if sub.empty:
            continue

        grouped = (
            sub.groupby([ref_col, desig_col], dropna=False)[qty_col]
            .sum()
            .reset_index()
            .sort_values(by=desig_col, kind="stable")
        )
        type_total = float(grouped[qty_col].sum())

        # Header total
        rows.append({
            "kind": "header",
            "type": tp,
            "reference": "",
            "designation": f"TOTAL {tp}",
            "quantite": type_total,
        })
        # Lignes produits avec Spare (+5%) après chaque produit
        for _, r in grouped.iterrows():
            ref = "" if pd.isna(r[ref_col]) else str(r[ref_col])
            desig = "" if pd.isna(r[desig_col]) else str(r[desig_col])
            qty = float(r[qty_col])
            rows.append({
                "kind": "product",
                "type": tp,
                "reference": ref,
                "designation": desig,
                "quantite": qty,
            })
            rows.append({
                "kind": "spare",
                "type": tp,
                "reference": ref,
                "designation": f"Spare (+5%) {desig}" if desig else "Spare (+5%)",
                "quantite": math.ceil(qty * 0.05),
            })
        # Inclineur (uniquement pour Rail)
        if tp.lower() == "rail":
            mask = sub[desig_col].apply(is_inclineur_rail)
            inclineur_total = float(sub.loc[mask, qty_col].sum())
            rows.append({
                "kind": "inclineur",
                "type": tp,
                "reference": "",
                "designation": "Inclineur (1 par rail 1320/1240/990/1187/908/650/535mm)",
                "quantite": inclineur_total,
            })

    # 3 lignes vides
    for _ in range(3):
        rows.append({"kind": "empty", "type": "", "reference": "", "designation": "", "quantite": ""})

    return rows


def build_par_secteur(df: pd.DataFrame, cols: dict) -> list[dict]:
    """
    Comptage par Secteur > Rayon > N° allée :
      - nb_eeg_es, nb_eeg_sa, nb_rail, nb_camera (somme des quantités)
    """
    secteur_col = cols["secteur"]
    rayon_col = cols["rayon"]
    allee_col = cols["allee"]
    type_col = cols["type"]
    desig_col = cols["designation"]
    qty_col = cols["quantite"]

    df = df.copy()
    df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    df["_eeg_subtype"] = df.apply(
        lambda r: classify_eeg(r[desig_col]) if r[type_col] == "EEG" else None, axis=1
    )

    grouped = df.groupby([secteur_col, rayon_col, allee_col], dropna=False)
    rows: list[dict] = []
    for (secteur, rayon, allee), g in grouped:
        eeg_es = float(g.loc[g["_eeg_subtype"] == "ES", qty_col].sum())
        eeg_sa = float(g.loc[g["_eeg_subtype"] == "SA", qty_col].sum())
        nb_rail = float(g.loc[g[type_col] == "Rail", qty_col].sum())
        # Caméra ou Camera
        nb_cam = float(g.loc[g[type_col].isin(["Caméra", "Camera"]), qty_col].sum())
        rows.append({
            "secteur": "" if pd.isna(secteur) else str(secteur),
            "rayon": "" if pd.isna(rayon) else str(rayon),
            "allee": "" if pd.isna(allee) else (str(int(allee)) if isinstance(allee, float) and allee.is_integer() else str(allee)),
            "nb_eeg_es": eeg_es,
            "nb_eeg_sa": eeg_sa,
            "nb_rail": nb_rail,
            "nb_camera": nb_cam,
        })

    # Tri lisible
    rows.sort(key=lambda r: (r["secteur"], r["rayon"], r["allee"]))
    return rows


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convertit en records JSON-safe (NaN/Inf -> None, Timestamps -> str)."""
    import numpy as np
    out = df.to_dict(orient="records")
    for rec in out:
        for k, v in list(rec.items()):
            if v is None:
                continue
            if isinstance(v, float):
                if math.isnan(v) or math.isinf(v):
                    rec[k] = None
            elif isinstance(v, (pd.Timestamp, datetime)):
                rec[k] = v.isoformat()
            elif isinstance(v, np.integer):
                rec[k] = int(v)
            elif isinstance(v, np.floating):
                fv = float(v)
                rec[k] = None if (math.isnan(fv) or math.isinf(fv)) else fv
            elif pd.isna(v):
                rec[k] = None
    return out


def sanitize_dict(d: dict) -> dict:
    """Convertit clés/valeurs NaN -> None pour sérialisation JSON."""
    out = {}
    for k, v in d.items():
        if isinstance(k, float) and (math.isnan(k) or math.isinf(k)):
            k = "N/A"
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            v = None
        out[str(k)] = v
    return out


@api_router.get("/")
async def root():
    return {"message": "Excel Inventory API", "version": "1.0"}


@api_router.post("/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    """Reçoit un fichier Excel, le traite, et renvoie les 3 onglets générés."""
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Le fichier doit être au format Excel (.xlsx ou .xls)")

    try:
        contents = await file.read()
        # Lire la première feuille
        df = pd.read_excel(io.BytesIO(contents), sheet_name=0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le fichier Excel : {e}")

    if df.empty:
        raise HTTPException(status_code=400, detail="Le fichier Excel est vide")

    # Détection colonnes
    cols = detect_columns(df)

    # Construire les onglets
    recap_rows = build_recap_produits(df, cols)
    secteur_rows = build_par_secteur(df, cols)
    raw_records = df_to_records(df)

    upload_id = str(uuid.uuid4())
    DATASTORE[upload_id] = {
        "filename": file.filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "columns": list(df.columns),
        "detected_cols": cols,
        "raw_records": raw_records,
        "recap_rows": recap_rows,
        "secteur_rows": secteur_rows,
    }

    # Persister métadonnée légère dans Mongo
    try:
        await db.uploads.insert_one({
            "upload_id": upload_id,
            "filename": file.filename,
            "uploaded_at": DATASTORE[upload_id]["uploaded_at"],
            "row_count": len(raw_records),
        })
    except Exception as e:
        logger.warning(f"Mongo insert failed: {e}")

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "row_count": len(raw_records),
        "columns": list(df.columns),
        "data": {
            "raw": raw_records,
            "recap": recap_rows,
            "secteur": secteur_rows,
        },
        "stats": {
            "total_rows": len(raw_records),
            "types": sanitize_dict(df[cols["type"]].value_counts().to_dict()),
            "secteurs": sanitize_dict(df[cols["secteur"]].value_counts().to_dict()),
        }
    }


@api_router.get("/dataset/{upload_id}")
async def get_dataset(upload_id: str):
    if upload_id not in DATASTORE:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    d = DATASTORE[upload_id]
    return {
        "upload_id": upload_id,
        "filename": d["filename"],
        "columns": d["columns"],
        "data": {
            "raw": d["raw_records"],
            "recap": d["recap_rows"],
            "secteur": d["secteur_rows"],
        },
    }


class RecapRowUpdate(BaseModel):
    type: Optional[str] = ""
    reference: Optional[str] = ""
    designation: Optional[str] = ""
    quantite: Optional[Union[str, float, int]] = ""  # accepte str ou nombre, on convertit


def _parse_quantite(v):
    """Parse quantité en nombre si possible, sinon retourne '' ou la valeur originale."""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(",", ".")
    if s == "":
        return ""
    try:
        f = float(s)
        return f
    except ValueError:
        return v  # on garde le texte tel quel si non numérique


@api_router.patch("/dataset/{upload_id}/recap-row/{index}")
async def update_recap_row(upload_id: str, index: int, payload: RecapRowUpdate):
    """Met à jour une ligne du récapitulatif. Réservé aux lignes éditables (kind='empty' ou 'manual')."""
    if upload_id not in DATASTORE:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = DATASTORE[upload_id]["recap_rows"]
    if index < 0 or index >= len(rows):
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    row = rows[index]
    if row["kind"] not in ("empty", "manual"):
        raise HTTPException(status_code=400, detail="Cette ligne n'est pas éditable")

    new_type = (payload.type or "").strip()
    new_ref = (payload.reference or "").strip()
    new_desig = (payload.designation or "").strip()
    new_qty = _parse_quantite(payload.quantite)

    # Si toutes les valeurs sont vides, on remet kind='empty'
    is_empty = not new_type and not new_ref and not new_desig and (new_qty == "" or new_qty == 0)
    row["type"] = new_type
    row["reference"] = new_ref
    row["designation"] = new_desig
    row["quantite"] = new_qty
    row["kind"] = "empty" if is_empty else "manual"
    return {"row": row, "index": index}


@api_router.post("/dataset/{upload_id}/recap-row")
async def add_recap_row(upload_id: str):
    """Ajoute une nouvelle ligne vide à la fin du récapitulatif."""
    if upload_id not in DATASTORE:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = DATASTORE[upload_id]["recap_rows"]
    new_row = {"kind": "empty", "type": "", "reference": "", "designation": "", "quantite": ""}
    rows.append(new_row)
    return {"row": new_row, "index": len(rows) - 1}


@api_router.delete("/dataset/{upload_id}/recap-row/{index}")
async def delete_recap_row(upload_id: str, index: int):
    """Supprime une ligne manuelle ou vide du récapitulatif."""
    if upload_id not in DATASTORE:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = DATASTORE[upload_id]["recap_rows"]
    if index < 0 or index >= len(rows):
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    if rows[index]["kind"] not in ("empty", "manual"):
        raise HTTPException(status_code=400, detail="Seules les lignes manuelles peuvent être supprimées")
    rows.pop(index)
    return {"ok": True, "remaining": len(rows)}


@api_router.get("/export/{upload_id}")
async def export_excel(upload_id: str, sheet: str = "all"):
    """Exporte le fichier Excel généré.

    sheet : 'all' | 'raw' | 'recap' | 'secteur'
    """
    if upload_id not in DATASTORE:
        raise HTTPException(status_code=404, detail="Dataset introuvable")

    d = DATASTORE[upload_id]
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book

        # Formats
        fmt_header = workbook.add_format({
            "bold": True, "bg_color": "#F3F4F6", "border": 1, "align": "left"
        })
        fmt_total = workbook.add_format({
            "bold": True, "bg_color": "#FEF3C7", "border": 1
        })
        fmt_spare = workbook.add_format({
            "bold": True, "bg_color": "#D1FAE5", "border": 1
        })
        fmt_inclineur = workbook.add_format({
            "bold": True, "bg_color": "#DBEAFE", "border": 1
        })
        fmt_cell = workbook.add_format({"border": 1})

        if sheet in ("all", "raw"):
            df_raw = pd.DataFrame(d["raw_records"])
            df_raw.to_excel(writer, sheet_name="Données", index=False)

        if sheet in ("all", "recap"):
            recap = d["recap_rows"]
            ws = workbook.add_worksheet("Récapitulatif")
            writer.sheets["Récapitulatif"] = ws
            headers = ["Type", "Référence", "Désignation", "Quantité"]
            for col_i, h in enumerate(headers):
                ws.write(0, col_i, h, fmt_header)
            for row_i, r in enumerate(recap, start=1):
                kind = r["kind"]
                if kind == "header":
                    fmt = fmt_total
                elif kind == "spare":
                    fmt = fmt_spare
                elif kind == "inclineur":
                    fmt = fmt_inclineur
                else:
                    fmt = fmt_cell
                ws.write(row_i, 0, r["type"], fmt)
                ws.write(row_i, 1, r["reference"], fmt)
                ws.write(row_i, 2, r["designation"], fmt)
                ws.write(row_i, 3, r["quantite"] if r["quantite"] != "" else "", fmt)
            ws.set_column(0, 0, 12)
            ws.set_column(1, 1, 14)
            ws.set_column(2, 2, 50)
            ws.set_column(3, 3, 12)

        if sheet in ("all", "secteur"):
            secteur = d["secteur_rows"]
            ws = workbook.add_worksheet("Par Secteur")
            writer.sheets["Par Secteur"] = ws
            headers = ["Secteur", "Rayon", "N° Allée", "EEG ES", "EEG SA", "Rails", "Caméras"]
            for col_i, h in enumerate(headers):
                ws.write(0, col_i, h, fmt_header)
            for row_i, r in enumerate(secteur, start=1):
                ws.write(row_i, 0, r["secteur"], fmt_cell)
                ws.write(row_i, 1, r["rayon"], fmt_cell)
                ws.write(row_i, 2, r["allee"], fmt_cell)
                ws.write(row_i, 3, r["nb_eeg_es"], fmt_cell)
                ws.write(row_i, 4, r["nb_eeg_sa"], fmt_cell)
                ws.write(row_i, 5, r["nb_rail"], fmt_cell)
                ws.write(row_i, 6, r["nb_camera"], fmt_cell)
            ws.set_column(0, 1, 14)
            ws.set_column(2, 6, 12)

    output.seek(0)
    filename = f"{Path(d['filename']).stem}_traité.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
