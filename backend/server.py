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
from collections import Counter
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
    depuis n'importe quel replica K8s.

    Architecture : le gros `payload` (raw_records, ~20k lignes) est gzippé une seule fois.
    Les champs éditables (recap_rows, comment_table, phasage) sont stockés en CHAMPS
    SÉPARÉS pour éviter de re-sérialiser tout le payload à chaque édition (OOM en prod).
    """
    default_comment = {
        "columns": ["Colonne 1", "Colonne 2", "Colonne 3", "Colonne 4", "Colonne 5"],
        "rows": [["", "", "", "", ""] for _ in range(8)],
    }
    payload = {
        "filename": data["filename"],
        "uploaded_at": data["uploaded_at"],
        "columns": data["columns"],
        "detected_cols": data["detected_cols"],
        "raw_records": data["raw_records"],
        "secteur_rows": data["secteur_rows"],
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
            # Champs éditables stockés EN CLAIR (petits) — update O(1)
            "recap_rows": data["recap_rows"],
            "comment_table": data.get("comment_table") or default_comment,
            "phasage": data.get("phasage") or {
                "es": {"nb_nuits": 3, "rows": []},
                "cam": {"nb_nuits": 3, "rows": [], "start_at_nuit": 5},
                "suivi": {"rows": []},
            },
            "surface_category": data.get("surface_category"),
        },
        upsert=True,
    )


async def persist_recap_rows(upload_id: str, recap_rows: list[dict]):
    """Update O(1) sur le champ recap_rows (hors payload gzippé)."""
    await db.datasets.update_one(
        {"upload_id": upload_id},
        {"$set": {"recap_rows": recap_rows}},
    )


async def persist_comment_table(upload_id: str, comment_table: dict):
    """Update O(1) sur le champ comment_table (hors payload gzippé)."""
    await db.datasets.update_one(
        {"upload_id": upload_id},
        {"$set": {"comment_table": comment_table}},
    )


async def persist_phasage(upload_id: str, phasage: dict):
    """Update O(1) sur le champ phasage (hors payload gzippé)."""
    await db.datasets.update_one(
        {"upload_id": upload_id},
        {"$set": {"phasage": phasage}},
    )


async def load_dataset(upload_id: str) -> Optional[dict]:
    """Récupère un dataset : d'abord en cache mémoire, sinon depuis MongoDB.
    Lit le payload gzippé + merge les champs éditables stockés à plat.
    Rétro-compatible avec les anciens datasets où ces champs étaient dans le payload.
    """
    if upload_id in DATASTORE:
        return DATASTORE[upload_id]
    doc = await db.datasets.find_one({"upload_id": upload_id}, {"_id": 0})
    if not doc:
        return None
    payload = json.loads(gzip.decompress(doc["payload"]).decode("utf-8"))
    # Champs éditables : champ Mongo plat prioritaire, sinon fallback ancien payload
    if "recap_rows" in doc:
        payload["recap_rows"] = doc["recap_rows"]
    if "comment_table" in doc:
        payload["comment_table"] = doc["comment_table"]
    if "phasage" in doc:
        payload["phasage"] = doc["phasage"]
    if "surface_category" in doc:
        payload["surface_category"] = doc["surface_category"]
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
        # Une ligne par produit avec Quantité, Spare (2% pour certains produits caméra, 5% sinon) et Total+Spare
        # Liste des produits à 2% (insensible à la casse, comparée à designation normalisée)
        PRODUITS_SPARE_2PCT = {
            "batterie caméra",
            "caméra (blanche)",
            "caméra (noire)",
            "support mobilier captana (blanc)",
            "support mobilier captana (noir)",
            "support ajustable adhésif captana",
        }
        # Produits sans spare (case vide, total = quantité)
        PRODUITS_SANS_SPARE = {
            "software caméra",
        }
        for _, r in grouped.iterrows():
            ref = "" if pd.isna(r[ref_col]) else str(r[ref_col])
            desig = "" if pd.isna(r[desig_col]) else str(r[desig_col])
            qty = float(r[qty_col])
            desig_norm = desig.strip().lower()
            if desig_norm in PRODUITS_SANS_SPARE:
                spare_val = ""
                total_plus_spare = qty
            else:
                spare_rate = 0.02 if desig_norm in PRODUITS_SPARE_2PCT else 0.05
                spare_val = math.ceil(qty * spare_rate)
                total_plus_spare = qty + spare_val
            rows.append({
                "kind": "product",
                "type": tp,
                "reference": ref,
                "designation": desig,
                "quantite": qty,
                "spare": spare_val,
                "total_plus_spare": total_plus_spare,
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

    # ===== Bonus rails → ES 1.5 (sans spare) =====
    # Règle : 1 rail (parmi RAILS_BONUS_ES15) = +1 EEG ES 1.5 de même couleur,
    #         ajouté UNIQUEMENT à total_plus_spare (sans spare additionnel).
    rail_bonus_by_color = {"noir": 0, "blanc": 0}
    rails_df = df[df[type_col].astype(str).str.lower() == "rail"].copy()
    if not rails_df.empty:
        rails_df[qty_col] = pd.to_numeric(rails_df[qty_col], errors="coerce").fillna(0)
        for _, rr in rails_df.iterrows():
            d_low = _norm_desig(rr[desig_col])
            if not d_low:
                continue
            q = float(rr[qty_col]) if rr[qty_col] else 0
            if q <= 0:
                continue
            for pat, color in RAILS_BONUS_ES15:
                if pat.lower() in d_low:
                    rail_bonus_by_color[color] += int(q)
                    break

    # Applique le bonus aux lignes ES 1.5 (noir) et ES 1.5 (blanc) du recap
    for color, bonus in rail_bonus_by_color.items():
        if bonus <= 0:
            continue
        target_label = f"es 1.5 ({color})"
        for r in rows:
            if r.get("kind") != "product":
                continue
            desig_norm = _norm_desig(r.get("designation"))
            # On strip un éventuel suffixe " — rajout de … rails" déjà présent
            base_desig = desig_norm.split(" — rajout de")[0]
            if base_desig == target_label:
                try:
                    cur_total = float(r.get("total_plus_spare") or 0)
                except (ValueError, TypeError):
                    cur_total = 0
                try:
                    cur_q = float(r.get("quantite") or 0)
                except (ValueError, TypeError):
                    cur_q = 0
                try:
                    cur_s = float(r.get("spare") or 0)
                except (ValueError, TypeError):
                    cur_s = 0
                # Si total était 0/vide, on recalcule depuis qté + spare
                if cur_total == 0 and (cur_q + cur_s) > 0:
                    cur_total = cur_q + cur_s
                r["total_plus_spare"] = cur_total + bonus
                # Met à jour la désignation pour signaler le bonus
                base_label = (r.get("designation") or "").split(" — rajout de")[0].strip()
                r["designation"] = f"{base_label} — rajout de {bonus} rails"
                # Mémorise pour rollback futur éventuel
                r["_rail_bonus"] = bonus
                r["_rail_bonus_color"] = color
                break

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
    # Détecte les caméras valides : Type=Caméra/Camera ET désignation contient "noir(e)" ou "blanc(he)"
    def _is_valid_camera(row) -> bool:
        if row[type_col] not in ("Caméra", "Camera"):
            return False
        d = str(row[desig_col] or "").lower()
        return ("noir" in d) or ("blanc" in d)

    df["_camera_valid"] = df.apply(_is_valid_camera, axis=1)

    grouped = df.groupby([secteur_col, rayon_col, allee_col], dropna=False)
    rows: list[dict] = []
    for (secteur, rayon, allee), g in grouped:
        eeg_es = float(g.loc[g["_eeg_subtype"] == "ES", qty_col].sum())
        eeg_sa = float(g.loc[g["_eeg_subtype"] == "SA", qty_col].sum())
        nb_rail = float(g.loc[g[type_col] == "Rail", qty_col].sum())
        # Caméra : uniquement les désignations contenant "noir(e)" ou "blanc(he)"
        nb_cam = float(g.loc[g["_camera_valid"], qty_col].sum())
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
        "surface_category": None,  # "plus_10000" | "moins_10000" | None
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
        "surface_category": None,
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
    """Met à jour une ligne du récapitulatif. Toutes les lignes sont éditables
    sauf les en-têtes de section (kind='header')."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = d["recap_rows"]
    if index < 0 or index >= len(rows):
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    row = rows[index]
    if row["kind"] == "header":
        raise HTTPException(status_code=400, detail="Les en-têtes de section ne sont pas éditables")
    is_dongle = row["kind"] == "dongle"
    is_inclineur = row["kind"] == "inclineur"

    new_type = (payload.type or "").strip()
    new_ref = (payload.reference or "").strip()
    new_desig = (payload.designation or "").strip()
    new_qty = _parse_quantite(payload.quantite)
    new_spare = _parse_quantite(payload.spare)

    # Auto-calcul du Spare = ceil(qty * 5%) si Quantité saisie et Spare vide/0
    # SAUF pour Dongle / Inclineur qui n'ont pas de règle Spare
    if (not is_dongle and not is_inclineur
            and isinstance(new_qty, (int, float)) and new_qty > 0
            and (new_spare == "" or new_spare == 0)):
        new_spare = math.ceil(float(new_qty) * 0.05)

    # Total + Spare auto-calculé (sauf pour Dongle/Inclineur)
    if is_dongle or is_inclineur:
        new_total_plus_spare = ""
    elif isinstance(new_qty, (int, float)) and isinstance(new_spare, (int, float)):
        new_total_plus_spare = new_qty + new_spare
    elif isinstance(new_qty, (int, float)) and (new_spare == "" or new_spare == 0):
        new_total_plus_spare = new_qty
    else:
        new_total_plus_spare = ""

    # Si toutes les valeurs sont vides, on remet kind='empty'
    is_empty = (
        not new_type and not new_ref and not new_desig
        and (new_qty == "" or new_qty == 0)
        and (new_spare == "" or new_spare == 0)
    )
    row["type"] = new_type
    row["reference"] = new_ref
    row["designation"] = new_desig
    row["quantite"] = new_qty
    row["spare"] = "" if (is_dongle or is_inclineur) else new_spare
    row["total_plus_spare"] = new_total_plus_spare
    # Le kind est préservé pour Dongle/Inclineur (couleur orange spéciale)
    # Pour les autres lignes (product, manual, empty), on bascule entre empty/manual
    if not is_dongle and not is_inclineur:
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


class SurfaceUpdate(BaseModel):
    category: Optional[str] = None  # "plus_10000" | "moins_10000" | None


