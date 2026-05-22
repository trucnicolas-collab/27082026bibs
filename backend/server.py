"""
Backend FastAPI pour l'application d'inventaire d'étiquettes électroniques.
Reçoit un fichier Excel, le traite et génère :
- Onglet "Données" : données brutes
- Onglet "Récapitulatif produits" : totaux par Type+Référence, Spare (+5%), Inclineur, 3 lignes vides
- Onglet "Par Secteur/Allée" : comptage EEG (ES/SA), Rails, Caméras
"""
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import json
import gzip
import math
import logging
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Union, Any
from pydantic import BaseModel
from bson.binary import Binary

import pandas as pd
import numpy as np

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# MongoDB
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Compression gzip automatique des réponses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Cache local par pod ; source de vérité = MongoDB (datasets collection)
DATASTORE: dict[str, dict] = {}


async def persist_dataset(upload_id: str, data: dict):
    """Stocke le dataset complet en MongoDB (gzippé) pour qu'il soit accessible
    depuis n'importe quel replica K8s."""
    payload = {
        "filename": data["filename"],
        "uploaded_at": data["uploaded_at"],
        "columns": data["columns"],
        "detected_cols": data["detected_cols"],
        "raw_records": data["raw_records"],
        "recap_rows": data["recap_rows"],
        "secteur_rows": data["secteur_rows"],
        "comment_table": data.get("comment_table") or {
            "columns": ["Colonne 1", "Colonne 2", "Colonne 3", "Colonne 4", "Colonne 5"],
            "rows": [["", "", "", "", ""] for _ in range(8)],
        },
    }
    raw_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    compressed = gzip.compress(raw_bytes, compresslevel=6)
    await db.datasets.replace_one(
        {"upload_id": upload_id},
        {
            "upload_id": upload_id,
            "filename": data["filename"],
            "uploaded_at": data["uploaded_at"],
            "row_count": len(data["raw_records"]),
            "size_bytes": len(raw_bytes),
            "compressed_bytes": len(compressed),
            "payload": Binary(compressed),
        },
        upsert=True,
    )


async def persist_recap_rows(upload_id: str, recap_rows: list[dict]):
    """Met à jour uniquement les recap_rows en base après une édition manuelle."""
    if upload_id not in DATASTORE:
        return
    # Recharger payload existant, mettre à jour recap_rows, réenregistrer.
    doc = await db.datasets.find_one({"upload_id": upload_id}, {"payload": 1, "_id": 0})
    if not doc:
        # Pas en base ? Re-persister entièrement depuis le cache mémoire.
        await persist_dataset(upload_id, DATASTORE[upload_id])
        return
    payload = json.loads(gzip.decompress(doc["payload"]).decode("utf-8"))
    payload["recap_rows"] = recap_rows
    raw_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    compressed = gzip.compress(raw_bytes, compresslevel=6)
    await db.datasets.update_one(
        {"upload_id": upload_id},
        {"$set": {"payload": Binary(compressed), "size_bytes": len(raw_bytes), "compressed_bytes": len(compressed)}},
    )


async def persist_comment_table(upload_id: str, comment_table: dict):
    """Met à jour uniquement le tableau de commentaires en base."""
    if upload_id not in DATASTORE:
        return
    doc = await db.datasets.find_one({"upload_id": upload_id}, {"payload": 1, "_id": 0})
    if not doc:
        await persist_dataset(upload_id, DATASTORE[upload_id])
        return
    payload = json.loads(gzip.decompress(doc["payload"]).decode("utf-8"))
    payload["comment_table"] = comment_table
    raw_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    compressed = gzip.compress(raw_bytes, compresslevel=6)
    await db.datasets.update_one(
        {"upload_id": upload_id},
        {"$set": {"payload": Binary(compressed), "size_bytes": len(raw_bytes), "compressed_bytes": len(compressed)}},
    )


