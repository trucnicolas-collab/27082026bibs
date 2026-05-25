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


async def persist_phasage(upload_id: str, phasage: dict):
    """Met à jour uniquement le phasage de pose en base."""
    if upload_id not in DATASTORE:
        return
    doc = await db.datasets.find_one({"upload_id": upload_id}, {"payload": 1, "_id": 0})
    if not doc:
        await persist_dataset(upload_id, DATASTORE[upload_id])
        return
    payload = json.loads(gzip.decompress(doc["payload"]).decode("utf-8"))
    payload["phasage"] = phasage
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


# === PHASAGE DE POSE ==========================================================

# Liste exacte des désignations comptées comme "Rails ES" (substring, casse insensible)
RAILS_ES_PATTERNS = [
    "1187 mm (noir)",
    "1240 mm (noir)",
    "1320 mm (blanc)",
    "1320 mm (noir)",
    "650 mm (noir)",
    "990 mm (blanc)",
    "990 mm (noir)",
]


def _norm_desig(s: Any) -> str:
    if s is None:
        return ""
    try:
        if isinstance(s, float) and math.isnan(s):
            return ""
    except (TypeError, ValueError):
        pass
    return str(s).strip().lower()


def _is_es_15(desig: str) -> bool:
    """Détecte 'ES 1.5' (insensible à la casse, accepte virgule décimale)."""
    d = _norm_desig(desig)
    return "es 1.5" in d or "es 1,5" in d


def _is_es_21(desig: str) -> bool:
    d = _norm_desig(desig)
    return "es 2.1" in d or "es 2,1" in d


def _is_rail_es(desig: str) -> bool:
    """Vérifie si la désignation contient une des longueurs de rail ES."""
    d = _norm_desig(desig)
    if not d:
        return False
    for pat in RAILS_ES_PATTERNS:
        if pat.lower() in d:
            return True
    return False


def compute_phasage_summary(d: dict) -> dict:
    """Pour chaque allée du dataset, calcule les comptes ES 1.5 / ES 2.1 / Rails ES,
    ainsi que les totaux globaux. Retourne un dict prêt à servir au frontend.
    """
    raw_records = d.get("raw_records", []) or []
    if not raw_records:
        return {"allees": [], "totals": {"es_15": 0, "es_21": 0, "rails_es": 0, "rails_es_by_desig": {}}}

    columns = list(raw_records[0].keys())
    # Détection colonnes
    secteur_col = next((c for c in ["Secteur"] if c in columns), None)
    rayon_col = next((c for c in ["Rayon"] if c in columns), None)
    allee_col = next((c for c in ["N° allée", "N° allee", "Allée", "Allee"] if c in columns), None)
    type_col = next((c for c in ["Type"] if c in columns), None)
    desig_col = next((c for c in ["Désignation", "Designation"] if c in columns), None)
    qty_col = next((c for c in ["Quantité", "Quantite"] if c in columns), None)

    # Agrégation par allée (clé = str de l'allée)
    by_allee: dict[str, dict] = {}
    totals = {"es_15": 0.0, "es_21": 0.0, "rails_es": 0.0, "rails_es_by_desig": {p: 0.0 for p in RAILS_ES_PATTERNS}}

    for r in raw_records:
        allee_raw = r.get(allee_col) if allee_col else None
        if allee_raw is None or (isinstance(allee_raw, float) and math.isnan(allee_raw)):
            continue
        # Normalisation : 1.0 -> "1"
        try:
            f = float(allee_raw)
            if f.is_integer():
                allee_key = str(int(f))
            else:
                allee_key = str(allee_raw)
        except (ValueError, TypeError):
            allee_key = str(allee_raw).strip()

        typ = str(r.get(type_col) or "").strip() if type_col else ""
        desig = str(r.get(desig_col) or "") if desig_col else ""
        try:
            qty = float(r.get(qty_col) or 0) if qty_col else 0
        except (ValueError, TypeError):
            qty = 0

        node = by_allee.setdefault(allee_key, {
            "allee": allee_key,
            "secteur": str(r.get(secteur_col) or "") if secteur_col else "",
            "rayon": str(r.get(rayon_col) or "") if rayon_col else "",
            "es_15": 0.0,
            "es_21": 0.0,
            "rails_es": 0.0,
            "rails_es_by_desig": {p: 0.0 for p in RAILS_ES_PATTERNS},
        })

        is_eeg = typ.lower() == "eeg"
        is_rail = typ.lower() == "rail"
        if is_eeg and _is_es_15(desig):
            node["es_15"] += qty
            totals["es_15"] += qty
        elif is_eeg and _is_es_21(desig):
            node["es_21"] += qty
            totals["es_21"] += qty
        elif is_rail and _is_rail_es(desig):
            node["rails_es"] += qty
            totals["rails_es"] += qty
            # détection précise du pattern pour le breakdown
            d_low = _norm_desig(desig)
            for pat in RAILS_ES_PATTERNS:
                if pat.lower() in d_low:
                    node["rails_es_by_desig"][pat] += qty
                    totals["rails_es_by_desig"][pat] += qty
                    break

    # Tri "logique" : Secteur > Rayon > N° allée numérique
    def _sort_key(v):
        try:
            return (str(v["secteur"]), str(v["rayon"]), (0, float(str(v["allee"]).replace(",", "."))))
        except (ValueError, TypeError):
            return (str(v["secteur"]), str(v["rayon"]), (1, str(v["allee"])))

    allees = sorted(by_allee.values(), key=_sort_key)
    # Round pour transit JSON propre
    def _r(x):
        try:
            f = float(x)
            return int(f) if f.is_integer() else round(f, 2)
        except (ValueError, TypeError):
            return 0
    for a in allees:
        a["es_15"] = _r(a["es_15"])
        a["es_21"] = _r(a["es_21"])
        a["rails_es"] = _r(a["rails_es"])
        a["rails_es_by_desig"] = {k: _r(v) for k, v in a["rails_es_by_desig"].items()}
    totals = {
        "es_15": _r(totals["es_15"]),
        "es_21": _r(totals["es_21"]),
        "rails_es": _r(totals["rails_es"]),
        "rails_es_by_desig": {k: _r(v) for k, v in totals["rails_es_by_desig"].items()},
    }

    return {
        "allees": allees,
        "totals": totals,
        "rails_es_patterns": RAILS_ES_PATTERNS,
    }