@api_router.patch("/dataset/{upload_id}/surface")
async def update_surface(upload_id: str, payload: SurfaceUpdate):
    """Définit la catégorie surface du magasin et ajoute :
      - +6000 si "plus_10000" (surface > 10 000 m²)
      - +4000 si "moins_10000" (surface < 10 000 m²)
    à la ligne 'SA 2.1 (noir)' existante du recap, **uniquement sur total_plus_spare**
    (pas de spare additionnel). La désignation est suffixée de " — rajout de X SA sans spare".

    Mécanisme : on stocke les valeurs d'origine (`_surface_base_quantite`, `_surface_base_spare`,
    `_surface_base_total`, `_surface_base_designation`) la première fois pour pouvoir
    revenir en arrière sans dérive cumulative.
    Si la ligne SA 2.1 (noir) n'existe pas dans le fichier, on crée une ligne dédiée
    (kind='surface_added') avec uniquement total_plus_spare = delta."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    cat = payload.category
    if cat not in (None, "plus_10000", "moins_10000"):
        raise HTTPException(status_code=400, detail="Catégorie surface invalide")
    delta = 6000 if cat == "plus_10000" else (4000 if cat == "moins_10000" else 0)
    d["surface_category"] = cat
    rows = d["recap_rows"]

    def _strip_surface_suffix(s: str) -> str:
        """Retire un éventuel ' — rajout de X SA sans spare' à la fin de la désignation."""
        if not s:
            return s
        # Marqueur unique pour faciliter le strip (en-dash + 'rajout de')
        idx = s.find(" — rajout de ")
        return s[:idx] if idx != -1 else s

    # 0) Nettoyage : on supprime systématiquement TOUTES les anciennes lignes
    #    `surface_added` orphelines (créées par les versions buggées précédentes).
    rows[:] = [r for r in rows if r.get("kind") != "surface_added"]

    # 1) Cherche la VRAIE ligne SA 2.1 (noir) — uniquement les lignes kind=product
    #    (on ignore les éventuelles lignes 'spare' ou orphelines).
    target = None
    for r in rows:
        if r.get("kind") != "product":
            continue
        base_desig = _strip_surface_suffix((r.get("designation") or "").strip())
        if base_desig.lower() == "sa 2.1 (noir)":
            target = r
            break

    if target is not None:
        # Mémorise les valeurs d'origine la 1ère fois (qty, spare, total, désignation)
        # Re-init si _surface_base_total == 0 alors que _surface_base_quantite > 0
        # (correction héritage des datasets où l'ancienne logique stockait base_t=0).
        needs_init = "_surface_base_quantite" not in target or (
            float(target.get("_surface_base_total") or 0) == 0
            and float(target.get("_surface_base_quantite") or 0) > 0
        )
        if needs_init:
            # Migration depuis l'ancien schéma (qte inflée + _surface_base) :
            # si _surface_base existe, on l'utilise comme qté d'origine et on recalcule spare/total.
            if "_surface_base" in target:
                try:
                    base_q = float(target.get("_surface_base") or 0)
                except (ValueError, TypeError):
                    base_q = 0
                target["_surface_base_quantite"] = base_q
                target["_surface_base_spare"] = math.ceil(base_q * 0.05) if base_q > 0 else 0
                target["_surface_base_total"] = base_q + target["_surface_base_spare"]
            else:
                try:
                    target["_surface_base_quantite"] = float(target.get("quantite") or 0)
                except (ValueError, TypeError):
                    target["_surface_base_quantite"] = 0
                try:
                    target["_surface_base_spare"] = float(target.get("spare") or 0)
                except (ValueError, TypeError):
                    target["_surface_base_spare"] = 0
                # Si total_plus_spare est vide/manquant, on le RECALCULE depuis qté + spare
                # pour éviter de partir de 0 et afficher un total incohérent après l'ajout.
                try:
                    raw_t = target.get("total_plus_spare")
                    if raw_t in ("", None):
                        target["_surface_base_total"] = target["_surface_base_quantite"] + target["_surface_base_spare"]
                    else:
                        target["_surface_base_total"] = float(raw_t)
                except (ValueError, TypeError):
                    target["_surface_base_total"] = target["_surface_base_quantite"] + target["_surface_base_spare"]
            target["_surface_base_designation"] = _strip_surface_suffix(target.get("designation") or "SA 2.1 (noir)")

        base_q = target["_surface_base_quantite"]
        base_s = target["_surface_base_spare"]
        base_t = target["_surface_base_total"]
        base_d = target["_surface_base_designation"]

        # Règle métier (utilisateur) : QUANTITÉ et SPARE restent INCHANGÉS.
        # Seul TOTAL+SPARE reçoit le delta (+6000 ou +4000).
        # La mention "— rajout de X SA sans spare" justifie l'écart visuel.
        target["quantite"] = base_q if base_q > 0 else ""
        target["spare"] = base_s if base_s > 0 else ""
        if delta > 0:
            target["total_plus_spare"] = base_t + delta
            target["designation"] = f"{base_d} — rajout de {int(delta)} SA sans spare"
        else:
            target["total_plus_spare"] = base_t if base_t > 0 else ""
            target["designation"] = base_d
    else:
        # Pas trouvé dans le fichier : ligne dédiée (kind='surface_added')
        added = next((r for r in rows if r.get("kind") == "surface_added"), None)
        if delta == 0:
            if added:
                rows.remove(added)
        else:
            if added is None:
                last_empty_idx = next((i for i, r in enumerate(rows) if r.get("kind") == "empty"), len(rows))
                added = {
                    "kind": "surface_added",
                    "type": "SA",
                    "reference": "",
                    "designation": f"SA 2.1 (noir) — rajout de {int(delta)} SA sans spare",
                    "quantite": delta,
                    "spare": "",
                    "total_plus_spare": delta,
                }
                rows.insert(last_empty_idx, added)
            else:
                added["designation"] = f"SA 2.1 (noir) — rajout de {int(delta)} SA sans spare"
                added["quantite"] = delta
                added["spare"] = ""
                added["total_plus_spare"] = delta
    # Persister recap + surface_category
    try:
        await persist_recap_rows(upload_id, rows)
        await db.datasets.update_one({"upload_id": upload_id}, {"$set": {"surface_category": cat}})
    except Exception as e:
        logger.warning(f"Mongo persist surface failed: {e}")
    return {"category": cat, "rows": rows}


@api_router.delete("/dataset/{upload_id}/recap-row/{index}")
async def delete_recap_row(upload_id: str, index: int):
    """Supprime une ligne du récapitulatif (sauf en-têtes de section)."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = d["recap_rows"]
    if index < 0 or index >= len(rows):
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    if rows[index]["kind"] == "header":
        raise HTTPException(status_code=400, detail="Les en-têtes de section ne sont pas supprimables")
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

# Couleurs FIXES par position dans la semaine (1..4) — identiques sur web + Excel.
# Couleurs muted/professionnelles, repérables sur Excel.
WEEK_NIGHT_PALETTE = [
    "#DBEAFE",  # 1 bleu doux
    "#FEF3C7",  # 2 jaune doux
    "#FEE2E2",  # 3 rouge doux
    "#DCFCE7",  # 4 vert doux
]


def night_position_in_week(nuit: int, weeks: list | None) -> int:
    """Convertit un n° de nuit absolu (1..N) en position dans sa semaine (1..nb_nuits_semaine).
    Si pas de découpage par semaine, on considère toutes les nuits comme une seule semaine
    (le n° de nuit absolu est utilisé directement, modulo 4 pour les couleurs)."""
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


def night_color_hex(nuit: int, weeks: list | None) -> str:
    """Couleur de fond Excel pour une nuit, selon sa position dans la semaine."""
    pos = night_position_in_week(nuit, weeks)
    if not pos:
        return "#FFFFFF"
    return WEEK_NIGHT_PALETTE[(pos - 1) % len(WEEK_NIGHT_PALETTE)]

# ===================================================================
# MODE MAGASIN (configuration métier de la branche)
# ===================================================================
# "magasin_1" (défaut, branche main) :
#   - Phasage de pose : EEG = ES 1.5 + ES 2.1 + bonus rails→ES 1.5 + saisonnier SA 2.1
#   - Col SA = toutes SA cumulées (info)
#   - Bonus rails→ES 1.5 appliqué dans Commandes ET dans Phasage
#
# "magasin_2" (cette branche) :
#   - Phasage de pose : EEG = ES 1.5 + ES 2.1 + SA 1.5 (noir+blanc) + saisonnier SA 2.1
#                       (PAS de bonus rails→ES 1.5 dans le Phasage)
#   - 2 colonnes SA séparées : "SA 1.5" (à installer, hors EEG) + "SA 2.1 (info)" (hors EEG)
#   - Bonus rails→ES 1.5 reste appliqué dans Commandes (recap inchangé)
STORE_MODE = os.environ.get("STORE_MODE", "magasin_1")