async def load_dataset(upload_id: str) -> Optional[dict]:
    """Récupère un dataset : d'abord en cache mémoire, sinon depuis MongoDB."""
    if upload_id in DATASTORE:
        return DATASTORE[upload_id]
    doc = await db.datasets.find_one({"upload_id": upload_id}, {"_id": 0})
    if not doc:
        return None
    payload = json.loads(gzip.decompress(doc["payload"]).decode("utf-8"))
    DATASTORE[upload_id] = payload
    return payload


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
    Construit le récapitulatif avec une colonne Spare (+5%) à côté de Quantité :
      Pour chaque Type (EEG, Fixation, Rail, Caméra) :
        - Ligne header "TOTAL <Type>" (total Quantité, total Spare)
        - Une ligne par (Référence, Désignation) avec Quantité et Spare = ceil(qty*0.05)
        - Ligne "INCLINEUR" (seulement pour Rail) avec Quantité (pas de Spare)
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

        # Header total — colonne Spare vide selon demande utilisateur
        rows.append({
            "kind": "header",
            "type": tp,
            "reference": "",
            "designation": f"TOTAL {tp}",
            "quantite": type_total,
            "spare": "",
            "total_plus_spare": "",
        })
        # Une ligne par produit avec Quantité, Spare (+5%) et Total+Spare
        for _, r in grouped.iterrows():
            ref = "" if pd.isna(r[ref_col]) else str(r[ref_col])
            desig = "" if pd.isna(r[desig_col]) else str(r[desig_col])
            qty = float(r[qty_col])
            spare = math.ceil(qty * 0.05)
            rows.append({
                "kind": "product",
                "type": tp,
                "reference": ref,
                "designation": desig,
                "quantite": qty,
                "spare": spare,
                "total_plus_spare": qty + spare,
            })
        # Inclineur (uniquement pour Rail) — comptable comme produit à commander
        if tp.lower() == "rail":
            mask = sub[desig_col].apply(is_inclineur_rail)
            inclineur_total = float(sub.loc[mask, qty_col].sum())
            inclineur_spare = math.ceil(inclineur_total * 0.05)
            rows.append({
                "kind": "inclineur",
                "type": tp,
                "reference": "16657",
                "designation": "Inclineur (1 par rail 1320/1240/990/1187/908/650/535mm)",
                "quantite": inclineur_total,
                "spare": inclineur_spare,
                "total_plus_spare": inclineur_total + inclineur_spare,
            })

    # Ligne Dongle — éditable, pas de Spare ni Total+Spare
    rows.append({
        "kind": "dongle",
        "type": "Accessoire",
        "reference": "",
        "designation": "Dongle",
        "quantite": "",
        "spare": "",
        "total_plus_spare": "",
    })

    # 3 lignes vides
    for _ in range(3):
        rows.append({"kind": "empty", "type": "", "reference": "", "designation": "", "quantite": "", "spare": "", "total_plus_spare": ""})

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