@api_router.get("/dataset/{upload_id}/phasage-summary")
async def get_phasage_summary(upload_id: str):
    """Retourne la liste des allées avec leurs comptes ES 1.5 / ES 2.1 / Rails ES
    + les totaux globaux pour l'onglet Phasage de pose."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    summary = compute_phasage_summary(d)
    summary["phasage"] = d.get("phasage") or {"nb_nuits": 3, "rows": []}
    return summary


class PhasageRow(BaseModel):
    id: str
    allee: str = ""
    nuit: Optional[int] = None


class PhasageUpdate(BaseModel):
    nb_nuits: int
    rows: list[PhasageRow]


@api_router.patch("/dataset/{upload_id}/phasage")
async def update_phasage(upload_id: str, payload: PhasageUpdate):
    """Sauvegarde l'état du tableau de phasage (nb nuits + assignations)."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    nb = max(1, min(int(payload.nb_nuits), 30))
    rows = [{"id": r.id, "allee": r.allee or "", "nuit": r.nuit if r.nuit and 1 <= r.nuit <= nb else None}
            for r in payload.rows]
    d["phasage"] = {"nb_nuits": nb, "rows": rows}
    try:
        await persist_phasage(upload_id, d["phasage"])
    except Exception as e:
        logger.warning(f"Mongo persist phasage failed: {e}")
    return {"ok": True, "phasage": d["phasage"]}