# Patterns de rails qui DÉCLENCHENT le bonus "+1 EEG ES 1.5 par rail"
# (selon liste utilisateur — 1187 EXCLU, 535 INCLUS)
RAILS_BONUS_ES15 = [
    ("1240 mm (noir)", "noir"),
    ("1320 mm (blanc)", "blanc"),
    ("1320 mm (noir)", "noir"),
    ("535 mm (noir)", "noir"),
    ("650 mm (noir)", "noir"),
    ("990 mm (blanc)", "blanc"),
    ("990 mm (noir)", "noir"),
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


def _is_sa(desig: str) -> bool:
    """Détecte toute étiquette SA (SA 1.5, SA 2.1, SA 4.2, SA 4.2 F&L, SA 4.2 Marée,
    SA 2.1 Freezer blanc/noir, etc.). Critère : la désignation contient 'SA ' (insensible
    à la casse), avec un espace pour éviter les faux positifs comme 'Plasa', 'Sade', etc."""
    d = _norm_desig(desig)
    if not d:
        return False
    return d.startswith("sa ") or " sa " in d


def _is_sa_15(desig: str) -> bool:
    """Détecte les étiquettes SA 1.5 (noir, blanc, …)."""
    d = _norm_desig(desig)
    return "sa 1.5" in d or "sa 1,5" in d


def _is_sa_21(desig: str) -> bool:
    """Détecte les étiquettes SA 2.1 (noir, blanc, freezer, …)."""
    d = _norm_desig(desig)
    return "sa 2.1" in d or "sa 2,1" in d


def _is_rail_es(desig: str) -> bool:
    """Vérifie si la désignation contient une des longueurs de rail ES."""
    d = _norm_desig(desig)
    if not d:
        return False
    for pat in RAILS_ES_PATTERNS:
        if pat.lower() in d:
            return True
    return False


def _is_valid_camera_desig(desig: str) -> bool:
    """Caméra valide = désignation contient 'noir(e)' ou 'blanc(he)'."""
    d = _norm_desig(desig)
    if not d:
        return False
    return ("noir" in d) or ("blanc" in d)


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
    # Détection robuste (insensible casse + variantes Élément/Gondole + fallback positionnel colonne G)
    elem_col = _detect_element_col(columns)
    if elem_col is None and len(columns) >= 7:
        elem_col = columns[6]
    type_col = next((c for c in ["Type"] if c in columns), None)
    desig_col = next((c for c in ["Désignation", "Designation"] if c in columns), None)
    qty_col = next((c for c in ["Quantité", "Quantite"] if c in columns), None)

    # Agrégation par allée (clé = str de l'allée)
    by_allee: dict[str, dict] = {}
    totals = {"es_15": 0.0, "es_21": 0.0, "sa": 0.0, "sa_15": 0.0, "sa_21": 0.0,
              "rails_es": 0.0, "cameras": 0.0,
              "es_15_bonus_noir": 0.0, "es_15_bonus_blanc": 0.0,
              "rails_es_by_desig": {p: 0.0 for p in RAILS_ES_PATTERNS}}

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

        secteur_v = str(r.get(secteur_col) or "") if secteur_col else ""
        rayon_v = str(r.get(rayon_col) or "") if rayon_col else ""
        # Clé composite : allée + secteur + rayon, pour conserver les doublons
        # d'allée appartenant à des secteurs/rayons différents.
        composite_key = f"{allee_key}__{secteur_v}__{rayon_v}"

        typ = str(r.get(type_col) or "").strip() if type_col else ""
        desig = str(r.get(desig_col) or "") if desig_col else ""
        try:
            qty = float(r.get(qty_col) or 0) if qty_col else 0
        except (ValueError, TypeError):
            qty = 0

        node = by_allee.setdefault(composite_key, {
            "uid": composite_key,
            "allee": allee_key,
            "secteur": secteur_v,
            "rayon": rayon_v,
            "es_15": 0.0,
            "es_21": 0.0,
            "sa": 0.0,         # Toutes SA confondues (legacy)
            "sa_15": 0.0,      # SA 1.5 (noir + blanc)
            "sa_21": 0.0,      # SA 2.1 (toutes variantes)
            "rails_es": 0.0,
            "cameras": 0.0,
            "camera_elems": [],
            "es_15_bonus_noir": 0.0,
            "es_15_bonus_blanc": 0.0,
            "rails_es_by_desig": {p: 0.0 for p in RAILS_ES_PATTERNS},
        })

        is_eeg = typ.lower() == "eeg"
        is_rail = typ.lower() == "rail"
        is_camera = typ.lower() in ("caméra", "camera")
        if is_eeg and _is_es_15(desig):
            node["es_15"] += qty
            totals["es_15"] += qty
        elif is_eeg and _is_es_21(desig):
            node["es_21"] += qty
            totals["es_21"] += qty
        elif is_eeg and _is_sa(desig):
            node["sa"] += qty
            totals["sa"] += qty
            # Split SA 1.5 vs SA 2.1 (utilisé par le Phasage de pose du magasin 2)
            if _is_sa_15(desig):
                node["sa_15"] += qty
                totals["sa_15"] += qty
            elif _is_sa_21(desig):
                node["sa_21"] += qty
                totals["sa_21"] += qty
        elif is_camera and _is_valid_camera_desig(desig):
            node["cameras"] += qty
            totals["cameras"] += qty
            # Capture le N° élément pour le détail par allée (autant de fois que la quantité)
            elem_v = r.get(elem_col) if elem_col else None
            if elem_v is not None and not (isinstance(elem_v, float) and math.isnan(elem_v)):
                try:
                    fe = float(elem_v)
                    elem_key = int(fe) if fe.is_integer() else fe
                except (ValueError, TypeError):
                    elem_key = str(elem_v).strip()
                if elem_key not in (None, ""):
                    try:
                        cnt = max(1, int(qty))
                    except (ValueError, TypeError):
                        cnt = 1
                    node["camera_elems"].extend([elem_key] * cnt)
        elif typ.lower() == "rail":
            d_low = _norm_desig(desig)
            # Comptage rails ES (RAILS_ES_PATTERNS) — utilisé pour la planification rails
            if _is_rail_es(desig):
                node["rails_es"] += qty
                totals["rails_es"] += qty
                for pat in RAILS_ES_PATTERNS:
                    if pat.lower() in d_low:
                        node["rails_es_by_desig"][pat] += qty
                        totals["rails_es_by_desig"][pat] += qty
                        break
            # Bonus rails → ES 1.5 (RAILS_BONUS_ES15) — utilisé pour ajouter des EEG
            # ES 1.5 supplémentaires dans le Phasage de pose, par couleur.
            for pat, color in RAILS_BONUS_ES15:
                if pat.lower() in d_low:
                    key = "es_15_bonus_noir" if color == "noir" else "es_15_bonus_blanc"
                    node[key] += qty
                    totals[key] += qty
                    break

    # Tri strictement ascendant numérique des allées (demande utilisateur).
    # Tie-breakers : secteur puis rayon (pour ordonner les doublons).
    def _smart_sort_key(v):
        a_str = str(v["allee"]).strip()
        secteur_s = str(v.get("secteur") or "")
        rayon_s = str(v.get("rayon") or "")
        try:
            return (0, float(a_str.replace(",", ".")), secteur_s, rayon_s)
        except (ValueError, TypeError):
            return (1, 0.0, a_str, secteur_s + "|" + rayon_s)

    allees = sorted(by_allee.values(), key=_smart_sort_key)

    # Détection des doublons d'allée (même n° dans des secteurs/rayons différents)
    # → on note dup_index (1, 2, 3...) sur les entrées dupliquées pour les distinguer
    #   visuellement côté frontend.
    allee_counts = Counter(v["allee"] for v in allees)
    dup_seen: dict[str, int] = {}
    for a in allees:
        n = a["allee"]
        if allee_counts[n] > 1:
            dup_seen[n] = dup_seen.get(n, 0) + 1
            a["is_dup"] = True
            a["dup_index"] = dup_seen[n]
            a["dup_total"] = allee_counts[n]
        else:
            a["is_dup"] = False
            a["dup_index"] = 1
            a["dup_total"] = 1
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
        a["sa"] = _r(a["sa"])
        a["sa_15"] = _r(a.get("sa_15", 0))
        a["sa_21"] = _r(a.get("sa_21", 0))
        a["rails_es"] = _r(a["rails_es"])
        a["cameras"] = _r(a.get("cameras", 0))
        a["es_15_bonus_noir"] = _r(a.get("es_15_bonus_noir", 0))
        a["es_15_bonus_blanc"] = _r(a.get("es_15_bonus_blanc", 0))
        # Tri smart numérique des n° éléments-caméras (ordre croissant) — on garde les doublons
        # car cela indique plusieurs caméras sur le même élément (à afficher en rouge)
        elems = a.get("camera_elems") or []
        def _elem_sort_key(v):
            try: return (0, float(str(v).replace(",", ".")))
            except (ValueError, TypeError): return (1, str(v))
        a["camera_elems"] = sorted(elems, key=_elem_sort_key)
        a["rails_es_by_desig"] = {k: _r(v) for k, v in a["rails_es_by_desig"].items()}
    totals = {
        "es_15": _r(totals["es_15"]),
        "es_21": _r(totals["es_21"]),
        "sa": _r(totals["sa"]),
        "sa_15": _r(totals.get("sa_15", 0)),
        "sa_21": _r(totals.get("sa_21", 0)),
        "rails_es": _r(totals["rails_es"]),
        "cameras": _r(totals.get("cameras", 0)),
        "es_15_bonus_noir": _r(totals.get("es_15_bonus_noir", 0)),
        "es_15_bonus_blanc": _r(totals.get("es_15_bonus_blanc", 0)),
        "rails_es_by_desig": {k: _r(v) for k, v in totals["rails_es_by_desig"].items()},
    }

    # Total SA 2.1 (noir) saisonnier issu de la catégorie surface du magasin
    surface_cat = d.get("surface_category") if isinstance(d, dict) else None
    sa_21_saisonnier = 6000 if surface_cat == "plus_10000" else (4000 if surface_cat == "moins_10000" else 0)

    # Zones saisonnières sélectionnables dans le phasage de pose
    # +10 000 m² → 3 zones de 2000 EEG (= 6000 SA 2.1 noir)
    # −10 000 m² → 2 zones de 2000 EEG (= 4000 SA 2.1 noir)
    seasonal_zones = []
    if surface_cat == "plus_10000":
        seasonal_zones = [
            {"id": "ZS1", "label": "Zone saisonnier 1", "eeg": 2000, "is_seasonal": True},
            {"id": "ZS2", "label": "Zone saisonnier 2", "eeg": 2000, "is_seasonal": True},
            {"id": "ZS3", "label": "Zone saisonnier 3", "eeg": 2000, "is_seasonal": True},
        ]
    elif surface_cat == "moins_10000":
        seasonal_zones = [
            {"id": "ZS1", "label": "Zone saisonnier 1", "eeg": 2000, "is_seasonal": True},
            {"id": "ZS2", "label": "Zone saisonnier 2", "eeg": 2000, "is_seasonal": True},
        ]

    return {
        "allees": allees,
        "totals": totals,
        "rails_es_patterns": RAILS_ES_PATTERNS,
        "sa_21_saisonnier": sa_21_saisonnier,
        "surface_category": surface_cat,
        "seasonal_zones": seasonal_zones,
        "store_mode": STORE_MODE,
    }


def _normalize_phasage(stored: Any) -> dict:
    """Normalise le phasage stocké en MongoDB (gère l'ancien format à plat)."""
    if not isinstance(stored, dict):
        return {
            "es": {"nb_nuits": 3, "rows": []},
            "cam": {"nb_nuits": 3, "rows": [], "start_at_nuit": 5},
            "suivi": {"rows": []},
        }
    # Ancien format : {nb_nuits, rows} -> migrer vers .es
    if "nb_nuits" in stored and "rows" in stored and "es" not in stored:
        return {
            "es": {"nb_nuits": stored.get("nb_nuits", 3), "rows": stored.get("rows", [])},
            "cam": {"nb_nuits": 3, "rows": [], "start_at_nuit": 5},
            "suivi": {"rows": []},
        }
    es = stored.get("es") or {"nb_nuits": 3, "rows": []}
    cam = stored.get("cam") or {"nb_nuits": 3, "rows": [], "start_at_nuit": 5}
    if "start_at_nuit" not in cam:
        cam["start_at_nuit"] = 5
    suivi = stored.get("suivi") or {"rows": []}
    return {"es": es, "cam": cam, "suivi": suivi}


@api_router.get("/dataset/{upload_id}/phasage-summary")
async def get_phasage_summary(upload_id: str):
    """Retourne la liste des allées avec leurs comptes ES / Rails ES / Caméras
    + les totaux globaux + l'état du phasage (ES, Cam, Suivi)."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    summary = compute_phasage_summary(d)
    summary["phasage"] = _normalize_phasage(d.get("phasage"))
    return summary


class PhasageRow(BaseModel):
    id: str
    allee: str = ""
    nuit: Optional[int] = None


class PhasagePlanning(BaseModel):
    nb_nuits: int
    rows: list[PhasageRow]
    start_at_nuit: Optional[int] = None
    weeks: Optional[list[int]] = None  # ex: [5, 3, 6] = 3 semaines avec 5/3/6 nuits


class SuiviRow(BaseModel):
    nuit: int
    es_reel: Optional[float] = None
    cam_reel: Optional[float] = None
    rails_geoloc: Optional[float] = None  # = Rails ES réel (champ DB historique)
    rails_geoloc_count: Optional[float] = None  # = nb rails géolocalisés (scan GPS)
    allee_reelle: Optional[str] = None    # = allée effectivement posée (saisie libre)


class PhasageFullUpdate(BaseModel):
    es: PhasagePlanning
    cam: PhasagePlanning
    suivi: Optional[dict] = None  # {"rows": [SuiviRow]}


def _sanitize_planning(p: PhasagePlanning) -> dict:
    nb = max(1, min(int(p.nb_nuits), 60))
    rows = [{"id": r.id, "allee": r.allee or "",
             "nuit": r.nuit if r.nuit and 1 <= r.nuit <= nb else None}
            for r in p.rows]
    out = {"nb_nuits": nb, "rows": rows}
    if p.start_at_nuit is not None:
        out["start_at_nuit"] = max(1, int(p.start_at_nuit))
    if p.weeks is not None:
        # Garde uniquement les valeurs positives, ajuste pour matcher nb_nuits si nécessaire
        w = [max(1, int(v)) for v in p.weeks if v is not None]
        out["weeks"] = w
    return out


@api_router.patch("/dataset/{upload_id}/phasage")
async def update_phasage(upload_id: str, payload: PhasageFullUpdate):
    """Sauvegarde l'état complet : ES + Caméras + Suivi (réalité)."""
    d = await load_dataset(upload_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    es = _sanitize_planning(payload.es)
    cam = _sanitize_planning(payload.cam)
    if "start_at_nuit" not in cam:
        cam["start_at_nuit"] = 5
    suivi = payload.suivi or {"rows": []}
    # Sanitize suivi
    suivi_rows = []
    for r in (suivi.get("rows") or []):
        try:
            nuit = int(r.get("nuit"))
        except (ValueError, TypeError):
            continue
        suivi_rows.append({
            "nuit": nuit,
            "es_reel": r.get("es_reel"),
            "cam_reel": r.get("cam_reel"),
            "rails_geoloc": r.get("rails_geoloc"),
            "rails_geoloc_count": r.get("rails_geoloc_count"),
            "allee_reelle": r.get("allee_reelle"),
        })
    d["phasage"] = {"es": es, "cam": cam, "suivi": {"rows": suivi_rows}}
    try:
        await persist_phasage(upload_id, d["phasage"])
    except Exception as e:
        logger.warning(f"Mongo persist phasage failed: {e}")
    return {"ok": True, "phasage": d["phasage"]}


def _allee_display_label(a: dict) -> str:
    """Label court pour l'affichage Excel (data validation + récap par nuit).
    - Non-dup : "8"
    - Doublon  : "112-1" / "112-2"
    - Zone saisonnier : "ZS1" (le label est déjà court)
    """
    num = str(a.get("allee") or "").strip()
    if a.get("is_seasonal"):
        return num
    if a.get("is_dup"):
        return f"{num}-{a.get('dup_index', 1)}"
    return num


def _build_uid_to_label(allees: list, seasonal_zones=None) -> dict:
    """Construit le mapping uid -> display_label utilisé pour convertir les
    assignations stockées en DB (uid) vers les labels courts affichés dans Excel."""
    mapping = {}
    for a in allees:
        uid = str(a.get("uid") or a.get("allee"))
        mapping[uid] = _allee_display_label(a)
    for z in (seasonal_zones or []):
        # uid = id ("ZS1"), label = id
        mapping[str(z.get("id"))] = str(z.get("id"))
    return mapping




def _write_phasage_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total):
    """Génère la feuille "Phasage de pose" INTERACTIVE (formules + listes déroulantes).

    Layout:
      - Cellule "Nb nuits" éditable + formule "Moyenne/nuit"
      - Bloc totaux globaux (statiques, ES 1.5/2.1/Rails ES + breakdown)
      - Tableau gauche : 1 ligne par allée du fichier
          * Col A "N° Allée" : liste déroulante (data validation) source = liste des allées
          * Col B/C/D : formules VLOOKUP -> auto-calcul ES 1.5 / ES 2.1 / Rails ES
          * Col E "Nuit" : liste déroulante (Nuit 1, Nuit 2, ...)
      - Tableau droite : agrégation par nuit via SUMIFS sur le tableau gauche
          * Col "Allées" : TEXTJOIN array formula
      - Feuille cachée "_Phasage_data" : table de référence des allées (allée -> es15/es21/rails)
    """
    summary = compute_phasage_summary(d)
    phasage_full = _normalize_phasage(d.get("phasage"))
    phasage = phasage_full["es"]
    nb_nuits = max(1, int(phasage.get("nb_nuits") or 3))
    rows_assign = phasage.get("rows") or []
    all_allees = summary["allees"]
    seasonal_zones = summary.get("seasonal_zones") or []
    totals = summary["totals"]
    n_allees = len(all_allees)
    n_zs = len(seasonal_zones)

    # Mapping uid -> label court pour la conversion des assignations stockées
    uid_to_label = _build_uid_to_label(all_allees, seasonal_zones)

    if n_allees == 0:
        # Pas de données -> feuille minimaliste
        ws = workbook.add_worksheet("Phasage de pose")
        writer.sheets["Phasage de pose"] = ws
        ws.write(0, 0, "Aucune allée détectée dans le fichier source.", fmt_header)
        return

    # ----- Feuille principale (créée AVANT _Phasage_data pour qu'elle soit "active") -----
    ws = workbook.add_worksheet("Phasage de pose")
    writer.sheets["Phasage de pose"] = ws
    ws.activate()

    # ----- Feuille cachée _Phasage_data : table de référence pour VLOOKUP -----
    ws_data = workbook.add_worksheet("_Phasage_data")
    writer.sheets["_Phasage_data"] = ws_data
    store_mode = summary.get("store_mode") or "magasin_1"
    is_m2 = store_mode == "magasin_2"

    # Col A = Label court (display, ex: "8", "112-1", "ZS1")
    # Col B = EEG :
    #   - Magasin 1 : ES 1.5 + ES 2.1 + bonus rails→ES 1.5
    #   - Magasin 2 : ES 1.5 + ES 2.1 + SA 1.5 (noir+blanc)
    # Col C = Rails ES
    # Col D = SA (info, mag1=toutes / mag2=SA 2.1 uniquement)
    # Col E = SA 1.5 (mag2 uniquement, info — déjà inclus dans EEG)
    headers = ["Allée", "EEG", "Rails ES", "SA 2.1 (info)" if is_m2 else "SA", "SA 1.5"] \
              if is_m2 else ["Allée", "EEG", "Rails ES", "SA", "Bonus rails"]
    ws_data.write_row(0, 0, headers)
    n_data_rows = n_allees + n_zs
    for i, a in enumerate(all_allees, start=1):
        es_brut = (a["es_15"] or 0) + (a["es_21"] or 0)
        bonus = (a.get("es_15_bonus_noir") or 0) + (a.get("es_15_bonus_blanc") or 0)
        sa_15_val = a.get("sa_15") or 0
        sa_21_val = a.get("sa_21") or 0
        ws_data.write_string(i, 0, _allee_display_label(a))
        if is_m2:
            ws_data.write_number(i, 1, es_brut + sa_15_val)
            ws_data.write_number(i, 2, a["rails_es"] or 0)
            ws_data.write_number(i, 3, sa_21_val)
            ws_data.write_number(i, 4, sa_15_val)
        else:
            ws_data.write_number(i, 1, es_brut + bonus)
            ws_data.write_number(i, 2, a["rails_es"] or 0)
            ws_data.write_number(i, 3, a.get("sa") or 0)
            ws_data.write_number(i, 4, bonus)
    # Ajoute les zones saisonnières comme allées sélectionnables (avec leur EEG)
    for j, z in enumerate(seasonal_zones, start=1):
        rr = n_allees + j
        ws_data.write_string(rr, 0, str(z["id"]))
        ws_data.write_number(rr, 1, int(z.get("eeg") or 0))
        ws_data.write_number(rr, 2, 0)
        # SA 2.1 (info) : 0 pour les zones (le saisonnier est déjà dans EEG, pas en double)
        ws_data.write_number(rr, 3, 0)
        ws_data.write_number(rr, 4, 0)
    ws_data.hide()

    # ----- Configuration de la feuille principale -----
    # Tableau gauche : A=N°Allée, B=ES, C=RailsES, D=SA (info), E=Nuit
    # Spacer : col F (5)
    # Tableau droit : G=Nuit, H=Allées, I=ES, J=RailsES, K=SA (info)
    ws.set_column(0, 0, 12)   # A N° Allée
    ws.set_column(1, 1, 12)   # B ES
    ws.set_column(2, 2, 12)   # C Rails ES
    ws.set_column(3, 3, 10)   # D SA (info)
    ws.set_column(4, 4, 12)   # E Nuit
    ws.set_column(5, 5, 3)    # F spacer
    ws.set_column(6, 6, 10)   # G Nuit
    ws.set_column(7, 7, 32)   # H Allées
    ws.set_column(8, 8, 12)   # I ES
    ws.set_column(9, 9, 12)   # J Rails ES
    ws.set_column(10, 10, 10) # K SA (info)

    fmt_title = workbook.add_format({"bold": True, "bg_color": "#056839", "font_color": "white",
                                     "border": 1, "font_size": 12, "align": "left"})
    fmt_lbl = workbook.add_format({"bold": True, "bg_color": "#F3F4F6", "border": 1, "align": "left"})
    fmt_num = workbook.add_format({"border": 1, "align": "right"})
    fmt_num_calc = workbook.add_format({"border": 1, "align": "right", "bg_color": "#FAFAFA"})
    fmt_input = workbook.add_format({"border": 1, "align": "center", "bg_color": "#FFFBEB", "bold": True})
    fmt_total_row = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right"})
    fmt_total_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "left"})
    fmt_italic = workbook.add_format({"italic": True, "border": 1, "font_color": "#6B7280"})

    # Format neutre pour les cellules Nuit (la couleur sera appliquée via mise en forme conditionnelle)
    fmt_nuit_cell = workbook.add_format({"border": 1, "align": "center"})

    # Couleurs FIXES par position dans la semaine — identiques au frontend.
    # On précalcule, pour chaque n° de nuit absolu (1..nb_nuits), la couleur
    # correspondant à sa position dans la semaine (4 couleurs récurrentes).
    weeks_list = phasage.get("weeks") or []
    cf_formats_left = {}
    cf_formats_right = {}
    for n in range(1, max(nb_nuits, 30) + 1):
        color = night_color_hex(n, weeks_list)
        cf_formats_left[n] = workbook.add_format({"bg_color": color, "border": 1})
        cf_formats_right[n] = workbook.add_format({"bg_color": color, "border": 1})

    # ----- En-tête supérieur -----
    ws.merge_range(0, 0, 0, 10, "Phasage de pose des étiquettes (EEG)", fmt_title)
    ws.write(1, 0, "Nb nuits :", fmt_lbl)
    ws.write_number(1, 1, nb_nuits, fmt_input)
    ws.write(1, 2, "Moyenne/nuit :", fmt_lbl)
    # Moyenne = Total EEG (B4) / Nb nuits (B2). EEG = Total ES + SA 2.1 saisonnier
    ws.write_formula(1, 3, "=IFERROR(ROUND(B4/B2,0),0)", fmt_num_calc)
    ws.write(1, 4, "Total EEG / Nb nuits", fmt_italic)

    # ----- Totaux globaux du fichier (statiques) -----
    # Total EEG selon le mode magasin :
    #   - mag 1 : ES + bonus rails + SA 2.1 saisonnier
    #   - mag 2 : ES + SA 1.5 + SA 2.1 saisonnier (bonus rails NON inclus)
    total_es_brut = (totals["es_15"] or 0) + (totals["es_21"] or 0)
    total_bonus = (totals.get("es_15_bonus_noir") or 0) + (totals.get("es_15_bonus_blanc") or 0)
    total_sa_15 = totals.get("sa_15") or 0
    total_sa_21 = totals.get("sa_21") or 0
    sa_21_saisonnier = int(summary.get("sa_21_saisonnier") or 0)
    if is_m2:
        total_eeg = total_es_brut + total_sa_15 + sa_21_saisonnier
    else:
        total_eeg = total_es_brut + total_bonus + sa_21_saisonnier
    ws.write(3, 0, "Total EEG", fmt_lbl)
    ws.write_number(3, 1, total_eeg, fmt_num)
    ws.write(3, 2, "Total Rails ES", fmt_lbl)
    ws.write_number(3, 3, totals["rails_es"], fmt_num)
    fmt_sa_total = workbook.add_format({"bold": True, "bg_color": "#F9FAFB", "border": 1,
                                         "align": "left", "italic": True, "font_color": "#6B7280"})
    fmt_sa_total_num = workbook.add_format({"border": 1, "align": "right", "bg_color": "#F9FAFB",
                                             "italic": True, "font_color": "#6B7280"})
    if is_m2:
        ws.write(3, 4, "Total SA 2.1 (info)", fmt_sa_total)
        ws.write_number(3, 5, total_sa_21, fmt_sa_total_num)
        # SA 1.5 (à poser, inclus dans EEG)
        fmt_sa15_lbl = workbook.add_format({"bold": True, "bg_color": "#F3E8FF", "border": 1,
                                             "align": "left", "font_color": "#6B21A8"})
        fmt_sa15_num = workbook.add_format({"bold": True, "border": 1, "align": "right",
                                             "bg_color": "#F3E8FF", "font_color": "#6B21A8"})
        ws.write(3, 6, "SA 1.5 (à poser)", fmt_sa15_lbl)
        ws.write_number(3, 7, total_sa_15, fmt_sa15_num)
        ws.write_string(3, 8, "(inclus dans Total EEG)", fmt_italic)
    else:
        ws.write(3, 4, "Total SA (info)", fmt_sa_total)
        ws.write_number(3, 5, totals.get("sa", 0), fmt_sa_total_num)

        # Bonus rails → ES 1.5 (info, déjà inclus dans Total EEG)
        fmt_bonus_lbl = workbook.add_format({"bold": True, "bg_color": "#DBEAFE", "border": 1,
                                              "align": "left", "font_color": "#1E40AF"})
        fmt_bonus_num = workbook.add_format({"bold": True, "border": 1, "align": "right",
                                              "bg_color": "#DBEAFE", "font_color": "#1E40AF"})
        ws.write(3, 6, "Bonus rails → ES 1.5", fmt_bonus_lbl)
        ws.write_number(3, 7, total_bonus, fmt_bonus_num)
        ws.write_string(3, 8, f"(noir {int(totals.get('es_15_bonus_noir') or 0)} / blanc {int(totals.get('es_15_bonus_blanc') or 0)})", fmt_italic)
    # SA 2.1 saisonnier sur ligne 5 (cellule F5 = G5? — col 5 = F)
    fmt_sa21_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1,
                                         "align": "left", "font_color": "#92400E"})
    fmt_sa21_num = workbook.add_format({"bold": True, "border": 1, "align": "right",
                                         "bg_color": "#FEF3C7", "font_color": "#92400E"})
    ws.write(4, 0, "SA 2.1 saisonnier", fmt_sa21_lbl)
    ws.write_number(4, 1, sa_21_saisonnier, fmt_sa21_num)
    ws.write(4, 2, "(réparti au prorata des ES par nuit)", fmt_italic)
    # Référence Excel B5 (1-based) qui contient le SA 2.1 saisonnier — utilisée par les formules EEG
    SA21_REF = "$B$5"

    ws.write(5, 0, "Rails ES par désignation :", fmt_lbl)
    r = 6
    for pat in RAILS_ES_PATTERNS:
        ws.write(r, 0, pat, fmt_cell)
        ws.write_number(r, 1, totals["rails_es_by_desig"].get(pat, 0), fmt_num)
        r += 1

    # ----- Tableau gauche (interactif) -----
    start_left = r + 2
    ws.merge_range(start_left, 0, start_left, 4, "Plan d'attribution par allée", fmt_title)
    # En magasin 2, SA = SA 2.1 (info uniquement). EEG inclut déjà SA 1.5.
    sa_col_label = "SA 2.1" if is_m2 else "SA"
    headers_left = ["N° Allée", "EEG", "Rails ES", sa_col_label, "Nuit"]
    for ci, h in enumerate(headers_left):
        ws.write(start_left + 1, ci, h, fmt_lbl)

    first_data_row = start_left + 2  # 0-indexed
    nb_rows_left = max(n_allees, len(rows_assign), 30)

    # Sources pour les data validations
    # _Phasage_data!$A$2:$A${n_data_rows+1} — inclut les zones saisonnières
    allee_source = f"=_Phasage_data!$A$2:$A${n_data_rows + 1}"
    # Constante : la dropdown de nuit propose exactement nb_nuits entrées.
    # Le tableau droit fait également nb_nuits lignes.
    nuit_labels = [f"Nuit {n}" for n in range(1, nb_nuits + 1)]

    # Pré-remplissage des assignations existantes (ordre = ordre du phasage utilisateur)
    # Conversion uid (DB) -> display_label (Excel)
    existing = []
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = uid_to_label.get(a_uid, a_uid)
        n = row.get("nuit")
        existing.append({"allee": a_label, "nuit": (int(n) if n and 1 <= int(n) <= nb_nuits else None)})

    # Plages pour les formules (Excel 1-based)
    excel_first = first_data_row + 1
    excel_last = first_data_row + nb_rows_left
    A_range = f"$A${excel_first}:$A${excel_last}"
    B_range = f"$B${excel_first}:$B${excel_last}"  # ES (1.5 + 2.1)
    C_range = f"$C${excel_first}:$C${excel_last}"  # Rails ES
    D_range_sa = f"$D${excel_first}:$D${excel_last}"  # SA (info)
    E_range = f"$E${excel_first}:$E${excel_last}"  # Nuit
    vlookup_range = f"_Phasage_data!$A$2:$D${n_data_rows + 1}"  # 4 colonnes: Allée, EEG, Rails, SA

    # Format italique pour la colonne SA (info, plus discret)
    fmt_sa_info = workbook.add_format({"border": 1, "align": "right", "bg_color": "#F9FAFB",
                                       "italic": True, "font_color": "#6B7280"})

    for i in range(nb_rows_left):
        rr = first_data_row + i
        excel_row = rr + 1  # 1-based
        ws.data_validation(rr, 0, rr, 0, {
            "validate": "list",
            "source": allee_source,
            "error_message": "Sélectionnez une allée existante dans le fichier",
            "error_title": "Allée inconnue",
        })
        if i < len(existing) and existing[i]["allee"]:
            ws.write_string(rr, 0, existing[i]["allee"], fmt_cell)
        else:
            ws.write_blank(rr, 0, None, fmt_cell)

        # ES (col 1) / Rails ES (col 2) / SA (col 3) : formules VLOOKUP
        ws.write_formula(rr, 1, f'=IFERROR(VLOOKUP(A{excel_row},{vlookup_range},2,FALSE),"")', fmt_num_calc)
        ws.write_formula(rr, 2, f'=IFERROR(VLOOKUP(A{excel_row},{vlookup_range},3,FALSE),"")', fmt_num_calc)
        ws.write_formula(rr, 3, f'=IFERROR(VLOOKUP(A{excel_row},{vlookup_range},4,FALSE),"")', fmt_sa_info)

        # Nuit (col 4 = E) : data validation + valeur préremplie + format neutre
        ws.data_validation(rr, 4, rr, 4, {
            "validate": "list",
            "source": nuit_labels,
        })
        if i < len(existing) and existing[i]["nuit"]:
            ws.write_string(rr, 4, f"Nuit {existing[i]['nuit']}", fmt_nuit_cell)
        else:
            ws.write_blank(rr, 4, None, fmt_nuit_cell)

    # ----- Tableau droite (formules SUMIFS, mise en forme conditionnelle pour les couleurs) -----
    col_right = 6
    ws.merge_range(start_left, col_right, start_left, col_right + 4, "Récap par nuit", fmt_title)
    headers_right = ["Nuit", "Allées", "EEG", "Rails ES", "SA 2.1" if is_m2 else "SA"]
    for ci, h in enumerate(headers_right):
        ws.write(start_left + 1, col_right + ci, h, fmt_lbl)

    # Pré-calcul des allées par nuit pour la colonne "Allées" (texte statique)
    # Conversion uid -> label court (8, 112-1, ZS1)
    night_allees_static: dict[int, list[str]] = {n: [] for n in range(1, nb_nuits + 1)}
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = uid_to_label.get(a_uid, a_uid)
        n = row.get("nuit")
        if a_label and n and 1 <= int(n) <= nb_nuits:
            night_allees_static[int(n)].append(a_label)

    # Tri ordonné des labels : utilise l'ordre déjà calculé dans summary["allees"]
    # (zones saisonnières en fin)
    smart_order = {}
    for i, a in enumerate(all_allees):
        smart_order[_allee_display_label(a)] = i
    for j, z in enumerate(seasonal_zones):
        smart_order[str(z["id"])] = n_allees + j

    def _sort_allee_key(a):
        return smart_order.get(str(a), 99999)

    fmt_cell_neutral = workbook.add_format({"border": 1, "align": "center"})
    fmt_num_neutral = workbook.add_format({"border": 1, "align": "right"})
    fmt_sa_neutral = workbook.add_format({"border": 1, "align": "right",
                                           "italic": True, "font_color": "#6B7280"})
    fmt_allees_neutral = workbook.add_format({"border": 1, "align": "left"})

    for i, n in enumerate(range(1, nb_nuits + 1), start=0):
        rrow = first_data_row + i
        nuit_label = f"Nuit {n}"
        ws.write(rrow, col_right + 0, nuit_label, fmt_cell_neutral)
        # Colonne "Allées" : texte statique (calculé à l'export)
        allees_sorted = sorted(night_allees_static.get(n, []), key=_sort_allee_key)
        allees_text = ", ".join(allees_sorted) if allees_sorted else ""
        ws.write_string(rrow, col_right + 1, allees_text, fmt_allees_neutral)
        # EEG par nuit :
        #   - Magasin 2 : simple SUMIFS sur col B (qui contient déjà ES+SA1.5+saisonnier des zones affectées)
        #   - Magasin 1 : SUMIFS + prorata SA 2.1 saisonnier sur les nuits ES
        if is_m2:
            eeg_formula = f'=SUMIFS({B_range},{E_range},"{nuit_label}")'
        else:
            eeg_formula = (f'=ROUND(SUMIFS({B_range},{E_range},"{nuit_label}")'
                           f'+IFERROR(SUMIFS({B_range},{E_range},"{nuit_label}")/SUM({B_range})*{SA21_REF},0),0)')
        ws.write_formula(rrow, col_right + 2, eeg_formula, fmt_num_neutral)
        ws.write_formula(rrow, col_right + 3,
                         f'=SUMIFS({C_range},{E_range},"{nuit_label}")', fmt_num_neutral)
        ws.write_formula(rrow, col_right + 4,
                         f'=SUMIFS({D_range_sa},{E_range},"{nuit_label}")', fmt_sa_neutral)

    # Ligne TOTAL (somme des nb_nuits lignes)
    rrow_total = first_data_row + nb_nuits
    excel_total_first = first_data_row + 1
    excel_total_last = first_data_row + nb_nuits
    ws.write(rrow_total, col_right + 0, "TOTAL", fmt_total_lbl)
    ws.write_formula(rrow_total, col_right + 1,
                     f'=COUNTA({A_range})&" allées planifiées"',
                     fmt_total_lbl)
    for offset in range(2, 5):
        col_letter = chr(ord('A') + col_right + offset)
        ws.write_formula(rrow_total, col_right + offset,
                         f"=SUM(${col_letter}${excel_total_first}:${col_letter}${excel_total_last})",
                         fmt_total_row)

    # ----- Découpage par semaine (optionnel, si phasage.es.weeks est défini) -----
    phasage_es_local = _normalize_phasage(d.get("phasage"))["es"]
    weeks = phasage_es_local.get("weeks") if isinstance(phasage_es_local, dict) else None
    nuit_col_right_letter = chr(ord('A') + col_right)  # G — utilisé par CF semaines et plus bas
    week_section_end = rrow_total  # sera mis à jour si weeks est défini
    if weeks and len(weeks) >= 1 and sum(weeks) > 0:
        nb_nuits_total = sum(weeks)
        # Tableau "Découpage par semaine" sous le récap droit, col_right
        ws_start = rrow_total + 3
        ws.merge_range(ws_start, col_right, ws_start, col_right + 4,
                       "Découpage par semaine", fmt_title)
        cur_row = ws_start + 1
        cumul = 0
        fmt_week_hdr = workbook.add_format({"bold": True, "bg_color": "#1F2937",
                                            "font_color": "white", "border": 1,
                                            "align": "center", "font_size": 11})
        fmt_subtotal = workbook.add_format({"bold": True, "bg_color": "#E5E7EB",
                                            "border": 1, "align": "right"})
        fmt_subtotal_lbl = workbook.add_format({"bold": True, "bg_color": "#E5E7EB",
                                                "border": 1, "align": "center"})
        for wi, nb in enumerate(weeks, start=1):
            n_start = cumul + 1
            n_end = cumul + nb
            cumul += nb
            # Header semaine
            ws.merge_range(cur_row, col_right, cur_row, col_right + 4,
                           f"Semaine {wi} (Nuits {n_start} → {n_end})", fmt_week_hdr)
            cur_row += 1
            # Headers colonnes
            for ci, h in enumerate(headers_right):
                ws.write(cur_row, col_right + ci, h, fmt_lbl)
            cur_row += 1
            # Lignes des nuits
            sub_first = cur_row + 1
            for n in range(n_start, n_end + 1):
                if n > nb_nuits:
                    # nuit au-delà du planificateur → ligne vide
                    ws.write(cur_row, col_right + 0, f"Nuit {n}", fmt_cell_neutral)
                    for k in range(1, 5):
                        ws.write_blank(cur_row, col_right + k, None, fmt_num_neutral)
                else:
                    nuit_label = f"Nuit {n}"
                    ws.write(cur_row, col_right + 0, nuit_label, fmt_cell_neutral)
                    allees_sorted = sorted(night_allees_static.get(n, []), key=_sort_allee_key)
                    ws.write_string(cur_row, col_right + 1,
                                    ", ".join(allees_sorted) if allees_sorted else "",
                                    fmt_allees_neutral)
                    ws.write_formula(cur_row, col_right + 2,
                                     f'=ROUND(SUMIFS({B_range},{E_range},"{nuit_label}")'
                                     f'+IFERROR(SUMIFS({B_range},{E_range},"{nuit_label}")/SUM({B_range})*{SA21_REF},0),0)',
                                     fmt_num_neutral)
                    ws.write_formula(cur_row, col_right + 3,
                                     f'=SUMIFS({C_range},{E_range},"{nuit_label}")', fmt_num_neutral)
                    ws.write_formula(cur_row, col_right + 4,
                                     f'=SUMIFS({D_range_sa},{E_range},"{nuit_label}")', fmt_sa_neutral)
                cur_row += 1
            sub_last = cur_row  # 1-indexed row of last data line
            # Sous-total semaine
            ws.write(cur_row, col_right + 0, f"Sous-total S{wi}", fmt_subtotal_lbl)
            ws.write(cur_row, col_right + 1, "", fmt_subtotal_lbl)
            for offset in range(2, 5):
                col_letter = chr(ord('A') + col_right + offset)
                ws.write_formula(cur_row, col_right + offset,
                                 f"=SUM(${col_letter}${sub_first}:${col_letter}${sub_last})",
                                 fmt_subtotal)
            cur_row += 2  # une ligne d'espace entre les semaines
            # CF couleur par nuit sur les lignes data de cette semaine
            data_first_0 = sub_first - 1  # 0-indexed
            data_last_0 = sub_last - 1
            for n in range(n_start, n_end + 1):
                if n > nb_nuits: continue
                cf_fmt = cf_formats_right.get(n)
                if cf_fmt:
                    ws.conditional_format(
                        data_first_0, col_right, data_last_0, col_right + 4,
                        {"type": "formula",
                         "criteria": f'=${nuit_col_right_letter}{sub_first}="Nuit {n}"',
                         "format": cf_fmt})
        week_section_end = cur_row

    # ----- Mise en forme conditionnelle : couleur de la nuit appliquée à toute la ligne -----
    # Tableau gauche : range A:E sur toutes les lignes data, formule basée sur la valeur en col E
    for n in range(1, nb_nuits + 1):
        cf_fmt = cf_formats_left[n]
        ws.conditional_format(
            first_data_row, 0, first_data_row + nb_rows_left - 1, 4,
            {
                "type": "formula",
                "criteria": f'=$E{first_data_row + 1}="Nuit {n}"',
                "format": cf_fmt,
            }
        )
    # Tableau droit : range G:K sur les lignes data, formule basée sur valeur en col G (Nuit)
    for n in range(1, nb_nuits + 1):
        cf_fmt = cf_formats_right[n]
        ws.conditional_format(
            first_data_row, col_right, first_data_row + nb_nuits - 1, col_right + 4,
            {
                "type": "formula",
                "criteria": f'=${nuit_col_right_letter}{first_data_row + 1}="Nuit {n}"',
                "format": cf_fmt,
            }
        )

    # Mise en forme conditionnelle : surligner en ROUGE les allées en DOUBLON
    fmt_duplicate = workbook.add_format({"bg_color": "#FEE2E2", "font_color": "#991B1B",
                                          "border": 1, "bold": True})
    ws.conditional_format(
        first_data_row, 0, first_data_row + nb_rows_left - 1, 0,
        {"type": "duplicate", "format": fmt_duplicate}
    )

    # ----- Graphique : répartition par nuit (barres ES + Rails ES) -----
    chart = workbook.add_chart({"type": "column"})
    cat_ref = f"='Phasage de pose'!${chr(ord('A')+col_right)}${excel_total_first}:${chr(ord('A')+col_right)}${excel_total_last}"
    es_ref = f"='Phasage de pose'!${chr(ord('A')+col_right+2)}${excel_total_first}:${chr(ord('A')+col_right+2)}${excel_total_last}"
    rails_ref = f"='Phasage de pose'!${chr(ord('A')+col_right+3)}${excel_total_first}:${chr(ord('A')+col_right+3)}${excel_total_last}"
    chart.add_series({
        "name": "ES",
        "categories": cat_ref,
        "values": es_ref,
        "fill": {"color": "#10B981"},
    })
    chart.add_series({
        "name": "Rails ES",
        "categories": cat_ref,
        "values": rails_ref,
        "fill": {"color": "#F59E0B"},
    })
    chart.set_title({"name": "Répartition ES par nuit"})
    chart.set_x_axis({"name": "Nuit"})
    chart.set_y_axis({"name": "Quantité"})
    chart.set_size({"width": 720, "height": 360})
    chart.set_style(11)
    chart_row = rrow_total + 3
    ws.insert_chart(chart_row, col_right, chart, {"x_offset": 0, "y_offset": 0})

    # Petite note d'aide en bas
    note_row = max(first_data_row + nb_rows_left, chart_row + 20) + 1
    ws.merge_range(note_row, 0, note_row, 10,
                   "Astuce : sélectionne une allée et une nuit dans les colonnes déroulantes — "
                   "les comptes (ES = somme ES 1.5 + ES 2.1, Rails ES, SA) et le récap par nuit se mettent à jour automatiquement. "
                   "La couleur de chaque ligne suit la nuit sélectionnée. "
                   "Les allées en DOUBLON sont surlignées en ROUGE dans la colonne « N° Allée ». "
                   "La colonne « Allées » du récap droit reflète l'état au moment de l'export — ré-exporte pour la rafraîchir.",
                   fmt_italic)






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