def _parse_excel(contents: bytes) -> pd.DataFrame:
    """Parse un xlsx avec calamine (rapide) puis openpyxl en fallback."""
    try:
        df = pd.read_excel(io.BytesIO(contents), sheet_name=0, engine="calamine")
        logger.info(f"Parsed with calamine: {df.shape[0]} rows x {df.shape[1]} cols")
        return df
    except Exception as e_cal:
        logger.warning(f"Calamine failed ({e_cal}), falling back to openpyxl")
    try:
        df = pd.read_excel(io.BytesIO(contents), sheet_name=0)
        logger.info(f"Parsed with openpyxl: {df.shape[0]} rows x {df.shape[1]} cols")
        return df
    except Exception as e:
        logger.exception("Excel parse error")
        raise HTTPException(status_code=400, detail=f"Impossible de lire le fichier Excel : {e}")


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convertit en records JSON-safe (NaN/Inf -> None, Timestamps -> str)."""
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

    contents = await file.read()
    logger.info(f"Upload received: {file.filename}, {len(contents)} bytes")

    df = _parse_excel(contents)

    if df.empty:
        raise HTTPException(status_code=400, detail="Le fichier Excel est vide")

    # Détection colonnes
    cols = detect_columns(df)

    # Construire les onglets
    logger.info("Building recap rows...")
    recap_rows = build_recap_produits(df, cols)
    logger.info(f"Recap built: {len(recap_rows)} rows")
    logger.info("Building secteur rows...")
    secteur_rows = build_par_secteur(df, cols)
    logger.info(f"Secteur built: {len(secteur_rows)} rows")
    logger.info("Converting raw records...")
    raw_records = df_to_records(df)
    logger.info(f"Raw records: {len(raw_records)} rows")

    upload_id = str(uuid.uuid4())
    DATASTORE[upload_id] = {
        "filename": file.filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "columns": list(df.columns),
        "detected_cols": cols,
        "raw_records": raw_records,
        "recap_rows": recap_rows,
        "secteur_rows": secteur_rows,
        "comment": "",
    }

    # Persister le dataset complet en MongoDB (gzippé) pour multi-replica
    try:
        await persist_dataset(upload_id, DATASTORE[upload_id])
    except Exception as e:
        logger.warning(f"Mongo persist failed: {e}")

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "row_count": len(raw_records),
        "columns": list(df.columns),
        "data": {
            "recap": recap_rows,
            "secteur": secteur_rows,
            "comment_table": {
                "columns": ["Colonne 1", "Colonne 2", "Colonne 3", "Colonne 4", "Colonne 5"],
                "rows": [["", "", "", "", ""] for _ in range(8)],
            },
            # raw_records non inclus ici pour garder la réponse légère ;
            # le frontend les chargera à la demande via GET /api/dataset/{id}/raw
        },
        "stats": {
            "total_rows": len(raw_records),
            "types": sanitize_dict(df[cols["type"]].value_counts().to_dict()),
            "secteurs": sanitize_dict(df[cols["secteur"]].value_counts().to_dict()),
        }
    }


@api_router.get("/dataset/{upload_id}")
async def get_dataset(upload_id: str):
    """Récupère métadonnées + recap + secteur (PAS les raw records, voir /raw)."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    return {
        "upload_id": upload_id,
        "filename": d["filename"],
        "columns": d["columns"],
        "row_count": len(d["raw_records"]),
        "data": {
            "recap": d["recap_rows"],
            "secteur": d["secteur_rows"],
            "comment_table": d.get("comment_table") or {
                "columns": ["Colonne 1", "Colonne 2", "Colonne 3", "Colonne 4", "Colonne 5"],
                "rows": [["", "", "", "", ""] for _ in range(8)],
            },
        },
    }


@api_router.get("/dataset/{upload_id}/raw")
async def get_dataset_raw(upload_id: str):
    """Récupère les données brutes (~9 MB pour 19780 lignes, mais gzippé HTTP ~600 KB)."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    return {
        "upload_id": upload_id,
        "columns": d["columns"],
        "raw": d["raw_records"],
    }


class RecapRowUpdate(BaseModel):
    type: Optional[str] = ""
    reference: Optional[str] = ""
    designation: Optional[str] = ""
    quantite: Optional[Union[str, float, int]] = ""  # accepte str ou nombre, on convertit
    spare: Optional[Union[str, float, int]] = ""  # accepte str ou nombre, on convertit


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
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = d["recap_rows"]
    if index < 0 or index >= len(rows):
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    row = rows[index]
    if row["kind"] not in ("empty", "manual", "dongle"):
        raise HTTPException(status_code=400, detail="Cette ligne n'est pas éditable")
    is_dongle = row["kind"] == "dongle"

    new_type = (payload.type or "").strip()
    new_ref = (payload.reference or "").strip()
    new_desig = (payload.designation or "").strip()
    new_qty = _parse_quantite(payload.quantite)
    new_spare = _parse_quantite(payload.spare)

    # Auto-calcul du Spare = ceil(qty * 5%) si Quantité saisie et Spare vide/0
    # SAUF pour Dongle qui n'a pas de règle Spare
    if not is_dongle and isinstance(new_qty, (int, float)) and new_qty > 0 and (new_spare == "" or new_spare == 0):
        new_spare = math.ceil(float(new_qty) * 0.05)

    # Total + Spare auto-calculé (sauf pour Dongle qui reste vide)
    if is_dongle:
        new_total_plus_spare = ""
    elif isinstance(new_qty, (int, float)) and isinstance(new_spare, (int, float)):
        new_total_plus_spare = new_qty + new_spare
    elif isinstance(new_qty, (int, float)) and (new_spare == "" or new_spare == 0):
        new_total_plus_spare = new_qty
    else:
        new_total_plus_spare = ""

    # Si toutes les valeurs sont vides, on remet kind='empty'
    # (sauf pour la ligne Dongle qui reste 'dongle' même vide)
    is_empty = (
        not new_type and not new_ref and not new_desig
        and (new_qty == "" or new_qty == 0)
        and (new_spare == "" or new_spare == 0)
    )
    row["type"] = new_type
    row["reference"] = new_ref
    row["designation"] = new_desig
    row["quantite"] = new_qty
    row["spare"] = "" if is_dongle else new_spare
    row["total_plus_spare"] = new_total_plus_spare
    if not is_dongle:
        row["kind"] = "empty" if is_empty else "manual"
    # Re-persister
    try:
        await persist_recap_rows(upload_id, rows)
    except Exception as e:
        logger.warning(f"Mongo persist recap failed: {e}")
    return {"row": row, "index": index}


@api_router.post("/dataset/{upload_id}/recap-row")
async def add_recap_row(upload_id: str):
    """Ajoute une nouvelle ligne vide à la fin du récapitulatif."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = d["recap_rows"]
    new_row = {"kind": "empty", "type": "", "reference": "", "designation": "", "quantite": "", "spare": "", "total_plus_spare": ""}
    rows.append(new_row)
    try:
        await persist_recap_rows(upload_id, rows)
    except Exception as e:
        logger.warning(f"Mongo persist recap failed: {e}")
    return {"row": new_row, "index": len(rows) - 1}


