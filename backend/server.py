"""
Backend FastAPI pour l'application d'inventaire d'étiquettes électroniques.
Reçoit un fichier Excel, le traite et génère :
- Onglet "Données" : données brutes
- Onglet "Récapitulatif produits" : totaux par Type+Référence, Spare (+5%), Inclineur, 3 lignes vides
- Onglet "Par Secteur/Allée" : comptage EEG (ES/SA), Rails, Caméras
"""
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response
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

# Auth
from auth import build_auth_router, make_get_current_user, setup_auth
get_current_user = make_get_current_user(db)

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Compression gzip automatique des réponses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Cache local par pod ; source de vérité = MongoDB (datasets collection)
DATASTORE: dict[str, dict] = {}


@app.on_event("startup")
async def _on_startup():
    try:
        await setup_auth(db)
    except Exception as e:
        logger.warning(f"setup_auth failed: {e}")
    try:
        # TTL : audit_log conservé 365 jours
        await db.audit_log.create_index("upload_id")
        await db.audit_log.create_index("timestamp", expireAfterSeconds=60 * 60 * 24 * 365)
    except Exception as e:
        logger.warning(f"audit_log index failed: {e}")
    try:
        # phasage_snapshots : TTL 30 jours + index upload_id (22/06/2026)
        # Conserve un snapshot complet du phasage à chaque save → restauration
        # possible depuis le panneau Historique.
        await db.phasage_snapshots.create_index("upload_id")
        await db.phasage_snapshots.create_index(
            "created_at", expireAfterSeconds=60 * 60 * 24 * 30
        )
    except Exception as e:
        logger.warning(f"phasage_snapshots index failed: {e}")


# Nombre maximum de snapshots conservés par session (les plus anciens sont purgés)
PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD = 20


async def save_phasage_snapshot(upload_id: str, user: Optional[dict],
                                phasage: dict) -> Optional[str]:
    """Insère un snapshot complet du phasage et purge les plus anciens
    au-delà de PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD. Retourne l'_id en str."""
    try:
        doc = {
            "upload_id": upload_id,
            "user_id": str(user["_id"]) if user else None,
            "user_email": (user.get("email") if user else None) or "anonyme",
            "phasage": phasage or {},
            "created_at": datetime.now(timezone.utc),
        }
        res = await db.phasage_snapshots.insert_one(doc)
        new_id = str(res.inserted_id)
        # Purge des plus anciens au-delà du quota
        cursor = db.phasage_snapshots.find(
            {"upload_id": upload_id},
            {"_id": 1, "created_at": 1},
        ).sort("created_at", -1).skip(PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD)
        to_delete = [d["_id"] async for d in cursor]
        if to_delete:
            await db.phasage_snapshots.delete_many({"_id": {"$in": to_delete}})
        return new_id
    except Exception as e:
        logger.warning(f"save_phasage_snapshot failed: {e}")
        return None