def _write_phasage_cam_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total):
    """Feuille "Phasage caméras" INTERACTIVE."""
    summary = compute_phasage_summary(d)
    phasage_full = _normalize_phasage(d.get("phasage"))
    phasage = phasage_full["cam"]
    nb_nuits = max(1, int(phasage.get("nb_nuits") or 3))
    start_at = int(phasage.get("start_at_nuit") or 5)
    rows_assign = phasage.get("rows") or []
    all_allees = [a for a in summary["allees"] if (a.get("cameras") or 0) > 0]
    totals = summary["totals"]
    n_allees = len(all_allees)

    # Mapping uid -> label court — basé sur TOUTES les allées du summary
    # (pour pouvoir convertir même les uids d'allées sans caméras qui auraient
    # été assignés par erreur).
    uid_to_label = _build_uid_to_label(summary["allees"], summary.get("seasonal_zones"))

    if n_allees == 0:
        ws = workbook.add_worksheet("Phasage caméras")
        writer.sheets["Phasage caméras"] = ws
        ws.write(0, 0, "Aucune caméra (noire/blanche) détectée.", fmt_header)
        return

    ws = workbook.add_worksheet("Phasage caméras")
    writer.sheets["Phasage caméras"] = ws
    ws.activate()
    ws_data = workbook.add_worksheet("_Phasage_cam_data")
    writer.sheets["_Phasage_cam_data"] = ws_data
    ws_data.write_row(0, 0, ["Allée", "Caméras"])
    for i, a in enumerate(all_allees, start=1):
        ws_data.write_string(i, 0, _allee_display_label(a))
        ws_data.write_number(i, 1, a.get("cameras") or 0)
    ws_data.hide()

    for c in range(7):
        ws.set_column(c, c, [12, 12, 12, 3, 12, 32, 12][c])

    fmt_title = workbook.add_format({"bold": True, "bg_color": "#7C3AED", "font_color": "white",
                                     "border": 1, "font_size": 12, "align": "left"})
    fmt_lbl = workbook.add_format({"bold": True, "bg_color": "#F3F4F6", "border": 1, "align": "left"})
    fmt_num = workbook.add_format({"border": 1, "align": "right"})
    fmt_num_calc = workbook.add_format({"border": 1, "align": "right", "bg_color": "#FAFAFA"})
    fmt_input = workbook.add_format({"border": 1, "align": "center", "bg_color": "#FFFBEB", "bold": True})
    fmt_total_row = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right"})
    fmt_total_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "left"})
    fmt_italic = workbook.add_format({"italic": True, "border": 1, "font_color": "#6B7280"})
    fmt_cell_neutral = workbook.add_format({"border": 1, "align": "center"})
    fmt_num_neutral = workbook.add_format({"border": 1, "align": "right"})
    fmt_allees_neutral = workbook.add_format({"border": 1, "align": "left"})

    # Couleurs FIXES par position dans la semaine — identiques au frontend.
    # Phasage caméras n'a pas de découpage par semaine → on cycle modulo 4 sur l'absolu.
    cf_left, cf_right = {}, {}
    for n in range(1, nb_nuits + 1):
        color = night_color_hex(n, None)
        cf_left[n] = workbook.add_format({"bg_color": color, "border": 1})
        cf_right[n] = workbook.add_format({"bg_color": color, "border": 1})

    ws.merge_range(0, 0, 0, 6, "Phasage de pose des caméras (noire & blanche)", fmt_title)
    ws.write(1, 0, "Nb nuits :", fmt_lbl)
    ws.write_number(1, 1, nb_nuits, fmt_input)
    ws.write(1, 2, "Démarrage :", fmt_lbl)
    ws.write_number(1, 3, start_at, fmt_input)
    ws.write(1, 4, "Info : ~300 caméras / nuit", fmt_italic)
    ws.write(3, 0, "Total Caméras", fmt_lbl)
    ws.write_number(3, 1, totals.get("cameras", 0), fmt_num)
    ws.write(3, 2, "Moyenne / nuit :", fmt_lbl)
    ws.write_formula(3, 3, "=IFERROR(ROUND(B4/B2,0),0)", fmt_num_calc)

    nuit_labels = [f"Nuit {start_at + i}" for i in range(nb_nuits)]

    existing = []
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = uid_to_label.get(a_uid, a_uid)
        n = row.get("nuit")
        existing.append({"allee": a_label, "nuit": (int(n) if n and 1 <= int(n) <= nb_nuits else None)})

    start_left = 6
    ws.merge_range(start_left, 0, start_left, 2, "Plan d'attribution par allée", fmt_title)
    for ci, h in enumerate(["N° Allée", "Caméras", "Nuit"]):
        ws.write(start_left + 1, ci, h, fmt_lbl)

    first_data_row = start_left + 2
    nb_rows_left = max(n_allees, len(rows_assign), 20)
    allee_source = f"=_Phasage_cam_data!$A$2:$A${n_allees + 1}"
    excel_first = first_data_row + 1
    excel_last = first_data_row + nb_rows_left
    A_range = f"$A${excel_first}:$A${excel_last}"
    B_range = f"$B${excel_first}:$B${excel_last}"
    C_range = f"$C${excel_first}:$C${excel_last}"
    vlookup_range = f"_Phasage_cam_data!$A$2:$B${n_allees + 1}"

    for i in range(nb_rows_left):
        rr = first_data_row + i
        excel_row = rr + 1
        ws.data_validation(rr, 0, rr, 0, {"validate": "list", "source": allee_source})
        if i < len(existing) and existing[i]["allee"]:
            ws.write_string(rr, 0, existing[i]["allee"], fmt_cell)
        else:
            ws.write_blank(rr, 0, None, fmt_cell)
        ws.write_formula(rr, 1, f'=IFERROR(VLOOKUP(A{excel_row},{vlookup_range},2,FALSE),"")', fmt_num_calc)
        ws.data_validation(rr, 2, rr, 2, {"validate": "list", "source": nuit_labels})
        if i < len(existing) and existing[i]["nuit"]:
            local_n = existing[i]["nuit"]
            ws.write_string(rr, 2, f"Nuit {start_at + local_n - 1}", fmt_cell_neutral)
        else:
            ws.write_blank(rr, 2, None, fmt_cell_neutral)

    col_right = 4
    ws.merge_range(start_left, col_right, start_left, col_right + 2, "Récap par nuit", fmt_title)
    for ci, h in enumerate(["Nuit", "Allées", "Caméras"]):
        ws.write(start_left + 1, col_right + ci, h, fmt_lbl)

    night_allees_static: dict[int, list[str]] = {n: [] for n in range(1, nb_nuits + 1)}
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = uid_to_label.get(a_uid, a_uid)
        n = row.get("nuit")
        if a_label and n and 1 <= int(n) <= nb_nuits:
            night_allees_static[int(n)].append(a_label)
    smart_order = {_allee_display_label(a): i for i, a in enumerate(all_allees)}
    def _sak(a): return smart_order.get(str(a), 99999)

    for i, n in enumerate(range(1, nb_nuits + 1)):
        rrow = first_data_row + i
        nuit_label = f"Nuit {start_at + n - 1}"
        ws.write(rrow, col_right + 0, nuit_label, fmt_cell_neutral)
        ws.write_string(rrow, col_right + 1, ", ".join(sorted(night_allees_static.get(n, []), key=_sak)), fmt_allees_neutral)
        ws.write_formula(rrow, col_right + 2, f'=SUMIFS({B_range},{C_range},"{nuit_label}")', fmt_num_neutral)

    rrow_total = first_data_row + nb_nuits
    ws.write(rrow_total, col_right + 0, "TOTAL", fmt_total_lbl)
    ws.write_formula(rrow_total, col_right + 1, f'=COUNTA({A_range})&" allées planifiées"', fmt_total_lbl)
    ws.write_formula(rrow_total, col_right + 2,
                     f"=SUM(${chr(ord('A')+col_right+2)}${excel_first}:${chr(ord('A')+col_right+2)}${first_data_row + nb_nuits})",
                     fmt_total_row)

    for n in range(1, nb_nuits + 1):
        nuit_label = f"Nuit {start_at + n - 1}"
        ws.conditional_format(first_data_row, 0, first_data_row + nb_rows_left - 1, 2,
            {"type": "formula", "criteria": f'=$C{first_data_row + 1}="{nuit_label}"', "format": cf_left[n]})
        nuit_col = chr(ord('A') + col_right)
        ws.conditional_format(first_data_row, col_right, first_data_row + nb_nuits - 1, col_right + 2,
            {"type": "formula", "criteria": f'=${nuit_col}{first_data_row + 1}="{nuit_label}"', "format": cf_right[n]})
    fmt_dup = workbook.add_format({"bg_color": "#FEE2E2", "font_color": "#991B1B", "border": 1, "bold": True})
    ws.conditional_format(first_data_row, 0, first_data_row + nb_rows_left - 1, 0,
        {"type": "duplicate", "format": fmt_dup})

    # --- Bloc détail par allée : Allée | N° Elements (couleur par nuit identique au récap) ---
    detail_idx = {_allee_display_label(a): a for a in all_allees}
    detail_rows = []  # list of (nuit, allee_label, [elems])
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = uid_to_label.get(a_uid, a_uid)
        n = row.get("nuit")
        if not a_label or not n: continue
        node = detail_idx.get(a_label)
        if not node: continue
        detail_rows.append((int(n), a_label, node.get("camera_elems") or []))
    # Tri (nuit, ordre allée)
    detail_rows.sort(key=lambda x: (x[0], smart_order.get(x[1], 99999)))

    if detail_rows:
        detail_start = first_data_row + nb_nuits + 3  # 2 lignes de blank après TOTAL récap
        ws.merge_range(detail_start, 0, detail_start, 2, "Détail caméras par allée", fmt_title)
        ws.write(detail_start + 1, 0, "Allées", fmt_lbl)
        ws.merge_range(detail_start + 1, 1, detail_start + 1, 2, "N° Elements", fmt_lbl)
        # Polices pour les rich strings (normal + rouge gras pour doublons)
        font_normal = workbook.add_format({"font_color": "#374151"})
        font_dup = workbook.add_format({"font_color": "#DC2626", "bold": True})
        # Cellules colorées par nuit (couleur identique au récap par nuit)
        for i, (n, a, elems) in enumerate(detail_rows):
            rr = detail_start + 2 + i
            color = night_color_hex(n, None)
            fmt_night_left = workbook.add_format({"bg_color": color, "border": 1, "align": "center"})
            fmt_night_right = workbook.add_format({"bg_color": color, "border": 1, "align": "left"})
            ws.write_string(rr, 0, a, fmt_night_left)
            # Construire la rich_string : éléments en rouge si doublons
            counts = {}
            for e in elems: counts[str(e)] = counts.get(str(e), 0) + 1
            if not elems:
                ws.merge_range(rr, 1, rr, 2, "", fmt_night_right)
            else:
                parts = []
                for idx, e in enumerate(elems):
                    if idx > 0:
                        parts.extend([font_normal, ", "])
                    is_dup = counts[str(e)] > 1
                    parts.extend([font_dup if is_dup else font_normal, str(e)])
                # write_rich_string ne supporte pas merge_range, donc on écrit dans la 1ère cellule
                # et on merge avec border seulement
                ws.merge_range(rr, 1, rr, 2, "", fmt_night_right)
                ws.write_rich_string(rr, 1, *parts, fmt_night_right)