@api_router.delete("/dataset/{upload_id}/recap-row/{index}")
async def delete_recap_row(upload_id: str, index: int):
    """Supprime une ligne manuelle ou vide du récapitulatif."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = d["recap_rows"]
    if index < 0 or index >= len(rows):
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    if rows[index]["kind"] not in ("empty", "manual"):
        raise HTTPException(status_code=400, detail="Seules les lignes manuelles peuvent être supprimées")
    rows.pop(index)
    try:
        await persist_recap_rows(upload_id, rows)
    except Exception as e:
        logger.warning(f"Mongo persist recap failed: {e}")
    return {"ok": True, "remaining": len(rows)}


class CommentTableUpdate(BaseModel):
    columns: list[str]
    rows: list[list[str]]


@api_router.patch("/dataset/{upload_id}/comment-table")
async def update_comment_table(upload_id: str, payload: CommentTableUpdate):
    """Met à jour le tableau de commentaires (colonnes + lignes)."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    d["comment_table"] = {"columns": payload.columns, "rows": payload.rows}
    try:
        await persist_comment_table(upload_id, d["comment_table"])
    except Exception as e:
        logger.warning(f"Mongo persist comment_table failed: {e}")
    return {"ok": True, "comment_table": d["comment_table"]}


def _detect_element_col(columns: list[str]) -> Optional[str]:
    """Trouve la colonne 'N° élément' / Gondole dans les données brutes (insensible à la casse)."""
    candidates = ["N° élément", "N° element", "Élément", "Element", "N° gondole", "Gondole"]
    lower_map = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def _allee_sort_key(v):
    """Trie les allées numériquement quand possible."""
    if v is None or v == "":
        return (1, "")
    try:
        return (0, float(str(v).replace(",", ".")))
    except (ValueError, TypeError):
        return (1, str(v))