def _write_phasage_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total):
    """Génère la feuille "Phasage de pose" avec :
      - En-tête : nb nuits, moyenne/nuit (ES1.5+ES2.1)
      - Bloc totaux globaux (ES 1.5, ES 2.1, breakdown rails ES par longueur)
      - Tableau gauche : assignations allée -> nuit (avec comptes auto)
      - Tableau droite : agrégation par nuit
    """
    summary = compute_phasage_summary(d)
    phasage = d.get("phasage") or {"nb_nuits": 3, "rows": []}
    nb_nuits = max(1, int(phasage.get("nb_nuits") or 3))
    rows_assign = phasage.get("rows") or []

    ws = workbook.add_worksheet("Phasage de pose")
    writer.sheets["Phasage de pose"] = ws
    ws.set_column(0, 0, 12)
    ws.set_column(1, 1, 14)
    ws.set_column(2, 2, 14)
    ws.set_column(3, 3, 14)
    ws.set_column(4, 4, 12)
    ws.set_column(5, 5, 4)
    ws.set_column(6, 6, 10)
    ws.set_column(7, 7, 32)
    ws.set_column(8, 8, 14)
    ws.set_column(9, 9, 14)
    ws.set_column(10, 10, 14)

    fmt_title = workbook.add_format({"bold": True, "bg_color": "#056839", "font_color": "white",
                                     "border": 1, "font_size": 12, "align": "left"})
    fmt_lbl = workbook.add_format({"bold": True, "bg_color": "#F3F4F6", "border": 1, "align": "left"})
    fmt_num = workbook.add_format({"border": 1, "align": "right"})
    fmt_total_row = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right"})
    fmt_total_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "left"})

    totals = summary["totals"]
    avg_per_night = (totals["es_15"] + totals["es_21"]) / nb_nuits if nb_nuits else 0

    ws.merge_range(0, 0, 0, 9, "Phasage de pose des étiquettes (ES 1.5 / ES 2.1)", fmt_title)
    ws.write(1, 0, "Nb nuits :", fmt_lbl)
    ws.write_number(1, 1, nb_nuits, fmt_num)
    ws.write(1, 2, "Moyenne/nuit :", fmt_lbl)
    ws.write_number(1, 3, round(avg_per_night, 1), fmt_num)
    ws.write(1, 4, "(ES1.5 + ES2.1) / nb nuits", workbook.add_format({"italic": True, "border": 1, "font_color": "#6B7280"}))

    ws.write(3, 0, "Total ES 1.5", fmt_lbl)
    ws.write_number(3, 1, totals["es_15"], fmt_num)
    ws.write(3, 2, "Total ES 2.1", fmt_lbl)
    ws.write_number(3, 3, totals["es_21"], fmt_num)
    ws.write(3, 4, "Total Rails ES", fmt_lbl)
    ws.write_number(3, 6, totals["rails_es"], fmt_num)

    ws.write(5, 0, "Rails ES par désignation :", fmt_lbl)
    r = 6
    for pat in RAILS_ES_PATTERNS:
        ws.write(r, 0, pat, fmt_cell)
        ws.write_number(r, 1, totals["rails_es_by_desig"].get(pat, 0), fmt_num)
        r += 1

    start_left = r + 2
    ws.merge_range(start_left, 0, start_left, 4, "Plan d'attribution par allée", fmt_title)
    headers_left = ["N° Allée", "ES 1.5", "ES 2.1", "Rails ES", "Nuit"]
    for ci, h in enumerate(headers_left):
        ws.write(start_left + 1, ci, h, fmt_lbl)

    allee_index = {str(a["allee"]): a for a in summary["allees"]}

    night_totals = {n: {"es_15": 0.0, "es_21": 0.0, "rails_es": 0.0} for n in range(1, nb_nuits + 1)}
    rr = start_left + 2
    for row in rows_assign:
        allee = str(row.get("allee") or "").strip()
        nuit = row.get("nuit")
        node = allee_index.get(allee)
        es15 = node["es_15"] if node else 0
        es21 = node["es_21"] if node else 0
        rails = node["rails_es"] if node else 0
        try:
            ws.write_number(rr, 0, int(allee), fmt_cell)
        except (ValueError, TypeError):
            ws.write(rr, 0, allee, fmt_cell)
        ws.write_number(rr, 1, es15, fmt_num)
        ws.write_number(rr, 2, es21, fmt_num)
        ws.write_number(rr, 3, rails, fmt_num)
        if nuit and 1 <= int(nuit) <= nb_nuits:
            ws.write(rr, 4, f"Nuit {int(nuit)}", fmt_num)
            night_totals[int(nuit)]["es_15"] += es15
            night_totals[int(nuit)]["es_21"] += es21
            night_totals[int(nuit)]["rails_es"] += rails
        else:
            ws.write(rr, 4, "—", fmt_num)
        rr += 1

    col_right = 6
    ws.merge_range(start_left, col_right, start_left, col_right + 4, "Récap par nuit", fmt_title)
    headers_right = ["Nuit", "Allées", "ES 1.5", "ES 2.1", "Rails ES"]
    for ci, h in enumerate(headers_right):
        ws.write(start_left + 1, col_right + ci, h, fmt_lbl)
    night_allees: dict[int, list[str]] = {n: [] for n in range(1, nb_nuits + 1)}
    for row in rows_assign:
        allee = str(row.get("allee") or "").strip()
        nuit = row.get("nuit")
        if allee and nuit and 1 <= int(nuit) <= nb_nuits:
            night_allees[int(nuit)].append(allee)
    # Tri num des allées par nuit
    def _sort_allee(a):
        try:
            return (0, float(str(a).replace(",", ".")))
        except (ValueError, TypeError):
            return (1, str(a))
    total_es15 = 0
    total_es21 = 0
    total_rails = 0
    for i, n in enumerate(range(1, nb_nuits + 1), start=0):
        rrow = start_left + 2 + i
        allees_list = sorted(night_allees[n], key=_sort_allee)
        ws.write(rrow, col_right + 0, f"Nuit {n}", fmt_cell)
        ws.write(rrow, col_right + 1, ", ".join(allees_list) if allees_list else "—", fmt_cell)
        ws.write_number(rrow, col_right + 2, round(night_totals[n]["es_15"], 2), fmt_num)
        ws.write_number(rrow, col_right + 3, round(night_totals[n]["es_21"], 2), fmt_num)
        ws.write_number(rrow, col_right + 4, round(night_totals[n]["rails_es"], 2), fmt_num)
        total_es15 += night_totals[n]["es_15"]
        total_es21 += night_totals[n]["es_21"]
        total_rails += night_totals[n]["rails_es"]
    rrow_total = start_left + 2 + nb_nuits
    ws.write(rrow_total, col_right + 0, "TOTAL", fmt_total_lbl)
    ws.write(rrow_total, col_right + 1, f"{sum(len(v) for v in night_allees.values())} allées", fmt_total_lbl)
    ws.write_number(rrow_total, col_right + 2, round(total_es15, 2), fmt_total_row)
    ws.write_number(rrow_total, col_right + 3, round(total_es21, 2), fmt_total_row)
    ws.write_number(rrow_total, col_right + 4, round(total_rails, 2), fmt_total_row)





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
    """Génère 2 feuilles "Par Secteur" :
      - "Par Secteur (rayon)"  : tableau par rayon — colonnes produits = désignations présentes dans CE rayon
      - "Par Secteur (global)" : tableau par rayon — colonnes produits = TOUTES les désignations du fichier

    Layout pour chaque rayon (les 2 feuilles partagent ce layout) :
        Secteur : XXX
        Rayon : YYY
        | N° Allée | Nbr éléments | <Désignation 1> | <Désignation 2> | ... |
        |    1     |      23      |       12        |       4         | ... |
        |    2     |      18      |       ...       |       ...       | ... |
        | TOTAL    |     SOMME    |       ...       |       ...       | ... |

    "Nbr éléments" = nombre de valeurs distinctes de la colonne G (élément/gondole) pour cette allée.
    """
    from collections import defaultdict
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
    # "Élément" = colonne G du fichier d'origine = identifiant unique de la gondole
    element_col = _detect_element_col(columns)
    if element_col is None and len(columns) >= 7:
        element_col = columns[6]  # fallback colonne G

    def _s(v):
        if v is None:
            return ""
        try:
            if isinstance(v, float) and math.isnan(v):
                return ""
        except (TypeError, ValueError):
            pass
        return str(v).strip()

    # ---- Agrégation ----
    # tree[secteur][rayon] = {
    #   "allees": { allee: { "elements": set(), "byDesig": {desig: qty} } },
    #   "desigs": { desig: type }
    # }
    tree: dict = {}
    all_desigs: dict = {}  # désignation -> type (pour tri)
    for r in raw_records:
        s = _s(r.get(cols["secteur"])) or "—"
        ra = _s(r.get(cols["rayon"])) or "—"
        al = _s(r.get(cols["allee"])) or "—"
        el = _s(r.get(element_col)) if element_col else ""
        typ = _s(r.get(cols["type"])) if cols["type"] else ""
        desig = _s(r.get(cols["designation"])) if cols["designation"] else ""
        try:
            qty = float(r.get(cols["quantite"]) or 0) if cols["quantite"] else 0
        except (ValueError, TypeError):
            qty = 0

        sect_d = tree.setdefault(s, {})
        ray_d = sect_d.setdefault(ra, {"allees": {}, "desigs": {}})
        if desig:
            ray_d["desigs"].setdefault(desig, typ)
            all_desigs.setdefault(desig, typ)
        al_d = ray_d["allees"].setdefault(al, {"elements": set(), "byDesig": defaultdict(float)})
        if el:
            al_d["elements"].add(el)
        if desig:
            al_d["byDesig"][desig] += qty

    # Tri global des désignations (Type, puis Désignation)
    global_desigs_sorted = [d_ for d_, _t in sorted(all_desigs.items(), key=lambda kv: (kv[1], kv[0]))]

    # Formats spécifiques
    fmt_sec_hdr = workbook.add_format({"bold": True, "bg_color": "#056839", "font_color": "white",
                                       "border": 1, "font_size": 11, "align": "left"})
    fmt_ray_hdr = workbook.add_format({"bold": True, "bg_color": "#D1FAE5", "font_color": "#064E3B",
                                       "border": 1, "align": "left"})
    fmt_col_hdr = workbook.add_format({"bold": True, "bg_color": "#F3F4F6", "border": 1,
                                       "align": "center", "text_wrap": True, "valign": "vcenter"})
    fmt_total_row = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right"})
    fmt_total_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "left"})
    fmt_num = workbook.add_format({"border": 1, "align": "right"})
    fmt_allee = workbook.add_format({"border": 1, "align": "center"})

    def _write_rayon_block(ws, start_row: int, secteur: str, rayon: str, ray_node: dict, prod_cols: list[str]) -> int:
        """Écrit un bloc de rayon en commençant à start_row. Retourne la prochaine ligne libre."""
        nb_total_cols = 2 + len(prod_cols)
        # Ligne 1 : Secteur
        ws.merge_range(start_row, 0, start_row, max(0, nb_total_cols - 1),
                       f"Secteur : {secteur}", fmt_sec_hdr) if nb_total_cols > 1 else ws.write(start_row, 0, f"Secteur : {secteur}", fmt_sec_hdr)
        # Ligne 2 : Rayon
        ws.merge_range(start_row + 1, 0, start_row + 1, max(0, nb_total_cols - 1),
                       f"Rayon : {rayon}", fmt_ray_hdr) if nb_total_cols > 1 else ws.write(start_row + 1, 0, f"Rayon : {rayon}", fmt_ray_hdr)
        # Ligne 3 : en-têtes colonnes
        ws.write(start_row + 2, 0, "N° Allée", fmt_col_hdr)
        ws.write(start_row + 2, 1, "Nbr éléments", fmt_col_hdr)
        for ci, dname in enumerate(prod_cols):
            ws.write(start_row + 2, 2 + ci, dname, fmt_col_hdr)

        # Lignes : 1 par allée
        allees = ray_node["allees"]
        sorted_allees = sorted(allees.keys(), key=_allee_sort_key)
        r = start_row + 3
        total_nb = 0
        total_by_desig = {d_: 0.0 for d_ in prod_cols}
        for allee in sorted_allees:
            node = allees[allee]
            # N° Allée
            try:
                ws.write_number(r, 0, float(allee) if "." in str(allee) else int(allee), fmt_allee)
            except (ValueError, TypeError):
                ws.write(r, 0, str(allee), fmt_allee)
            nb = len(node["elements"])
            ws.write_number(r, 1, nb, fmt_num)
            total_nb += nb
            for ci, dname in enumerate(prod_cols):
                v = node["byDesig"].get(dname, 0)
                if v:
                    ws.write_number(r, 2 + ci, v, fmt_num)
                    total_by_desig[dname] += v
                else:
                    ws.write(r, 2 + ci, "", fmt_num)
            r += 1
        # Ligne TOTAL
        ws.write(r, 0, "TOTAL", fmt_total_lbl)
        ws.write_number(r, 1, total_nb, fmt_total_row)
        for ci, dname in enumerate(prod_cols):
            v = total_by_desig[dname]
            if v:
                ws.write_number(r, 2 + ci, v, fmt_total_row)
            else:
                ws.write(r, 2 + ci, "", fmt_total_row)
        r += 1
        # ligne vide entre 2 rayons
        return r + 1

    def _write_sheet(sheet_name: str, mode: str):
        ws = workbook.add_worksheet(sheet_name)
        writer.sheets[sheet_name] = ws
        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 13)
        # largeur produits
        ws.set_column(2, 200, 16)

        row = 0
        for secteur in sorted(tree.keys(), key=str):
            rayons = tree[secteur]
            for rayon in sorted(rayons.keys(), key=str):
                ray_node = rayons[rayon]
                if mode == "global":
                    prod_cols = global_desigs_sorted
                else:
                    # Désignations de ce rayon, triées par Type puis Désignation
                    prod_cols = [
                        d_ for d_, _t in sorted(ray_node["desigs"].items(), key=lambda kv: (kv[1], kv[0]))
                    ]
                row = _write_rayon_block(ws, row, secteur, rayon, ray_node, prod_cols)
        if row == 0:
            ws.write(0, 0, "Aucune donnée", fmt_header)

    _write_sheet("Par Secteur (rayon)", "rayon")
    _write_sheet("Par Secteur (global)", "global")




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

        if sheet in ("all", "phasage"):
            _write_phasage_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

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