def _build_consolidated_nuit_data(d, summary):
    """Construit le planning consolidé { nuit_globale: {type, allees, es, cam, rails_es} }."""
    phasage_full = _normalize_phasage(d.get("phasage"))
    es_plan = phasage_full["es"]
    cam_plan = phasage_full["cam"]
    start_at = int(cam_plan.get("start_at_nuit") or 5)
    # idx clé = uid (= ce qui est stocké en DB dans rows[].allee)
    idx = {str(a.get("uid") or a["allee"]): a for a in summary["allees"]}
    uid_to_label = _build_uid_to_label(summary["allees"], summary.get("seasonal_zones"))
    nuit_data: dict[int, dict] = {}
    for r in es_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = idx.get(a_uid)
        if not node: continue
        a_label = uid_to_label.get(a_uid, a_uid)
        gn = int(n)
        dn = nuit_data.setdefault(gn, {"type": "ES", "allees": [], "es": 0, "cam": 0, "rails_es": 0})
        dn["allees"].append(a_label)
        dn["es"] += (node.get("es_15") or 0) + (node.get("es_21") or 0)
        dn["rails_es"] += node.get("rails_es") or 0
    for r in cam_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = idx.get(a_uid)
        if not node: continue
        a_label = uid_to_label.get(a_uid, a_uid)
        gn = start_at + int(n) - 1
        dn = nuit_data.setdefault(gn, {"type": "Caméras", "allees": [], "es": 0, "cam": 0, "rails_es": 0})
        if dn["es"] > 0:
            dn["type"] = "Mixte"
        elif dn["type"] != "Mixte":
            dn["type"] = "Caméras"
        dn["allees"].append(a_label)
        dn["cam"] += node.get("cameras") or 0
    return nuit_data