def _write_par_secteur_sheets(workbook, writer, d, fmt_header, fmt_cell, fmt_total, fmt_inclineur):
    """Génère 2 feuilles :
      - "Par Secteur" : tableau plat (1 ligne / produit) avec autofilter Excel
      - "Par Secteur (Hiérarchie)" : structure repliable Secteur > Rayon > Allée > Gondole > Produits
    """
    raw_records = d.get("raw_records", []) or []
    if not raw_records:
        return

    columns = list(raw_records[0].keys())
    cols = {
        "secteur": next((c for c in ["Secteur"] if c in columns), None),
        "rayon": next((c for c in ["Rayon"] if c in columns), None),
        "allee": next((c for c in ["N° allée", "N° allee", "Allée", "Allee"] if c in columns), None),
        "type": next((c for c in ["Type"] if c in columns), None),
        "designation": next((c for c in ["Désignation", "Designation"] if c in columns), None),
        "quantite": next((c for c in ["Quantité", "Quantite"] if c in columns), None),
    }
    element_col = _detect_element_col(columns)

    # ----- 1) Feuille plate "Par Secteur" -----
    ws = workbook.add_worksheet("Par Secteur")
    writer.sheets["Par Secteur"] = ws
    flat_headers = ["Secteur", "Rayon", "N° Allée", "N° Gondole", "Type", "Désignation", "Quantité"]
    for ci, h in enumerate(flat_headers):
        ws.write(0, ci, h, fmt_header)

    def _norm(v):
        if v is None:
            return ""
        try:
            if isinstance(v, float) and math.isnan(v):
                return ""
        except (TypeError, ValueError):
            pass
        return v

    flat_rows = []
    for r in raw_records:
        flat_rows.append({
            "secteur": _norm(r.get(cols["secteur"])) if cols["secteur"] else "",
            "rayon": _norm(r.get(cols["rayon"])) if cols["rayon"] else "",
            "allee": _norm(r.get(cols["allee"])) if cols["allee"] else "",
            "element": _norm(r.get(element_col)) if element_col else "",
            "type": _norm(r.get(cols["type"])) if cols["type"] else "",
            "designation": _norm(r.get(cols["designation"])) if cols["designation"] else "",
            "quantite": _norm(r.get(cols["quantite"])) if cols["quantite"] else "",
        })
    # Tri stable pour faciliter la lecture
    flat_rows.sort(key=lambda x: (
        str(x["secteur"]),
        str(x["rayon"]),
        _allee_sort_key(x["allee"]),
        _allee_sort_key(x["element"]),
        str(x["type"]),
        str(x["designation"]),
    ))

    def _write_num_or_str(ws, row, col, val, fmt):
        if val == "" or val is None:
            ws.write(row, col, "", fmt)
            return
        try:
            num = float(val)
            if num.is_integer():
                ws.write_number(row, col, int(num), fmt)
            else:
                ws.write_number(row, col, num, fmt)
        except (ValueError, TypeError):
            ws.write(row, col, str(val), fmt)

    for ri, fr in enumerate(flat_rows, start=1):
        ws.write(ri, 0, str(fr["secteur"]) if fr["secteur"] != "" else "", fmt_cell)
        ws.write(ri, 1, str(fr["rayon"]) if fr["rayon"] != "" else "", fmt_cell)
        _write_num_or_str(ws, ri, 2, fr["allee"], fmt_cell)
        _write_num_or_str(ws, ri, 3, fr["element"], fmt_cell)
        ws.write(ri, 4, str(fr["type"]) if fr["type"] != "" else "", fmt_cell)
        ws.write(ri, 5, str(fr["designation"]) if fr["designation"] != "" else "", fmt_cell)
        _write_num_or_str(ws, ri, 6, fr["quantite"], fmt_cell)

    ws.set_column(0, 0, 14)
    ws.set_column(1, 1, 18)
    ws.set_column(2, 3, 12)
    ws.set_column(4, 4, 12)
    ws.set_column(5, 5, 50)
    ws.set_column(6, 6, 10)
    if flat_rows:
        ws.autofilter(0, 0, len(flat_rows), len(flat_headers) - 1)
        ws.freeze_panes(1, 0)

    # ----- 2) Feuille hiérarchique "Par Secteur (Hiérarchie)" -----
    ws2 = workbook.add_worksheet("Par Secteur (Hiérarchie)")
    writer.sheets["Par Secteur (Hiérarchie)"] = ws2

    fmt_sec = workbook.add_format({"bold": True, "bg_color": "#056839", "font_color": "white", "border": 1, "font_size": 11})
    fmt_ray = workbook.add_format({"bold": True, "bg_color": "#D1FAE5", "font_color": "#064E3B", "border": 1})
    fmt_all = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "font_color": "#78350F", "border": 1})
    fmt_gon = workbook.add_format({"italic": True, "bg_color": "#F3F4F6", "font_color": "#1F2937", "border": 1})
    fmt_prd = workbook.add_format({"border": 1})
    fmt_qty = workbook.add_format({"border": 1, "align": "right"})

    # Construction de l'arbre
    from collections import defaultdict
    tree = {}
    for fr in flat_rows:
        s = str(fr["secteur"]) if fr["secteur"] != "" else "—"
        ra = str(fr["rayon"]) if fr["rayon"] != "" else "—"
        al = fr["allee"] if fr["allee"] != "" else "—"
        el = fr["element"] if fr["element"] != "" else "—"
        try:
            qty = float(fr["quantite"]) if fr["quantite"] not in ("", None) else 0
        except (ValueError, TypeError):
            qty = 0
        tree.setdefault(s, {}).setdefault(ra, {}).setdefault(al, {}).setdefault(el, []).append({
            "type": str(fr["type"]) if fr["type"] != "" else "",
            "designation": str(fr["designation"]) if fr["designation"] != "" else "",
            "qty": qty,
        })

    h_headers = ["Niveau", "Libellé", "Détail", "Quantité"]
    for ci, h in enumerate(h_headers):
        ws2.write(0, ci, h, fmt_header)

    row = 1
    for secteur in sorted(tree.keys(), key=str):
        rayons = tree[secteur]
        sec_total = sum(p["qty"] for ra in rayons.values() for al in ra.values() for el in al.values() for p in el)
        nb_gondoles_sec = sum(len(al) for ra in rayons.values() for al in ra.values())
        ws2.write(row, 0, "Secteur", fmt_sec)
        ws2.write(row, 1, secteur, fmt_sec)
        ws2.write(row, 2, f"{len(rayons)} rayon(s) · {nb_gondoles_sec} gondole(s)", fmt_sec)
        ws2.write_number(row, 3, sec_total, fmt_sec)
        row += 1
        for rayon in sorted(rayons.keys(), key=str):
            allees = rayons[rayon]
            ray_total = sum(p["qty"] for al in allees.values() for el in al.values() for p in el)
            nb_gondoles_ray = sum(len(al) for al in allees.values())
            ws2.write(row, 0, "  Rayon", fmt_ray)
            ws2.write(row, 1, rayon, fmt_ray)
            ws2.write(row, 2, f"{len(allees)} allée(s) · {nb_gondoles_ray} gondole(s)", fmt_ray)
            ws2.write_number(row, 3, ray_total, fmt_ray)
            row += 1
            for allee in sorted(allees.keys(), key=_allee_sort_key):
                elements = allees[allee]
                al_total = sum(p["qty"] for el in elements.values() for p in el)
                ws2.write(row, 0, "    Allée", fmt_all)
                ws2.write(row, 1, f"Allée {allee}", fmt_all)
                ws2.write(row, 2, f"{len(elements)} gondole(s)", fmt_all)
                ws2.write_number(row, 3, al_total, fmt_all)
                row += 1
                for element in sorted(elements.keys(), key=_allee_sort_key):
                    products = elements[element]
                    el_total = sum(p["qty"] for p in products)
                    ws2.write(row, 0, "      Gondole", fmt_gon)
                    ws2.write(row, 1, f"Gondole {element}", fmt_gon)
                    ws2.write(row, 2, f"{len(products)} produit(s)", fmt_gon)
                    ws2.write_number(row, 3, el_total, fmt_gon)
                    row += 1
                    # Agréger les produits par (type, désignation) pour éviter les doublons visuels
                    agg = defaultdict(float)
                    for p in products:
                        agg[(p["type"], p["designation"])] += p["qty"]
                    for (typ, desig), q in sorted(agg.items()):
                        ws2.write(row, 0, "        ", fmt_prd)
                        ws2.write(row, 1, typ, fmt_prd)
                        ws2.write(row, 2, desig, fmt_prd)
                        ws2.write_number(row, 3, q, fmt_qty)
                        row += 1

    ws2.set_column(0, 0, 14)
    ws2.set_column(1, 1, 28)
    ws2.set_column(2, 2, 48)
    ws2.set_column(3, 3, 12)
    if row > 1:
        ws2.freeze_panes(1, 0)