async def log_audit(upload_id: Optional[str], user: Optional[dict],
                    action: str, target: str = "", details: Optional[dict] = None):
    """Append une entrée d'audit. Best-effort : un échec ne casse pas l'opération métier."""
    try:
        await db.audit_log.insert_one({
            "upload_id": upload_id,
            "user_id": str(user["_id"]) if user else None,
            "user_email": (user.get("email") if user else None) or "anonyme",
            "user_name": (user.get("name") if user else None) or "",
            "action": action,
            "target": target or "",
            "details": details or {},
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning(f"log_audit failed: {e}")


async def persist_dataset(upload_id: str, data: dict, user_id: Optional[str] = None):
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
    update_doc = {
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
            # auto_sort_by_nuit (22/06/2026) : nouvelles sessions, on regroupe
            # automatiquement les lignes par nuit dès qu'elles sont assignées.
            # Les anciennes sessions n'ont pas ce flag → comportement inchangé.
            "es": {"nb_nuits": 3, "rows": [], "auto_sort_by_nuit": True},
            "cam": {"nb_nuits": 3, "rows": [], "start_at_nuit": 5, "auto_sort_by_nuit": True},
            "suivi": {"rows": []},
        },
        "surface_category": data.get("surface_category"),
        "dongles_quantity": data.get("dongles_quantity") or 0,
        "vt_start_date": data.get("vt_start_date") or "",
        "vt_end_date": data.get("vt_end_date") or "",
        "store_name": data.get("store_name") or "",
        "store_city": data.get("store_city") or "",
        "store_code": data.get("store_code") or "",
        "store_address": data.get("store_address") or "",
        "participants": data.get("participants") or "",
        "responsable_magasin": data.get("responsable_magasin") or "",
        "responsable_vusion": data.get("responsable_vusion") or "",
        "prestataire_install": data.get("prestataire_install") or "",
        "plan_prevention_signe": data.get("plan_prevention_signe") or "",
        "doc_version": data.get("doc_version") or "",
        "date_validation_carrefour": data.get("date_validation_carrefour") or "",
    }
    if user_id is not None:
        update_doc["user_id"] = user_id
    await db.datasets.replace_one(
        {"upload_id": upload_id},
        update_doc,
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


async def load_dataset(upload_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Récupère un dataset : d'abord en cache mémoire, sinon depuis MongoDB.
    Lit le payload gzippé + merge les champs éditables stockés à plat.
    Rétro-compatible avec les anciens datasets où ces champs étaient dans le payload.

    Si user_id est fourni, vérifie que le dataset appartient à cet utilisateur
    (ou est un dataset legacy sans owner — accessible par l'admin uniquement via filtre amont).
    """
    if upload_id in DATASTORE:
        cached = DATASTORE[upload_id]
        if user_id is not None:
            owner = cached.get("user_id")
            if owner is not None and owner != user_id:
                return None
        return cached
    query: dict = {"upload_id": upload_id}
    if user_id is not None:
        # On accepte aussi les datasets legacy sans user_id (rétro-compatibilité)
        query = {"upload_id": upload_id, "$or": [{"user_id": user_id}, {"user_id": {"$exists": False}}]}
    doc = await db.datasets.find_one(query, {"_id": 0})
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
    if "dongles_quantity" in doc:
        payload["dongles_quantity"] = doc["dongles_quantity"]
    for fld in ("vt_start_date", "vt_end_date", "store_name", "store_city",
                "store_code", "store_address", "participants",
                "responsable_magasin", "responsable_vusion",
                "prestataire_install", "plan_prevention_signe",
                "doc_version", "date_validation_carrefour"):
        if fld in doc:
            payload[fld] = doc[fld]
    if "user_id" in doc:
        payload["user_id"] = doc["user_id"]
    DATASTORE[upload_id] = payload
    return payload


# Longueurs de rails qui comptent pour 1 inclineur
INCLINEUR_LENGTHS = ["1320mm", "1240mm", "990mm", "1187mm", "908mm", "650mm", "535mm"]

# === MOQ par référence (Minimum Order Quantity) ===
# Source : fichier MOQ.xlsx fourni par l'utilisateur le 23/06/2026.
# Liste maintenue manuellement ici ; si une référence n'est pas listée,
# on n'arrondit pas (Total+MOQ affiche "—" côté UI).
MOQ_BY_REF: dict[str, int] = {
    "11892": 5,   "12202": 10,  "13585": 48,  "13827": 25,  "14218": 5,
    "14466": 25,  "14745": 24,  "15024": 100, "15395": 24,  "15506": 24,
    "15507": 24,  "15550": 60,  "15551": 10,  "15910": 100, "15912": 100,
    "16362": 100, "16441": 50,  "16574": 100, "16607": 100, "16639": 1,
    "16657": 100, "16783": 1,   "16808": 100, "16957": 24,  "17103": 40,
    "17165": 25,  "17285": 24,  "17651": 25,  "17717": 25,  "17723": 1,
    "17724": 100, "17741": 50,  "17868": 24,  "17869": 100, "17870": 100,
    "17889": 1,   "17900": 1,   "17929": 1,   "17938": 1,   "17940": 1,
    "18048": 90,  "18052": 1,   "18107": 50,  "18108": 50,  "18173": 24,
    "18183": 1,   "18216": 50,  "18217": 50,  "18308": 1,   "3903": 25,
    "3962": 50,   "3966": 50,   "3971": 50,   "4507": 100,  "4552": 1,
    "6669": 1,    "9484": 50,
}


def _compute_total_moq(total_plus_spare, ref) -> int | str:
    """Calcule Total+MOQ pour une ligne. Si la référence n'a pas de MOQ
    déclaré, retourne "—" (tiret cadratin) — l'UI affichera tel quel.
    Si MOQ = 0 ou 1 → pas d'arrondi nécessaire.
    """
    try:
        total = float(total_plus_spare) if total_plus_spare not in (None, "") else 0
    except (ValueError, TypeError):
        return ""
    if total <= 0:
        return ""
    moq = MOQ_BY_REF.get(str(ref or "").strip())
    if moq is None:
        return "—"
    if moq <= 1:
        return int(total) if total == int(total) else total
    rounded = int(math.ceil(total / moq) * moq)
    return rounded


def _apply_total_moq_and_bonuses(rows: list[dict]) -> list[dict]:
    """Pour chaque ligne du recap, expose les bonus dans des champs dédiés
    (`fleche`, `signaletique`, `saisonnier`) et calcule `total_moq` à partir
    de `total_plus_spare` et du MOQ par référence. Idempotent.

    Nettoie aussi l'éventuel suffixe ' — rajout de X ...' présent dans
    les désignations (héritage des anciennes versions) — récupère au passage
    le bonus rails/flèches si pas encore stocké dans `_rail_bonus`/`_fleche_bonus`.
    """
    import re as _re
    pat_rajout = _re.compile(r"\s+—\s+rajout de\s+(\d+)\s+([\wéèàùâêîôû()]+)", _re.IGNORECASE)
    for r in rows:
        kind = r.get("kind")
        # Strip suffix ancien dans la désignation (toutes lignes)
        desig = r.get("designation") or ""
        if " — rajout de " in desig:
            # Tente de récupérer le 1er nombre + mot-clé pour rétro-remplir
            matches = pat_rajout.findall(desig)
            for num_str, word in matches:
                w = word.lower()
                num = int(num_str)
                if "rail" in w and not r.get("_rail_bonus"):
                    r["_rail_bonus"] = num
                elif ("flèche" in w or "fleche" in w) and not r.get("_fleche_bonus"):
                    r["_fleche_bonus"] = num
            # Retire toute la portion " — rajout de ..."
            r["designation"] = desig.split(" — rajout de")[0].strip()
        if kind in ("header", "empty"):
            r["total_moq"] = ""
            r.setdefault("fleche", "")
            r.setdefault("signaletique", "")
            r.setdefault("saisonnier", "")
            continue
        # Détecte la ligne pour savoir si Flèche/Signalétique/Saisonnier s'appliquent
        d_norm = (r.get("designation") or "").strip().lower()
        # Flèche : ES 1.5 (noir) ou SA 1.5 (noir)
        if d_norm in ("es 1.5 (noir)", "sa 1.5 (noir)"):
            fb = r.get("_fleche_bonus")
            r["fleche"] = int(fb) if (fb and fb > 0) else ""
        else:
            r["fleche"] = ""
        # Signalétique : ES 1.5 (noir) ou ES 1.5 (blanc)
        if d_norm in ("es 1.5 (noir)", "es 1.5 (blanc)"):
            rb = r.get("_rail_bonus")
            r["signaletique"] = int(rb) if (rb and rb > 0) else ""
        else:
            r["signaletique"] = ""
        # Saisonnier : SA 2.1 (noir) ou SA 1.5 (noir) uniquement
        if d_norm in ("sa 2.1 (noir)", "sa 1.5 (noir)"):
            if "_surface_base_total" in r:
                try:
                    cur_t = float(r.get("total_plus_spare") or 0)
                    base_t = float(r.get("_surface_base_total") or 0)
                    delta = cur_t - base_t
                    r["saisonnier"] = int(delta) if delta > 0 else ""
                except (ValueError, TypeError):
                    r["saisonnier"] = ""
            else:
                r["saisonnier"] = ""
        elif kind == "surface_added" and d_norm in ("sa 2.1 (noir)", "sa 1.5 (noir)"):
            try:
                r["saisonnier"] = int(float(r.get("total_plus_spare") or 0))
            except (ValueError, TypeError):
                r["saisonnier"] = ""
        else:
            r["saisonnier"] = ""
        # Total + MOQ
        r["total_moq"] = _compute_total_moq(r.get("total_plus_spare"), r.get("reference"))
    # Re-organise en sections (idempotent ; appelé partout via ce helper)
    return _apply_sections(rows)


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


def _classify_section(designation: str, ref: str, kind: str, type_: str) -> str:
    """Classifie une ligne de recap dans l'une des 6 sections (23/06/2026 v5).
    Sections retournées : "EEG", "Rails EdgeSense", "Rails/Fixation SA", "Captana", "Dongles", "VCare".
    """
    d = (designation or "").strip().lower()
    t = (type_ or "").strip().lower()
    if d.startswith("v:care") or t == "vcare" or kind == "vcare":
        return "VCare"
    if kind == "dongle" or t == "dongle":
        return "Dongles"
    if any(d.startswith(p) for p in ("es 1.5", "es 2.1", "sa 1.5", "sa 2.1", "sa 4.2")):
        return "EEG"
    if d.startswith("face arrière") or d.startswith("face arriere"):
        return "Rails EdgeSense"
    if d == "inclineur" or kind == "inclineur" or "inclineur" in d:
        return "Rails EdgeSense"
    if d == "vis fixation":
        return "Rails EdgeSense"
    import re as _re
    if _re.search(r"\bmm\b", d) and ("rail" in t or t == "rail" or d.startswith("rail") or _re.match(r"^\d{3,4}\s*mm", d)):
        return "Rails EdgeSense"
    if d.startswith("rail "):
        return "Rails EdgeSense"
    captana_designations = (
        "caméra (blanche)", "caméra (noire)",
        "batterie caméra", "software caméra",
        "support mobilier captana (blanc)", "support mobilier captana (noir)",
        "support ajustable adhésif captana",
        "pied réglable 0,5-1 m adhésif captana",
    )
    if d in captana_designations:
        return "Captana"
    return "Rails/Fixation SA"


def _apply_sections(rows: list[dict]) -> list[dict]:
    """Re-organise les recap_rows en 6 sections (séparateurs bleu clair)."""
    SECTIONS = ["EEG", "Rails EdgeSense", "Rails/Fixation SA", "Captana", "Dongles", "VCare"]
    empties = [r for r in rows if r.get("kind") == "empty"]
    others = [r for r in rows
              if r.get("kind") not in ("empty", "header", "section")]
    buckets: dict[str, list[dict]] = {s: [] for s in SECTIONS}
    for r in others:
        sec = _classify_section(
            r.get("designation"), r.get("reference"), r.get("kind"), r.get("type"))
        buckets.setdefault(sec, buckets["Rails/Fixation SA"]).append(r)
    result: list[dict] = []
    for sec in SECTIONS:
        if not buckets[sec]:
            continue
        result.append({
            "kind": "section",
            "type": sec,
            "reference": "",
            "designation": "",
            "quantite": "", "spare": "", "total_plus_spare": "",
            "fleche": "", "signaletique": "", "saisonnier": "",
            "total_moq": "",
        })
        result.extend(buckets[sec])
    result.extend(empties)
    return result


def _validate_missing_refs(rows: list[dict]) -> list[str]:
    """Retourne la liste des désignations de lignes dont la référence est
    vide OU contient des caractères non-numériques (24/06/2026).
    """
    bad: list[str] = []
    for r in rows:
        kind = r.get("kind")
        if kind in ("section", "header", "empty"):
            continue
        ref = (r.get("reference") or "").strip()
        if not ref or not ref.isdigit():
            desig = (r.get("designation") or "").strip() or f"(ligne kind={kind})"
            bad.append(desig)
    return bad


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
    # NOTE: les lignes "Flèche" du brut sont volontairement EXCLUES du recap
    # car elles sont déjà comptabilisées comme +1 ES 1.5 (noir) chacune dans
    # la ligne "ES 1.5 (noir)" (cf. bloc Bonus flèches ci-dessous).
    preferred_order = ["EEG", "Fixation", "Rail", "Caméra", "Camera"]
    types_in_data = [t for t in df[type_col].dropna().unique()
                     if not _is_fleche(t)]
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
                if cur_total == 0 and (cur_q + cur_s) > 0:
                    cur_total = cur_q + cur_s
                r["total_plus_spare"] = cur_total + bonus
                # 23/06/2026 : suffixe retiré (info exposée via colonne Signalétique).
                r["designation"] = (r.get("designation") or "").split(" — rajout de")[0].strip()
                r["_rail_bonus"] = bonus
                r["_rail_bonus_color"] = color
                break

    # ===== Bonus flèches → ES 1.5 (noir) (sans spare) =====
    # Règle : chaque ligne du brut marquée "flèche" (Type ou Désignation)
    # ajoute +1 EEG ES 1.5 (noir) à total_plus_spare, sans spare additionnel.
    # S'applique APRÈS le bonus rails — l'annotation cumule les deux.
    fleche_total = 0
    if not df.empty:
        mask = df.apply(
            lambda r: _is_fleche(r.get(type_col)) or _is_fleche(r.get(desig_col)),
            axis=1,
        )
        fleche_df = df[mask]
        if not fleche_df.empty:
            fleche_total = int(pd.to_numeric(fleche_df[qty_col], errors="coerce").fillna(0).sum())

    # Applique le bonus à la ligne ES 1.5 (noir) ET à SA 1.5 (noir) du recap
    # (23/06/2026 : sur les 2 lignes si elles existent toutes les deux).
    if fleche_total > 0:
        target_labels = ("es 1.5 (noir)", "sa 1.5 (noir)")
        for r in rows:
            if r.get("kind") != "product":
                continue
            desig_norm = _norm_desig(r.get("designation"))
            base_desig = desig_norm.split(" — rajout de")[0]
            if base_desig not in target_labels:
                continue
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
            if cur_total == 0 and (cur_q + cur_s) > 0:
                cur_total = cur_q + cur_s
            r["total_plus_spare"] = cur_total + fleche_total
            # On préserve la désignation brute (sans suffixe " — rajout de X")
            # car le détail est désormais exposé via des colonnes dédiées
            # (Flèche, Signalétique, Saisonnier).
            r["designation"] = (r.get("designation") or "").split(" — rajout de")[0].strip()
            r["_fleche_bonus"] = fleche_total

    # Ligne Dongle — éditable, pas de Spare ni Total+Spare
    # Référence fixe = 16639 (rajoutée automatiquement)
    rows.append({
        "kind": "dongle",
        "type": "Accessoire",
        "reference": "16639",
        "designation": "Dongle",
        "quantite": "",
        "spare": "",
        "total_plus_spare": "",
    })

    # ===== Bloc VCare =====
    # Règle utilisateur (11/06/2026) : 1 unité produit installée = 1 unité
    # VCare correspondant. La quantité du VCare est calculée à partir de
    # `total_plus_spare` (= quantité posée + spare) des produits sources.
    # Spare VCare : 5 % pour ES/SA/Rails, 2 % pour le VCare caméra (16783).
    # Mais avant cela, on synchronise batterie + software caméra sur la
    # somme des caméras (règle utilisateur 21/06/2026) — ainsi le VCare
    # 16783 calculé ensuite sera juste.
    rows = _refresh_batterie_software_block(rows)
    _vcare_rows = _build_vcare_rows(rows, df, cols)
    if _vcare_rows:
        rows.extend(_vcare_rows)

    # 3 lignes vides
    for _ in range(3):
        rows.append({"kind": "empty", "type": "", "reference": "", "designation": "", "quantite": "", "spare": "", "total_plus_spare": ""})

    # Calcule fleche/signaletique/saisonnier/total_moq + sectioning (23/06/2026)
    rows = _apply_total_moq_and_bonuses(rows)
    return rows


# Mapping VCare : (refs sources, ref VCare, désignation VCare)
# Règle simple (12/06/2026) : 1 unité VCare = 1 unité produit posée (avec son
# spare déjà appliqué). On somme le `total_plus_spare` des refs sources et on
# le reporte DIRECTEMENT dans le `total_plus_spare` du VCare. Pas de spare
# ajouté côté VCare (sinon on aurait du spare en double).
# Le rajout saisonnier "sans spare" (présent dans la désignation) est exclu.
VCARE_MAPPING = [
    (["15024", "17673", "17724"], "17889", "V:Care 7Y E300 1.5 BWRY"),
    (["17869", "16362"],           "18052", "V:Care Lite 7Y ES300 1.5 BWRY"),
    (["15910", "17740"],           "17900", "V:Care 7Y E300 2.1 BWRY"),
    (["17870"],                    "17723", "V:Care Lite 7Y ES300 2.1 BWRY"),
    (["15912", "17979"],           "17940", "V:Care 5Y E300 2.1 F BWRY"),
    (["15551"],                    "17929", "V:Care 5Y E300 4.2 BWRY"),
    (["15550"],                    "17938", "V:Care Lite 5Y E300 4.2 WP BWRY"),
    # Rails ES — liste exacte fournie par l'utilisateur (12/06/2026) :
    # 16957=1187mm noir, 15507=1240mm noir, 14745=1320mm noir, 13585=535mm noir,
    # 18173=650mm noir, 17285=908mm noir, 15395=990mm blanc, 15506=990mm noir,
    # 17868=1320mm blanc.
    (["16957", "15507", "14745", "13585", "18173", "17285", "15395", "15506", "17868"],
                                   "18183", "V:Care 7Y ES Rail"),
    (["11892", "14218"],           "16783", "V:Care Lite 3Y Captana StoreEy"),
]


def _build_vcare_rows(rows: list[dict], df: pd.DataFrame, cols: dict) -> list[dict]:
    """Construit le bloc 'TOTAL VCare'. Règle simple (12/06/2026 — option b
    utilisateur) : la quantité VCare = somme du `Total + Spare` des refs
    sources, sans soustraction. Le rajout saisonnier "sans spare" et les
    bonus rails sont INCLUS (= VCare couvre exactement ce qui est affiché
    en Total dans la ligne source)."""
    def _vcare_src_value(r: dict) -> float:
        try:
            tps = float(r.get("total_plus_spare") or 0)
        except (ValueError, TypeError):
            try:
                tps = float(r.get("quantite") or 0) + float(r.get("spare") or 0)
            except (ValueError, TypeError):
                tps = 0
        return max(tps, 0)

    # Index ref → contribution VCare cumulée
    # On inclut 'manual' (lignes éditées par l'utilisateur — restent des
    # produits valides) en plus de 'product' et 'surface_added'.
    src_val: dict[str, float] = {}
    for r in rows:
        if r.get("kind") not in ("product", "surface_added", "manual"):
            continue
        ref = str(r.get("reference") or "").strip()
        if not ref:
            continue
        src_val[ref] = src_val.get(ref, 0) + _vcare_src_value(r)

    pending: list[dict] = []
    for sources, vcare_ref, vcare_desig in VCARE_MAPPING:
        val = sum(src_val.get(s, 0) for s in sources)
        if val <= 0:
            continue
        pending.append({
            "kind": "product",
            "type": "VCare",
            "reference": vcare_ref,
            "designation": vcare_desig,
            "quantite": float(val),
            "spare": "",
            "total_plus_spare": float(val),
        })

    if not pending:
        return []
    total_qty = sum(p["quantite"] for p in pending)
    return [{
        "kind": "header",
        "type": "VCare",
        "reference": "",
        "designation": "TOTAL VCare",
        "quantite": total_qty,
        "spare": "",
        "total_plus_spare": total_qty,
    }] + pending


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


# Alias de références : si l'utilisateur saisit une ancienne réf dans le fichier,
# elle est automatiquement remplacée par la réf canonique avant tout calcul.
# 26/02/2026 — 17979 ≡ 15912 (V:Care 5Y E300 2.1 F BWRY).
REF_ALIASES: dict[str, str] = {
    "17979": "15912",
}


def _normalize_reference_column(df: pd.DataFrame) -> pd.DataFrame:
    """Applique REF_ALIASES sur la colonne Référence (Référence/Reference)."""
    ref_col = find_col(df, EXPECTED_COLS["reference"])
    if ref_col is None or not REF_ALIASES:
        return df

    def _alias(val):
        if val is None:
            return val
        try:
            if isinstance(val, float) and math.isnan(val):
                return val
        except Exception:
            pass
        if isinstance(val, float) and float(val).is_integer():
            key = str(int(val))
        else:
            key = str(val).strip()
        new = REF_ALIASES.get(key)
        if new is None:
            return val
        # Si valeur d'origine numérique, on garde un int pour ne pas casser
        # le typage de la colonne dans pandas.
        if isinstance(val, (int, np.integer)) or (
            isinstance(val, float) and float(val).is_integer()
        ):
            try:
                return int(new)
            except ValueError:
                return new
        return new

    df[ref_col] = df[ref_col].map(_alias)
    return df


def _parse_excel(contents: bytes) -> pd.DataFrame:
    """Parse un xlsx avec calamine (rapide) puis openpyxl en fallback."""
    try:
        df = pd.read_excel(io.BytesIO(contents), sheet_name=0, engine="calamine")
        logger.info(f"Parsed with calamine: {df.shape[0]} rows x {df.shape[1]} cols")
        return _normalize_reference_column(df)
    except Exception as e_cal:
        logger.warning(f"Calamine failed ({e_cal}), falling back to openpyxl")
    try:
        df = pd.read_excel(io.BytesIO(contents), sheet_name=0)
        logger.info(f"Parsed with openpyxl: {df.shape[0]} rows x {df.shape[1]} cols")
        return _normalize_reference_column(df)
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
async def upload_excel(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
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

    user_id = str(current_user["_id"])
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
        "user_id": user_id,
    }

    # Persister le dataset complet en MongoDB (gzippé) pour multi-replica
    try:
        await persist_dataset(upload_id, DATASTORE[upload_id], user_id=user_id)
    except Exception as e:
        logger.warning(f"Mongo persist failed: {e}")

    await log_audit(upload_id, current_user, "session_created",
                    target=file.filename,
                    details={"row_count": len(raw_records)})

    autre_rows_count = len(_filter_autre_rows(DATASTORE[upload_id]))
    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "row_count": len(raw_records),
        "columns": list(df.columns),
        "surface_category": None,
        "has_autre": autre_rows_count > 0,
        "autre_count": autre_rows_count,
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


@api_router.get("/datasets")
async def list_datasets(current_user: dict = Depends(get_current_user)):
    """Liste les sessions de l'utilisateur connecté (métadonnées légères).
    Triées de la plus récente à la plus ancienne."""
    user_id = str(current_user["_id"])
    cursor = db.datasets.find(
        {"user_id": user_id},
        {"_id": 0, "upload_id": 1, "filename": 1, "uploaded_at": 1,
         "row_count": 1, "size_bytes": 1, "compressed_bytes": 1,
         "label": 1, "share_enabled": 1, "share_token": 1},
    ).sort("uploaded_at", -1)
    items = await cursor.to_list(length=500)
    return {"datasets": items}


@api_router.get("/dataset/{upload_id}")
async def get_dataset(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Récupère métadonnées + recap + secteur (PAS les raw records, voir /raw)."""
    user_id = str(current_user["_id"])
    d = await load_dataset(upload_id, user_id=user_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = _filter_autre_rows(d)
    # On TOUJOURS recalcule batterie/software caméra + VCare à la lecture
    # pour que les règles métier (mapping, taux, formule, sync caméras)
    # prennent effet immédiatement sur les sessions existantes — sans
    # nécessiter une ré-édition manuelle ni de re-upload.
    recap_rows = _refresh_batterie_software_block(d["recap_rows"])
    recap_rows = _refresh_vcare_block(recap_rows)
    # Bonus + MOQ (23/06/2026)
    recap_rows = _apply_total_moq_and_bonuses(recap_rows)
    return {
        "upload_id": upload_id,
        "filename": d["filename"],
        "columns": d["columns"],
        "row_count": len(d["raw_records"]),
        "surface_category": d.get("surface_category"),
        "dongles_quantity": int(d.get("dongles_quantity") or 0),
        "vt_start_date": d.get("vt_start_date") or "",
        "vt_end_date": d.get("vt_end_date") or "",
        "store_name": d.get("store_name") or "",
        "store_city": d.get("store_city") or "",
        "store_code": d.get("store_code") or "",
        "store_address": d.get("store_address") or "",
        "participants": d.get("participants") or "",
        "responsable_magasin": d.get("responsable_magasin") or "",
        "responsable_vusion": d.get("responsable_vusion") or "",
        "prestataire_install": d.get("prestataire_install") or "",
        "plan_prevention_signe": d.get("plan_prevention_signe") or "",
        "doc_version": d.get("doc_version") or "",
        "date_validation_carrefour": d.get("date_validation_carrefour") or "",
        "has_autre": len(rows) > 0,
        "autre_count": len(rows),
        "data": {
            "recap": recap_rows,
            "secteur": d["secteur_rows"],
            "comment_table": d.get("comment_table") or {
                "columns": ["Colonne 1", "Colonne 2", "Colonne 3", "Colonne 4", "Colonne 5"],
                "rows": [["", "", "", "", ""] for _ in range(8)],
            },
        },
    }


@api_router.delete("/dataset/{upload_id}")
async def delete_dataset(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Supprime un dataset (libère l'espace serveur + cache mémoire)."""
    user_id = str(current_user["_id"])
    res = await db.datasets.delete_one({
        "upload_id": upload_id,
        "$or": [{"user_id": user_id}, {"user_id": {"$exists": False}}],
    })
    DATASTORE.pop(upload_id, None)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    await log_audit(upload_id, current_user, "session_deleted")
    return {"deleted": True, "upload_id": upload_id}


# ---- Renommage de session (label personnalisé) ----------------------------
class DatasetLabelUpdate(BaseModel):
    label: Optional[str] = ""


@api_router.patch("/dataset/{upload_id}/label")
async def update_dataset_label(upload_id: str, payload: DatasetLabelUpdate,
                               current_user: dict = Depends(get_current_user)):
    """Définit un libellé personnalisé pour une session.
    Le label peut être vide (= retour au filename brut)."""
    user_id = str(current_user["_id"])
    new_label = (payload.label or "").strip()[:200]
    res = await db.datasets.update_one(
        {"upload_id": upload_id, "user_id": user_id},
        {"$set": {"label": new_label}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    # Invalide le cache pour que la prochaine lecture remonte le nouveau label
    DATASTORE.pop(upload_id, None)
    await log_audit(upload_id, current_user, "label_changed", target=new_label or "(libellé vidé)")
    return {"upload_id": upload_id, "label": new_label}


# ---- Partage de session lecture-seule ------------------------------------
import secrets as _secrets


@api_router.post("/dataset/{upload_id}/share")
async def enable_share(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Active (ou régénère) un lien de partage public lecture-seule.
    Retourne le `share_token` à utiliser dans l'URL frontend (ex: /share/<token>)."""
    user_id = str(current_user["_id"])
    token = _secrets.token_urlsafe(24)
    res = await db.datasets.update_one(
        {"upload_id": upload_id, "user_id": user_id},
        {"$set": {"share_token": token, "share_enabled": True}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    DATASTORE.pop(upload_id, None)
    await log_audit(upload_id, current_user, "share_enabled")
    return {"upload_id": upload_id, "share_token": token, "share_enabled": True}


@api_router.delete("/dataset/{upload_id}/share")
async def disable_share(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Désactive le partage : le lien existant ne fonctionne plus."""
    user_id = str(current_user["_id"])
    res = await db.datasets.update_one(
        {"upload_id": upload_id, "user_id": user_id},
        {"$set": {"share_enabled": False}, "$unset": {"share_token": ""}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    DATASTORE.pop(upload_id, None)
    await log_audit(upload_id, current_user, "share_disabled")
    return {"upload_id": upload_id, "share_enabled": False}


async def _resolve_share_token(share_token: str) -> dict:
    """Récupère le doc dataset à partir d'un share_token public."""
    doc = await db.datasets.find_one(
        {"share_token": share_token, "share_enabled": True},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Lien de partage invalide ou désactivé")
    upload_id = doc["upload_id"]
    payload = json.loads(gzip.decompress(doc["payload"]).decode("utf-8"))
    for f in ("recap_rows", "comment_table", "phasage", "surface_category",
              "dongles_quantity", "user_id", "label"):
        if f in doc:
            payload[f] = doc[f]
    DATASTORE[upload_id] = payload
    return payload


@api_router.get("/share/{share_token}")
async def get_shared_dataset(share_token: str):
    """Endpoint PUBLIC (sans auth) : récupère les métadonnées + recap + secteur
    d'un dataset partagé en lecture seule."""
    d = await _resolve_share_token(share_token)
    return {
        "upload_id": d.get("upload_id") or d.get("filename"),
        "filename": d["filename"],
        "label": d.get("label") or "",
        "columns": d["columns"],
        "row_count": len(d["raw_records"]),
        "surface_category": d.get("surface_category"),
        "dongles_quantity": int(d.get("dongles_quantity") or 0),
        "shared": True,
        "data": {
            "recap": d["recap_rows"],
            "secteur": d["secteur_rows"],
            "comment_table": d.get("comment_table") or {
                "columns": ["Colonne 1", "Colonne 2", "Colonne 3", "Colonne 4", "Colonne 5"],
                "rows": [["", "", "", "", ""] for _ in range(8)],
            },
        },
    }


@api_router.get("/share/{share_token}/raw")
async def get_shared_raw(share_token: str):
    """Endpoint PUBLIC : données brutes d'un dataset partagé."""
    d = await _resolve_share_token(share_token)
    return {"columns": d["columns"], "raw": d["raw_records"]}


@api_router.get("/share/{share_token}/phasage-summary")
async def get_shared_phasage(share_token: str):
    """Endpoint PUBLIC : summary phasage d'un dataset partagé."""
    d = await _resolve_share_token(share_token)
    summary = compute_phasage_summary(d)
    summary["phasage"] = _normalize_phasage(d.get("phasage"))
    summary["vt_start_date"] = d.get("vt_start_date") or ""
    summary["store_name"] = d.get("store_name") or ""
    summary["store_code"] = d.get("store_code") or ""
    return summary


@api_router.get("/share/{share_token}/export")
async def export_shared(share_token: str, sheet: str = "all"):
    """Endpoint PUBLIC : téléchargement de l'export Excel d'un dataset partagé."""
    d = await _resolve_share_token(share_token)
    return await _build_export(d, sheet)


@api_router.get("/dataset/{upload_id}/raw")
async def get_dataset_raw(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Récupère les données brutes (~9 MB pour 19780 lignes, mais gzippé HTTP ~600 KB)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    return {
        "upload_id": upload_id,
        "columns": d["columns"],
        "raw": d["raw_records"],
    }


@api_router.get("/dataset/{upload_id}/activity")
async def get_dataset_activity(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Retourne l'historique des modifications d'une session (max 200 entrées, plus récentes d'abord)."""
    # Vérifie propriété
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    cursor = db.audit_log.find(
        {"upload_id": upload_id},
        {"_id": 0},
    ).sort("timestamp", -1).limit(200)
    items = await cursor.to_list(length=200)
    # Sérialise les timestamps
    for it in items:
        ts = it.get("timestamp")
        if hasattr(ts, "isoformat"):
            it["timestamp"] = ts.isoformat()
    return {"activity": items, "count": len(items)}


@api_router.get("/dataset/{upload_id}/phasage-snapshots")
async def list_phasage_snapshots(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Liste les snapshots versionnés du phasage (20 derniers max, 30j TTL)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    cursor = db.phasage_snapshots.find(
        {"upload_id": upload_id},
        {"phasage": 0},  # On n'envoie pas le payload complet ici
    ).sort("created_at", -1).limit(PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD)
    items = await cursor.to_list(length=PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD)
    for it in items:
        it["id"] = str(it.pop("_id"))
        ts = it.get("created_at")
        if hasattr(ts, "isoformat"):
            it["created_at"] = ts.isoformat()
    return {"snapshots": items, "count": len(items)}


@api_router.post("/dataset/{upload_id}/phasage-restore/{snapshot_id}")
async def restore_phasage_snapshot(upload_id: str, snapshot_id: str,
                                    current_user: dict = Depends(get_current_user)):
    """Restaure le phasage à partir d'un snapshot versionné."""
    from bson import ObjectId
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    try:
        snap = await db.phasage_snapshots.find_one({
            "_id": ObjectId(snapshot_id),
            "upload_id": upload_id,
        })
    except Exception:
        raise HTTPException(status_code=400, detail="Snapshot ID invalide")
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot introuvable")
    new_phasage = snap.get("phasage") or {}
    if not isinstance(new_phasage, dict):
        raise HTTPException(status_code=500, detail="Snapshot corrompu")
    # Sauvegarde un snapshot du phasage actuel AVANT restauration
    # (pour pouvoir annuler la restauration si nécessaire).
    await save_phasage_snapshot(upload_id, current_user, d.get("phasage") or {})
    d["phasage"] = new_phasage
    try:
        await persist_phasage(upload_id, d["phasage"])
    except Exception as e:
        logger.warning(f"Mongo persist phasage failed (restore): {e}")
    new_snap_id = await save_phasage_snapshot(upload_id, current_user, new_phasage)
    await log_audit(
        upload_id, current_user, "phasage_restored",
        target=f"snapshot {snapshot_id[:8]}...",
        details={"restored_from": snapshot_id, "snapshot_id": new_snap_id},
    )
    return {"ok": True, "phasage": new_phasage}


def _filter_autre_rows(d: dict) -> list[dict]:
    """Retourne les lignes du fichier original dont la Référence contient 'AUTRE'
    (insensible à la casse), peu importe le Type (Fixation, EEG, Rail, etc.).
    Couvre les variantes AUTRE1, AUTRE3, AUTRE A, "Mat AUTRE", etc.
    """
    raw = d.get("raw_records") or []
    cols = d.get("detected_cols") or {}
    ref_col = cols.get("reference")
    if not ref_col:
        return []
    out = []
    for r in raw:
        ref = str(r.get(ref_col) or "").strip().upper()
        if "AUTRE" in ref:
            out.append(r)
    return out


@api_router.get("/dataset/{upload_id}/autre")
async def get_dataset_autre(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Retourne les lignes de fixation 'AUTRE*' du fichier original (lecture seule).
    Endpoint léger : ne renvoie que les lignes filtrées (typiquement <50)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = _filter_autre_rows(d)
    return {
        "upload_id": upload_id,
        "columns": d["columns"],
        "rows": rows,
        "count": len(rows),
    }


@api_router.get("/share/{share_token}/autre")
async def get_shared_autre(share_token: str):
    """Endpoint PUBLIC : lignes AUTRE* d'un dataset partagé."""
    d = await _resolve_share_token(share_token)
    rows = _filter_autre_rows(d)
    return {"columns": d["columns"], "rows": rows, "count": len(rows)}



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


def _refresh_batterie_software_block(rows: list[dict]) -> list[dict]:
    """Synchronise les lignes 'batterie caméra' et 'software caméra' avec
    la somme des caméras blanche + noire.

    Règle utilisateur (21/06/2026) :
      - batterie.quantite        = caméra_blanche.quantite + caméra_noire.quantite
      - batterie.total_plus_spare = caméra_blanche.t+s     + caméra_noire.t+s
      - batterie.spare           = batterie.t+s - batterie.quantite
      - software.quantite        = idem batterie
      - software.total_plus_spare = idem batterie
      - software.spare           = "" (pas de spare)

    Si les caméras n'ont aucune quantité, on vide aussi batterie/software.
    """
    def _to_float(v):
        try:
            return float(v) if v not in (None, "") else 0.0
        except (TypeError, ValueError):
            return 0.0

    # Trouve les sources (caméra blanche + caméra noire) par désignation
    sum_qty = 0.0
    sum_tps = 0.0
    for r in rows:
        desig = (r.get("designation") or "").strip().lower()
        if desig in ("caméra (blanche)", "caméra (noire)"):
            sum_qty += _to_float(r.get("quantite"))
            sum_tps += _to_float(r.get("total_plus_spare"))

    has_data = sum_qty > 0 or sum_tps > 0
    for r in rows:
        desig = (r.get("designation") or "").strip().lower()
        if desig == "batterie caméra":
            if has_data:
                r["quantite"] = int(sum_qty) if sum_qty.is_integer() else sum_qty
                r["total_plus_spare"] = int(sum_tps) if sum_tps.is_integer() else sum_tps
                diff = sum_tps - sum_qty
                r["spare"] = int(diff) if diff.is_integer() else diff
            else:
                r["quantite"] = 0
                r["spare"] = 0
                r["total_plus_spare"] = 0
        elif desig == "software caméra":
            if has_data:
                r["quantite"] = int(sum_qty) if sum_qty.is_integer() else sum_qty
                # Software sans spare : total+spare = quantité (pas de t+s des caméras)
                r["total_plus_spare"] = int(sum_qty) if sum_qty.is_integer() else sum_qty
            else:
                r["quantite"] = 0
                r["total_plus_spare"] = 0
            r["spare"] = ""  # toujours vide pour software caméra
    return rows


def _refresh_vcare_block(rows: list[dict]) -> list[dict]:
    """Reconstruit le bloc 'TOTAL VCare' à partir des lignes produit courantes.
    Retire l'ancien bloc VCare (s'il existe) et le ré-insère avant les lignes
    vides finales. Utilisé après chaque édition d'une ligne du récap pour que
    les VCare restent synchronisés avec les quantités."""
    # 1) Retire le bloc VCare existant
    cleaned = [r for r in rows if not (
        r.get("type") == "VCare" and r.get("kind") in ("header", "product")
    )]
    # 2) Recalcule à partir des lignes courantes
    new_vcare = _build_vcare_rows(cleaned, pd.DataFrame(), {})
    if not new_vcare:
        return cleaned
    # 3) Insère avant la queue de lignes vides
    # Trouve l'index de la première ligne 'empty' consécutive en fin
    insert_at = len(cleaned)
    for i in range(len(cleaned) - 1, -1, -1):
        if cleaned[i].get("kind") == "empty":
            insert_at = i
        else:
            break
    return cleaned[:insert_at] + new_vcare + cleaned[insert_at:]


@api_router.patch("/dataset/{upload_id}/recap-row/{index}")
async def update_recap_row(upload_id: str, index: int, payload: RecapRowUpdate, current_user: dict = Depends(get_current_user)):
    """Met à jour une ligne du récapitulatif. Toutes les lignes sont éditables
    sauf les en-têtes de section (kind='header')."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
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
    # Alias de référence (ex: 17979 -> 15912)
    if new_ref in REF_ALIASES:
        new_ref = REF_ALIASES[new_ref]
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
    # Recalcule batterie + software caméra (auto = somme caméras N+B), puis
    # le bloc VCare. Cf. règles utilisateur 21/06/2026 + 11/06/2026.
    rows = _refresh_batterie_software_block(rows)
    rows = _refresh_vcare_block(rows)
    rows = _apply_total_moq_and_bonuses(rows)
    # Re-persister
    try:
        await persist_recap_rows(upload_id, rows)
    except Exception as e:
        logger.warning(f"Mongo persist recap failed: {e}")
    return {"row": row, "index": index, "rows": rows}


@api_router.post("/dataset/{upload_id}/recap-row")
async def add_recap_row(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Ajoute une nouvelle ligne vide à la fin du récapitulatif."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
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


class DonglesUpdate(BaseModel):
    quantity: Optional[int] = None  # nombre de dongles à ajouter (sans spare)


@api_router.patch("/dataset/{upload_id}/dongles")
async def update_dongles(upload_id: str, payload: DonglesUpdate, current_user: dict = Depends(get_current_user)):
    """Définit le nombre de dongles à inclure dans la commande.
    Le nombre est ajouté à `total_plus_spare` de la ligne Dongle (sans spare).
    La référence reste fixée à 16639. La quantité de base reste vide (info)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if "recap_rows" not in d:
        raise HTTPException(status_code=404, detail="Recap rows not found")
    qty = int(payload.quantity or 0)
    rows = d["recap_rows"]
    for r in rows:
        if r.get("kind") == "dongle":
            r["reference"] = "16639"
            if qty > 0:
                r["total_plus_spare"] = qty
                r["quantite"] = qty
                r["spare"] = ""
            else:
                r["quantite"] = ""
                r["spare"] = ""
                r["total_plus_spare"] = ""
            break
    try:
        await persist_recap_rows(upload_id, rows)
        await db.datasets.update_one({"upload_id": upload_id}, {"$set": {"dongles_quantity": qty}})
    except Exception as e:
        logger.warning(f"Mongo persist dongles failed: {e}")
    rows = _apply_total_moq_and_bonuses(rows)
    await log_audit(upload_id, current_user, "dongles_changed", details={"quantity": qty})
    return {"quantity": qty, "rows": rows}


@api_router.patch("/dataset/{upload_id}/surface")
async def update_surface(upload_id: str, payload: SurfaceUpdate, current_user: dict = Depends(get_current_user)):
    """Définit la catégorie surface du magasin et applique les rajouts SA
    correspondants (sans spare), uniquement sur `total_plus_spare`.

    Règles utilisateur (23/06/2026) :
      • +10000m² → SA 2.1 (noir) +4800, SA 1.5 (noir) +1200, Support indiv alu SA +6000
      • -10000m² → SA 2.1 (noir) +3200, SA 1.5 (noir) +800,  Support indiv alu SA +4000
      • Aucun spare ajouté. La désignation est suffixée
        de " — rajout de X SA sans spare" (ou X supports).
      • On stocke les valeurs d'origine (`_surface_base_*`) la 1ère fois
        pour pouvoir revenir en arrière sans dérive cumulative.
      • Si une ligne cible n'existe pas dans le fichier, on crée une ligne
        dédiée (kind='surface_added') avec uniquement total_plus_spare = delta.
    """
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    cat = payload.category
    if cat not in (None, "plus_10000", "moins_10000"):
        raise HTTPException(status_code=400, detail="Catégorie surface invalide")
    # Delta par ligne cible — règles 23/06/2026
    if cat == "plus_10000":
        delta_sa21, delta_sa15, delta_support = 4800, 1200, 6000
    elif cat == "moins_10000":
        delta_sa21, delta_sa15, delta_support = 3200, 800, 4000
    else:
        delta_sa21 = delta_sa15 = delta_support = 0
    d["surface_category"] = cat
    rows = d["recap_rows"]

    def _strip_surface_suffix(s: str) -> str:
        """Retire un éventuel ' — rajout de X SA/supports sans spare' à la fin."""
        if not s:
            return s
        idx = s.find(" — rajout de ")
        return s[:idx] if idx != -1 else s

    def _apply_delta_to_row(target: dict, delta: int, suffix_word: str,
                              default_desig: str) -> None:
        """Applique le delta sur la ligne (init des _surface_base_* si besoin)."""
        needs_init = "_surface_base_quantite" not in target or (
            float(target.get("_surface_base_total") or 0) == 0
            and float(target.get("_surface_base_quantite") or 0) > 0
        )
        if needs_init:
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
                try:
                    raw_t = target.get("total_plus_spare")
                    if raw_t in ("", None):
                        target["_surface_base_total"] = target["_surface_base_quantite"] + target["_surface_base_spare"]
                    else:
                        target["_surface_base_total"] = float(raw_t)
                except (ValueError, TypeError):
                    target["_surface_base_total"] = target["_surface_base_quantite"] + target["_surface_base_spare"]
            target["_surface_base_designation"] = _strip_surface_suffix(target.get("designation") or default_desig)

        base_q = target["_surface_base_quantite"]
        base_s = target["_surface_base_spare"]
        base_t = target["_surface_base_total"]
        base_d = target["_surface_base_designation"]
        target["quantite"] = base_q if base_q > 0 else ""
        target["spare"] = base_s if base_s > 0 else ""
        if delta > 0:
            target["total_plus_spare"] = base_t + delta
            # 23/06/2026 : suffixe retiré, info via colonne Saisonnier.
            target["designation"] = base_d
        else:
            target["total_plus_spare"] = base_t if base_t > 0 else ""
            target["designation"] = base_d

    # 0) Nettoyage : on supprime systématiquement TOUTES les anciennes lignes
    #    `surface_added` orphelines (créées par les versions buggées précédentes).
    rows[:] = [r for r in rows if r.get("kind") != "surface_added"]

    def _find_product(predicate) -> Optional[dict]:
        for r in rows:
            if r.get("kind") != "product":
                continue
            base_desig = _strip_surface_suffix((r.get("designation") or "").strip()).lower()
            if predicate(base_desig):
                return r
        return None

    def _create_surface_added(designation: str, delta: int, where_type: str = "SA") -> None:
        last_empty_idx = next((i for i, r in enumerate(rows) if r.get("kind") == "empty"), len(rows))
        rows.insert(last_empty_idx, {
            "kind": "surface_added",
            "type": where_type,
            "reference": "",
            "designation": designation,
            "quantite": delta,
            "spare": "",
            "total_plus_spare": delta,
        })

    # 1) SA 2.1 (noir)
    t_sa21 = _find_product(lambda d: d == "sa 2.1 (noir)")
    if t_sa21 is not None:
        _apply_delta_to_row(t_sa21, delta_sa21, "SA", "SA 2.1 (noir)")
    elif delta_sa21 > 0:
        _create_surface_added("SA 2.1 (noir)", delta_sa21)

    # 2) SA 1.5 (noir) — règle ajoutée 23/06/2026
    t_sa15 = _find_product(lambda d: d == "sa 1.5 (noir)")
    if t_sa15 is not None:
        _apply_delta_to_row(t_sa15, delta_sa15, "SA", "SA 1.5 (noir)")
    elif delta_sa15 > 0:
        _create_surface_added("SA 1.5 (noir)", delta_sa15)

    # 3) Support individuel alu SA
    t_support = _find_product(lambda d: "support individuel alu sa" in d)
    if t_support is not None:
        _apply_delta_to_row(t_support, delta_support, "supports", "Support individuel alu SA")
    elif delta_support > 0:
        _create_surface_added("Support individuel alu SA", delta_support, where_type="Support")

    # Recalcule batterie + software caméra + VCare (les changements de surface
    # ajoutent/retirent des SA → VCare doit suivre).
    rows = _refresh_batterie_software_block(rows)
    rows = _refresh_vcare_block(rows)
    rows = _apply_total_moq_and_bonuses(rows)
    # Persister recap + surface_category
    try:
        await persist_recap_rows(upload_id, rows)
        await db.datasets.update_one({"upload_id": upload_id}, {"$set": {"surface_category": cat}})
    except Exception as e:
        logger.warning(f"Mongo persist surface failed: {e}")
    await log_audit(upload_id, current_user, "surface_changed", details={"category": cat or "aucune"})
    return {"category": cat, "rows": rows}


@api_router.delete("/dataset/{upload_id}/recap-row/{index}")
async def delete_recap_row(upload_id: str, index: int, current_user: dict = Depends(get_current_user)):
    """Supprime une ligne du récapitulatif (sauf en-têtes de section)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    rows = d["recap_rows"]
    if index < 0 or index >= len(rows):
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    if rows[index]["kind"] == "header":
        raise HTTPException(status_code=400, detail="Les en-têtes de section ne sont pas supprimables")
    deleted = dict(rows[index])
    rows.pop(index)
    # Recalcule VCare (la suppression d'une source modifie les totaux VCare).
    rows = _refresh_vcare_block(rows)
    rows = _apply_total_moq_and_bonuses(rows)
    try:
        await persist_recap_rows(upload_id, rows)
    except Exception as e:
        logger.warning(f"Mongo persist recap failed: {e}")
    await log_audit(upload_id, current_user, "recap_row_deleted",
                    target=str(deleted.get("designation", "") or deleted.get("reference", "")),
                    details={"index": index})
    return {"ok": True, "remaining": len(rows), "deleted_index": index, "rows": rows}


class CommentTableUpdate(BaseModel):
    columns: list[str]
    rows: list[list[str]]


@api_router.patch("/dataset/{upload_id}/comment-table")
async def update_comment_table(upload_id: str, payload: CommentTableUpdate, current_user: dict = Depends(get_current_user)):
    """Met à jour le tableau de commentaires (colonnes + lignes)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    d["comment_table"] = {"columns": payload.columns, "rows": payload.rows}
    try:
        await persist_comment_table(upload_id, d["comment_table"])
    except Exception as e:
        logger.warning(f"Mongo persist comment_table failed: {e}")
    await log_audit(upload_id, current_user, "comment_table_updated",
                    details={"cols": len(payload.columns), "rows": len(payload.rows)})
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
# (1187 inclus depuis le 08/02/2026)
RAILS_BONUS_ES15 = [
    ("1187 mm (noir)", "noir"),
    ("1187 mm (blanc)", "blanc"),
    ("1240 mm (noir)", "noir"),
    ("1320 mm (blanc)", "blanc"),
    ("1320 mm (noir)", "noir"),
    ("535 mm (noir)", "noir"),
    ("650 mm (noir)", "noir"),
    ("990 mm (blanc)", "blanc"),
    ("990 mm (noir)", "noir"),
]


def _is_fleche(s: Any) -> bool:
    """Détecte si une chaîne décrit une 'flèche' (accent/casse insensibles).
    Une flèche dans le brut compte pour +1 ES 1.5 (noir) automatiquement,
    et apparaît comme annotation 'dont flèches' dans le Phasage de pose.
    """
    if s is None:
        return False
    try:
        if isinstance(s, float) and math.isnan(s):
            return False
    except (TypeError, ValueError):
        pass
    import unicodedata
    norm = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode("ascii").lower().strip()
    return "fleche" in norm


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
              "es_15_bonus_noir": 0.0, "es_15_bonus_blanc": 0.0,  # legacy (toujours 0 désormais)
              "fleches": 0.0,
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
            "fleches": 0.0,
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
        # Détection flèche : Type OU Désignation contient "flèche".
        # Chaque flèche = +1 EEG ES 1.5 (noir) à rajouter automatiquement.
        elif _is_fleche(typ) or _is_fleche(desig):
            node["fleches"] += qty
            totals["fleches"] += qty

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
        a["fleches"] = _r(a.get("fleches", 0))
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
        "fleches": _r(totals.get("fleches", 0)),
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
        "dongles_quantity": int(d.get("dongles_quantity") or 0) if isinstance(d, dict) else 0,
    }


def _normalize_phasage(stored: Any) -> dict:
    """Normalise le phasage stocké en MongoDB (gère l'ancien format à plat)."""
    if not isinstance(stored, dict):
        return {
            "es": {"nb_nuits": 3, "rows": []},
            "cam": {"nb_nuits": 3, "rows": [], "start_at_nuit": 5},
            "suivi": {"rows": []},
            "dates": {},
        }
    # Ancien format : {nb_nuits, rows} -> migrer vers .es
    if "nb_nuits" in stored and "rows" in stored and "es" not in stored:
        return {
            "es": {"nb_nuits": stored.get("nb_nuits", 3), "rows": stored.get("rows", [])},
            "cam": {"nb_nuits": 3, "rows": [], "start_at_nuit": 5},
            "suivi": {"rows": []},
            "dates": {},
        }
    es = stored.get("es") or {"nb_nuits": 3, "rows": []}
    cam = stored.get("cam") or {"nb_nuits": 3, "rows": [], "start_at_nuit": 5}
    if "start_at_nuit" not in cam:
        cam["start_at_nuit"] = 5
    suivi = stored.get("suivi") or {"rows": []}
    dates = stored.get("dates") if isinstance(stored.get("dates"), dict) else {}
    return {"es": es, "cam": cam, "suivi": suivi, "dates": dates}


@api_router.get("/dataset/{upload_id}/phasage-summary")
async def get_phasage_summary(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Retourne la liste des allées avec leurs comptes ES / Rails ES / Caméras
    + les totaux globaux + l'état du phasage (ES, Cam, Suivi)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    summary = compute_phasage_summary(d)
    summary["phasage"] = _normalize_phasage(d.get("phasage"))
    summary["vt_start_date"] = d.get("vt_start_date") or ""
    summary["store_name"] = d.get("store_name") or ""
    summary["store_code"] = d.get("store_code") or ""
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
    dates: Optional[dict] = None  # {"1": "2026-02-15", "2": "2026-02-16", ...}


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
async def update_phasage(upload_id: str, payload: PhasageFullUpdate, current_user: dict = Depends(get_current_user)):
    """Sauvegarde l'état complet : ES + Caméras + Suivi (réalité)."""
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    es = _sanitize_planning(payload.es)
    cam = _sanitize_planning(payload.cam)
    if "start_at_nuit" not in cam:
        cam["start_at_nuit"] = 5
    # Préserve auto_sort_by_nuit (flag introduit le 22/06/2026 — n'est pas
    # transmis par le frontend, il est figé à l'upload pour les nouvelles
    # sessions et absent pour les anciennes).
    _prev = d.get("phasage") if isinstance(d.get("phasage"), dict) else {}
    for _key, _payload in (("es", es), ("cam", cam)):
        _prev_block = (_prev or {}).get(_key) or {}
        if "auto_sort_by_nuit" in _prev_block:
            _payload["auto_sort_by_nuit"] = _prev_block["auto_sort_by_nuit"]
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
    # Préserve les anciennes dates si non envoyées
    prev_phasage = d.get("phasage") if isinstance(d.get("phasage"), dict) else None
    prev_dates = prev_phasage.get("dates") if isinstance(prev_phasage, dict) else None

    new_phasage = {"es": es, "cam": cam, "suivi": {"rows": suivi_rows}}
    # Dates par nuit (clés = "1", "2", ... ; valeurs ISO "YYYY-MM-DD")
    if payload.dates is not None:
        clean_dates = {}
        for k, v in (payload.dates or {}).items():
            try:
                kn = int(k)
            except (ValueError, TypeError):
                continue
            if kn <= 0:
                continue
            sv = str(v or "").strip()[:10]
            if sv and re.match(r"^\d{4}-\d{2}-\d{2}$", sv):
                clean_dates[str(kn)] = sv
        new_phasage["dates"] = clean_dates
    elif isinstance(prev_dates, dict):
        new_phasage["dates"] = prev_dates
    d["phasage"] = new_phasage
    try:
        await persist_phasage(upload_id, d["phasage"])
    except Exception as e:
        logger.warning(f"Mongo persist phasage failed: {e}")
    # Snapshot versionné (22/06/2026) — restaurable depuis l'Historique.
    snapshot_id = await save_phasage_snapshot(upload_id, current_user, d["phasage"])
    # Détermine ce qui a changé pour le log
    changed = []
    if payload.dates is not None: changed.append("dates")
    if (prev_phasage or {}).get("es") != es: changed.append("planning ES")
    if (prev_phasage or {}).get("cam") != cam: changed.append("planning Caméras")
    if (prev_phasage or {}).get("suivi", {}).get("rows") != suivi_rows: changed.append("suivi")
    if changed:
        details = {"nb_nuits_es": es.get("nb_nuits"), "nb_nuits_cam": cam.get("nb_nuits")}
        if snapshot_id:
            details["snapshot_id"] = snapshot_id
        await log_audit(upload_id, current_user, "phasage_updated",
                        target=", ".join(changed), details=details)
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
    assignations stockées en DB (uid) vers les labels courts affichés dans Excel.

    Inclut un fallback "numéro de base" : si l'uid est de la forme
    "{N}__{SECTEUR}__{RAYON}", on enregistre aussi le mapping `{N}__*` pour
    rattraper les assignations historiques où le secteur/rayon a changé après
    un re-upload du fichier (sinon les calculs caméras retombent à 0)."""
    mapping = {}
    # Mapping principal uid → label exact
    for a in allees:
        uid = str(a.get("uid") or a.get("allee"))
        mapping[uid] = _allee_display_label(a)
    # Fallback par numéro de base (priorité au mapping exact, donc setdefault)
    base_to_labels: dict[str, list[str]] = {}
    for a in allees:
        base = str(a.get("allee") or "").strip()
        if base:
            base_to_labels.setdefault(base, []).append(_allee_display_label(a))
    # Pour chaque uid composite absent, on tente un mapping via le préfixe.
    # On n'écrase JAMAIS un mapping exact.
    # On ne crée le fallback que si une seule label correspond (sinon ambigu).
    for base, labels in base_to_labels.items():
        if len(set(labels)) == 1:
            mapping.setdefault(base, labels[0])  # uid simple "10"
    for z in (seasonal_zones or []):
        # uid = id ("ZS1"), label = id
        mapping[str(z.get("id"))] = str(z.get("id"))
    return mapping


def _resolve_uid_label(uid: str, mapping: dict) -> str:
    """Résout un uid (potentiellement composite "{N}__SECTEUR__RAYON") vers son
    label affichable. Tente l'exact, puis le numéro de base avant le premier
    "__". Retourne l'uid d'origine si rien ne matche."""
    if uid in mapping:
        return mapping[uid]
    base = uid.split("__", 1)[0] if "__" in uid else uid
    return mapping.get(base, uid)


def _full_allee_index(summary: dict) -> dict:
    """Index uid -> noeud allée. INCLUT les zones saisonnières (SZ) avec
    secteur='Zone saisonnier'. Ces zones étaient précédemment ignorées dans
    les récap des exports Excel (RTR + Carrefour), causant leur disparition.
    Leur EEG (eeg=2000 par SZ par défaut) est comptabilisé via es_21 pour
    que les agrégations existantes les somment naturellement.

    Fallback ajouté : on enregistre aussi un mapping `base allée → premier
    nœud trouvé` pour rattraper les assignations stockées en DB avec un
    secteur/rayon qui n'existe plus après re-upload (sinon `idx.get(uid)`
    renvoie None et l'allée disparaît silencieusement des récaps).
    """
    idx = {str(a.get("uid") or a.get("allee")): a
           for a in (summary.get("allees") or [])}
    # Fallback par numéro de base (n'écrase pas les uids exacts).
    by_base: dict[str, list] = {}
    for a in (summary.get("allees") or []):
        base = str(a.get("allee") or "").strip()
        if base:
            by_base.setdefault(base, []).append(a)
    for base, nodes in by_base.items():
        # On n'ajoute le fallback que s'il n'existe pas déjà comme uid exact
        # ET qu'il n'y a aucune ambiguïté (1 seule allée pour ce numéro).
        if base not in idx and len(nodes) == 1:
            idx[base] = nodes[0]
    for z in (summary.get("seasonal_zones") or []):
        sz_eeg = float(z.get("eeg") or 0)
        idx[str(z["id"])] = {
            "uid": z["id"], "allee": z["id"],
            "es_15": 0, "es_21": sz_eeg,
            "sa": float(z.get("sa_21") or 0), "sa_15": 0,
            "sa_21": float(z.get("sa_21") or 0),
            "rails_es": 0, "rails_es_by_desig": {},
            "cameras": 0, "camera_elems": [],
            "fleches": 0,
            "es_15_bonus_noir": 0, "es_15_bonus_blanc": 0,
            "secteur": "Zone saisonnier",
            "rayon": z.get("label") or z["id"],
            "seasonal_eeg": sz_eeg, "is_seasonal": True,
        }
    return idx


def _resolve_idx_node(uid: str, idx: dict):
    """Récupère le nœud allée depuis l'index avec fallback sur le numéro de
    base avant le premier `__`. Retourne None si introuvable."""
    node = idx.get(uid)
    if node is not None:
        return node
    if "__" in uid:
        return idx.get(uid.split("__", 1)[0])
    return None


def _format_sr_grouped(sr_pairs) -> str:
    """Reçoit une liste de "Secteur:Rayon" et retourne une chaîne factorisée :
       ["NAL:Bébé", "NAL:Homme", "PGC:Animalerie"]
       -> "NAL : Bébé / Homme | PGC : Animalerie"
    """
    if not sr_pairs:
        return ""
    by_sec: dict = {}
    order: list = []
    for s in sr_pairs:
        s = (s or "").strip()
        if not s:
            continue
        if ":" in s:
            sec, ray = s.split(":", 1)
        else:
            sec, ray = s, ""
        sec = sec.strip()
        ray = ray.strip()
        if not sec:
            continue
        if sec not in by_sec:
            by_sec[sec] = []
            order.append(sec)
        if ray and ray not in by_sec[sec]:
            by_sec[sec].append(ray)
    parts = []
    for sec in order:
        rays = by_sec[sec]
        parts.append(f"{sec} : {' / '.join(rays)}" if rays else sec)
    return " | ".join(parts)





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
        fleches = a.get("fleches") or 0
        sa_15_val = a.get("sa_15") or 0
        sa_21_val = a.get("sa_21") or 0
        ws_data.write_string(i, 0, _allee_display_label(a))
        if is_m2:
            # Magasin 2 : EEG = ES + SA 1.5 + flèches (aligné app)
            ws_data.write_number(i, 1, es_brut + sa_15_val + fleches)
            ws_data.write_number(i, 2, a["rails_es"] or 0)
            ws_data.write_number(i, 3, sa_21_val)
            ws_data.write_number(i, 4, sa_15_val)
        else:
            # Magasin 1 : EEG = ES + bonus rails + flèches (aligné app)
            ws_data.write_number(i, 1, es_brut + bonus + fleches)
            ws_data.write_number(i, 2, a["rails_es"] or 0)
            ws_data.write_number(i, 3, a.get("sa") or 0)
            ws_data.write_number(i, 4, bonus)
    # Ajoute les zones saisonnières comme allées sélectionnables (avec leur EEG)
    for j, z in enumerate(seasonal_zones, start=1):
        rr = n_allees + j
        ws_data.write_string(rr, 0, str(z["id"]))
        ws_data.write_number(rr, 1, int(z.get("eeg") or 0))
        ws_data.write_number(rr, 2, 0)
        # SA 2.1 (info) : on remonte z.sa_21 pour aligner le récap SA par nuit
        # avec celui affiché dans l'application (sinon les nuits avec ZS
        # apparaissent en moins-X SA dans l'export).
        ws_data.write_number(rr, 3, int(z.get("sa_21") or 0))
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
    ws.set_column(7, 7, 11)   # H Date
    ws.set_column(8, 8, 18)   # I Secteur/Rayon
    ws.set_column(9, 9, 32)   # J Allées
    ws.set_column(10, 10, 12) # K EEG
    ws.set_column(11, 11, 12) # L Rails ES
    ws.set_column(12, 12, 10) # M SA (info)
    ws.set_column(13, 13, 10) # N Caméras

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
    # Désactive l'avertissement "Nombre stocké sous forme de texte" (les n°
    # d'allée sont volontairement en texte pour supporter "201-2", "ZS1"…).
    ws.ignore_errors({"number_stored_as_text": "A1:Z2000"})
    ws.write(1, 0, "Nb nuits :", fmt_lbl)
    ws.write_number(1, 1, nb_nuits, fmt_input)
    ws.write(1, 2, "Moyenne/nuit :", fmt_lbl)
    # Moyenne = Total EEG (B4) / Nb nuits (B2). EEG = Total ES + SA 2.1 saisonnier
    ws.write_formula(1, 3, "=IFERROR(ROUND(B4/B2,0),0)", fmt_num_calc)
    ws.write(1, 4, "Total EEG / Nb nuits", fmt_italic)

    # ----- Totaux globaux du fichier (statiques) -----
    # Total EEG = somme des EEG par nuit (alignée sur le récap droit + l'application).
    # Le SA 2.1 saisonnier reste affiché en ligne 5 pour information mais
    # n'est plus inclus dans ce total (sinon la somme ≠ TOTAL du récap).
    total_es_brut = (totals["es_15"] or 0) + (totals["es_21"] or 0)
    total_bonus = (totals.get("es_15_bonus_noir") or 0) + (totals.get("es_15_bonus_blanc") or 0)
    total_fleches = totals.get("fleches") or 0
    total_sa_15 = totals.get("sa_15") or 0
    total_sa_21 = totals.get("sa_21") or 0
    sa_21_saisonnier = int(summary.get("sa_21_saisonnier") or 0)
    if is_m2:
        # Magasin 2 : ES + SA 1.5 + flèches
        total_eeg = total_es_brut + total_sa_15 + total_fleches
    else:
        # Magasin 1 : ES + bonus rails + flèches
        total_eeg = total_es_brut + total_bonus + total_fleches
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
    ws.write(4, 2, "(info — n'est pas inclus dans le total EEG ci-dessus)", fmt_italic)
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
        a_label = _resolve_uid_label(a_uid, uid_to_label)
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
    NB_RIGHT_COLS = 8  # Nuit | Date | Secteur/Rayon | Allées | EEG | Rails ES | SA | Caméras
    ws.merge_range(start_left, col_right, start_left, col_right + NB_RIGHT_COLS - 1, "Récap par nuit", fmt_title)
    headers_right = ["Nuit", "Date", "Secteur/Rayon", "Allées", "EEG", "Rails ES", "SA 2.1" if is_m2 else "SA", "Caméras"]
    for ci, h in enumerate(headers_right):
        ws.write(start_left + 1, col_right + ci, h, fmt_lbl)

    # Map dates par nuit + Secteur/Rayon par nuit (déduplication)
    dates_map_es = phasage_full.get("dates") or {}
    idx_allees_full = _full_allee_index(summary)
    sr_by_nuit_es: dict[int, list[str]] = {}
    for r2 in rows_assign:
        n2 = r2.get("nuit")
        a_uid = str(r2.get("allee") or "").strip()
        if not n2 or not a_uid:
            continue
        node = _resolve_idx_node(a_uid, idx_allees_full)
        if not node:
            continue
        sec = node.get("secteur") or ""
        ray = node.get("rayon") or ""
        if sec or ray:
            k = f"{sec}{':' + ray if ray else ''}"
            sr_by_nuit_es.setdefault(int(n2), [])
            if k not in sr_by_nuit_es[int(n2)]:
                sr_by_nuit_es[int(n2)].append(k)

    # Pré-calcul des allées par nuit pour la colonne "Allées" (texte statique)
    # Conversion uid -> label court (8, 112-1, ZS1)
    night_allees_static: dict[int, list[str]] = {n: [] for n in range(1, nb_nuits + 1)}
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = _resolve_uid_label(a_uid, uid_to_label)
        n = row.get("nuit")
        if a_label and n and 1 <= int(n) <= nb_nuits:
            night_allees_static[int(n)].append(a_label)

    # Caméras par nuit globale (depuis le Phasage caméras)
    cam_plan = phasage_full.get("cam") or {}
    cam_start_at = int(cam_plan.get("start_at_nuit") or 5)
    allee_uid_to_cam = {str(a.get("uid") or a["allee"]): float(a.get("cameras") or 0) for a in summary["allees"]}
    cam_per_night: dict[int, float] = {n: 0.0 for n in range(1, nb_nuits + 1)}
    for cr in (cam_plan.get("rows") or []):
        try:
            cn = int(cr.get("nuit") or 0)
        except (ValueError, TypeError):
            cn = 0
        if cn <= 0:
            continue
        global_n = cam_start_at + cn - 1
        if 1 <= global_n <= nb_nuits:
            cam_per_night[global_n] += allee_uid_to_cam.get(str(cr.get("allee") or ""), 0)

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
    # Date et Secteur/Rayon : on ne fixe PAS de bg blanc, pour que la CF par
    # nuit puisse colorer la ligne entière (cf. demande du 06/02/2026).
    fmt_date_neutral = workbook.add_format({"border": 1, "align": "center",
                                             "num_format": "dd/mm/yyyy"})
    fmt_sr_neutral = workbook.add_format({"border": 1, "align": "left",
                                           "font_size": 9, "text_wrap": True})

    for i, n in enumerate(range(1, nb_nuits + 1), start=0):
        rrow = first_data_row + i
        nuit_label = f"Nuit {n}"
        ws.write(rrow, col_right + 0, nuit_label, fmt_cell_neutral)
        # Date (col_right + 1) — fond blanc
        date_iso = dates_map_es.get(str(n))
        if date_iso:
            try:
                from datetime import datetime as _dt
                ws.write_datetime(rrow, col_right + 1, _dt.strptime(date_iso, "%Y-%m-%d").date(), fmt_date_neutral)
            except Exception:
                ws.write_string(rrow, col_right + 1, date_iso, fmt_date_neutral)
        else:
            ws.write_blank(rrow, col_right + 1, None, fmt_date_neutral)
        # Secteur/Rayon (col_right + 2) — fond blanc
        sr_list = sr_by_nuit_es.get(n) or []
        ws.write_string(rrow, col_right + 2, _format_sr_grouped(sr_list), fmt_sr_neutral)
        # Colonne "Allées" : texte statique (calculé à l'export)
        allees_sorted = sorted(night_allees_static.get(n, []), key=_sort_allee_key)
        allees_text = ", ".join(allees_sorted) if allees_sorted else ""
        ws.write_string(rrow, col_right + 3, allees_text, fmt_allees_neutral)
        # EEG par nuit : SUMIFS simple (aligné sur l'affichage de l'application).
        # La distribution prorata du SA 2.1 saisonnier n'est PAS ajoutée
        # car elle créait un écart entre la somme par nuit dans Excel et
        # le total affiché dans l'app (capture utilisateur du 11/06/2026).
        eeg_formula = f'=SUMIFS({B_range},{E_range},"{nuit_label}")'
        ws.write_formula(rrow, col_right + 4, eeg_formula, fmt_num_neutral)
        ws.write_formula(rrow, col_right + 5,
                         f'=SUMIFS({C_range},{E_range},"{nuit_label}")', fmt_num_neutral)
        ws.write_formula(rrow, col_right + 6,
                         f'=SUMIFS({D_range_sa},{E_range},"{nuit_label}")', fmt_sa_neutral)
        # Colonne Caméras (col_right + 7)
        fmt_cam_neutral = workbook.add_format({"border": 1, "align": "right",
                                                "bold": True, "font_color": "#6B21A8"})
        cam_val = int(round(cam_per_night.get(n, 0)))
        if cam_val > 0:
            ws.write_number(rrow, col_right + 7, cam_val, fmt_cam_neutral)
        else:
            ws.write_blank(rrow, col_right + 7, None, fmt_cam_neutral)

    # Ligne TOTAL (somme des nb_nuits lignes)
    rrow_total = first_data_row + nb_nuits
    excel_total_first = first_data_row + 1
    excel_total_last = first_data_row + nb_nuits
    ws.write(rrow_total, col_right + 0, "TOTAL", fmt_total_lbl)
    # Date + Secteur/Rayon : cellules vides
    ws.write_blank(rrow_total, col_right + 1, None, fmt_total_lbl)
    ws.write_blank(rrow_total, col_right + 2, None, fmt_total_lbl)
    ws.write_formula(rrow_total, col_right + 3,
                     f'=COUNTA({A_range})&" allées planifiées"',
                     fmt_total_lbl)
    for offset in range(4, 8):  # 4..7 = EEG, Rails, SA, Caméras
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
            ws.merge_range(cur_row, col_right, cur_row, col_right + NB_RIGHT_COLS - 1,
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
                    ws.write(cur_row, col_right + 0, f"Nuit {n}", fmt_cell_neutral)
                    ws.write_blank(cur_row, col_right + 1, None, fmt_date_neutral)
                    ws.write_blank(cur_row, col_right + 2, None, fmt_sr_neutral)
                    for k in range(3, NB_RIGHT_COLS):
                        ws.write_blank(cur_row, col_right + k, None, fmt_num_neutral)
                else:
                    nuit_label = f"Nuit {n}"
                    ws.write(cur_row, col_right + 0, nuit_label, fmt_cell_neutral)
                    # Date
                    date_iso_w = dates_map_es.get(str(n))
                    if date_iso_w:
                        try:
                            from datetime import datetime as _dt
                            ws.write_datetime(cur_row, col_right + 1, _dt.strptime(date_iso_w, "%Y-%m-%d").date(), fmt_date_neutral)
                        except Exception:
                            ws.write_string(cur_row, col_right + 1, date_iso_w, fmt_date_neutral)
                    else:
                        ws.write_blank(cur_row, col_right + 1, None, fmt_date_neutral)
                    # Secteur/Rayon
                    sr_list_w = sr_by_nuit_es.get(n) or []
                    ws.write_string(cur_row, col_right + 2, _format_sr_grouped(sr_list_w), fmt_sr_neutral)
                    # Allées
                    allees_sorted = sorted(night_allees_static.get(n, []), key=_sort_allee_key)
                    ws.write_string(cur_row, col_right + 3,
                                    ", ".join(allees_sorted) if allees_sorted else "",
                                    fmt_allees_neutral)
                    ws.write_formula(cur_row, col_right + 4,
                                     f'=SUMIFS({B_range},{E_range},"{nuit_label}")',
                                     fmt_num_neutral)
                    ws.write_formula(cur_row, col_right + 5,
                                     f'=SUMIFS({C_range},{E_range},"{nuit_label}")', fmt_num_neutral)
                    ws.write_formula(cur_row, col_right + 6,
                                     f'=SUMIFS({D_range_sa},{E_range},"{nuit_label}")', fmt_sa_neutral)
                    # Caméras
                    fmt_cam_week = workbook.add_format({"border": 1, "align": "right",
                                                         "bold": True, "font_color": "#6B21A8"})
                    cam_val_w = int(round(cam_per_night.get(n, 0)))
                    if cam_val_w > 0:
                        ws.write_number(cur_row, col_right + 7, cam_val_w, fmt_cam_week)
                    else:
                        ws.write_blank(cur_row, col_right + 7, None, fmt_cam_week)
                cur_row += 1
            sub_last = cur_row  # 1-indexed row of last data line
            # Sous-total semaine
            ws.write(cur_row, col_right + 0, f"Sous-total S{wi}", fmt_subtotal_lbl)
            ws.write(cur_row, col_right + 1, "", fmt_subtotal_lbl)
            ws.write(cur_row, col_right + 2, "", fmt_subtotal_lbl)
            ws.write(cur_row, col_right + 3, "", fmt_subtotal_lbl)
            for offset in range(4, NB_RIGHT_COLS):  # 4..7 = EEG, Rails, SA, Caméras
                col_letter = chr(ord('A') + col_right + offset)
                ws.write_formula(cur_row, col_right + offset,
                                 f"=SUM(${col_letter}${sub_first}:${col_letter}${sub_last})",
                                 fmt_subtotal)
            cur_row += 2  # une ligne d'espace entre les semaines
            # CF couleur par nuit sur les lignes data de cette semaine — toutes
            # les colonnes (Nuit, Date, SR, Allées, EEG, Rails, SA, Caméras)
            # sont colorées (demande du 06/02/2026).
            data_first_0 = sub_first - 1  # 0-indexed
            data_last_0 = sub_last - 1
            for n in range(n_start, n_end + 1):
                if n > nb_nuits: continue
                cf_fmt = cf_formats_right.get(n)
                if cf_fmt:
                    ws.conditional_format(
                        data_first_0, col_right, data_last_0, col_right + NB_RIGHT_COLS - 1,
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
    # Tableau droit : range G:N (Nuit, Date, SR, Allées, EEG, Rails, SA, Caméras)
    # — TOUTES les colonnes (y compris Date et SR) sont colorées par la CF
    # selon la nuit (demande du 06/02/2026).
    for n in range(1, nb_nuits + 1):
        cf_fmt = cf_formats_right[n]
        ws.conditional_format(
            first_data_row, col_right, first_data_row + nb_nuits - 1, col_right + NB_RIGHT_COLS - 1,
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

    # ----- Graphique supprimé (demande utilisateur 04/06/2026) -----
    chart_row = rrow_total + 3  # conservé pour le calcul de la note d'aide ci-dessous

    # Petite note d'aide en bas
    note_row = max(first_data_row + nb_rows_left, chart_row + 2) + 1
    ws.merge_range(note_row, 0, note_row, 13,
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

    # A=Allée, B=Caméras, C=Nuit, D=spacer, E=Nuit, F=Date, G=Secteur/Rayon, H=Allées, I=Caméras
    widths = [12, 12, 12, 3, 12, 11, 18, 32, 12]
    for c in range(len(widths)):
        ws.set_column(c, c, widths[c])

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
    # Désactive l'avertissement "Nombre stocké sous forme de texte" sur tout
    # l'onglet (les n° d'allée et d'éléments sont volontairement en texte pour
    # supporter "201-2", "ZS1"… et garder la cohérence VLOOKUP).
    ws.ignore_errors({"number_stored_as_text": "A1:Z2000"})
    ws.write(1, 0, "Nb nuits :", fmt_lbl)
    ws.write_number(1, 1, nb_nuits, fmt_input)
    ws.write(1, 2, "Démarrage :", fmt_lbl)
    ws.write_number(1, 3, start_at, fmt_input)
    ws.write(3, 0, "Total Caméras", fmt_lbl)
    ws.write_number(3, 1, totals.get("cameras", 0), fmt_num)
    ws.write(3, 2, "Moyenne / nuit :", fmt_lbl)
    _moyenne_cached = round((totals.get("cameras", 0) or 0) / nb_nuits) if nb_nuits else 0
    ws.write_formula(3, 3, "=IFERROR(ROUND(B4/B2,0),0)", fmt_num_calc, _moyenne_cached)

    nuit_labels = [f"Nuit {start_at + i}" for i in range(nb_nuits)]

    existing = []
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = _resolve_uid_label(a_uid, uid_to_label)
        n = row.get("nuit")
        existing.append({"allee": a_label, "nuit": (int(n) if n and 1 <= int(n) <= nb_nuits else None), "uid": a_uid})

    # Précalcul caméras par allée assignée (cache pour VLOOKUP)
    # et caméras par nuit locale (cache pour SUMIFS). Sans cache, certains
    # tableurs (LibreOffice, Google Sheets, Excel en mode "ouverture rapide")
    # affichent 0 jusqu'à un recalcul manuel.
    # Fallback : si l'uid composite stocké en DB ne matche plus (re-upload avec
    # secteur/rayon différent), on retombe sur le numéro de base.
    uid_to_cam = {str(a.get("uid") or a.get("allee")): float(a.get("cameras") or 0) for a in all_allees}
    base_to_cam: dict[str, float] = {}
    for a in all_allees:
        base = str(a.get("allee") or "").strip()
        if base:
            base_to_cam[base] = base_to_cam.get(base, 0) + float(a.get("cameras") or 0)
    label_to_cam = {_allee_display_label(a): float(a.get("cameras") or 0) for a in all_allees}
    cam_by_nuit_local = {n: 0 for n in range(1, nb_nuits + 1)}
    for e in existing:
        c = uid_to_cam.get(e["uid"])
        if c is None:
            base_uid = e["uid"].split("__", 1)[0] if "__" in e["uid"] else e["uid"]
            c = base_to_cam.get(base_uid, label_to_cam.get(e["allee"], 0))
        e["_cam"] = c
        if e["nuit"]:
            cam_by_nuit_local[e["nuit"]] = cam_by_nuit_local.get(e["nuit"], 0) + e["_cam"]

    # Tri des assignations : d'abord par nuit (croissante, None à la fin),
    # puis par numéro d'allée (tri naturel — "8" avant "10", "201-2" en suivant
    # le numéro de base). Sans ce tri, le Plan d'attribution affiche les allées
    # dans l'ordre où l'utilisateur les a ajoutées → des allées de Nuit 5
    # peuvent apparaître après celles de Nuit 7 si elles ont été ajoutées
    # tardivement.
    def _allee_sort_key(label: str):
        s = str(label or "")
        # ZS toujours à la fin
        if s.startswith("ZS"):
            return (1, 10**9, s)
        # Sépare en (numéro entier, suffixe texte) — "201-2" → (201, "-2")
        import re as _re
        m = _re.match(r"^(\d+)(.*)$", s)
        if m:
            return (0, int(m.group(1)), m.group(2))
        return (0, 10**9, s)

    existing.sort(key=lambda e: (
        e["nuit"] if e["nuit"] is not None else 10**9,
        _allee_sort_key(e["allee"]),
    ))

    start_left = 6
    # Plan d'attribution par allée — RETIRÉ sur demande utilisateur (12/06/2026).
    # On ne garde que le récap par nuit (colonnes A..E) + Détail caméras
    # par allée. Les valeurs Caméras du récap sont écrites en statique
    # (précalculées dans cam_by_nuit_local).
    first_data_row = start_left + 2
    nb_rows_left = 0  # plus de plan d'attribution

    col_right = 0
    NB_RIGHT_COLS_CAM = 5  # Nuit | Date | Secteur/Rayon | Allées | Caméras
    ws.merge_range(start_left, col_right, start_left, col_right + NB_RIGHT_COLS_CAM - 1, "Récap par nuit", fmt_title)
    for ci, h in enumerate(["Nuit", "Date", "Secteur/Rayon", "Allées", "Caméras"]):
        ws.write(start_left + 1, col_right + ci, h, fmt_lbl)

    # Map dates par nuit globale (start_at + n - 1) + Secteur/Rayon par nuit locale
    dates_map_cam = phasage_full.get("dates") or {}
    idx_allees_cam = {str(a.get("uid") or a["allee"]): a for a in all_allees}
    # Fallback par numéro de base : si une assignation référence un uid composite
    # obsolète (re-upload avec secteur/rayon différent), on retombe sur la 1ère
    # allée correspondante avec caméras.
    for a in all_allees:
        base = str(a.get("allee") or "").strip()
        if base and base not in idx_allees_cam:
            idx_allees_cam[base] = a
    sr_by_nuit_cam: dict[int, list[str]] = {}
    for r2 in rows_assign:
        n2 = r2.get("nuit")
        a_uid = str(r2.get("allee") or "").strip()
        if not n2 or not a_uid:
            continue
        node = _resolve_idx_node(a_uid, idx_allees_cam)
        if not node:
            continue
        sec = node.get("secteur") or ""
        ray = node.get("rayon") or ""
        if sec or ray:
            k = f"{sec}{':' + ray if ray else ''}"
            sr_by_nuit_cam.setdefault(int(n2), [])
            if k not in sr_by_nuit_cam[int(n2)]:
                sr_by_nuit_cam[int(n2)].append(k)

    # Date / SR — pas de bg explicite : la CF par nuit colore toute la ligne
    fmt_date_cam = workbook.add_format({"border": 1, "align": "center", "num_format": "dd/mm/yyyy"})
    fmt_sr_cam = workbook.add_format({"border": 1, "align": "left", "font_size": 9, "text_wrap": True})

    night_allees_static: dict[int, list[str]] = {n: [] for n in range(1, nb_nuits + 1)}
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = _resolve_uid_label(a_uid, uid_to_label)
        n = row.get("nuit")
        if a_label and n and 1 <= int(n) <= nb_nuits:
            night_allees_static[int(n)].append(a_label)
    smart_order = {_allee_display_label(a): i for i, a in enumerate(all_allees)}
    def _sak(a): return smart_order.get(str(a), 99999)

    for i, n in enumerate(range(1, nb_nuits + 1)):
        rrow = first_data_row + i
        global_n = start_at + n - 1
        nuit_label = f"Nuit {global_n}"
        ws.write(rrow, col_right + 0, nuit_label, fmt_cell_neutral)
        # Date (col_right + 1)
        date_iso_cam = dates_map_cam.get(str(global_n))
        if date_iso_cam:
            try:
                from datetime import datetime as _dt
                ws.write_datetime(rrow, col_right + 1, _dt.strptime(date_iso_cam, "%Y-%m-%d").date(), fmt_date_cam)
            except Exception:
                ws.write_string(rrow, col_right + 1, date_iso_cam, fmt_date_cam)
        else:
            ws.write_blank(rrow, col_right + 1, None, fmt_date_cam)
        # Secteur/Rayon (col_right + 2) — clé = nuit locale n
        sr_list_c = sr_by_nuit_cam.get(n) or []
        ws.write_string(rrow, col_right + 2, _format_sr_grouped(sr_list_c), fmt_sr_cam)
        # Allées (col_right + 3)
        ws.write_string(rrow, col_right + 3, ", ".join(sorted(night_allees_static.get(n, []), key=_sak)), fmt_allees_neutral)
        # Caméras (col_right + 4) — valeur statique (LEFT supprimé,
        # plus de SUMIFS à appliquer).
        _cam_n_cached = int(round(cam_by_nuit_local.get(n, 0) or 0))
        ws.write_number(rrow, col_right + 4, _cam_n_cached, fmt_num_neutral)

    rrow_total = first_data_row + nb_nuits
    ws.write(rrow_total, col_right + 0, "TOTAL", fmt_total_lbl)
    ws.write_blank(rrow_total, col_right + 1, None, fmt_total_lbl)
    ws.write_blank(rrow_total, col_right + 2, None, fmt_total_lbl)
    _allees_planifiees = sum(1 for e in existing if e["allee"])
    ws.write_string(rrow_total, col_right + 3, f"{_allees_planifiees} allées planifiées", fmt_total_lbl)
    _total_cached = int(round(sum(cam_by_nuit_local.values())))
    ws.write_number(rrow_total, col_right + 4, _total_cached, fmt_total_row)

    for n in range(1, nb_nuits + 1):
        global_n = start_at + n - 1
        nuit_label = f"Nuit {global_n}"
        nuit_col = chr(ord('A') + col_right)
        # CF sur le récap droit uniquement (Nuit, Date, SR, Allées, Caméras)
        ws.conditional_format(first_data_row, col_right, first_data_row + nb_nuits - 1, col_right + NB_RIGHT_COLS_CAM - 1,
            {"type": "formula", "criteria": f'=${nuit_col}{first_data_row + 1}="{nuit_label}"', "format": cf_right[n]})
    fmt_dup = workbook.add_format({"bg_color": "#FEE2E2", "font_color": "#991B1B", "border": 1, "bold": True})
    # CF doublons sur LEFT supprimée (plus de plan d'attribution).

    # --- Bloc détail par allée : Allée | N° Elements (couleur par nuit identique au récap) ---
    detail_idx = {_allee_display_label(a): a for a in all_allees}
    detail_rows = []  # list of (nuit, allee_label, [elems])
    for row in rows_assign:
        a_uid = str(row.get("allee") or "").strip()
        a_label = _resolve_uid_label(a_uid, uid_to_label)
        n = row.get("nuit")
        if not a_label or not n: continue
        node = detail_idx.get(a_label)
        if not node: continue
        detail_rows.append((int(n), a_label, node.get("camera_elems") or []))
    # Tri (nuit, ordre allée)
    detail_rows.sort(key=lambda x: (x[0], smart_order.get(x[1], 99999)))

    if detail_rows:
        # Le Détail commence après le récap par nuit + TOTAL + une ligne vide.
        # (Le LEFT "Plan d'attribution" a été retiré donc nb_rows_left = 0.)
        detail_start = first_data_row + nb_nuits + 3
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
    idx = _full_allee_index(summary)
    uid_to_label = _build_uid_to_label(summary["allees"], summary.get("seasonal_zones"))
    nuit_data: dict[int, dict] = {}
    for r in es_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = _resolve_idx_node(a_uid, idx)
        if not node: continue
        a_label = _resolve_uid_label(a_uid, uid_to_label)
        gn = int(n)
        dn = nuit_data.setdefault(gn, {"type": "ES", "allees": [], "es": 0, "cam": 0, "rails_es": 0})
        dn["allees"].append(a_label)
        dn["es"] += (node.get("es_15") or 0) + (node.get("es_21") or 0)
        dn["rails_es"] += node.get("rails_es") or 0
    for r in cam_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = _resolve_idx_node(a_uid, idx)
        if not node: continue
        a_label = _resolve_uid_label(a_uid, uid_to_label)
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
    idx = _full_allee_index(summary)
    uid_to_label = _build_uid_to_label(summary["allees"], summary.get("seasonal_zones"))

    # Construit pour chaque nuit globale les agrégats ES et Cam séparés
    per_nuit: dict[int, dict] = {}
    for r in es_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = _resolve_idx_node(a_uid, idx)
        if not node: continue
        a_label = _resolve_uid_label(a_uid, uid_to_label)
        gn = int(n)
        dn = per_nuit.setdefault(gn, {
            "es_allees": [], "es": 0, "rails_es": 0, "sa": 0,
            "cam_allees": [], "cam": 0,
        })
        dn["es_allees"].append(a_label)
        # EEG par nuit = ES (1.5 + 2.1) + bonus rails (sur ES 1.5) + flèches.
        # Aligné sur l'affichage du frontend PhasageTab (magasin_1). Pour
        # les zones saisonnières, `es_21` contient déjà `z.eeg` via
        # `_full_allee_index` → naturellement inclus.
        dn["es"] += (node.get("es_15") or 0) + (node.get("es_21") or 0)
        dn["es"] += (node.get("es_15_bonus_noir") or 0) + (node.get("es_15_bonus_blanc") or 0)
        dn["es"] += node.get("fleches") or 0
        dn["rails_es"] += node.get("rails_es") or 0
        dn["sa"] += node.get("sa") or 0
    for r in cam_plan.get("rows") or []:
        n, a_uid = r.get("nuit"), str(r.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = _resolve_idx_node(a_uid, idx)
        if not node: continue
        a_label = _resolve_uid_label(a_uid, uid_to_label)
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
    dates_map = phasage_full.get("dates") or {}

    # Construit deux maps Secteur:Rayon par nuit (déduplication) — séparées
    # ES (gauche) et Cam (droite) pour permettre l'affichage en colonnes
    # distinctes dans le tableau full (demande du 06/02/2026).
    sr_by_nuit_es: dict[int, list[str]] = {}
    sr_by_nuit_cam: dict[int, list[str]] = {}
    for r2 in es_plan.get("rows") or []:
        n, a_uid = r2.get("nuit"), str(r2.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = _resolve_idx_node(a_uid, idx)
        if not node: continue
        sec = node.get("secteur") or ""
        ray = node.get("rayon") or ""
        if sec or ray:
            key = f"{sec}{':' + ray if ray else ''}"
            sr_by_nuit_es.setdefault(int(n), [])
            if key not in sr_by_nuit_es[int(n)]:
                sr_by_nuit_es[int(n)].append(key)
    for r2 in cam_plan.get("rows") or []:
        n, a_uid = r2.get("nuit"), str(r2.get("allee") or "").strip()
        if not n or not a_uid: continue
        node = _resolve_idx_node(a_uid, idx)
        if not node: continue
        gn = start_at + int(n) - 1
        sec = node.get("secteur") or ""
        ray = node.get("rayon") or ""
        if sec or ray:
            key = f"{sec}{':' + ray if ray else ''}"
            sr_by_nuit_cam.setdefault(gn, [])
            if key not in sr_by_nuit_cam[gn]:
                sr_by_nuit_cam[gn].append(key)

    ws = workbook.add_worksheet("Phasage full")
    writer.sheets["Phasage full"] = ws
    # 10 colonnes : A B C D E (Sec EEG) | F (Nuit blanc) G (Date) | H (Sec Cam) I J
    ws.set_column(0, 0, 32)   # A Allées (ES)
    ws.set_column(1, 1, 10)   # B ES
    ws.set_column(2, 2, 10)   # C Rails ES
    ws.set_column(3, 3, 8)    # D SA
    ws.set_column(4, 4, 20)   # E Secteur/Rayon EEG
    ws.set_column(5, 5, 8)    # F Nuit (partagée — BLANC)
    ws.set_column(6, 6, 11)   # G Date
    ws.set_column(7, 7, 20)   # H Secteur/Rayon Cam
    ws.set_column(8, 8, 28)   # I Allées (Cam)
    ws.set_column(9, 9, 10)   # J Caméras

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
    # Nuit reste la SEULE colonne à fond blanc (demande utilisateur 06/02/2026)
    fmt_nuit = workbook.add_format({"bold": True, "border": 1, "align": "center", "bg_color": "#FFFFFF"})
    fmt_total_row = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "right"})
    fmt_total_lbl = workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "border": 1, "align": "center"})

    # Row 0 : titre global (fusionné A:J)
    ws.merge_range(0, 0, 0, 9, "Phasage full — Planning consolidé", fmt_title)
    # Row 1 : sous-titres distincts pour chaque bloc
    # Bloc ES = A..E (Allées, ES, Rails, SA, Secteur EEG)
    # Bloc Nuit = F..G (Nuit, Date)
    # Bloc Cam = H..J (Secteur Cam, Allées, Caméras)
    ws.merge_range(1, 0, 1, 4, "Phasage étiquettes et rails", fmt_subtitle_es)
    ws.merge_range(1, 5, 1, 6, "Nuit", fmt_subtitle_nuit)
    ws.merge_range(1, 7, 1, 9, "Phasage caméras", fmt_subtitle_cam)
    # Row 2 : en-têtes de colonnes
    headers = ["Allées", "ES", "Rails ES", "SA", "Secteur/Rayon",
               "Nuit", "Date",
               "Secteur/Rayon", "Allées", "Caméras"]
    for ci, h in enumerate(headers):
        ws.write(2, ci, h, fmt_lbl)

    # Couleurs FIXES par position dans la semaine (récupérées du Phasage ES)
    phasage_full_obj = _normalize_phasage(d.get("phasage"))
    weeks_full = phasage_full_obj["es"].get("weeks") or []

    # Pas de bg_color blanc explicite sur Date / SR — la CF colore tout (sauf Nuit)
    fmt_date_cell = workbook.add_format({"border": 1, "align": "center", "num_format": "dd/mm/yyyy"})
    fmt_sr_cell = workbook.add_format({"border": 1, "align": "left", "text_wrap": True, "font_size": 9})
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
        # Secteur/Rayon EEG (col E)
        sr_list_es = sr_by_nuit_es.get(n) or []
        ws.write_string(r, 4, _format_sr_grouped(sr_list_es), fmt_sr_cell)
        # Nuit (col F, BLANCHE par fmt_nuit)
        ws.write_number(r, 5, n, fmt_nuit)
        # Date (col G)
        date_iso = dates_map.get(str(n))
        if date_iso:
            try:
                from datetime import datetime as _dt
                ws.write_datetime(r, 6, _dt.strptime(date_iso, "%Y-%m-%d").date(), fmt_date_cell)
            except Exception:
                ws.write_string(r, 6, date_iso, fmt_date_cell)
        else:
            ws.write_blank(r, 6, None, fmt_date_cell)
        # Secteur/Rayon Cam (col H)
        sr_list_cam = sr_by_nuit_cam.get(n) or []
        ws.write_string(r, 7, _format_sr_grouped(sr_list_cam), fmt_sr_cell)
        # Bloc Cam (cols I-J)
        if info["cam_allees"]:
            ws.write_string(r, 8, ", ".join(info["cam_allees"]), fmt_text)
            ws.write_number(r, 9, round(info["cam"]), fmt_num)
        else:
            for c in range(8, 10):
                ws.write_blank(r, c, None, fmt_num)
        r += 1
    last_excel = r

    # Ligne TOTAL
    if r > 3:
        ws.write(r, 0, "", fmt_total_lbl)
        ws.write_formula(r, 1, f"=SUM(B{first_excel}:B{last_excel})", fmt_total_row)
        ws.write_formula(r, 2, f"=SUM(C{first_excel}:C{last_excel})", fmt_total_row)
        ws.write_formula(r, 3, f"=SUM(D{first_excel}:D{last_excel})", fmt_total_row)
        ws.write(r, 4, "", fmt_total_lbl)  # Secteur EEG
        ws.write_formula(r, 5, f'=COUNTA(F{first_excel}:F{last_excel})&" nuits"', fmt_total_lbl)
        ws.write(r, 6, "", fmt_total_lbl)
        ws.write(r, 7, "", fmt_total_lbl)  # Secteur Cam
        ws.write(r, 8, "", fmt_total_lbl)
        ws.write_formula(r, 9, f"=SUM(J{first_excel}:J{last_excel})", fmt_total_row)

        # Mise en forme conditionnelle par nuit : colore TOUTES les colonnes
        # SAUF la Nuit (col F), conformément à la demande du 06/02/2026.
        for night_num in range(1, max(sorted_nuits) + 1):
            color = night_color_hex(night_num, weeks_full)
            fmt_night = workbook.add_format({"bg_color": color, "border": 1})
            # A:E (cols 0..4) — bloc ES + Secteur EEG
            ws.conditional_format(3, 0, last_excel - 1, 4,
                {"type": "formula",
                 "criteria": f'=$F4={night_num}',
                 "format": fmt_night})
            # G (col 6) — Date seule (skip Nuit en col F)
            ws.conditional_format(3, 6, last_excel - 1, 6,
                {"type": "formula",
                 "criteria": f'=$F4={night_num}',
                 "format": fmt_night})
            # H:J (cols 7..9) — Secteur Cam + Allées Cam + Caméras
            ws.conditional_format(3, 7, last_excel - 1, 9,
                {"type": "formula",
                 "criteria": f'=$F4={night_num}',
                 "format": fmt_night})

    ws.freeze_panes(3, 0)


def _write_code_couleur_sheet(workbook, writer, d):
    """Feuille "Tableau date" : pour chaque nuit du planning ES, affiche
        Date (saisie manuelle) / EEG (auto) / Caméra (auto) / SA (info, italique).
    Couleurs récurrentes bleu/jaune/rouge/vert selon position dans la semaine.
    Layout : 1 colonne par nuit, 4 lignes (Date / EEG / Caméra / SA) + une colonne
    « Libellé » à gauche. Limite à 16 nuits par ligne pour rester lisible.
    """
    phasage_full = _normalize_phasage(d.get("phasage"))
    es = phasage_full.get("es", {})
    cam = phasage_full.get("cam", {})
    nb_es = int(es.get("nb_nuits") or 0)
    nb_cam = int(cam.get("nb_nuits") or 0)
    start_at = int(cam.get("start_at_nuit") or (nb_es + 1))
    weeks_list = es.get("weeks") or []
    dates_map = phasage_full.get("dates") or {}

    # Calcule totaux EEG / Cam / SA par nuit (même logique que TableauDateTab JS)
    summary = compute_phasage_summary(d)
    store_mode = summary.get("store_mode") or "magasin_1"
    is_mag2 = store_mode == "magasin_2"
    idx_allee = {str(a.get("uid") or a["allee"]): a for a in summary["allees"]}
    seasonal_idx = {z["id"]: z for z in (summary.get("seasonal_zones") or [])}
    totals_by_nuit: dict[int, dict] = {}
    for r in es.get("rows") or []:
        n = r.get("nuit")
        if not n: continue
        a_uid = str(r.get("allee") or "").strip()
        node = idx_allee.get(a_uid)
        zone = seasonal_idx.get(a_uid)
        t = totals_by_nuit.setdefault(int(n), {"eeg": 0, "cam": 0, "sa": 0})
        if zone:
            t["eeg"] += zone.get("eeg") or 0
        elif node:
            base = (node.get("es_15") or 0) + (node.get("es_21") or 0)
            bonus = 0 if is_mag2 else ((node.get("es_15_bonus_noir") or 0) + (node.get("es_15_bonus_blanc") or 0))
            sa15 = (node.get("sa_15") or 0) if is_mag2 else 0
            t["eeg"] += base + bonus + sa15
            t["sa"] += (node.get("sa_21") or 0) if is_mag2 else (node.get("sa") or 0)
    for r in cam.get("rows") or []:
        n = r.get("nuit")
        if not n: continue
        a_uid = str(r.get("allee") or "").strip()
        node = idx_allee.get(a_uid)
        if not node: continue
        gn = start_at + int(n) - 1
        t = totals_by_nuit.setdefault(gn, {"eeg": 0, "cam": 0, "sa": 0})
        t["cam"] += node.get("cameras") or 0

    ws = workbook.add_worksheet("Tableau date")
    writer.sheets["Tableau date"] = ws

    fmt_title = workbook.add_format({
        "bold": True, "font_size": 16, "align": "center", "valign": "vcenter",
        "bg_color": "#1F2937", "font_color": "white", "border": 1,
    })
    fmt_sub = workbook.add_format({
        "italic": True, "align": "left", "valign": "vcenter",
        "bg_color": "#F3F4F6", "font_color": "#6B7280", "font_size": 10,
    })
    fmt_lbl_left = workbook.add_format({
        "bold": True, "align": "left", "valign": "vcenter", "border": 1,
        "bg_color": "#F9FAFB", "font_size": 11, "font_color": "#374151",
    })
    fmt_lbl_left_italic = workbook.add_format({
        "bold": True, "italic": True, "align": "left", "valign": "vcenter", "border": 1,
        "bg_color": "#F9FAFB", "font_size": 11, "font_color": "#6B7280",
    })
    fmt_date_iso = workbook.add_format({"num_format": "dd/mm/yyyy"})

    # Construit la liste de toutes les nuits à afficher
    all_nights: list[int] = list(range(1, nb_es + 1))
    for n in range(1, nb_cam + 1):
        gn = start_at + n - 1
        if gn not in all_nights:
            all_nights.append(gn)
    all_nights.sort()
    if not all_nights:
        ws.write(0, 0, "Aucune nuit configurée", fmt_sub)
        return

    total = len(all_nights)
    cols_per_row = 16
    LABEL_COL_WIDTH = 12
    CELL_W = 14

    # Largeurs
    ws.set_column(0, 0, LABEL_COL_WIDTH)
    ws.set_column(1, cols_per_row, CELL_W)

    ws.merge_range(0, 0, 0, min(cols_per_row, total), "Tableau date", fmt_title)
    ws.set_row(0, 30)
    ws.merge_range(1, 0, 1, min(cols_per_row, total),
                   f"{total} nuits · récurrence couleurs : bleu (pos 1) / jaune (2) / rouge (3) / vert (4)",
                   fmt_sub)

    LABELS = [
        ("Date", False),
        ("EEG", False),
        ("Caméra", False),
        ("SA", True),  # italique : info
    ]
    BLOCK_HEIGHT = 5  # 1 header + 4 rows + 1 separator
    ROW_HEADER_OFFSET = 3

    for chunk_idx, chunk_start in enumerate(range(0, total, cols_per_row)):
        chunk = all_nights[chunk_start:chunk_start + cols_per_row]
        base_row = ROW_HEADER_OFFSET + chunk_idx * BLOCK_HEIGHT
        # Ligne d'en-tête (Nuit n)
        ws.write(base_row, 0, "", fmt_lbl_left)
        for i, n in enumerate(chunk):
            color = night_color_hex(n, weeks_list)
            fmt_h = workbook.add_format({
                "bg_color": color, "border": 1, "align": "center", "valign": "vcenter",
                "font_size": 12, "bold": True, "font_color": "#111827",
            })
            ws.write(base_row, i + 1, f"Nuit {n}", fmt_h)
        ws.set_row(base_row, 24)
        # 4 lignes : Date / EEG / Caméra / SA
        for li, (label, italic) in enumerate(LABELS):
            row = base_row + 1 + li
            ws.write(row, 0, label, fmt_lbl_left_italic if italic else fmt_lbl_left)
            for i, n in enumerate(chunk):
                color = night_color_hex(n, weeks_list)
                base_fmt = {
                    "bg_color": color, "border": 1,
                    "align": "center", "valign": "vcenter", "font_size": 11,
                }
                if italic:
                    base_fmt["italic"] = True
                    base_fmt["font_color"] = "#6B7280"
                t = totals_by_nuit.get(n, {"eeg": 0, "cam": 0, "sa": 0})
                if label == "Date":
                    date_iso = dates_map.get(str(n))
                    if date_iso:
                        try:
                            from datetime import datetime as _dt
                            dval = _dt.strptime(date_iso, "%Y-%m-%d").date()
                            f = workbook.add_format({**base_fmt, "num_format": "dd/mm/yyyy"})
                            ws.write_datetime(row, i + 1, dval, f)
                        except Exception:
                            f = workbook.add_format(base_fmt)
                            ws.write(row, i + 1, date_iso, f)
                    else:
                        f = workbook.add_format(base_fmt)
                        ws.write(row, i + 1, "", f)
                elif label == "EEG":
                    f = workbook.add_format({**base_fmt, "bold": True})
                    ws.write_number(row, i + 1, int(t["eeg"]), f)
                elif label == "Caméra":
                    f = workbook.add_format(base_fmt)
                    ws.write_number(row, i + 1, int(t["cam"]), f)
                else:  # SA
                    f = workbook.add_format(base_fmt)
                    ws.write_number(row, i + 1, int(t["sa"]), f)
            ws.set_row(row, 22)

    # ---- Tableaux PAR SEMAINE (ajout 12/06/2026) ----
    # Pour chaque semaine définie dans weeks_list, on génère un sous-tableau
    # identique au global mais limité aux nuits de cette semaine. Si aucune
    # semaine n'est définie (weeks_list vide), on saute cette section.
    if weeks_list and len(weeks_list) > 0:
        # Calcule la dernière ligne utilisée par les blocs globaux
        nb_global_chunks = (total + cols_per_row - 1) // cols_per_row
        cur_row = ROW_HEADER_OFFSET + nb_global_chunks * BLOCK_HEIGHT + 2

        # Sépare les nuits par semaine selon la liste weeks_list (= nb nuits / sem)
        nuit_cursor = 1
        for wi, w in enumerate(weeks_list):
            ww = int(w or 0)
            if ww <= 0:
                continue
            week_nights = list(range(nuit_cursor, nuit_cursor + ww))
            nuit_cursor += ww
            # Garde uniquement les nuits réellement présentes (1..nb_es)
            week_nights = [n for n in week_nights if n in totals_by_nuit or n in all_nights]
            if not week_nights:
                continue

            # Titre de la semaine
            week_end_col = min(cols_per_row, len(week_nights))
            ws.merge_range(cur_row, 0, cur_row, week_end_col,
                           f"Semaine {wi + 1} — Nuits {week_nights[0]} à {week_nights[-1]}",
                           fmt_title)
            ws.set_row(cur_row, 26)
            cur_row += 1
            ws.merge_range(cur_row, 0, cur_row, week_end_col,
                           f"{len(week_nights)} nuit(s) · couleurs par position dans la semaine",
                           fmt_sub)
            cur_row += 2  # espace

            # Pour les semaines longues (>16 nuits), on chunke aussi
            for chunk_start in range(0, len(week_nights), cols_per_row):
                chunk = week_nights[chunk_start:chunk_start + cols_per_row]
                base_row = cur_row
                ws.write(base_row, 0, "", fmt_lbl_left)
                for i, n in enumerate(chunk):
                    color = night_color_hex(n, weeks_list)
                    fmt_h = workbook.add_format({
                        "bg_color": color, "border": 1, "align": "center", "valign": "vcenter",
                        "font_size": 12, "bold": True, "font_color": "#111827",
                    })
                    ws.write(base_row, i + 1, f"Nuit {n}", fmt_h)
                ws.set_row(base_row, 24)
                for li, (label, italic) in enumerate(LABELS):
                    row = base_row + 1 + li
                    ws.write(row, 0, label, fmt_lbl_left_italic if italic else fmt_lbl_left)
                    for i, n in enumerate(chunk):
                        color = night_color_hex(n, weeks_list)
                        base_fmt = {"bg_color": color, "border": 1, "align": "center",
                                    "valign": "vcenter", "font_size": 11}
                        if italic:
                            base_fmt["italic"] = True
                            base_fmt["font_color"] = "#6B7280"
                        t = totals_by_nuit.get(n, {"eeg": 0, "cam": 0, "sa": 0})
                        if label == "Date":
                            date_iso = dates_map.get(str(n))
                            if date_iso:
                                try:
                                    from datetime import datetime as _dt
                                    dval = _dt.strptime(date_iso, "%Y-%m-%d").date()
                                    f = workbook.add_format({**base_fmt, "num_format": "dd/mm/yyyy"})
                                    ws.write_datetime(row, i + 1, dval, f)
                                except Exception:
                                    f = workbook.add_format(base_fmt)
                                    ws.write(row, i + 1, date_iso, f)
                            else:
                                f = workbook.add_format(base_fmt)
                                ws.write(row, i + 1, "", f)
                        elif label == "EEG":
                            f = workbook.add_format({**base_fmt, "bold": True})
                            ws.write_number(row, i + 1, int(t["eeg"]), f)
                        elif label == "Caméra":
                            f = workbook.add_format(base_fmt)
                            ws.write_number(row, i + 1, int(t["cam"]), f)
                        else:
                            f = workbook.add_format(base_fmt)
                            ws.write_number(row, i + 1, int(t["sa"]), f)
                    ws.set_row(row, 22)
                cur_row = base_row + BLOCK_HEIGHT
            cur_row += 2  # espace entre semaines

    # Free the unused fmt_date_iso (silence linter)
    _ = fmt_date_iso


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
async def export_excel(upload_id: str, sheet: str = "all", current_user: dict = Depends(get_current_user)):
    """Exporte le fichier Excel généré.

    sheet : 'all' | 'raw' | 'recap' | 'secteur' | 'parsecteur' | 'comment'
    """
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    _check_export_refs(d)
    return await _build_export(d, sheet)


def _check_export_refs(d: dict) -> None:
    """Bloque l'export si une ou plusieurs lignes du recap n'ont pas de référence."""
    recap = _refresh_vcare_block(d.get("recap_rows") or [])
    recap = _refresh_batterie_software_block(recap)
    bad = _validate_missing_refs(recap)
    if bad:
        raise HTTPException(
            status_code=400,
            detail=(
                "Export bloqué : "
                f"{len(bad)} ligne(s) avec une référence invalide "
                "(vide ou non-numérique) — veuillez corriger la colonne "
                "Référence dans le tableau Commandes avant de relancer l'export. "
                "Les références doivent contenir uniquement des chiffres. "
                f"Désignations concernées : {', '.join(bad[:10])}"
                + (" ..." if len(bad) > 10 else "")
            ),
        )


async def _build_export(d: dict, sheet: str = "all"):
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
            # On recalcule TOUJOURS le bloc VCare pour appliquer les
            # règles VCare courantes sur les sessions existantes.
            recap = _refresh_vcare_block(d["recap_rows"])
            recap = _apply_total_moq_and_bonuses(recap)
            ws = workbook.add_worksheet("Commandes")
            writer.sheets["Commandes"] = ws
            fmt_section = workbook.add_format({
                "bold": True, "bg_color": "#DDEBF7", "border": 1,
                "font_size": 11, "align": "left",
            })
            headers = ["Type", "Réf.", "Désignation", "Total", "Spare", "Flèche", "Signalétique", "Saisonnier", "Total", "Total + MOQ"]
            for col_i, h in enumerate(headers):
                ws.write(0, col_i, h, fmt_header)
            for row_i, r in enumerate(recap, start=1):
                kind = r["kind"]
                if kind == "section":
                    # Séparateur de section sur fond bleu clair (cellule A → fusion sur 10 colonnes)
                    ws.merge_range(row_i, 0, row_i, 9, r.get("type", ""), fmt_section)
                    continue
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
                ws.write(row_i, 5, r.get("fleche", "") if r.get("fleche", "") != "" else "", fmt)
                ws.write(row_i, 6, r.get("signaletique", "") if r.get("signaletique", "") != "" else "", fmt)
                ws.write(row_i, 7, r.get("saisonnier", "") if r.get("saisonnier", "") != "" else "", fmt)
                ws.write(row_i, 8, r.get("total_plus_spare", "") if r.get("total_plus_spare", "") != "" else "", fmt)
                tm = r.get("total_moq", "")
                ws.write(row_i, 9, tm if tm not in ("", None) else "", fmt)
            # Largeurs serrées pour tenir dans une slide PPTX (10 colonnes)
            ws.set_column(0, 0, 7)    # Type
            ws.set_column(1, 1, 7)    # Réf.
            ws.set_column(2, 2, 28)   # Désignation
            ws.set_column(3, 3, 8)    # Total (qty)
            ws.set_column(4, 4, 7)    # Spare
            ws.set_column(5, 5, 7)    # Flèche
            ws.set_column(6, 6, 11)   # Signalétique
            ws.set_column(7, 7, 10)   # Saisonnier
            ws.set_column(8, 8, 8)    # Total (sum)
            ws.set_column(9, 9, 11)   # Total + MOQ
            if len(recap) > 0:
                ws.autofilter(0, 0, len(recap), 9)
                ws.freeze_panes(1, 0)

        if sheet in ("all", "parsecteur"):
            _write_par_secteur_sheets(workbook, writer, d, fmt_header, fmt_cell, fmt_total, fmt_inclineur)

        # Feuille "Tableau phasage" supprimée (demande utilisateur 04/06/2026) :
        # les données restent disponibles dans la feuille "Recap par secteur" (rayon)
        # qui couvre les mêmes informations de comptage.

        if sheet in ("all", "phasage"):
            _write_phasage_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

        if sheet in ("all", "phasage_cam"):
            _write_phasage_cam_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

        if sheet in ("all", "phasage_full"):
            _write_phasage_full_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

        if sheet in ("all", "suivi"):
            _write_suivi_sheet(workbook, writer, d, fmt_header, fmt_cell, fmt_total)

        if sheet in ("all", "code_couleur"):
            _write_code_couleur_sheet(workbook, writer, d)

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


# =============================================================================
# Export "Carrefour" — fichier Excel à 5 onglets, simplifié pour transmission
# au client Carrefour. Reprend les tableaux récap des onglets phasage déjà
# présents dans l'app, mais en VERSION STATIQUE (pas de formules ni de listes
# déroulantes) pour que le destinataire puisse lire sans risque de manip.
# =============================================================================

@api_router.get("/export-carrefour/{upload_id}")
async def export_carrefour(upload_id: str, current_user: dict = Depends(get_current_user)):
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    _check_export_refs(d)
    await log_audit(upload_id, current_user, "carrefour_export_downloaded")
    return await _build_carrefour_export(d)


@api_router.get("/export-pptx/{upload_id}")
async def export_pptx(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Export PowerPoint complet à partir du template `cr_vt_template.pptx`.
    Remplit les slides 8, 11-20 avec les données de la session. Les slides
    1-7, 9 et 10 restent inchangées."""
    from pathlib import Path
    import pptx_export
    d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    _check_export_refs(d)

    def _abbr_rayon(name: str) -> str:
        """Abrège un nom de rayon de plus de 8 caractères : on garde les 6
        premiers caractères + « . », tout en préservant un éventuel
        suffixe numérique en fin de chaîne (pour ne pas confondre
        « Zone saisonnier 1/2/3 » → « Zone s. 1/2/3 »).

        Ex: "Conserves" -> "Conser.", "Boulangerie" -> "Boulan.",
            "Zone saisonnier 2" -> "Zone s. 2".
        """
        import re as _re
        name = (name or "").strip()
        if len(name) <= 8:
            return name
        # Sépare un éventuel suffixe numérique en fin (avec espaces autour)
        m = _re.match(r"^(.*?)(\s+\d+)\s*$", name)
        if m:
            base, num = m.group(1).strip(), m.group(2).strip()
            if len(base) <= 6:
                return f"{base} {num}"
            return f"{base[:6].rstrip()}. {num}"
        return name[:6].rstrip() + "."

    def _compress_sr_list(sr_list: list[str]) -> str:
        """Regroupe les paires `Secteur:Rayon` par secteur et abrège les
        noms de rayons longs (> 8 caractères) pour gagner de la place
        dans le PPTX. Ex: ["NAL:Conserves", "NAL:Liquides", "PGC:Épicerie"]
        -> "NAL : Conser., Liquides | PGC : Épicer.".
        """
        if not sr_list:
            return ""
        # Préserve l'ordre d'apparition des secteurs ET des rayons
        from collections import OrderedDict
        groups: "OrderedDict[str, list[str]]" = OrderedDict()
        for item in sr_list:
            if ":" in item:
                sec, ray = item.split(":", 1)
                sec, ray = sec.strip(), ray.strip()
            else:
                sec, ray = item.strip(), ""
            if sec not in groups:
                groups[sec] = []
            ray_abbr = _abbr_rayon(ray) if ray else ""
            if ray_abbr and ray_abbr not in groups[sec]:
                groups[sec].append(ray_abbr)
        parts = []
        for sec, rays in groups.items():
            if rays:
                parts.append(f"{sec} : {', '.join(rays)}")
            else:
                parts.append(sec)
        return " | ".join(parts)

    def _adapter(doc):
        """Convertit `_aggregate_phasage_for_export` au format attendu par pptx_export."""
        a = _aggregate_phasage_for_export(doc)
        summary = compute_phasage_summary(doc)
        # Format nuit_es : flatten allees + sr en chaînes
        nuit_es = {}
        for n, b in (a.get("es_per_nuit") or {}).items():
            nuit_es[int(n)] = {
                "date": (a.get("dates") or {}).get(str(n)),
                "sr": _compress_sr_list(b.get("secteurs_rayons") or []),
                "allees_str": ", ".join(str(x) for x in (b.get("allees") or [])),
                "eeg": b.get("es", 0),
                "rails_es": b.get("rails_es", 0),
                "sa": b.get("sa", 0),
                "cam": (a.get("cam_per_nuit") or {}).get(int(n), {}).get("cam", 0),
            }
        nuit_cam = {}
        for n, b in (a.get("cam_per_nuit") or {}).items():
            nuit_cam[int(n)] = {
                "date": (a.get("dates") or {}).get(str(n)),
                "sr": _compress_sr_list(b.get("secteurs_rayons") or []),
                "allees_str": ", ".join(str(x) for x in (b.get("allees") or [])),
                "cam": b.get("cam", 0),
            }
        # totals_by_nuit pour Tableau date
        totals_by_nuit = {}
        for n in set(nuit_es.keys()) | set(nuit_cam.keys()):
            totals_by_nuit[n] = {
                "eeg": nuit_es.get(n, {}).get("eeg", 0),
                "cam": nuit_cam.get(n, {}).get("cam", 0),
                "sa":  nuit_es.get(n, {}).get("sa",  0),
            }
        all_nights = sorted(set(nuit_es.keys()) | set(nuit_cam.keys()))
        cam_nights = sorted(nuit_cam.keys())
        return {
            "nuit_es": nuit_es,
            "nuit_cam": nuit_cam,
            "totals_by_nuit": totals_by_nuit,
            "dates_map": a.get("dates") or {},
            "weeks": a.get("weeks_es") or [],
            "all_nights": all_nights,
            "cam_nights": cam_nights,
        }

    # Détail caméras par allée
    summary = compute_phasage_summary(d)
    detail_rows: list[tuple[str, str]] = []
    for a in summary.get("allees", []):
        elems = a.get("camera_elems") or []
        if elems:
            label = _allee_display_label(a)
            detail_rows.append((label, ", ".join(str(e) for e in elems)))
    detail_rows.sort(key=lambda x: (0, int(x[0]) if x[0].isdigit() else 999, x[0]))

    # Recap rows à jour (avec VCare recalculé)
    recap = _refresh_vcare_block(d.get("recap_rows") or [])
    recap = _apply_total_moq_and_bonuses(recap)

    try:
        # build_pptx est CPU-bound (parse + écrit un .pptx de ~38 Mo) → on l'exécute
        # dans un threadpool pour ne pas bloquer la boucle event de FastAPI.
        # Sinon les requêtes concurrentes (d'autres utilisateurs) sont mises en
        # attente et Cloudflare ferme la connexion (erreur 520).
        from starlette.concurrency import run_in_threadpool
        from functools import partial
        data = await run_in_threadpool(
            partial(pptx_export.build_pptx, d,
                    aggregate_fn=_adapter, recap_rows=recap,
                    summary=summary, detail_cam_rows=detail_rows),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("PPTX export failed")
        raise HTTPException(status_code=500, detail=f"Erreur PowerPoint : {e}")

    await log_audit(upload_id, current_user, "pptx_export_downloaded")
    base = Path(d["filename"]).stem
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{base}_CR_VT.pptx"'},
    )


def _aggregate_phasage_for_export(d: dict) -> dict:
    """Agrégation par nuit pour les onglets de l'export Carrefour.

    Retourne :
      {
        "es_per_nuit": {n: {"allees": [...], "es":..., "rails_es":..., "sa":...,
                            "secteurs_rayons": [...]}},
        "cam_per_nuit": {n_global: {"allees": [...], "cam":...,
                                    "secteurs_rayons": [...],
                                    "cam_elems_by_allee": {label: [el, ...]}}},
        "weeks_es": [...],
        "nb_nuits_es": int,
        "nb_nuits_cam": int,
        "cam_start_at": int,
        "dates": {str(n): iso},
        "totals_es": {"es":..., "rails_es":..., "sa":...},
        "totals_cam": {"cam":...},
      }
    """
    summary = compute_phasage_summary(d)
    phasage = _normalize_phasage(d.get("phasage"))
    es_plan = phasage.get("es", {})
    cam_plan = phasage.get("cam", {})
    dates = phasage.get("dates") or {}

    nb_es = int(es_plan.get("nb_nuits") or 0)
    nb_cam = int(cam_plan.get("nb_nuits") or 0)
    cam_start_at = int(cam_plan.get("start_at_nuit") or 5)
    weeks_es = es_plan.get("weeks") or []

    # Index complet (allées + zones saisonnières avec EEG comptabilisé en es_21)
    idx = _full_allee_index(summary)

    def _lbl(a_uid: str, node: dict) -> str:
        if node.get("is_seasonal"):
            return str(a_uid)
        num = str(node.get("allee") or "").strip()
        if node.get("is_dup"):
            return f"{num}-{node.get('dup_index', 1)}"
        return num

    def _sr_key(node: dict) -> str:
        sec = (node.get("secteur") or "").strip()
        ray = (node.get("rayon") or "").strip()
        if not sec and not ray:
            return ""
        return f"{sec}{':' + ray if ray else ''}"

    es_per_nuit: dict[int, dict] = {}
    for r in es_plan.get("rows") or []:
        a_uid = str(r.get("allee") or "").strip()
        n = r.get("nuit")
        if not n or not a_uid:
            continue
        node = _resolve_idx_node(a_uid, idx)
        if not node:
            continue
        gn = int(n)
        b = es_per_nuit.setdefault(gn, {
            "allees": [], "es": 0, "rails_es": 0, "sa": 0, "secteurs_rayons": [],
        })
        b["allees"].append(_lbl(a_uid, node))
        # EEG par nuit = ES (1.5+2.1) + bonus rails (sur ES 1.5) + flèches.
        # Aligné sur l'affichage frontend du Phasage de pose (magasin_1).
        b["es"] += float(node.get("es_15") or 0) + float(node.get("es_21") or 0)
        b["es"] += float(node.get("es_15_bonus_noir") or 0) + float(node.get("es_15_bonus_blanc") or 0)
        b["es"] += float(node.get("fleches") or 0)
        b["rails_es"] += float(node.get("rails_es") or 0)
        b["sa"] += float(node.get("sa") or 0)
        sr = _sr_key(node)
        if sr and sr not in b["secteurs_rayons"]:
            b["secteurs_rayons"].append(sr)

    cam_per_nuit: dict[int, dict] = {}
    for r in cam_plan.get("rows") or []:
        a_uid = str(r.get("allee") or "").strip()
        n = r.get("nuit")
        if not n or not a_uid:
            continue
        node = _resolve_idx_node(a_uid, idx)
        if not node:
            continue
        gn = cam_start_at + int(n) - 1
        b = cam_per_nuit.setdefault(gn, {
            "allees": [], "cam": 0, "secteurs_rayons": [], "cam_elems_by_allee": {},
        })
        lbl = _lbl(a_uid, node)
        b["allees"].append(lbl)
        b["cam"] += float(node.get("cameras") or 0)
        sr = _sr_key(node)
        if sr and sr not in b["secteurs_rayons"]:
            b["secteurs_rayons"].append(sr)
        elems = node.get("camera_elems") or []
        if elems:
            b["cam_elems_by_allee"][lbl] = list(elems)

    return {
        "summary": summary,
        "es_per_nuit": es_per_nuit,
        "cam_per_nuit": cam_per_nuit,
        "weeks_es": weeks_es,
        "nb_nuits_es": nb_es,
        "nb_nuits_cam": nb_cam,
        "cam_start_at": cam_start_at,
        "dates": dates,
        "totals_es": {
            "es": sum(b["es"] for b in es_per_nuit.values()),
            "rails_es": sum(b["rails_es"] for b in es_per_nuit.values()),
            "sa": sum(b["sa"] for b in es_per_nuit.values()),
        },
        "totals_cam": {"cam": sum(b["cam"] for b in cam_per_nuit.values())},
    }


async def _build_carrefour_export(d: dict):
    """5 onglets :
       1. Commandes  (recap_rows)
       2. Récap EEG par nuit
       3. Récap caméra par nuit
       4. Caméra par élément
       5. Récap complet (EEG + Cam par nuit)
    """
    output = io.BytesIO()
    agg = _aggregate_phasage_for_export(d)

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book

        # Formats communs
        fmt_h = wb.add_format({
            "bold": True, "bg_color": "#056839", "font_color": "white",
            "border": 1, "align": "center", "valign": "vcenter",
        })
        fmt_h_eeg = wb.add_format({
            "bold": True, "bg_color": "#9BD9B5", "font_color": "#064E3B",
            "border": 1, "align": "center",
        })
        fmt_h_cam = wb.add_format({
            "bold": True, "bg_color": "#E5D6FF", "font_color": "#4C1D95",
            "border": 1, "align": "center",
        })
        fmt_lbl = wb.add_format({"bold": True, "bg_color": "#F3F4F6",
                                 "border": 1, "align": "left"})
        fmt_cell = wb.add_format({"border": 1, "align": "left"})
        fmt_num = wb.add_format({"border": 1, "align": "right"})
        fmt_total = wb.add_format({"bold": True, "bg_color": "#FEF3C7",
                                   "border": 1, "align": "left"})
        fmt_total_n = wb.add_format({"bold": True, "bg_color": "#FEF3C7",
                                     "border": 1, "align": "right"})
        fmt_total_lbl = wb.add_format({"bold": True, "bg_color": "#FEF3C7",
                                       "border": 1, "align": "center"})
        fmt_inclineur = wb.add_format({"bold": True, "bg_color": "#DBEAFE",
                                       "border": 1})
        fmt_date = wb.add_format({"border": 1, "align": "center",
                                  "num_format": "dd/mm/yyyy"})

        # On précompile les couleurs par nuit (déclinaisons left/centre/right)
        def make_palette(n_max: int, weeks: list | None) -> dict:
            out = {}
            for n in range(1, n_max + 1):
                color = night_color_hex(int(n), weeks)
                out[n] = {
                    "right": wb.add_format({"bg_color": color, "border": 1, "align": "right"}),
                    "right_b": wb.add_format({"bg_color": color, "border": 1, "align": "right", "bold": True}),
                    "left": wb.add_format({"bg_color": color, "border": 1, "align": "left"}),
                    "center": wb.add_format({"bg_color": color, "border": 1, "align": "center", "bold": True}),
                    "date": wb.add_format({"bg_color": color, "border": 1, "align": "center", "num_format": "dd/mm/yyyy"}),
                    "sr": wb.add_format({"bg_color": color, "border": 1, "align": "left",
                                         "font_size": 9, "text_wrap": True}),
                }
            return out

        weeks_es = agg["weeks_es"]
        n_es = agg["nb_nuits_es"]
        n_cam = agg["nb_nuits_cam"]
        cam_start = agg["cam_start_at"]
        # Palettes — pour Cam le n_global commence à cam_start ; on stocke par
        # nuit globale + on calcule la couleur sur la position absolue (pas semaines)
        es_palette = make_palette(n_es, weeks_es) if n_es else {}
        cam_palette: dict[int, dict] = {}
        for i in range(n_cam):
            gn = cam_start + i
            color = night_color_hex(i + 1, None)  # pas de semaines côté cam
            cam_palette[gn] = {
                "right": wb.add_format({"bg_color": color, "border": 1, "align": "right"}),
                "right_b": wb.add_format({"bg_color": color, "border": 1, "align": "right", "bold": True}),
                "left": wb.add_format({"bg_color": color, "border": 1, "align": "left"}),
                "center": wb.add_format({"bg_color": color, "border": 1, "align": "center", "bold": True}),
                "date": wb.add_format({"bg_color": color, "border": 1, "align": "center", "num_format": "dd/mm/yyyy"}),
                "sr": wb.add_format({"bg_color": color, "border": 1, "align": "left",
                                     "font_size": 9, "text_wrap": True}),
            }

        # ===== 1. Commandes =====
        # On recalcule TOUJOURS le bloc VCare pour appliquer les règles
        # courantes (les VCare persistés peuvent être obsolètes).
        recap = _refresh_vcare_block(d.get("recap_rows") or [])
        recap = _apply_total_moq_and_bonuses(recap)
        ws = wb.add_worksheet("Commandes")
        writer.sheets["Commandes"] = ws
        fmt_section_cf = wb.add_format({
            "bold": True, "bg_color": "#DDEBF7", "border": 1,
            "font_size": 11, "align": "left",
        })
        headers = ["Type", "Réf.", "Désignation", "Total", "Spare", "Flèche", "Signalétique", "Saisonnier", "Total", "Total + MOQ"]
        for ci, h in enumerate(headers):
            ws.write(0, ci, h, fmt_h)
        for ri, r in enumerate(recap, start=1):
            kind = r.get("kind")
            if kind == "section":
                ws.merge_range(ri, 0, ri, 9, r.get("type", ""), fmt_section_cf)
                continue
            if kind == "header":
                f = fmt_total
            elif kind == "inclineur":
                f = fmt_inclineur
            else:
                f = wb.add_format({"border": 1})
            ws.write(ri, 0, r.get("type", ""), f)
            ws.write(ri, 1, r.get("reference", ""), f)
            ws.write(ri, 2, r.get("designation", ""), f)
            ws.write(ri, 3, r.get("quantite", "") if r.get("quantite", "") != "" else "", f)
            ws.write(ri, 4, r.get("spare", "") if r.get("spare", "") != "" else "", f)
            ws.write(ri, 5, r.get("fleche", "") if r.get("fleche", "") != "" else "", f)
            ws.write(ri, 6, r.get("signaletique", "") if r.get("signaletique", "") != "" else "", f)
            ws.write(ri, 7, r.get("saisonnier", "") if r.get("saisonnier", "") != "" else "", f)
            ws.write(ri, 8, r.get("total_plus_spare", "") if r.get("total_plus_spare", "") != "" else "", f)
            tm = r.get("total_moq", "")
            ws.write(ri, 9, tm if tm not in ("", None) else "", f)
        # Largeurs serrées (cohérentes avec l'export RTR)
        ws.set_column(0, 0, 7)
        ws.set_column(1, 1, 7)
        ws.set_column(2, 2, 28)
        ws.set_column(3, 3, 8)
        ws.set_column(4, 4, 7)
        ws.set_column(5, 5, 7)
        ws.set_column(6, 6, 11)
        ws.set_column(7, 7, 10)
        ws.set_column(8, 8, 8)
        ws.set_column(9, 9, 11)
        if recap:
            ws.autofilter(0, 0, len(recap), 9)
            ws.freeze_panes(1, 0)

        # ===== 2. Récap EEG par nuit =====
        ws = wb.add_worksheet("Récap EEG par nuit")
        writer.sheets["Récap EEG par nuit"] = ws
        ws.merge_range(0, 0, 0, 5, "Récap EEG et rails par nuit", fmt_h)
        cols2 = ["Nuit", "Date", "Secteur/Rayon", "Allées", "EEG", "Rails ES"]
        widths2 = [10, 12, 28, 36, 12, 12]
        for ci, (h, w) in enumerate(zip(cols2, widths2)):
            ws.write(1, ci, h, fmt_lbl)
            ws.set_column(ci, ci, w)
        for i, n in enumerate(range(1, n_es + 1), start=0):
            row = 2 + i
            bucket = agg["es_per_nuit"].get(n, {})
            p = es_palette.get(n, {})
            ws.write(row, 0, f"Nuit {n}", p.get("center", fmt_cell))
            d_iso = agg["dates"].get(str(n))
            if d_iso:
                try:
                    ws.write_datetime(row, 1, datetime.strptime(d_iso, "%Y-%m-%d").date(),
                                      p.get("date", fmt_date))
                except Exception:
                    ws.write_string(row, 1, d_iso, p.get("date", fmt_date))
            else:
                ws.write_blank(row, 1, None, p.get("date", fmt_date))
            ws.write(row, 2, _format_sr_grouped(bucket.get("secteurs_rayons") or []),
                     p.get("sr", fmt_cell))
            ws.write(row, 3, ", ".join(str(a) for a in (bucket.get("allees") or [])),
                     p.get("left", fmt_cell))
            ws.write(row, 4, int(round(bucket.get("es") or 0)), p.get("right", fmt_num))
            ws.write(row, 5, int(round(bucket.get("rails_es") or 0)),
                     p.get("right", fmt_num))
        # TOTAL
        tot_row = 2 + n_es
        ws.write(tot_row, 0, "TOTAL", fmt_total_lbl)
        ws.write(tot_row, 1, f"{n_es} nuits", fmt_total_lbl)
        ws.write(tot_row, 2, "", fmt_total_lbl)
        n_allees_es = sum(len(b.get("allees") or []) for b in agg["es_per_nuit"].values())
        ws.write(tot_row, 3, f"{n_allees_es} allée{'s' if n_allees_es != 1 else ''}",
                 fmt_total_lbl)
        ws.write(tot_row, 4, int(round(agg["totals_es"]["es"])), fmt_total_n)
        ws.write(tot_row, 5, int(round(agg["totals_es"]["rails_es"])), fmt_total_n)
        ws.freeze_panes(2, 0)

        # ===== 3. Récap caméra par nuit =====
        ws = wb.add_worksheet("Récap caméra par nuit")
        writer.sheets["Récap caméra par nuit"] = ws
        ws.merge_range(0, 0, 0, 4, "Récap caméras par nuit", fmt_h)
        cols3 = ["Nuit", "Date", "Secteur/Rayon", "Allées", "Caméras"]
        widths3 = [10, 12, 28, 38, 14]
        for ci, (h, w) in enumerate(zip(cols3, widths3)):
            ws.write(1, ci, h, fmt_lbl)
            ws.set_column(ci, ci, w)
        cam_nights_sorted = sorted(agg["cam_per_nuit"].keys()) or list(range(cam_start, cam_start + n_cam))
        for i, n in enumerate(cam_nights_sorted, start=0):
            row = 2 + i
            bucket = agg["cam_per_nuit"].get(n, {})
            p = cam_palette.get(n, {})
            ws.write(row, 0, f"Nuit {n}", p.get("center", fmt_cell))
            d_iso = agg["dates"].get(str(n))
            if d_iso:
                try:
                    ws.write_datetime(row, 1, datetime.strptime(d_iso, "%Y-%m-%d").date(),
                                      p.get("date", fmt_date))
                except Exception:
                    ws.write_string(row, 1, d_iso, p.get("date", fmt_date))
            else:
                ws.write_blank(row, 1, None, p.get("date", fmt_date))
            ws.write(row, 2, _format_sr_grouped(bucket.get("secteurs_rayons") or []),
                     p.get("sr", fmt_cell))
            ws.write(row, 3, ", ".join(str(a) for a in (bucket.get("allees") or [])),
                     p.get("left", fmt_cell))
            ws.write(row, 4, int(round(bucket.get("cam") or 0)), p.get("right", fmt_num))
        tot_row = 2 + len(cam_nights_sorted)
        ws.write(tot_row, 0, "TOTAL", fmt_total_lbl)
        ws.write(tot_row, 1, f"{n_cam} nuits", fmt_total_lbl)
        ws.write(tot_row, 2, "", fmt_total_lbl)
        n_allees_cam = sum(len(b.get("allees") or []) for b in agg["cam_per_nuit"].values())
        ws.write(tot_row, 3, f"{n_allees_cam} allée{'s' if n_allees_cam != 1 else ''}",
                 fmt_total_lbl)
        ws.write(tot_row, 4, int(round(agg["totals_cam"]["cam"])), fmt_total_n)
        ws.freeze_panes(2, 0)

        # ===== 4. Caméra par élément =====
        ws = wb.add_worksheet("Caméra par élément")
        writer.sheets["Caméra par élément"] = ws
        ws.merge_range(0, 0, 0, 2, "Détail caméras par allée", fmt_h)
        for ci, h in enumerate(["N° Allée", "Nb caméras", "Éléments concernés"]):
            ws.write(1, ci, h, fmt_lbl)
        ws.set_column(0, 0, 12)
        ws.set_column(1, 1, 12)
        ws.set_column(2, 2, 80)
        # Aplatir : liste allées avec leurs éléments
        seen: dict[str, list] = {}
        for n in sorted(agg["cam_per_nuit"].keys()):
            b = agg["cam_per_nuit"][n]
            for lbl, elems in (b.get("cam_elems_by_allee") or {}).items():
                if lbl not in seen:
                    seen[lbl] = list(elems)
        row = 2
        fmt_text_wrap = wb.add_format({"border": 1, "align": "left", "text_wrap": True,
                                       "valign": "top"})
        fmt_lbl_b = wb.add_format({"border": 1, "align": "center", "bold": True})
        for lbl, elems in seen.items():
            ws.write(row, 0, str(lbl), fmt_lbl_b)
            ws.write(row, 1, len(elems), fmt_num)
            ws.write(row, 2, ", ".join(str(e) for e in elems), fmt_text_wrap)
            row += 1
        if seen:
            ws.write(row, 0, "TOTAL", fmt_total_lbl)
            ws.write(row, 1, sum(len(e) for e in seen.values()), fmt_total_n)
            ws.write(row, 2, f"{len(seen)} allée(s) avec caméras", fmt_total_lbl)
        ws.freeze_panes(2, 0)

        # ===== 5. Récap complet (EEG + Cam par nuit, juxtaposé) =====
        ws = wb.add_worksheet("Récap complet")
        writer.sheets["Récap complet"] = ws
        # En-têtes 2 lignes : bloc EEG | Nuit (blanc) | bloc Cam
        # Cols : 0 Allées EEG | 1 EEG | 2 Rails ES | 3 SA | 4 Sec EEG |
        #        5 Nuit (blanc) | 6 Date |
        #        7 Sec Cam | 8 Allées Cam | 9 Caméras
        ws.merge_range(0, 0, 0, 4, "Phasage étiquettes et rails", fmt_h_eeg)
        ws.merge_range(0, 5, 0, 6, "Nuit", fmt_h)
        ws.merge_range(0, 7, 0, 9, "Phasage caméras", fmt_h_cam)
        headers5 = ["Allées", "ES", "Rails ES", "SA", "Secteur/Rayon EEG",
                    "Nuit", "Date",
                    "Secteur/Rayon Cam", "Allées", "Caméras"]
        widths5 = [22, 10, 10, 10, 22, 8, 11, 22, 22, 12]
        for ci, (h, w) in enumerate(zip(headers5, widths5)):
            if ci in (5, 6):
                ws.write(1, ci, h, fmt_lbl)
            elif ci < 5:
                ws.write(1, ci, h, fmt_h_eeg)
            else:
                ws.write(1, ci, h, fmt_h_cam)
            ws.set_column(ci, ci, w)
        # Données : 1 ligne par nuit ES (1..n_es) ; bloc Cam rempli si nuit
        # correspondante existe dans cam_per_nuit
        for i, n in enumerate(range(1, n_es + 1), start=0):
            row = 2 + i
            es = agg["es_per_nuit"].get(n, {})
            cam = agg["cam_per_nuit"].get(n, {})
            p_es = es_palette.get(n, {})
            p_cam = cam_palette.get(n, p_es)
            # Bloc EEG
            ws.write(row, 0, ", ".join(str(a) for a in (es.get("allees") or [])),
                     p_es.get("left", fmt_cell))
            ws.write(row, 1, int(round(es.get("es") or 0)), p_es.get("right", fmt_num))
            ws.write(row, 2, int(round(es.get("rails_es") or 0)), p_es.get("right", fmt_num))
            ws.write(row, 3, int(round(es.get("sa") or 0)), p_es.get("right", fmt_num))
            ws.write(row, 4, _format_sr_grouped(es.get("secteurs_rayons") or []),
                     p_es.get("sr", fmt_cell))
            # Nuit (BLANCHE — seule colonne sans fond)
            ws.write(row, 5, f"{n}", wb.add_format({
                "border": 1, "align": "center", "bold": True, "bg_color": "#FFFFFF"
            }))
            # Date (colorée — on prend la couleur de la nuit globale)
            d_iso = agg["dates"].get(str(n))
            if d_iso:
                try:
                    ws.write_datetime(row, 6, datetime.strptime(d_iso, "%Y-%m-%d").date(),
                                      p_es.get("date", fmt_date))
                except Exception:
                    ws.write_string(row, 6, d_iso, p_es.get("date", fmt_date))
            else:
                ws.write_blank(row, 6, None, p_es.get("date", fmt_date))
            # Bloc Cam
            ws.write(row, 7, _format_sr_grouped(cam.get("secteurs_rayons") or []),
                     p_cam.get("sr", fmt_cell) if cam else fmt_cell)
            ws.write(row, 8, ", ".join(str(a) for a in (cam.get("allees") or [])),
                     p_cam.get("left", fmt_cell) if cam else fmt_cell)
            if cam.get("cam"):
                ws.write(row, 9, int(round(cam.get("cam") or 0)),
                         p_cam.get("right", fmt_num))
            else:
                ws.write_blank(row, 9, None, fmt_cell)

        # Ligne TOTAL
        tot_row = 2 + n_es
        ws.write(tot_row, 0, "", fmt_total_lbl)
        ws.write(tot_row, 1, int(round(agg["totals_es"]["es"])), fmt_total_n)
        ws.write(tot_row, 2, int(round(agg["totals_es"]["rails_es"])), fmt_total_n)
        ws.write(tot_row, 3, int(round(agg["totals_es"]["sa"])), fmt_total_n)
        ws.write(tot_row, 4, "", fmt_total_lbl)
        ws.write(tot_row, 5, f"{n_es} nuits", wb.add_format({
            "border": 1, "align": "center", "bold": True, "bg_color": "#FFFFFF"
        }))
        ws.write(tot_row, 6, "", fmt_total_lbl)
        ws.write(tot_row, 7, "", fmt_total_lbl)
        ws.write(tot_row, 8, f"{n_cam} nuits cam", fmt_total_lbl)
        ws.write(tot_row, 9, int(round(agg["totals_cam"]["cam"])), fmt_total_n)
        ws.freeze_panes(2, 0)

        # ===== 6. Recap par secteur (24/06/2026) =====
        # Mêmes 2 feuilles que dans l'export RTR, basées sur les raw_records.
        try:
            _write_par_secteur_sheets(wb, writer, d, fmt_h, fmt_cell, fmt_total, fmt_inclineur)
        except Exception as e:
            logger.warning(f"Recap par secteur (Carrefour) failed: {e}")

    output.seek(0)
    filename = f"{Path(d['filename']).stem}_Carrefour.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


api_router.include_router(build_auth_router(db))
app.include_router(api_router)

# CORS : on doit autoriser explicitement l'origin frontend (FRONTEND_URL) car
# allow_credentials=True est incompatible avec allow_origins=["*"]
_frontend_url = os.environ.get('FRONTEND_URL', '').strip()
_cors_origins = os.environ.get('CORS_ORIGINS', '*').split(',')
if _frontend_url and _frontend_url not in _cors_origins:
    _cors_origins = [_frontend_url] + [o for o in _cors_origins if o and o != '*']
if not _cors_origins or _cors_origins == ['*']:
    _cors_origins = [_frontend_url] if _frontend_url else ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