def _write_phasage_full_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total):
    """Vue consolidée Excel — Phasage étiquettes/rails et Phasage caméras côte à côte,
    alignés sur une colonne Nuit centrale partagée."""
    summary = compute_phasage_summary(d)
    phasage_full = _normalize_phasage(d.get("phasage"))
    es_plan = phasage_full["es"]
    cam_plan = phasage_full["cam"]
    start_at = int(cam_plan.get("start_at_nuit") or 5)
    # idx clé = uid (ce qui est stocké en DB dans rows[].allee)
    idx = {str(a.get("uid") or a["allee"]): a for a in summary["allees"]}
    uid_to_label = _build_uid_to_label(summary["allees"], summary.get("seasonal_zones"))

    # Construit pour chaque nuit globale les agrégats ES et Cam séparés
    per_nuit: dict[int, dict] = {}
    for r in es_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = idx.get(a_uid)
        if not node: continue
        a_label = uid_to_label.get(a_uid, a_uid)
        gn = int(n)
        dn = per_nuit.setdefault(gn, {
            "es_allees": [], "es": 0, "rails_es": 0, "sa": 0,
            "cam_allees": [], "cam": 0,
        })
        dn["es_allees"].append(a_label)
        dn["es"] += (node.get("es_15") or 0) + (node.get("es_21") or 0)
        dn["rails_es"] += node.get("rails_es") or 0
        dn["sa"] += node.get("sa") or 0
    for r in cam_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = idx.get(a_uid)
        if not node: continue
        a_label = uid_to_label.get(a_uid, a_uid)
        gn = start_at + int(n) - 1
        dn = per_nuit.setdefault(gn, {
            "es_allees": [], "es": 0, "rails_es": 0, "sa": 0,
            "cam_allees": [], "cam": 0,
        })
        dn["cam_allees"].append(a_label)
        dn["cam"] += node.get("cameras") or 0

    # Tri smart des allées dans chaque liste (par label court)
    order_idx = {_allee_display_label(a): i for i, a in enumerate(summary["allees"])}
    for dn in per_nuit.values():
        dn["es_allees"].sort(key=lambda x: order_idx.get(x, 9999))
        dn["cam_allees"].sort(key=lambda x: order_idx.get(x, 9999))

    sorted_nuits = sorted(per_nuit.keys())

    ws = workbook.add_worksheet("Phasage full")
    writer.sheets["Phasage full"] = ws
    # 7 colonnes : A B C D | E (Nuit) | F G
    ws.set_column(0, 0, 32)   # A Allées (ES)
    ws.set_column(1, 1, 10)   # B ES
    ws.set_column(2, 2, 10)   # C Rails ES
    ws.set_column(3, 3, 8)    # D SA
    ws.set_column(4, 4, 10)   # E Nuit (partagée)
    ws.set_column(5, 5, 28)   # F Allées (Cam)
    ws.set_column(6, 6, 10)   # G Caméras

    fmt_title = workbook.add_format({"bold": True, "bg_color": "#056839", "font_color": "white",
                                     "border": 1, "font_size": 13, "align": "center"})
    fmt_subtitle_es = workbook.add_format({"bold": True, "bg_color": "#D1FAE5", "font_color": "#065F46",
                                            "border": 1, "font_size": 11, "align": "center"})
    fmt_subtitle_cam = workbook.add_format({"bold": True, "bg_color": "#EDE9FE", "font_color": "#5B21B6",
                                             "border": 1, "font_size": 11, "align": "center"})
    fmt_subtitle_nuit = workbook.add_format({"bold": True, "bg_color": "#1F2937", "font_color": "white",
                                              "border": 1, "font_size": 11, "align": "center"})
    fmt_lbl = workbook.add_format({"bold": True, "bg_color": "#F3F4F6", "border": 1, "align": "center"})
    fmt_text = workbook.add_format({"border": 1, "align": "left", "text_wrap": True})
    fmt_num = workbook.add_format({"border": 1, "align": "right"})
    fmt_nuit = workbook.add_format({"bold": True, "border": 1, "align": "center", "bg_color": "#F9FAFB"})
    fmt_total_row = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right"})
    fmt_total_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "center"})

    # Row 0 : titre global (fusionné A:G)
    ws.merge_range(0, 0, 0, 6, "Phasage full — Planning consolidé", fmt_title)
    # Row 1 : sous-titres distincts pour chaque bloc
    ws.merge_range(1, 0, 1, 3, "Phasage étiquettes et rails", fmt_subtitle_es)
    ws.write(1, 4, "Nuit", fmt_subtitle_nuit)
    ws.merge_range(1, 5, 1, 6, "Phasage caméras", fmt_subtitle_cam)
    # Row 2 : en-têtes de colonnes
    headers = ["Allées", "ES", "Rails ES", "SA", "Nuit", "Allées", "Caméras"]
    for ci, h in enumerate(headers):
        ws.write(2, ci, h, fmt_lbl)

    # Couleurs douces par nuit (10 couleurs en rotation) — appliquées via CF
    # Couleurs FIXES par position dans la semaine (récupérées du Phasage ES)
    phasage_full_obj = _normalize_phasage(d.get("phasage"))
    weeks_full = phasage_full_obj["es"].get("weeks") or []

    r = 3
    first_excel = r + 1
    for n in sorted_nuits:
        info = per_nuit[n]
        # Bloc ES (cols A-D)
        if info["es_allees"]:
            ws.write_string(r, 0, ", ".join(info["es_allees"]), fmt_text)
            ws.write_number(r, 1, round(info["es"]), fmt_num)
            ws.write_number(r, 2, round(info["rails_es"]), fmt_num)
            ws.write_number(r, 3, round(info["sa"]), fmt_num)
        else:
            for c in range(0, 4):
                ws.write_blank(r, c, None, fmt_num)
        # Nuit (col E, centrée, couleur par CF)
        ws.write_number(r, 4, n, fmt_nuit)
        # Bloc Cam (cols F-G)
        if info["cam_allees"]:
            ws.write_string(r, 5, ", ".join(info["cam_allees"]), fmt_text)
            ws.write_number(r, 6, round(info["cam"]), fmt_num)
        else:
            for c in range(5, 7):
                ws.write_blank(r, c, None, fmt_num)
        r += 1
    last_excel = r

    # Ligne TOTAL
    if r > 3:
        ws.write(r, 0, "", fmt_total_lbl)
        ws.write_formula(r, 1, f"=SUM(B{first_excel}:B{last_excel})", fmt_total_row)
        ws.write_formula(r, 2, f"=SUM(C{first_excel}:C{last_excel})", fmt_total_row)
        ws.write_formula(r, 3, f"=SUM(D{first_excel}:D{last_excel})", fmt_total_row)
        ws.write_formula(r, 4, f'=COUNTA(E{first_excel}:E{last_excel})&" nuits"', fmt_total_lbl)
        ws.write(r, 5, "", fmt_total_lbl)
        ws.write_formula(r, 6, f"=SUM(G{first_excel}:G{last_excel})", fmt_total_row)

        # Mise en forme conditionnelle par nuit : colore TOUTE la ligne (A-G) selon le numéro de nuit
        # Utilisation de la formule =$E4=N (référence absolue colonne E)
        for night_num in range(1, max(sorted_nuits) + 1):
            # Couleur = position dans la semaine pour la phase ES (les nuits caméras
            # commencent à start_at_nuit, on les considère hors-semaine → cycle modulo 4)
            color = night_color_hex(night_num, weeks_full)
            fmt_night = workbook.add_format({"bg_color": color, "border": 1})
            ws.conditional_format(3, 0, last_excel - 1, 6,
                {"type": "formula",
                 "criteria": f'=$E4={night_num}',
                 "format": fmt_night})

    ws.freeze_panes(3, 0)