@api_router.get("/export/{upload_id}")
async def export_excel(upload_id: str, sheet: str = "all"):
    """Exporte le fichier Excel généré.

    sheet : 'all' | 'raw' | 'recap' | 'secteur' | 'parsecteur' | 'comment'
    """
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")

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
        fmt_inclineur = workbook.add_format({
            "bold": True, "bg_color": "#DBEAFE", "border": 1
        })
        fmt_cell = workbook.add_format({"border": 1})

        if sheet in ("all", "raw"):
            df_raw = pd.DataFrame(d["raw_records"])
            df_raw.to_excel(writer, sheet_name="Données", index=False)
            ws_raw = writer.sheets["Données"]
            if len(df_raw) > 0:
                # Active les filtres Excel natifs sur toutes les colonnes
                ws_raw.autofilter(0, 0, len(df_raw), max(0, len(df_raw.columns) - 1))
                ws_raw.freeze_panes(1, 0)

        if sheet in ("all", "recap"):
            recap = d["recap_rows"]
            ws = workbook.add_worksheet("Récapitulatif")
            writer.sheets["Récapitulatif"] = ws
            headers = ["Type", "Référence", "Désignation", "Quantité", "Spare (+5%)", "Total + Spare"]
            for col_i, h in enumerate(headers):
                ws.write(0, col_i, h, fmt_header)
            for row_i, r in enumerate(recap, start=1):
                kind = r["kind"]
                if kind == "header":
                    fmt = fmt_total
                elif kind == "inclineur":
                    fmt = fmt_inclineur
                else:
                    fmt = fmt_cell
                ws.write(row_i, 0, r["type"], fmt)
                ws.write(row_i, 1, r["reference"], fmt)
                ws.write(row_i, 2, r["designation"], fmt)
                ws.write(row_i, 3, r["quantite"] if r["quantite"] != "" else "", fmt)
                ws.write(row_i, 4, r.get("spare", "") if r.get("spare", "") != "" else "", fmt)
                ws.write(row_i, 5, r.get("total_plus_spare", "") if r.get("total_plus_spare", "") != "" else "", fmt)
            ws.set_column(0, 0, 12)
            ws.set_column(1, 1, 14)
            ws.set_column(2, 2, 50)
            ws.set_column(3, 3, 12)
            ws.set_column(4, 4, 14)
            ws.set_column(5, 5, 16)
            if len(recap) > 0:
                ws.autofilter(0, 0, len(recap), 5)
                ws.freeze_panes(1, 0)

        if sheet in ("all", "secteur"):
            secteur = d["secteur_rows"]
            ws = workbook.add_worksheet("Phasage")
            writer.sheets["Phasage"] = ws
            headers = ["Secteur", "Rayon", "N° Allée", "EEG ES", "EEG SA", "Rails", "Caméras"]
            for col_i, h in enumerate(headers):
                ws.write(0, col_i, h, fmt_header)
            for row_i, r in enumerate(secteur, start=1):
                ws.write(row_i, 0, r["secteur"], fmt_cell)
                ws.write(row_i, 1, r["rayon"], fmt_cell)
                # N° Allée : convertir en nombre si possible pour permettre le tri numérique dans Excel
                allee_val = r["allee"]
                try:
                    allee_num = int(allee_val) if str(allee_val).isdigit() else float(allee_val)
                    ws.write_number(row_i, 2, allee_num, fmt_cell)
                except (ValueError, TypeError):
                    ws.write(row_i, 2, allee_val, fmt_cell)
                ws.write(row_i, 3, r["nb_eeg_es"], fmt_cell)
                ws.write(row_i, 4, r["nb_eeg_sa"], fmt_cell)
                ws.write(row_i, 5, r["nb_rail"], fmt_cell)
                ws.write(row_i, 6, r["nb_camera"], fmt_cell)
            ws.set_column(0, 1, 14)
            ws.set_column(2, 6, 12)
            if len(secteur) > 0:
                ws.autofilter(0, 0, len(secteur), 6)
                ws.freeze_panes(1, 0)

        if sheet in ("all", "parsecteur"):
            _write_par_secteur_sheets(workbook, writer, d, fmt_header, fmt_cell, fmt_total, fmt_inclineur)


        if sheet in ("all", "comment"):
            ct = d.get("comment_table") or {"columns": [], "rows": []}
            ws = workbook.add_worksheet("Commentaire")
            writer.sheets["Commentaire"] = ws
            cols_ct = ct.get("columns", [])
            rows_ct = ct.get("rows", [])
            for ci, h in enumerate(cols_ct):
                ws.write(0, ci, h, fmt_header)
            cell_fmt = workbook.add_format({"border": 1, "text_wrap": True, "valign": "top"})
            for ri, row in enumerate(rows_ct, start=1):
                for ci, v in enumerate(row):
                    ws.write(ri, ci, v or "", cell_fmt)
            if cols_ct:
                ws.set_column(0, len(cols_ct) - 1, 25)
            if len(rows_ct) > 0 and len(cols_ct) > 0:
                ws.autofilter(0, 0, len(rows_ct), len(cols_ct) - 1)
                ws.freeze_panes(1, 0)

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


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