def _write_suivi_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total):
    """Comparaison prévu / réalité — entièrement éditable dans Excel via formules natives.

    Layout 18 colonnes :
      A Nuit | B Type | C Allée phasage | D Allée réelle |
      E ES prévu | F ES réel | G Diff ES | H % ES |
      I Cam prévue | J Cam réelle | K Diff Cam | L % Cam |
      M Rails ES prévu | N Rails ES réel | O Diff Rails | P % Rails |
      Q Géolocalisés | R % Géoloc

    Règles :
    - Diff/% sont vides si la cellule Réel est vide (formule IF(F="","",...))
    - Bandeau ligne 2 : % sans coloration rouge/verte (neutre)
    - Ligne data : background vert clair si au moins un Réel est saisi
    - Diff per row : font rouge si négatif / vert si positif (CF)
    - Compatible vieil Excel : pas de TEXTJOIN, pas de formules array
    """
    summary = compute_phasage_summary(d)
    nuit_data = _build_consolidated_nuit_data(d, summary)
    phasage_full = _normalize_phasage(d.get("phasage"))
    suivi = phasage_full.get("suivi") or {"rows": []}
    suivi_idx = {int(r["nuit"]): r for r in (suivi.get("rows") or []) if r.get("nuit") is not None}

    ws = workbook.add_worksheet("Suivi phasage")
    writer.sheets["Suivi phasage"] = ws
    widths = [8, 10, 28, 14,
              11, 11, 11, 8,
              11, 11, 11, 8,
              12, 12, 12, 8,
              11, 8]
    for ci, w in enumerate(widths):
        ws.set_column(ci, ci, w)

    fmt_title = workbook.add_format({"bold": True, "bg_color": "#0E7490", "font_color": "white",
                                     "border": 1, "font_size": 12, "align": "left"})
    fmt_lbl = workbook.add_format({"bold": True, "bg_color": "#F3F4F6", "border": 1, "align": "center",
                                    "text_wrap": True})
    fmt_num = workbook.add_format({"border": 1, "align": "right"})
    fmt_num_prev = workbook.add_format({"border": 1, "align": "right", "bg_color": "#F9FAFB"})
    fmt_input = workbook.add_format({"border": 1, "align": "right", "bg_color": "#FFFBEB"})
    fmt_input_text = workbook.add_format({"border": 1, "align": "left", "bg_color": "#FFFBEB"})
    fmt_pct_row = workbook.add_format({"border": 1, "align": "right", "num_format": "0%",
                                       "bg_color": "#F9FAFB", "font_color": "#374151"})
    fmt_total_row = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right"})
    fmt_total_pct = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right",
                                         "num_format": "0%"})
    fmt_total_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "left"})
    fmt_positive = workbook.add_format({"border": 1, "align": "right", "font_color": "#047857"})
    fmt_negative = workbook.add_format({"border": 1, "align": "right", "font_color": "#B91C1C"})

    ws.merge_range(0, 0, 0, 17, "Suivi phasage — Prévu vs Réalité", fmt_title)
    for ci, h in enumerate(["Nuit", "Type", "Allée phasage", "Allée réelle",
                             "ES prévu", "ES réel", "Diff ES", "% ES",
                             "Cam prévue", "Cam réelle", "Diff Cam", "% Cam",
                             "Rails ES prévu", "Rails ES réel", "Diff Rails ES", "% Rails",
                             "Géolocalisés", "% Géoloc"]):
        ws.write(2, ci, h, fmt_lbl)

    sorted_nuits = sorted(nuit_data.keys())

    # Bandeau d'avancement (row 1) — 4 jauges neutres (sans CF rouge/vert)
    if sorted_nuits:
        total_excel = 4 + len(sorted_nuits)
        fmt_pct_value = workbook.add_format({
            "bold": True, "border": 1, "align": "center", "num_format": "0%",
            "bg_color": "#FFFFFF", "font_size": 12, "font_color": "#374151",
        })
        fmt_lbl_es = workbook.add_format({"bold": True, "bg_color": "#ECFDF5", "border": 1,
                                          "align": "right", "font_color": "#065F46", "font_size": 11})
        fmt_lbl_cam = workbook.add_format({"bold": True, "bg_color": "#FAF5FF", "border": 1,
                                           "align": "right", "font_color": "#5B21B6", "font_size": 11})
        fmt_lbl_rails = workbook.add_format({"bold": True, "bg_color": "#FFFBEB", "border": 1,
                                             "align": "right", "font_color": "#92400E", "font_size": 11})
        fmt_lbl_geo = workbook.add_format({"bold": True, "bg_color": "#F0F9FF", "border": 1,
                                           "align": "right", "font_color": "#075985", "font_size": 11})
        ws.set_row(1, 22)
        # ES: label A2:D2 (cols 0-3), value E2:H2 (cols 4-7)
        ws.merge_range(1, 0, 1, 3, "% Avancement ES :", fmt_lbl_es)
        ws.merge_range(1, 4, 1, 7, f'=IFERROR(F{total_excel}/E{total_excel},0)', fmt_pct_value)
        # Caméras: label I2:J2 (8-9), value K2:L2 (10-11)
        ws.merge_range(1, 8, 1, 9, "Caméras :", fmt_lbl_cam)
        ws.merge_range(1, 10, 1, 11, f'=IFERROR(J{total_excel}/I{total_excel},0)', fmt_pct_value)
        # Rails ES: label M2:N2 (12-13), value O2:P2 (14-15)
        ws.merge_range(1, 12, 1, 13, "Rails ES :", fmt_lbl_rails)
        ws.merge_range(1, 14, 1, 15, f'=IFERROR(N{total_excel}/M{total_excel},0)', fmt_pct_value)
        # Géolocalisés: label Q2 (16), value R2 (17)
        ws.write(1, 16, "Géoloc :", fmt_lbl_geo)
        ws.write_formula(1, 17, f'=IFERROR(Q{total_excel}/N{total_excel},0)', fmt_pct_value)
        # PAS de conditional formatting sur le bandeau (couleur neutre)

    r = 3
    first_excel = r + 1
    for n in sorted_nuits:
        info = nuit_data[n]
        existing = suivi_idx.get(n, {})
        excel_row = r + 1
        # A=Nuit, B=Type, C=Allée phasage, D=Allée réelle
        ws.write_number(r, 0, n, fmt_num)
        ws.write(r, 1, info["type"], fmt_num)
        ws.write_string(r, 2, ", ".join(info["allees"]), fmt_num)
        allee_reelle = existing.get("allee_reelle")
        if allee_reelle not in (None, ""):
            ws.write_string(r, 3, str(allee_reelle), fmt_input_text)
        else:
            ws.write_blank(r, 3, None, fmt_input_text)
        # ES (E=4, F=5 input, G=6 Diff, H=7 %)
        ws.write_number(r, 4, round(info["es"]), fmt_num_prev)
        es_reel = existing.get("es_reel")
        if es_reel not in (None, ""):
            try: ws.write_number(r, 5, float(es_reel), fmt_input)
            except (ValueError, TypeError): ws.write_blank(r, 5, None, fmt_input)
        else:
            ws.write_blank(r, 5, None, fmt_input)
        ws.write_formula(r, 6, f'=IF(F{excel_row}="","",F{excel_row}-E{excel_row})', fmt_num)
        ws.write_formula(r, 7, f'=IF(F{excel_row}="","",IFERROR(F{excel_row}/E{excel_row},""))', fmt_pct_row)
        # Cam (I=8, J=9, K=10, L=11)
        ws.write_number(r, 8, round(info["cam"]), fmt_num_prev)
        cam_reel = existing.get("cam_reel")
        if cam_reel not in (None, ""):
            try: ws.write_number(r, 9, float(cam_reel), fmt_input)
            except (ValueError, TypeError): ws.write_blank(r, 9, None, fmt_input)
        else:
            ws.write_blank(r, 9, None, fmt_input)
        ws.write_formula(r, 10, f'=IF(J{excel_row}="","",J{excel_row}-I{excel_row})', fmt_num)
        ws.write_formula(r, 11, f'=IF(J{excel_row}="","",IFERROR(J{excel_row}/I{excel_row},""))', fmt_pct_row)
        # Rails ES (M=12, N=13, O=14, P=15)
        ws.write_number(r, 12, round(info.get("rails_es") or 0), fmt_num_prev)
        rg = existing.get("rails_geoloc")
        if rg not in (None, ""):
            try: ws.write_number(r, 13, float(rg), fmt_input)
            except (ValueError, TypeError): ws.write_blank(r, 13, None, fmt_input)
        else:
            ws.write_blank(r, 13, None, fmt_input)
        ws.write_formula(r, 14, f'=IF(N{excel_row}="","",N{excel_row}-M{excel_row})', fmt_num)
        ws.write_formula(r, 15, f'=IF(N{excel_row}="","",IFERROR(N{excel_row}/M{excel_row},""))', fmt_pct_row)
        # Géoloc (Q=16, R=17)
        gc = existing.get("rails_geoloc_count")
        if gc not in (None, ""):
            try: ws.write_number(r, 16, float(gc), fmt_input)
            except (ValueError, TypeError): ws.write_blank(r, 16, None, fmt_input)
        else:
            ws.write_blank(r, 16, None, fmt_input)
        ws.write_formula(r, 17, f'=IF(Q{excel_row}="","",IFERROR(Q{excel_row}/N{excel_row},""))', fmt_pct_row)
        r += 1
    last_excel = r
    if r > 3:
        # Ligne TOTAL
        ws.write(r, 0, "TOTAL", fmt_total_lbl)
        ws.write(r, 1, "", fmt_total_lbl)
        ws.write_formula(r, 2, f'=COUNTA(A{first_excel}:A{last_excel})&" nuits"', fmt_total_lbl)
        ws.write(r, 3, "", fmt_total_lbl)
        # Sommes (colonnes numériques sauf %)
        for col_letter, col_idx in [("E", 4), ("F", 5), ("G", 6),
                                     ("I", 8), ("J", 9), ("K", 10),
                                     ("M", 12), ("N", 13), ("O", 14),
                                     ("Q", 16)]:
            ws.write_formula(r, col_idx,
                f"=SUM({col_letter}{first_excel}:{col_letter}{last_excel})", fmt_total_row)
        # % du TOTAL (toujours calculés, même si Réel sommé = 0)
        excel_total = r + 1
        ws.write_formula(r, 7, f'=IFERROR(F{excel_total}/E{excel_total},0)', fmt_total_pct)
        ws.write_formula(r, 11, f'=IFERROR(J{excel_total}/I{excel_total},0)', fmt_total_pct)
        ws.write_formula(r, 15, f'=IFERROR(N{excel_total}/M{excel_total},0)', fmt_total_pct)
        ws.write_formula(r, 17, f'=IFERROR(Q{excel_total}/N{excel_total},0)', fmt_total_pct)

        # CF Diff (cols G=6, K=10, O=14) — rouge/vert sur les diffs non vides
        for diff_col in (6, 10, 14):
            ws.conditional_format(3, diff_col, last_excel - 1, diff_col,
                {"type": "cell", "criteria": ">", "value": 0, "format": fmt_positive})
            ws.conditional_format(3, diff_col, last_excel - 1, diff_col,
                {"type": "cell", "criteria": "<", "value": 0, "format": fmt_negative})

        # CF "ligne traitée" : si au moins un Réel est saisi (F, J, N, Q), surligne TOUTE la ligne en BLEU PÂLE.
        # On crée plusieurs formats pour préserver la lisibilité (alignement, format %) tout en imposant
        # le bg bleu pâle sur les 18 colonnes.
        treated_criteria = '=COUNTA($F4,$J4,$N4,$Q4)>0'
        fmt_t_label = workbook.add_format({"bg_color": "#DBEAFE", "border": 1, "bold": True,
                                           "font_color": "#1E3A8A", "align": "right"})
        fmt_t_text = workbook.add_format({"bg_color": "#DBEAFE", "border": 1, "font_color": "#1E3A8A",
                                          "align": "left"})
        fmt_t_num = workbook.add_format({"bg_color": "#DBEAFE", "border": 1, "font_color": "#1E3A8A",
                                         "align": "right"})
        fmt_t_pct = workbook.add_format({"bg_color": "#DBEAFE", "border": 1, "font_color": "#1E3A8A",
                                         "align": "right", "num_format": "0%"})
        # Cols A, B (Nuit, Type) — bold label
        ws.conditional_format(3, 0, last_excel - 1, 1,
            {"type": "formula", "criteria": treated_criteria, "format": fmt_t_label})
        # Col C (Allée phasage) — right-aligned text
        ws.conditional_format(3, 2, last_excel - 1, 2,
            {"type": "formula", "criteria": treated_criteria, "format": fmt_t_label})
        # Col D (Allée réelle) — left-aligned input
        ws.conditional_format(3, 3, last_excel - 1, 3,
            {"type": "formula", "criteria": treated_criteria, "format": fmt_t_text})
        # Cols numériques (E, F, G, I, J, K, M, N, O, Q)
        for col in (4, 5, 6, 8, 9, 10, 12, 13, 14, 16):
            ws.conditional_format(3, col, last_excel - 1, col,
                {"type": "formula", "criteria": treated_criteria, "format": fmt_t_num})
        # Cols % (H, L, P, R) — format %
        for col in (7, 11, 15, 17):
            ws.conditional_format(3, col, last_excel - 1, col,
                {"type": "formula", "criteria": treated_criteria, "format": fmt_t_pct})

    ws.merge_range(r + 2, 0, r + 2, 17,
                   "Cellules jaunes = à remplir manuellement (Allée réelle / ES réel / Cam réelle "
                   "/ Rails ES réel / Géolocalisés). Diff, % et totaux se recalculent automatiquement. "
                   "Les lignes traitées sont surlignées en bleu pâle.",
                   workbook.add_format({"italic": True, "border": 1, "font_color": "#6B7280"}))




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

    _write_sheet("Recap par secteur", "rayon")
    _write_sheet("Recap par secteur (global)", "global")




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
            ws = workbook.add_worksheet("Commandes")
            writer.sheets["Commandes"] = ws
            headers = ["Type", "Référence", "Désignation", "Quantité", "Spare", "Total + Spare"]
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

        if sheet in ("all", "parsecteur"):
            _write_par_secteur_sheets(workbook, writer, d, fmt_header, fmt_cell, fmt_total, fmt_inclineur)

        if sheet in ("all", "secteur"):
            secteur = d["secteur_rows"]
            ws = workbook.add_worksheet("Tableau phasage")
            writer.sheets["Tableau phasage"] = ws
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

        if sheet in ("all", "phasage"):
            _write_phasage_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

        if sheet in ("all", "phasage_cam"):
            _write_phasage_cam_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

        if sheet in ("all", "phasage_full"):
            _write_phasage_full_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

        if sheet in ("all", "suivi"):
            _write_suivi_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

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
