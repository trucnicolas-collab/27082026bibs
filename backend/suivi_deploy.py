"""Suivi de déploiement — API de l'app séparée (/suivi).

Validation des allées (prévu VS réel posé VS géolocalisé), photos par allée,
stock & alertes rupture, incidents par nuit, rapport Excel par nuit (avec photos),
replanification automatique, accès équipe terrain sans compte (token).
"""
import io
import math
import os
import uuid
import logging
from datetime import datetime, timezone, date
from typing import Optional, List

import requests as _requests
import xlsxwriter
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

FAMILIES = [
    ("es_15", "EEG ES 1.5"),
    ("es_21", "EEG ES 2.1"),
    ("rails_es", "Rails ES"),
    ("sa_15", "SA 1.5"),
    ("sa_21_std", "SA 2.1"),
    ("sa_21_freezer", "SA 2.1 freezer"),
    ("sa_42", "SA 4.2 / 4.2 WP"),
    ("cameras", "Caméras"),
]
FAMILY_KEYS = [k for k, _ in FAMILIES]
FAMILY_LABELS = dict(FAMILIES)
EEG_KEYS = ["es_15", "es_21", "sa_15", "sa_21_std", "sa_21_freezer", "sa_42"]
# Familles à géolocaliser (posé VS géolocalisé) — hors SA 4.2 / saisonnier / caisses
# Familles à géolocaliser (v28, 13/02/2026) côté EEG : Rails ES + EEG SA 1.5
# + EEG SA 2.1 uniquement. On peut poser sans géolocaliser (case à cocher côté
# UI), mais pas l'inverse. Note : sa_21_freezer et sa_42 n'ont PAS de géoloc.
# Les caméras et fixations sont gérées séparément dans le module CAM.
GEO_KEYS = ["rails_es", "sa_15", "sa_21_std"]
JUSTIF_FAMILIES = set(EEG_KEYS) | {"rails_es"}
JUSTIF_THRESHOLD = 0.05  # 5% d'écart prévu/réel → justification
MAX_EEG_PER_NIGHT = 4900.0
MAX_PHOTO_BYTES = 8 * 1024 * 1024

# Statuts d'allée valides côté suivi (au-delà de a_faire par défaut)
ALLEE_STATUSES = {"a_faire", "validee", "bloquee", "a_finaliser", "non_faite"}


def is_camera_fixation(desig: str, typ: str) -> bool:
    """True si le produit est une fixation destinée aux caméras Captana.
    Ces produits appartiennent au phasage caméra, PAS au phasage EEG — ils doivent
    être exclus de la liste produits d'une allée EEG."""
    d = (desig or "").lower()
    t = (typ or "").lower()
    return "fixation" in t and ("captana" in d or "camera" in d or "caméra" in d)


# Désignations de la section « Captana » du récap Commande (miroir de
# _classify_section côté server.py). Tout produit dont la désignation appartient
# à cette liste doit être suivi côté PHASAGE CAMÉRA, pas côté EEG. Les fixations
# spécifiques caméras (support mobilier / ajustable / pied réglable) sont incluses.
CAPTANA_DESIGNATIONS = {
    "caméra (blanche)", "caméra (noire)",
    "batterie caméra", "software caméra",
    "support mobilier captana (blanc)", "support mobilier captana (noir)",
    "support ajustable adhésif captana",
    "pied réglable 0,5-1 m adhésif captana",
}


def is_cam_side_product(desig: str, typ: str) -> bool:
    """True si le produit relève du PHASAGE CAMÉRA (caméra elle-même ou
    fixation spécifique caméra) et doit être exclu du suivi EEG."""
    d = (desig or "").strip().lower()
    t = (typ or "").strip().lower()
    if t in ("caméra", "camera"):
        return True
    if d in CAPTANA_DESIGNATIONS:
        return True
    if "captana" in d:
        return True
    if is_camera_fixation(desig, typ):
        return True
    return False

# ---------------------------------------------------------------- Object storage
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_PREFIX = "phasage-crf"
_storage_key = None


def _init_storage():
    global _storage_key
    if _storage_key:
        return _storage_key
    resp = _requests.post(f"{STORAGE_URL}/init",
                          json={"emergent_key": os.environ.get("EMERGENT_LLM_KEY")}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def _put_object(path: str, data: bytes, content_type: str) -> dict:
    key = _init_storage()
    resp = _requests.put(f"{STORAGE_URL}/objects/{path}",
                         headers={"X-Storage-Key": key, "Content-Type": content_type},
                         data=data, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _get_object(path: str):
    key = _init_storage()
    resp = _requests.get(f"{STORAGE_URL}/objects/{path}",
                         headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


def _r(x):
    try:
        f = float(x or 0)
        return int(f) if f.is_integer() else round(f, 2)
    except (ValueError, TypeError):
        return 0


def _plan_for_allee(a: dict) -> dict:
    return {
        "es_15": _r((a.get("es_15") or 0) + (a.get("fleches") or 0)
                    + (a.get("es_15_bonus_noir") or 0) + (a.get("es_15_bonus_blanc") or 0)),
        "es_21": _r(a.get("es_21")),
        "rails_es": _r(a.get("rails_es")),
        "sa_15": _r(a.get("sa_15")),
        "sa_21_std": _r(a.get("sa_21_std")),
        "sa_21_freezer": _r(a.get("sa_21_freezer")),
        "sa_42": _r(a.get("sa_42")),
        "cameras": _r(a.get("cameras")),
    }


def _eeg_sum(vals: dict) -> float:
    return sum(float(vals.get(k) or 0) for k in EEG_KEYS)


class ProductEntry(BaseModel):
    designation: str
    reel: Optional[float] = Field(default=None, ge=0)
    geo: Optional[float] = Field(default=None, ge=0)


class ExtraProduct(BaseModel):
    designation: str
    qty: float = Field(ge=0)


class AlleeUpdate(BaseModel):
    uid: str
    products: Optional[List[ProductEntry]] = None
    extra_products: Optional[List[ExtraProduct]] = None  # produits posés non prévus
    status: Optional[str] = None  # a_faire | validee | bloquee | a_finaliser | non_faite
    comment: Optional[str] = None
    geoloc_comment: Optional[str] = None
    justification: Optional[str] = None  # écart > 5% EEG/rails
    nuit_reelle: Optional[int] = None  # 0 → retour à la nuit planifiée
    nuit_rattrapage: Optional[int] = None  # nuit prévue pour rattraper une allée non faite


class CamAlleeUpdate(BaseModel):
    uid: str
    cameras_reel: Optional[float] = Field(default=None, ge=0)
    cameras_geo: Optional[float] = Field(default=None, ge=0)
    fixations_reel: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    comment: Optional[str] = None
    geoloc_comment: Optional[str] = None
    nuit_reelle: Optional[int] = None


class StockUpdate(BaseModel):
    designation: str
    recu: Optional[float] = Field(default=None, ge=0)


class IncidentCreate(BaseModel):
    nuit: int
    text: str


class ReplanRequest(BaseModel):
    apply: bool = False


class PublishUpdate(BaseModel):
    published: bool


def build_suivi_router(db, load_dataset, get_current_user, compute_phasage_summary,
                       normalize_phasage, save_phasage_snapshot, persist_phasage,
                       classify_family, compute_node_sa_install=None,
                       full_allee_index=None):
    router = APIRouter(prefix="/suivi")
    terrain = APIRouter(prefix="/suivi-terrain")

    async def _load(upload_id: str, current_user: dict) -> dict:
        # Superadmin (créateur) : pas de restriction de propriétaire
        scope = None if current_user.get("role") == "superadmin" else str(current_user["_id"])
        d = await load_dataset(upload_id, user_id=scope)
        if d is None:
            raise HTTPException(status_code=404, detail="Dataset introuvable")
        return d

    async def _get_doc(upload_id: str, user_id: str = "") -> dict:
        doc = await db.suivi_docs.find_one({"upload_id": upload_id})
        if not doc:
            doc = {
                "upload_id": upload_id, "user_id": user_id,
                "allees": [], "stock_received": {}, "incidents": [],
                "published": False, "published_by": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.suivi_docs.insert_one(dict(doc))
        doc.pop("_id", None)
        return doc

    async def _resolve_terrain(upload_id: str):
        doc = await db.suivi_docs.find_one({"upload_id": upload_id, "published": True})
        if not doc:
            raise HTTPException(status_code=404, detail="Magasin non publié au suivi terrain")
        doc.pop("_id", None)
        d = await load_dataset(doc["upload_id"])
        if d is None:
            raise HTTPException(status_code=404, detail="Dataset introuvable")
        return d, doc

    def _apply_seasonal_zones(matidx: dict, by_uid: dict, summary: dict):
        """Injecte les Zones Saisonnières (ZS) côté Suivi de déploiement.

        SOURCE DE VÉRITÉ : `full_allee_index(summary)` de server.py (fonction
        `_full_allee_index`). C'est la MÊME fonction utilisée par tous les
        exports Phasage (Excel « Tableau date », « Recap Carrefour », PPTX
        slide 11, etc.). On ne duplique donc AUCUNE logique métier ici.

        On enrichit ensuite `matidx` avec des « produits synthétiques » basés
        sur les champs sa_15 / sa_21_std du nœud canonique, car le module
        Suivi doit permettre aux poseurs de saisir la qté posée par produit.
        """
        if full_allee_index is None:
            return matidx, by_uid  # Aucune ZS possible sans la source de vérité
        full_idx = full_allee_index(summary)
        for zid, node in full_idx.items():
            if not node.get("is_seasonal"):
                continue
            # 1) Copie le nœud canonique dans by_uid (mêmes champs que Phasage)
            by_uid[zid] = node
            # 2) Fabrique les produits synthétiques pour le suivi terrain
            sa15 = float(node.get("sa_15") or 0)
            sa21 = float(node.get("sa_21_std") or node.get("sa_21") or 0)
            label = node.get("rayon") or zid
            totals = {}
            types = {}
            if sa15 > 0:
                dg1 = "SA 1.5 (Zone saisonnier)"
                totals[dg1] = sa15
                types[dg1] = "EEG"
            if sa21 > 0:
                dg2 = "SA 2.1 (Zone saisonnier)"
                totals[dg2] = sa21
                types[dg2] = "EEG"
            matidx[zid] = {
                "uid": zid, "allee": zid,
                "secteur": node.get("secteur") or "Zone saisonnier",
                "rayon": label,
                "totals": totals, "types": types,
                "elements": {"(sans élément)": dict(totals)} if totals else {},
            }
        return matidx, by_uid

    # ------------------------------------------------------------ état complet
    def _build_state(d: dict, doc: dict, upload_id: str, is_terrain: bool = False) -> dict:
        summary = compute_phasage_summary(d)
        ph = normalize_phasage(d.get("phasage"))
        es = ph.get("es") or {}
        nb_nuits = int(es.get("nb_nuits") or 0)
        dates = ph.get("dates") or {}
        by_uid = {str(a.get("uid") or a.get("allee")): a for a in (summary.get("allees") or [])}
        nuit_by_uid = {}
        for row in (es.get("rows") or []):
            n = row.get("nuit")
            if n:
                nuit_by_uid[str(row.get("allee") or row.get("id"))] = int(n)
        entries = {str(e.get("uid")): e for e in (doc.get("allees") or [])}
        matidx = _materiel_par_allee(d)
        # (v27) Injecte les Zones Saisonnières (non présentes dans raw_records)
        _apply_seasonal_zones(matidx, by_uid, summary)
        cfg_sa = d.get("sa_install") or {}

        def _sa_families_off(node_uid: str) -> set:
            """Retourne l'ensemble des familles SA à NE PAS poser pour une allée
            (basé sur la config sa_install du phasage).

            Règles :
             - Si l'utilisateur a répondu « Non » (enabled=False, answered=True) :
               TOUTES les familles SA présentes sur l'allée sont exclues.
             - Si enabled=True (toutes ou sélection) : on utilise
               compute_node_sa_install pour déterminer les familles à exclure.
             - Sinon (question non répondue) : pas de filtrage (comportement legacy)."""
            a = by_uid.get(node_uid) or {}
            # (v27) Les Zones Saisonnières sont TOUJOURS posées par la VT (SA 1.5
            # + SA 2.1). Elles ne sont pas affectées par le choix « SA hors
            # saisonnier » du panneau sa_install.
            if a.get("is_seasonal"):
                return set()
            answered = bool(cfg_sa.get("answered"))
            enabled = bool(cfg_sa.get("enabled"))
            off = set()
            # Cas explicite : « Non, je n'installe pas de SA hors saisonnier »
            if answered and not enabled:
                for fam in ("sa_15", "sa_21_std", "sa_21_freezer", "sa_42"):
                    if float(a.get(fam) or (a.get("sa_21") if fam == "sa_21_std" else 0) or 0) > 0:
                        off.add(fam)
                return off
            if not enabled:
                return off
            inst = compute_node_sa_install(a, cfg_sa) if compute_node_sa_install else {}
            # sa_15
            if not inst.get("sa_15") and float(a.get("sa_15") or 0) > 0:
                off.add("sa_15")
            # sa_21_std (le champ inst["sa_21"] correspond à sa_21_std)
            if not inst.get("sa_21") and float(a.get("sa_21_std") or a.get("sa_21") or 0) > 0:
                off.add("sa_21_std")
            # sa_21_freezer
            if not inst.get("freezer") and float(a.get("sa_21_freezer") or 0) > 0:
                off.add("sa_21_freezer")
            # sa_42
            if not inst.get("sa_42") and float(a.get("sa_42") or 0) > 0:
                off.add("sa_42")
            return off

        allees = []
        for uid, nuit_plan in nuit_by_uid.items():
            a = by_uid.get(uid) or {}
            e = entries.get(uid) or {}
            plan = _plan_for_allee(a)
            mat = matidx.get(uid) or {"totals": {}, "types": {}}
            sa_off = _sa_families_off(uid)
            # Neutralise le plan pour les familles SA « à ne pas poser » afin
            # que les KPI (eeg_plan, total_eeg_plan, restant à poser) ne comptent
            # plus ces produits qui ne relèvent pas de ce magasin.
            for fam in sa_off:
                if fam in plan:
                    plan[fam] = 0.0
            # Neutralise aussi les caméras côté EEG (elles ont leur propre suivi).
            if "cameras" in plan:
                plan["cameras"] = 0.0
            pentries = {str(p.get("designation")): p for p in (e.get("products") or [])}
            products = []
            reel_fam = {k: None for k in FAMILY_KEYS}
            geo_fam = {k: None for k in GEO_KEYS}
            gap_fam = {k: 0.0 for k in GEO_KEYS}
            has_reel = False
            for desig in sorted(mat["totals"].keys(), key=lambda s: s.lower()):
                pplan = _r(mat["totals"][desig])
                typ = (mat.get("types") or {}).get(desig) or ""
                # (J) TOUT produit côté caméras (caméras + fixations Captana)
                # est suivi via le phasage CAMÉRA, pas EEG.
                if is_cam_side_product(desig, typ):
                    continue
                fam = classify_family(typ, desig)
                # Sécurité supplémentaire : si classify_family renvoie
                # « cameras » (ex : désignation contient « caméra »), on exclut.
                if fam == "cameras":
                    continue
                # (I) Filtrer les SA marquées « à ne pas poser » dans le phasage
                if fam in sa_off:
                    continue
                # Filtrer les produits avec quantité prévue = 0 (aucun à poser)
                if pplan <= 0:
                    continue
                is_geo = fam in GEO_KEYS
                pe = pentries.get(desig) or {}
                preel = pe.get("reel")
                pgeo = pe.get("geo")
                preel = None if preel is None else _r(preel)
                pgeo = None if pgeo is None else _r(pgeo)
                if preel is not None:
                    has_reel = True
                    if fam:
                        reel_fam[fam] = _r((reel_fam[fam] or 0) + preel)
                if pgeo is not None and is_geo:
                    geo_fam[fam] = _r((geo_fam[fam] or 0) + pgeo)
                pgap = 0
                if is_geo and preel is not None and pgeo is not None and pgeo < preel:
                    pgap = _r(preel - pgeo)
                    gap_fam[fam] = _r(gap_fam[fam] + pgap)
                products.append({
                    "designation": desig, "type": typ, "family": fam,
                    "is_geo": is_geo, "plan": pplan, "reel": preel,
                    "geo": pgeo, "gap": pgap,
                    "delta": (None if preel is None else _r(preel - pplan)),
                })
            reel = reel_fam
            geo = geo_fam
            geo_gap = {k: v for k, v in gap_fam.items() if v > 0}
            justif_products = []
            for p in products:
                if p["family"] in JUSTIF_FAMILIES and p["reel"] is not None and p["plan"]:
                    ecart = abs(p["reel"] - p["plan"])
                    if ecart > JUSTIF_THRESHOLD * p["plan"]:
                        justif_products.append({
                            "designation": p["designation"], "plan": p["plan"], "reel": p["reel"],
                            "ecart_pct": _r(100.0 * ecart / p["plan"]),
                        })
            extra_products = [
                {"designation": str(x.get("designation") or ""), "qty": _r(x.get("qty") or 0)}
                for x in (e.get("extra_products") or [])
            ]
            nuit_reelle = e.get("nuit_reelle")
            eff = int(nuit_reelle) if nuit_reelle else nuit_plan
            delta = {k: (None if reel[k] is None else _r(reel[k] - plan[k])) for k in FAMILY_KEYS}
            photos = [{"id": p.get("id"), "author": p.get("author") or "",
                       "created_at": p.get("created_at") or ""}
                      for p in (e.get("photos") or [])]
            # === Métriques Pose vs Géoloc (indépendantes) ===
            # Pose : sur tous les produits à poser (plan > 0), combien ont reel saisi
            pose_products = [p for p in products if (p["plan"] or 0) > 0]
            pose_saisis = sum(1 for p in pose_products if p["reel"] is not None)
            pose_pose = sum(1 for p in pose_products if (p["reel"] or 0) >= (p["plan"] or 0))
            pose_complete = bool(pose_products) and pose_saisis == len(pose_products)
            # Géoloc : uniquement sur les produits géolocalisables avec plan > 0 (ou reel > 0)
            geo_products = [p for p in products if p["is_geo"] and ((p["reel"] or 0) > 0 or (p["plan"] or 0) > 0)]
            geo_saisis = sum(1 for p in geo_products if p["geo"] is not None)
            geo_ok = sum(1 for p in geo_products if (p["geo"] or 0) >= (p["reel"] or 0))
            geo_complete = bool(geo_products) and geo_ok == len(geo_products)
            # Allée déplacée = nuit_reelle explicitement différente de nuit_plan
            is_deplacee = nuit_reelle is not None and int(nuit_reelle) != int(nuit_plan)
            allees.append({
                "uid": uid,
                "allee": a.get("allee") or uid.split("__")[0],
                "secteur": a.get("secteur") or "",
                "rayon": a.get("rayon") or "",
                "nuit_plan": nuit_plan,
                "nuit_reelle": nuit_reelle,
                "nuit_eff": eff,
                "nuit_rattrapage": e.get("nuit_rattrapage"),
                "is_deplacee": is_deplacee,
                "plan": plan,
                "reel": reel,
                "delta": delta,
                "geo": geo,
                "geo_gap": geo_gap,
                "geoloc_comment": e.get("geoloc_comment") or "",
                "photos": photos,
                "products": products,
                "nb_produits": len(products),
                "nb_saisis": sum(1 for p in products if p["reel"] is not None),
                # Séparation pose / géoloc
                "pose_total": len(pose_products),
                "pose_saisis": pose_saisis,
                "pose_pose": pose_pose,
                "pose_complete": pose_complete,
                "geo_total": len(geo_products),
                "geo_saisis": geo_saisis,
                "geo_ok": geo_ok,
                "geo_complete": geo_complete,
                "eeg_plan": _r(_eeg_sum(plan)),
                "eeg_reel": _r(_eeg_sum({k: (reel[k] or 0) for k in FAMILY_KEYS})) if has_reel else None,
                "justification": e.get("justification") or "",
                "justif_products": justif_products,
                "extra_products": extra_products,
                "status": e.get("status") or "a_faire",
                "comment": e.get("comment") or "",
                "has_reel": has_reel,
            })

        def _sk(x):
            try:
                return (x["nuit_eff"], 0, float(str(x["allee"]).replace(",", ".")), x["secteur"])
            except (ValueError, TypeError):
                return (x["nuit_eff"], 1, 0.0, str(x["allee"]))
        allees.sort(key=_sk)

        max_night = max([nb_nuits or 1] + [x["nuit_eff"] for x in allees]) if allees else (nb_nuits or 1)
        today = date.today().isoformat()
        nights = []
        for n in range(1, max_night + 1):
            items = [x for x in allees if x["nuit_eff"] == n]
            plan_eeg = sum(x["eeg_plan"] for x in items)
            reel_eeg = sum(x["eeg_reel"] or 0 for x in items if x["eeg_reel"] is not None)
            validated = sum(1 for x in items if x["status"] == "validee")
            blocked = sum(1 for x in items if x["status"] == "bloquee")
            a_finaliser = sum(1 for x in items if x["status"] == "a_finaliser")
            non_faites = sum(1 for x in items if x["status"] == "non_faite")
            nb_deplacees = sum(1 for x in items if x.get("is_deplacee") and x["status"] != "validee")
            # Séparation pose / géoloc au niveau nuit
            pose_saisis_tot = sum(int(x.get("pose_saisis") or 0) for x in items)
            pose_total_tot = sum(int(x.get("pose_total") or 0) for x in items)
            geo_saisis_tot = sum(int(x.get("geo_saisis") or 0) for x in items)
            geo_total_tot = sum(int(x.get("geo_total") or 0) for x in items)
            nb_pose_complete = sum(1 for x in items if x.get("pose_complete"))
            nb_geo_complete = sum(1 for x in items if x.get("geo_complete"))
            # Allées rapatriées en avance = allées dont la nuit planifiée était postérieure
            nb_rapatriees = sum(1 for x in items if (x.get("nuit_plan") or 0) > n)
            started = any(x["has_reel"] or x["status"] != "a_faire" for x in items)
            complete = bool(items) and validated == len(items)
            date_n = str(dates.get(str(n)) or dates.get(n) or "")
            nights.append({
                "nuit": n, "date": date_n,
                "nb_allees": len(items),
                "nb_validees": validated, "nb_bloquees": blocked,
                "nb_a_finaliser": a_finaliser,
                "nb_non_faites": non_faites,
                "nb_deplacees": nb_deplacees,
                "nb_rapatriees": nb_rapatriees,
                "nb_pose_complete": nb_pose_complete,
                "nb_geo_complete": nb_geo_complete,
                "pose_saisis": pose_saisis_tot,
                "pose_total": pose_total_tot,
                "geo_saisis": geo_saisis_tot,
                "geo_total": geo_total_tot,
                "eeg_plan": _r(plan_eeg), "eeg_reel": _r(reel_eeg),
                "delta_eeg": _r(reel_eeg - plan_eeg) if started else None,
                "complete": complete, "started": started,
                "is_past": bool(date_n) and date_n < today,
            })

        total_eeg_plan = _r(sum(x["eeg_plan"] for x in allees))
        total_eeg_reel = _r(sum(x["eeg_reel"] or 0 for x in allees))
        n_valid = sum(1 for x in allees if x["status"] == "validee")
        n_block = sum(1 for x in allees if x["status"] == "bloquee")
        nights_started = [n for n in nights if n["started"]]
        nights_done = [n for n in nights if n["complete"]]
        rythme_prevu = _r(total_eeg_plan / nb_nuits) if nb_nuits else 0
        rythme_reel = _r(sum(n["eeg_reel"] for n in nights_done) / len(nights_done)) if nights_done else 0
        eeg_restant = _r(max(0.0, sum(x["eeg_plan"] for x in allees if x["status"] != "validee")))
        nuits_plan_restantes = max(0, nb_nuits - len(nights_done))
        nuits_estimees = math.ceil(eeg_restant / rythme_reel) if rythme_reel > 0 else None
        avance_nuits = (nuits_plan_restantes - nuits_estimees) if nuits_estimees is not None else None
        cumul_delta = _r(sum((n["delta_eeg"] or 0) for n in nights_done))

        # ---- Stock PAR PRODUIT (chaque désignation du fichier) ----
        stock_received = doc.get("stock_received")
        if not isinstance(stock_received, list):
            stock_received = []
        recu_by_desig = {str(s.get("designation")): s.get("recu") for s in stock_received}
        prod_agg = {}
        for x in allees:
            not_valid = x["status"] != "validee"
            for p in x["products"]:
                g = prod_agg.setdefault(p["designation"], {
                    "designation": p["designation"], "type": p["type"], "family": p["family"],
                    "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0})
                g["prevu"] += p["plan"] or 0
                g["pose"] += p["reel"] or 0
                if not_valid:
                    g["restant_a_poser"] += max(0.0, (p["plan"] or 0) - (p["reel"] or 0))
            for ep in x["extra_products"]:
                g = prod_agg.setdefault(ep["designation"], {
                    "designation": ep["designation"], "type": "", "family": None,
                    "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0, "extra": True})
                g["pose"] += ep["qty"] or 0
        # ---- Agrégation stock côté CAMÉRAS (caméras + fixations spécifiques) ----
        # Utilise le phasage caméras (rows) pour connaître les uids concernés.
        cam_rows_map = {}
        for row in ((ph.get("cam") or {}).get("rows") or []):
            n = row.get("nuit")
            if n:
                cam_rows_map[str(row.get("allee") or row.get("id"))] = int(n)
        cam_entries_stock = {str(e.get("uid")): e for e in (doc.get("cam_allees") or [])}
        for uid_cam in cam_rows_map.keys():
            matc = matidx.get(uid_cam) or {"totals": {}, "types": {}}
            entry_cam = cam_entries_stock.get(uid_cam) or {}
            status_cam = entry_cam.get("status") or "a_faire"
            not_valid_cam = status_cam != "validee"
            reel_cam_total = float(entry_cam.get("cameras_reel") or 0)
            fix_reel_total = float(entry_cam.get("fixations_reel") or 0)
            # Calcule les totaux plan caméra vs fixation pour la ventilation du réel
            plan_cam_total = 0.0
            plan_fix_total = 0.0
            for dg, q in (matc.get("totals") or {}).items():
                tdg = (matc.get("types") or {}).get(dg) or ""
                if not is_cam_side_product(dg, tdg):
                    continue
                q = float(q or 0)
                if q <= 0:
                    continue
                if (tdg or "").strip().lower() in ("caméra", "camera"):
                    plan_cam_total += q
                else:
                    plan_fix_total += q
            for dg in sorted((matc.get("totals") or {}).keys(), key=lambda s: s.lower()):
                q = float(matc["totals"].get(dg) or 0)
                if q <= 0:
                    continue
                tdg = (matc.get("types") or {}).get(dg) or ""
                if not is_cam_side_product(dg, tdg):
                    continue
                is_cam_device = (tdg.strip().lower() in ("caméra", "camera"))
                fam_stock = "cameras" if is_cam_device else None
                # Répartition du réel proportionnellement aux quantités prévues
                if is_cam_device and plan_cam_total > 0:
                    pose = reel_cam_total * (q / plan_cam_total)
                elif (not is_cam_device) and plan_fix_total > 0:
                    pose = fix_reel_total * (q / plan_fix_total)
                else:
                    pose = 0.0
                g = prod_agg.setdefault(dg, {
                    "designation": dg, "type": tdg, "family": fam_stock,
                    "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0})
                g["prevu"] += q
                g["pose"] += pose
                if not_valid_cam:
                    g["restant_a_poser"] += max(0.0, q - pose)
        # (v28 iter2) Fusion des Zones Saisonnières dans les SA (noir) correspondants
        # pour l'affichage stock — les poseurs reçoivent une seule livraison de
        # SA 1.5 noir et SA 2.1 noir, sans distinction ZS. On garde la traçabilité
        # dans le matériel par nuit / écran allée, mais on agrège au niveau stock.
        # Détection intelligente du nom cible (variantes possibles : « SA 1.5 noir »,
        # « SA 1.5 (noir) », etc.) — on cherche la 1ère désignation qui match.
        def _find_noir_target(pref: str) -> str | None:
            pref_l = pref.lower()
            for dg in prod_agg.keys():
                dgl = dg.lower()
                if dgl.startswith(pref_l) and "noir" in dgl and "saisonn" not in dgl:
                    return dg
            return None

        for zs_desig, prefix in (("SA 1.5 (Zone saisonnier)", "sa 1.5"),
                                 ("SA 2.1 (Zone saisonnier)", "sa 2.1")):
            if zs_desig not in prod_agg:
                continue
            target_desig = _find_noir_target(prefix)
            zs = prod_agg.pop(zs_desig)
            if target_desig and target_desig in prod_agg:
                tgt = prod_agg[target_desig]
                tgt["prevu"] += zs["prevu"]
                tgt["pose"] += zs["pose"]
                tgt["restant_a_poser"] += zs["restant_a_poser"]
            else:
                # Aucune cible « (noir) » dans le fichier → on garde la ZS mais
                # sous un libellé neutre pour ne pas afficher « Zone saisonnier »
                # dans le stock.
                fallback = "SA 1.5 (noir)" if prefix == "sa 1.5" else "SA 2.1 (noir)"
                zs["designation"] = fallback
                prod_agg[fallback] = zs

        stock, alerts = [], []
        for desig in sorted(prod_agg.keys(), key=lambda s: s.lower()):
            g = prod_agg[desig]
            recu = recu_by_desig.get(desig)
            recu_eff = float(recu) if recu is not None else g["prevu"]
            restant_stock = recu_eff - g["pose"]
            manque = max(0.0, g["restant_a_poser"] - max(0.0, restant_stock))
            alert = manque > 0 and g["prevu"] > 0
            stock.append({
                "designation": desig, "label": desig,
                "type": g["type"], "family": g["family"],
                "prevu": _r(g["prevu"]),
                "recu": (None if recu is None else _r(recu)),
                "recu_theorique": recu is None,
                "pose": _r(g["pose"]),
                "restant_stock": _r(restant_stock),
                "restant_a_poser": _r(g["restant_a_poser"]),
                "manque": _r(manque), "alert": alert,
            })
            if alert:
                alerts.append({
                    "type": "rupture", "family": g["family"], "label": desig,
                    "designation": desig,
                    "manque": _r(manque),
                    "message": (f"{desig} : il manque {_r(manque)} unité(s) pour finir la pose "
                                f"(stock restant {_r(restant_stock)}, encore {_r(g['restant_a_poser'])} à poser)"),
                })
        for x in allees:
            if x["status"] == "a_finaliser":
                alerts.append({
                    "type": "a_finaliser", "family": None,
                    "label": f"Allée {x['allee']}",
                    "uid": x["uid"], "nuit": x["nuit_eff"],
                    "message": (f"Allée {x['allee']} ({x['secteur']}) — nuit {x['nuit_eff']} À FINALISER une autre nuit"
                                + (f" : {x['comment']}" if x["comment"] else "")),
                })
            if x["status"] == "non_faite":
                nr = x.get("nuit_rattrapage")
                alerts.append({
                    "type": "non_faite", "family": None,
                    "label": f"Allée {x['allee']}",
                    "uid": x["uid"], "nuit": x["nuit_eff"],
                    "nuit_rattrapage": nr,
                    "en_attente": nr is None,
                    "message": (f"Allée {x['allee']} ({x['secteur']}) — nuit {x['nuit_eff']} NON FAITE"
                                + (f", rattrapage nuit {nr}" if nr else " — EN ATTENTE (nuit de rattrapage à définir)")
                                + (f" : {x['comment']}" if x["comment"] else "")),
                })
            if x["status"] == "bloquee":
                alerts.append({
                    "type": "blocage", "family": None,
                    "label": f"Allée {x['allee']}",
                    "message": (f"Allée {x['allee']} ({x['secteur']} / {x['rayon']}) — nuit {x['nuit_eff']} bloquée"
                                + (f" : {x['comment']}" if x["comment"] else "")),
                })
            gaps = {k: v for k, v in (x.get("geo_gap") or {}).items() if v and v > 0}
            if gaps:
                detail = ", ".join(f"{FAMILY_LABELS[k]} : {_r(v)} posé(s) non géolocalisé(s)" for k, v in gaps.items())
                needs_expl = not bool(x["geoloc_comment"])
                msg = f"Allée {x['allee']} (nuit {x['nuit_eff']}) — {detail}."
                msg += " ⚠ Explication demandée." if needs_expl else f" Explication : {x['geoloc_comment']}"
                alerts.append({
                    "type": "geoloc", "family": None,
                    "label": f"Allée {x['allee']}",
                    "uid": x["uid"], "nuit": x["nuit_eff"],
                    "needs_explanation": needs_expl,
                    "message": msg,
                })

        # ---- Phasage caméras (suivi à part) ----
        cam = ph.get("cam") or {}
        cam_start = int(cam.get("start_at_nuit") or 1)
        cam_nb = int(cam.get("nb_nuits") or 0)
        cam_nuit_by_uid = {}
        for row in (cam.get("rows") or []):
            n = row.get("nuit")
            if n:
                cam_nuit_by_uid[str(row.get("allee") or row.get("id"))] = int(n)
        cam_entries = {str(e.get("uid")): e for e in (doc.get("cam_allees") or [])}
        cam_allees = []
        for uid, nuit_plan in cam_nuit_by_uid.items():
            a = by_uid.get(uid) or {}
            e = cam_entries.get(uid) or {}
            plan_c = _r(a.get("cameras") or 0)
            reel_c = e.get("cameras_reel")
            geo_c = e.get("cameras_geo")
            reel_c = None if reel_c is None else _r(reel_c)
            geo_c = None if geo_c is None else _r(geo_c)
            gap = _r(reel_c - geo_c) if (reel_c is not None and geo_c is not None and geo_c < reel_c) else 0
            nuit_reelle = e.get("nuit_reelle")
            eff = int(nuit_reelle) if nuit_reelle else nuit_plan
            matc = matidx.get(uid) or {"totals": {}, "types": {}}
            # Liste détaillée des produits côté caméra (caméras + fixations
            # spécifiques Captana). On les extrait tous depuis raw_records
            # à partir du référentiel Captana défini dans is_cam_side_product.
            cam_products = []
            fix_plan = 0.0
            for dg in sorted((matc.get("totals") or {}).keys(), key=lambda s: s.lower()):
                q = float(matc["totals"].get(dg) or 0)
                if q <= 0:
                    continue
                tdg = ((matc.get("types") or {}).get(dg) or "")
                if not is_cam_side_product(dg, tdg):
                    continue
                is_camera_device = (tdg.strip().lower() in ("caméra", "camera"))
                pr = _r(q)
                cam_products.append({
                    "designation": dg,
                    "type": tdg,
                    "is_camera": is_camera_device,
                    "is_fixation": (not is_camera_device),
                    "plan": pr,
                })
                if not is_camera_device:
                    fix_plan += q
            fix_reel = e.get("fixations_reel")
            fix_reel = None if fix_reel is None else _r(fix_reel)
            cam_allees.append({
                "fix_plan": _r(fix_plan) if fix_plan else None,
                "fix_reel": fix_reel,
                "fix_delta": (None if (fix_reel is None or not fix_plan) else _r(fix_reel - fix_plan)),
                "uid": uid,
                "allee": a.get("allee") or uid.split("__")[0],
                "secteur": a.get("secteur") or "",
                "rayon": a.get("rayon") or "",
                "nuit_plan": nuit_plan, "nuit_reelle": nuit_reelle, "nuit_eff": eff,
                "nuit_abs": cam_start + eff - 1,
                "plan": plan_c, "reel": reel_c, "geo": geo_c,
                "delta": (None if reel_c is None else _r(reel_c - plan_c)),
                "geo_gap": gap,
                "elements": a.get("camera_elems") or [],
                "products": cam_products,
                "status": e.get("status") or "a_faire",
                "comment": e.get("comment") or "",
                "geoloc_comment": e.get("geoloc_comment") or "",
            })

        def _cam_sk(x):
            try:
                return (x["nuit_eff"], 0, float(str(x["allee"]).replace(",", ".")))
            except (ValueError, TypeError):
                return (x["nuit_eff"], 1, 0.0)
        cam_allees.sort(key=_cam_sk)
        cam_max = max([cam_nb or 1] + [x["nuit_eff"] for x in cam_allees]) if cam_allees else (cam_nb or 1)
        cam_nights = []
        for n in range(1, cam_max + 1):
            items = [x for x in cam_allees if x["nuit_eff"] == n]
            abs_n = cam_start + n - 1
            validated = sum(1 for x in items if x["status"] == "validee")
            cam_nights.append({
                "nuit": n, "nuit_abs": abs_n,
                "date": str(dates.get(str(abs_n)) or dates.get(abs_n) or ""),
                "nb_allees": len(items),
                "nb_validees": validated,
                "nb_bloquees": sum(1 for x in items if x["status"] == "bloquee"),
                "cam_plan": _r(sum(x["plan"] for x in items)),
                "cam_reel": _r(sum(x["reel"] or 0 for x in items)),
                "complete": bool(items) and validated == len(items),
            })
        for x in cam_allees:
            if x["status"] == "bloquee":
                alerts.append({
                    "type": "blocage", "family": None,
                    "label": f"Caméras allée {x['allee']}",
                    "message": (f"Caméras — allée {x['allee']} ({x['secteur']}) nuit {x['nuit_abs']} bloquée"
                                + (f" : {x['comment']}" if x["comment"] else "")),
                })
            if x["geo_gap"]:
                needs_expl = not bool(x["geoloc_comment"])
                msg = f"Caméras — allée {x['allee']} (nuit {x['nuit_abs']}) : {x['geo_gap']} posée(s) non géolocalisée(s)."
                msg += " ⚠ Explication demandée." if needs_expl else f" Explication : {x['geoloc_comment']}"
                alerts.append({"type": "geoloc", "family": "cameras", "label": f"Caméras allée {x['allee']}",
                               "uid": x["uid"], "needs_explanation": needs_expl, "message": msg})

        incidents = sorted(doc.get("incidents") or [], key=lambda i: (i.get("nuit") or 0, i.get("created_at") or ""))

        state = {
            "upload_id": upload_id,
            "store_name": d.get("store_name") or "",
            "store_code": d.get("store_code") or "",
            "filename": d.get("filename") or "",
            "nb_nuits": nb_nuits,
            "dates": {str(k): v for k, v in dates.items()},
            "geo_keys": GEO_KEYS,
            "allees": allees,
            "nights": nights,
            "stock": stock,
            "alerts": alerts,
            "incidents": incidents,
            "is_terrain": is_terrain,
            "cam": {
                "start_at_nuit": cam_start,
                "nb_nuits": cam_nb,
                "nights": cam_nights,
                "allees": cam_allees,
            },
            "stats": {
                "eeg_prevues": total_eeg_plan,
                "eeg_posees": total_eeg_reel,
                "pct": _r(100.0 * total_eeg_reel / total_eeg_plan) if total_eeg_plan else 0,
                # Séparation pose / géoloc (agrégat toutes nuits)
                "pose_saisis": sum(int(x.get("pose_saisis") or 0) for x in allees),
                "pose_total": sum(int(x.get("pose_total") or 0) for x in allees),
                "pose_pct": _r(100.0 * sum(int(x.get("pose_saisis") or 0) for x in allees) / max(1, sum(int(x.get("pose_total") or 0) for x in allees))) if any(x.get("pose_total") for x in allees) else 0,
                "geo_saisis": sum(int(x.get("geo_saisis") or 0) for x in allees),
                "geo_total": sum(int(x.get("geo_total") or 0) for x in allees),
                "geo_pct": _r(100.0 * sum(int(x.get("geo_saisis") or 0) for x in allees) / max(1, sum(int(x.get("geo_total") or 0) for x in allees))) if any(x.get("geo_total") for x in allees) else 0,
                "allees_deplacees": sum(1 for x in allees if x.get("is_deplacee") and x["status"] != "validee"),
                "allees_total": len(allees),
                "allees_validees": n_valid,
                "allees_bloquees": n_block,
                "nuits_terminees": len(nights_done),
                "nuits_commencees": len(nights_started),
                "rythme_prevu": rythme_prevu,
                "rythme_reel": rythme_reel,
                "eeg_restant": eeg_restant,
                "nuits_estimees_restantes": nuits_estimees,
                "avance_nuits": avance_nuits,
                "cumul_delta_eeg": cumul_delta,
            },
        }
        if not is_terrain:
            state["publication"] = {
                "published": bool(doc.get("published")),
                "published_by": doc.get("published_by") or "",
            }
        return state

    # ------------------------------------------------------- mutations partagées
    async def _apply_allee_update(upload_id: str, doc: dict, payload: AlleeUpdate, author: str,
                                  valid_designations=None):
        fields = payload.dict(exclude_unset=True)
        uid = fields.pop("uid")
        prods = fields.pop("products", None)
        extras = fields.pop("extra_products", None)
        if "status" in fields and fields["status"] not in (None,) and fields["status"] not in ALLEE_STATUSES:
            raise HTTPException(status_code=400, detail="Statut invalide")
        if fields.get("nuit_reelle") == 0:
            fields["nuit_reelle"] = None
        arr = doc.get("allees") or []
        entry = next((e for e in arr if str(e.get("uid")) == uid), None)
        if entry is None:
            entry = {"uid": uid}
            arr.append(entry)
        entry.update(fields)
        if extras is not None:
            entry["extra_products"] = [
                {"designation": str(x.get("designation") or "").strip(), "qty": float(x.get("qty") or 0)}
                for x in extras if str(x.get("designation") or "").strip() and float(x.get("qty") or 0) > 0
            ]
        if prods:
            plist = entry.setdefault("products", [])
            pmap = {str(p.get("designation")): p for p in plist}
            for item in prods:
                desig = str(item.get("designation") or "").strip()
                if not desig:
                    continue
                if valid_designations is not None and desig not in valid_designations:
                    continue
                node = pmap.get(desig)
                if node is None:
                    node = {"designation": desig}
                    plist.append(node)
                    pmap[desig] = node
                if "reel" in item:
                    node["reel"] = item["reel"]
                if "geo" in item:
                    node["geo"] = item["geo"]
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        entry["updated_by"] = author
        if fields.get("status") == "validee":
            entry["validated_at"] = entry["updated_at"]
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$set": {"allees": arr}})
        return uid

    async def _add_photo(upload_id: str, doc: dict, uid: str, file: UploadFile, author: str):
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier vide")
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=400, detail="Photo trop volumineuse (max 8 Mo)")
        ct = file.content_type or "image/jpeg"
        if not ct.startswith("image/"):
            raise HTTPException(status_code=400, detail="Seules les images sont acceptées")
        pid = uuid.uuid4().hex[:12]
        ext = "png" if "png" in ct else ("webp" if "webp" in ct else "jpg")
        path = f"{APP_PREFIX}/suivi/{upload_id}/{pid}.{ext}"
        try:
            result = _put_object(path, data, ct)
        except Exception as e:
            logger.error(f"Photo upload failed: {e}")
            raise HTTPException(status_code=502, detail="Stockage photo indisponible, réessayez")
        arr = doc.get("allees") or []
        entry = next((e for e in arr if str(e.get("uid")) == uid), None)
        if entry is None:
            entry = {"uid": uid}
            arr.append(entry)
        photo = {"id": pid, "path": result.get("path") or path, "content_type": ct,
                 "author": author, "created_at": datetime.now(timezone.utc).isoformat()}
        entry.setdefault("photos", []).append(photo)
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$set": {"allees": arr}})
        return {"ok": True, "photo": {"id": pid, "author": author, "created_at": photo["created_at"]}}

    def _find_photo(doc: dict, photo_id: str):
        for e in (doc.get("allees") or []):
            for p in (e.get("photos") or []):
                if p.get("id") == photo_id:
                    return e, p
        return None, None

    def _photo_response(doc: dict, photo_id: str):
        _e, p = _find_photo(doc, photo_id)
        if not p:
            raise HTTPException(status_code=404, detail="Photo introuvable")
        try:
            data, ct = _get_object(p["path"])
        except Exception:
            raise HTTPException(status_code=404, detail="Photo indisponible")
        return Response(content=data, media_type=p.get("content_type") or ct,
                        headers={"Cache-Control": "private, max-age=3600"})

    async def _delete_photo(upload_id: str, doc: dict, photo_id: str):
        arr = doc.get("allees") or []
        found = False
        for e in arr:
            photos = e.get("photos") or []
            new = [p for p in photos if p.get("id") != photo_id]
            if len(new) != len(photos):
                e["photos"] = new
                found = True
        if not found:
            raise HTTPException(status_code=404, detail="Photo introuvable")
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$set": {"allees": arr}})
        return {"ok": True}

    async def _create_incident(upload_id: str, payload: IncidentCreate, author: str):
        inc = {
            "id": str(uuid.uuid4())[:8],
            "nuit": payload.nuit,
            "text": payload.text.strip(),
            "author": author,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not inc["text"]:
            raise HTTPException(status_code=400, detail="Texte vide")
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$push": {"incidents": inc}})
        return {"ok": True, "incident": inc}

    # ------------------------------------------------- Rapport Excel par nuit
    def _rapport_response(d: dict, doc: dict, upload_id: str, nuit: int):
        state = _build_state(d, doc, upload_id)
        items = [x for x in state["allees"] if x["nuit_eff"] == nuit]
        if not items:
            raise HTTPException(status_code=404, detail=f"Aucune allée sur la nuit {nuit}")
        night = next((n for n in state["nights"] if n["nuit"] == nuit), {})
        fams = [k for k in FAMILY_KEYS if any((x["plan"].get(k) or 0) > 0 or x["reel"].get(k) is not None for x in items)]

        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {"in_memory": True})
        ws = wb.add_worksheet(f"Nuit {nuit}")
        f_title = wb.add_format({"bold": True, "font_size": 14, "font_color": "#005BAB"})
        f_sub = wb.add_format({"font_size": 10, "font_color": "#666666"})
        f_h = wb.add_format({"bold": True, "bg_color": "#005BAB", "font_color": "white",
                             "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
        f_c = wb.add_format({"border": 1, "align": "center"})
        f_cl = wb.add_format({"border": 1})
        f_ok = wb.add_format({"border": 1, "align": "center", "bg_color": "#DBEAFE"})
        f_neg = wb.add_format({"border": 1, "align": "center", "bg_color": "#FEE2E2", "font_color": "#B91C1C"})
        f_pos = wb.add_format({"border": 1, "align": "center", "bg_color": "#FEF3C7", "font_color": "#92400E"})
        f_geo_bad = wb.add_format({"border": 1, "align": "center", "bg_color": "#FEE2E2", "font_color": "#B91C1C", "bold": True})
        f_tot = wb.add_format({"bold": True, "border": 1, "align": "center", "bg_color": "#E5E7EB"})
        f_kpi_l = wb.add_format({"bold": True})

        store = state["store_name"] or state["filename"]
        ws.write(0, 0, f"Rapport de pose — Nuit {nuit}", f_title)
        ws.write(1, 0, f"{store}" + (f" · {state['store_code']}" if state["store_code"] else "")
                 + (f" · {night.get('date')}" if night.get("date") else ""), f_sub)
        ws.write(2, 0, f"Généré le {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC", f_sub)

        row = 4
        st = state["stats"]
        delta_n = night.get("delta_eeg")
        geo_gap_total = _r(sum(sum(x["geo_gap"].values()) for x in items if x["geo_gap"]))
        kpis = [
            ("EEG prévues cette nuit", night.get("eeg_plan", 0)),
            ("EEG posées cette nuit", night.get("eeg_reel", 0)),
            ("Écart cette nuit", delta_n if delta_n is not None else "—"),
            ("Allées validées", f"{night.get('nb_validees', 0)} / {night.get('nb_allees', 0)}"),
            ("Allées à finaliser une autre nuit", night.get("nb_a_finaliser", 0)),
            ("Posés non géolocalisés (rails/SA)", geo_gap_total),
            ("Rythme moyen réel (EEG/nuit)", st["rythme_reel"] or "—"),
            ("Rythme prévu (EEG/nuit)", st["rythme_prevu"]),
            ("Écart cumulé (nuits terminées)", st["cumul_delta_eeg"]),
            ("Avance/retard estimé (nuits)", st["avance_nuits"] if st["avance_nuits"] is not None else "—"),
        ]
        for label, val in kpis:
            ws.write(row, 0, label, f_kpi_l)
            ws.write(row, 2, val)
            row += 1
        # Compteur "non faites"
        nb_non_faites = sum(1 for x in items if x["status"] == "non_faite")
        if nb_non_faites:
            ws.write(row, 0, "Allées non faites", f_kpi_l)
            ws.write(row, 2, nb_non_faites)
            row += 1

        # ---- Allées "non faites" en attente (rattrapage non défini) ----
        pending = [x for x in items if x["status"] == "non_faite" and not x.get("nuit_rattrapage")]
        if pending:
            row += 1
            f_pending_title = wb.add_format({"bold": True, "font_size": 12, "font_color": "#B91C1C"})
            ws.write(row, 0, f"⏳ Allées « non faites » EN ATTENTE (rattrapage à définir) — {len(pending)}", f_pending_title)
            row += 1
            for c, h in enumerate(["Allée", "Secteur", "Rayon", "Raison"]):
                ws.write(row, c, h, f_h)
            row += 1
            for x in pending:
                ws.write(row, 0, x["allee"], f_c)
                ws.write(row, 1, x["secteur"], f_cl)
                ws.write(row, 2, x["rayon"] or "", f_cl)
                ws.write(row, 3, x["comment"] or "—", f_cl)
                row += 1
            row += 1

        # ---- Alerte stock : produits en risque de manque ----
        stock_alerts = [s for s in (state.get("stock") or []) if s.get("alert")]
        if stock_alerts:
            row += 1
            f_alert_title = wb.add_format({"bold": True, "font_size": 12, "font_color": "#B91C1C"})
            ws.write(row, 0, f"⚠ Risque de manque de stock ({len(stock_alerts)} produit(s))", f_alert_title)
            row += 1
            for c, h in enumerate(["Produit", "Prévu", "Reçu", "Posé", "Restant stock", "Restant à poser", "Manque"]):
                ws.write(row, c, h, f_h)
            row += 1
            for s in stock_alerts:
                ws.write(row, 0, s["designation"], f_cl)
                ws.write(row, 1, s["prevu"], f_c)
                ws.write(row, 2, s["recu"] if s.get("recu") is not None else "—", f_c)
                ws.write(row, 3, s["pose"], f_c)
                ws.write(row, 4, s["restant_stock"], f_c)
                ws.write(row, 5, s["restant_a_poser"], f_c)
                ws.write(row, 6, s["manque"], f_geo_bad)
                row += 1
            row += 1
        if isinstance(delta_n, (int, float)):
            verdict = ("⚡ Plus rapide que prévu" if delta_n > 0 else
                       ("🐢 Plus lent que prévu" if delta_n < 0 else "✔ Conforme au prévisionnel"))
            ws.write(row, 0, "Verdict", f_kpi_l)
            ws.write(row, 2, verdict)
            row += 1
        row += 1

        # Tableau des allées (prévu / réel / géo / Δ) + colonnes distinctes Pose vs Géoloc
        headers = ["Allée", "Secteur", "Rayon", "Pose", "Géoloc", "Déplacée ?"]
        col_plan = {}
        for k in fams:
            col_plan[k] = len(headers)
            headers += [f"{FAMILY_LABELS[k]} prévu", f"{FAMILY_LABELS[k]} réel"]
            if k in GEO_KEYS:
                headers.append("Géoloc")
            headers.append("Δ")
        headers += ["Statut", "Justification écart >5%", "Commentaire POSE", "Commentaire GÉOLOC"]
        for c, h in enumerate(headers):
            ws.write(row, c, h, f_h)
        ws.set_column(0, 0, 8)
        ws.set_column(1, 2, 16)
        ws.set_column(3, len(headers) - 5, 9)
        ws.set_column(len(headers) - 3, len(headers) - 1, 28)
        row += 1
        status_lbl = {"a_faire": "À faire", "validee": "Validée", "bloquee": "BLOQUÉE",
                      "a_finaliser": "À FINALISER", "non_faite": "NON FAITE"}
        tot_plan = {k: 0.0 for k in fams}
        tot_reel = {k: 0.0 for k in fams}
        tot_geo = {k: 0.0 for k in fams}
        for x in items:
            c = 0
            ws.write(row, c, x["allee"], f_c); c += 1
            ws.write(row, c, x["secteur"], f_cl); c += 1
            ws.write(row, c, x["rayon"], f_cl); c += 1
            # Pose X/Y — écart en rouge si non complet
            ws.write(row, c, f"{x.get('pose_saisis') or 0}/{x.get('pose_total') or 0}",
                     f_c if x.get("pose_complete") else f_geo_bad)
            c += 1
            # Géoloc A/B (— si aucun produit à géolocaliser)
            if (x.get("geo_total") or 0) > 0:
                ws.write(row, c, f"{x.get('geo_saisis') or 0}/{x.get('geo_total') or 0}",
                         f_c if x.get("geo_complete") else f_geo_bad)
            else:
                ws.write(row, c, "—", f_c)
            c += 1
            # Déplacée ?
            if x.get("is_deplacee"):
                ws.write(row, c, f"Depuis N{x['nuit_plan']}", f_geo_bad)
            else:
                ws.write(row, c, "", f_c)
            c += 1
            for k in fams:
                p = x["plan"].get(k) or 0
                rv = x["reel"].get(k)
                dv = x["delta"].get(k)
                tot_plan[k] += p
                tot_reel[k] += rv or 0
                ws.write(row, c, p, f_c); c += 1
                ws.write(row, c, rv if rv is not None else "", f_c); c += 1
                if k in GEO_KEYS:
                    gv = x["geo"].get(k)
                    tot_geo[k] += gv or 0
                    gap = x["geo_gap"].get(k)
                    ws.write(row, c, gv if gv is not None else "", f_geo_bad if gap else f_c)
                    c += 1
                if dv is None:
                    ws.write(row, c, "", f_c)
                else:
                    ws.write(row, c, dv, f_ok if dv == 0 else (f_neg if dv < 0 else f_pos))
                c += 1
            stx = x["status"]
            ws.write(row, c, status_lbl.get(stx, stx),
                     f_ok if stx == "validee" else (f_neg if stx in ("bloquee", "a_finaliser") else f_c)); c += 1
            ws.write(row, c, x.get("justification") or "", f_cl); c += 1
            ws.write(row, c, x["comment"], f_cl); c += 1
            ws.write(row, c, x["geoloc_comment"], f_cl)
            row += 1
        ws.write(row, 0, "TOTAL", f_tot)
        ws.write(row, 1, "", f_tot)
        ws.write(row, 2, "", f_tot)
        c = 3
        for k in fams:
            ws.write(row, c, _r(tot_plan[k]), f_tot); c += 1
            ws.write(row, c, _r(tot_reel[k]), f_tot); c += 1
            if k in GEO_KEYS:
                ws.write(row, c, _r(tot_geo[k]), f_tot); c += 1
            ws.write(row, c, _r(tot_reel[k] - tot_plan[k]), f_tot); c += 1
        for cc in range(c, len(headers)):
            ws.write(row, cc, "", f_tot)
        row += 2

        # Produits supplémentaires posés (non prévus)
        extras_rows = [(x["allee"], ep) for x in items for ep in (x.get("extra_products") or [])]
        if extras_rows:
            ws.write(row, 0, "Produits supplémentaires posés (non prévus)", f_title)
            row += 1
            for c0, h in enumerate(["Allée", "Désignation", "Quantité"]):
                ws.write(row, c0, h, f_h)
            row += 1
            for al, ep in extras_rows:
                ws.write(row, 0, al, f_c)
                ws.write(row, 1, ep["designation"], f_cl)
                ws.write(row, 2, ep["qty"], f_c)
                row += 1
            row += 1

        # Justifications d'écart > 5% (EEG / rails ES)
        justif_rows = [x for x in items if x.get("justif_products")]
        if justif_rows:
            ws.write(row, 0, "Écarts > 5% (EEG / rails ES) et justifications", f_title)
            row += 1
            for c0, h in enumerate(["Allée", "Produit", "Prévu", "Posé", "Écart %", "Justification"]):
                ws.write(row, c0, h, f_h)
            ws.set_column(5, 5, 40)
            row += 1
            for x in justif_rows:
                for jp in x["justif_products"]:
                    ws.write(row, 0, x["allee"], f_c)
                    ws.write(row, 1, jp["designation"], f_cl)
                    ws.write(row, 2, jp["plan"], f_c)
                    ws.write(row, 3, jp["reel"], f_c)
                    ws.write(row, 4, jp["ecart_pct"], f_neg)
                    ws.write(row, 5, x.get("justification") or "⚠ manquante", f_cl)
                    row += 1
            row += 1

        # Caméras de la nuit (si phasage caméras couvre cette nuit absolue)
        cam_items = [x for x in ((state.get("cam") or {}).get("allees") or []) if x.get("nuit_abs") == nuit]
        if cam_items:
            ws.write(row, 0, "Caméras de la nuit", f_title)
            row += 1
            for c0, h in enumerate(["Allée", "Secteur", "Prévu", "Posées", "Géoloc", "Fixations prévues", "Fixations posées", "Statut", "Commentaire"]):
                ws.write(row, c0, h, f_h)
            row += 1
            for x in cam_items:
                ws.write(row, 0, x["allee"], f_c)
                ws.write(row, 1, x["secteur"], f_cl)
                ws.write(row, 2, x["plan"], f_c)
                ws.write(row, 3, x["reel"] if x["reel"] is not None else "", f_c)
                ws.write(row, 4, x["geo"] if x["geo"] is not None else "", f_geo_bad if x["geo_gap"] else f_c)
                ws.write(row, 5, x.get("fix_plan") if x.get("fix_plan") is not None else "", f_c)
                ws.write(row, 6, x["fix_reel"] if x.get("fix_reel") is not None else "", f_c)
                ws.write(row, 7, status_lbl.get(x["status"], x["status"]),
                         f_ok if x["status"] == "validee" else (f_neg if x["status"] == "bloquee" else f_c))
                ws.write(row, 8, x["comment"], f_cl)
                row += 1
            row += 1

        incs = [i for i in state["incidents"] if i.get("nuit") == nuit]
        if incs:
            ws.write(row, 0, "Incidents de la nuit", f_title)
            row += 1
            for i in incs:
                ws.write(row, 0, f"• {i.get('text')}", f_cl)
                ws.write(row, 4, i.get("author") or "", f_sub)
                row += 1
            row += 1

        # Photos des allées de la nuit
        entries = {str(e.get("uid")): e for e in (doc.get("allees") or [])}
        night_photos = []
        for x in items:
            for p in (entries.get(x["uid"], {}).get("photos") or []):
                night_photos.append((x["allee"], p))
        if night_photos:
            try:
                from PIL import Image as PILImage
                ws.write(row, 0, "Photos", f_title)
                row += 1
                col_positions = [0, 4, 8]
                r0, max_rows = row, 0
                for i, (allee_label, p) in enumerate(night_photos[:30]):
                    try:
                        data, _ct = _get_object(p["path"])
                        im = PILImage.open(io.BytesIO(data))
                        w, h = im.size
                        scale = min(1.0, 230.0 / float(w))
                        ci = i % 3
                        if ci == 0 and i > 0:
                            r0 += max_rows
                            max_rows = 0
                        ws.write(r0, col_positions[ci], f"Allée {allee_label}", f_sub)
                        ws.insert_image(r0 + 1, col_positions[ci], f"{p['id']}.jpg",
                                        {"image_data": io.BytesIO(data), "x_scale": scale, "y_scale": scale})
                        max_rows = max(max_rows, int((h * scale) / 20) + 3)
                    except Exception as pe:
                        logger.warning(f"Photo embed failed ({p.get('id')}): {pe}")
                        continue
            except Exception as e:
                logger.warning(f"Photos section failed: {e}")

        # Feuille 2 : détail par produit
        ws2 = wb.add_worksheet("Détail produits")
        headers2 = ["Allée", "Secteur", "Désignation", "Type", "Prévu", "Posé", "Géolocalisé", "Δ"]
        for c, h in enumerate(headers2):
            ws2.write(0, c, h, f_h)
        ws2.set_column(0, 1, 12)
        ws2.set_column(2, 2, 42)
        ws2.set_column(3, 7, 11)
        rr = 1
        for x in items:
            for p in x["products"]:
                ws2.write(rr, 0, x["allee"], f_c)
                ws2.write(rr, 1, x["secteur"], f_cl)
                ws2.write(rr, 2, p["designation"], f_cl)
                ws2.write(rr, 3, p["type"], f_c)
                ws2.write(rr, 4, p["plan"], f_c)
                ws2.write(rr, 5, p["reel"] if p["reel"] is not None else "", f_c)
                if p["is_geo"]:
                    ws2.write(rr, 6, p["geo"] if p["geo"] is not None else "", f_geo_bad if p["gap"] else f_c)
                else:
                    ws2.write(rr, 6, "—", f_c)
                dv = p["delta"]
                if dv is None:
                    ws2.write(rr, 7, "", f_c)
                else:
                    ws2.write(rr, 7, dv, f_ok if dv == 0 else (f_neg if dv < 0 else f_pos))
                rr += 1

        # Feuille 3 : Écart phasage vs réel (EEG + Caméras)
        ecart_eeg = None
        ecart_cam = None
        try:
            ecart_eeg = _materiel_nuit(d, doc, nuit, mode="eeg")
        except HTTPException:
            pass
        try:
            ecart_cam = _materiel_nuit(d, doc, nuit, mode="cam")
        except HTTPException:
            pass
        if (ecart_eeg and ecart_eeg.get("ecarts")) or (ecart_cam and ecart_cam.get("ecarts")):
            ws_ec = wb.add_worksheet("Écart phasage vs réel")
            ws_ec.write(0, 0, f"Écart phasage vs réel — Nuit {nuit}", f_title)
            ws_ec.write(1, 0, "Comparaison quantités prévues (phasage) vs réel posé, par produit. "
                              "Bonus > +5%, Manque < -5%.", f_sub)
            ws_ec.set_column(0, 0, 42)
            ws_ec.set_column(1, 1, 12)
            ws_ec.set_column(2, 6, 11)
            r_ec = 3

            def _write_ecart_block(title: str, block: dict):
                nonlocal r_ec
                if not block or not block.get("ecarts"):
                    return
                stats = block.get("ecart_stats") or {}
                ws_ec.write(r_ec, 0, title, f_kpi_l)
                r_ec += 1
                ws_ec.write(r_ec, 0, "Conforme (±5%)", f_kpi_l)
                ws_ec.write(r_ec, 1, stats.get("nb_conforme", 0), f_ok)
                ws_ec.write(r_ec, 2, "Bonus posé (>+5%)", f_kpi_l)
                ws_ec.write(r_ec, 3, stats.get("nb_bonus", 0), f_pos)
                ws_ec.write(r_ec, 4, "Sous-livré (<-5%)", f_kpi_l)
                ws_ec.write(r_ec, 5, stats.get("nb_manque", 0), f_neg)
                r_ec += 2
                # En-tête tableau
                for c0, h in enumerate(["Désignation", "Type", "Prévu", "Réel", "Δ", "Écart %", "Statut"]):
                    ws_ec.write(r_ec, c0, h, f_h)
                r_ec += 1
                status_lbl_ec = {"conforme": "Conforme", "bonus": "Bonus", "manque": "Manque"}
                fmt_ec = {"conforme": f_ok, "bonus": f_pos, "manque": f_neg}
                # Manques d'abord (priorité logistique), puis bonus, puis conforme
                order = {"manque": 0, "bonus": 1, "conforme": 2}
                for e in sorted(block["ecarts"], key=lambda x: (order.get(x["status"], 9), x["designation"].lower())):
                    fc = fmt_ec.get(e["status"], f_c)
                    ws_ec.write(r_ec, 0, e["designation"], f_cl)
                    ws_ec.write(r_ec, 1, e.get("type") or "", f_c)
                    ws_ec.write(r_ec, 2, e["plan"], f_c)
                    ws_ec.write(r_ec, 3, e["reel"], fc)
                    dv = e["delta"]
                    ws_ec.write(r_ec, 4, dv, fc)
                    pct = (dv / e["plan"] * 100) if e["plan"] else 0
                    ws_ec.write(r_ec, 5, f"{pct:+.1f}%", fc)
                    ws_ec.write(r_ec, 6, status_lbl_ec.get(e["status"], e["status"]), fc)
                    r_ec += 1
                # Sous-total
                total_plan = sum(e["plan"] or 0 for e in block["ecarts"])
                total_reel = sum(e["reel"] or 0 for e in block["ecarts"])
                total_delta = total_reel - total_plan
                ws_ec.write(r_ec, 0, "TOTAL", f_tot)
                ws_ec.write(r_ec, 1, "", f_tot)
                ws_ec.write(r_ec, 2, total_plan, f_tot)
                ws_ec.write(r_ec, 3, total_reel, f_tot)
                ws_ec.write(r_ec, 4, total_delta, f_tot)
                pct_tot = (total_delta / total_plan * 100) if total_plan else 0
                ws_ec.write(r_ec, 5, f"{pct_tot:+.1f}%", f_tot)
                ws_ec.write(r_ec, 6, "", f_tot)
                r_ec += 2

            _write_ecart_block("EEG · Écarts par produit", ecart_eeg)
            _write_ecart_block("CAMÉRAS · Écarts par produit", ecart_cam)

        # Feuille 4 : synthèse dashboard de toutes les nuits
        ws3 = wb.add_worksheet("Synthèse déploiement")
        ws3.write(0, 0, "Synthèse du déploiement — toutes les nuits", f_title)
        ws3.write(1, 0, f"{store} — état au {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC", f_sub)
        r3 = 3
        gkpis = [
            ("EEG prévues (total magasin)", st["eeg_prevues"]),
            ("EEG posées (total)", st["eeg_posees"]),
            ("Avancement (%)", st["pct"]),
            ("Allées validées", f"{st['allees_validees']} / {st['allees_total']}"),
            ("Allées bloquées", st["allees_bloquees"]),
            ("Nuits terminées", f"{st['nuits_terminees']} / {state['nb_nuits']}"),
            ("Rythme réel (EEG/nuit)", st["rythme_reel"] or "—"),
            ("Rythme prévu (EEG/nuit)", st["rythme_prevu"]),
            ("EEG restant à poser", st["eeg_restant"]),
            ("Nuits estimées restantes", st["nuits_estimees_restantes"] if st["nuits_estimees_restantes"] is not None else "—"),
            ("Avance/retard estimé (nuits)", st["avance_nuits"] if st["avance_nuits"] is not None else "—"),
            ("Écart cumulé EEG (nuits terminées)", st["cumul_delta_eeg"]),
        ]
        for label, val in gkpis:
            ws3.write(r3, 0, label, f_kpi_l)
            ws3.write(r3, 2, val)
            r3 += 1
        r3 += 1
        heads3 = ["Nuit", "Date", "Allées", "Validées", "Bloquées", "À finaliser",
                  "EEG prévu", "EEG posé", "Écart", "Statut"]
        for c0, h in enumerate(heads3):
            ws3.write(r3, c0, h, f_h)
        ws3.set_column(0, 0, 10)
        ws3.set_column(1, 1, 12)
        ws3.set_column(2, 9, 11)
        r3 += 1
        for n in state["nights"]:
            if not n["nb_allees"]:
                continue
            stat = "Terminée" if n["complete"] else ("En cours" if n["started"] else "À venir")
            if n["nb_a_finaliser"]:
                stat = "À FINALISER"
            f_stat = f_neg if (n["nb_a_finaliser"] or n["nb_bloquees"]) else (f_ok if n["complete"] else f_c)
            ws3.write(r3, 0, f"{n['nuit']}" + (" ◀ cette nuit" if n["nuit"] == nuit else ""), f_stat)
            ws3.write(r3, 1, n["date"] or "", f_c)
            ws3.write(r3, 2, n["nb_allees"], f_c)
            ws3.write(r3, 3, n["nb_validees"], f_c)
            ws3.write(r3, 4, n["nb_bloquees"], f_neg if n["nb_bloquees"] else f_c)
            ws3.write(r3, 5, n["nb_a_finaliser"], f_neg if n["nb_a_finaliser"] else f_c)
            ws3.write(r3, 6, n["eeg_plan"], f_c)
            ws3.write(r3, 7, n["eeg_reel"], f_c)
            dv = n["delta_eeg"]
            ws3.write(r3, 8, "" if dv is None else dv,
                      f_c if dv is None else (f_ok if dv == 0 else (f_neg if dv < 0 else f_pos)))
            ws3.write(r3, 9, stat, f_stat)
            r3 += 1

        wb.close()
        buf.seek(0)
        from server import _export_basename  # lazy import (évite dep circulaire)
        fname = f"{_export_basename(d)}_Rapport_nuit_{nuit}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    async def _apply_cam_update(upload_id: str, doc: dict, payload: CamAlleeUpdate, author: str):
        fields = payload.dict(exclude_unset=True)
        uid = fields.pop("uid")
        if "status" in fields and fields["status"] not in (None, "a_faire", "validee", "bloquee"):
            raise HTTPException(status_code=400, detail="Statut invalide")
        if fields.get("nuit_reelle") == 0:
            fields["nuit_reelle"] = None
        arr = doc.get("cam_allees") or []
        entry = next((e for e in arr if str(e.get("uid")) == uid), None)
        if entry is None:
            entry = {"uid": uid}
            arr.append(entry)
        entry.update(fields)
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        entry["updated_by"] = author
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$set": {"cam_allees": arr}})
        return uid

    # ------------------------------------------ Matériel prévu (3 niveaux)
    def _materiel_par_allee(d: dict) -> dict:
        raw = d.get("raw_records") or []
        if not raw:
            return {}
        cols = list(raw[0].keys())
        secteur_col = "Secteur" if "Secteur" in cols else None
        rayon_col = "Rayon" if "Rayon" in cols else None
        type_col = "Type" if "Type" in cols else None
        allee_col = next((c for c in ["N° allée", "N° allee", "Allée", "Allee"] if c in cols), None)
        elem_col = next((c for c in cols if "lément" in c or "lement" in c.lower()), None)
        if elem_col is None and len(cols) >= 7:
            elem_col = cols[6]
        desig_col = next((c for c in ["Désignation", "Designation"] if c in cols), None)
        qty_col = next((c for c in ["Quantité", "Quantite"] if c in cols), None)
        idx = {}
        for r in raw:
            allee_raw = r.get(allee_col) if allee_col else None
            if allee_raw is None or (isinstance(allee_raw, float) and math.isnan(allee_raw)):
                continue
            try:
                f = float(allee_raw)
                allee_key = str(int(f)) if f.is_integer() else str(allee_raw)
            except (ValueError, TypeError):
                allee_key = str(allee_raw).strip()
            secteur_v = str(r.get(secteur_col) or "") if secteur_col else ""
            rayon_v = str(r.get(rayon_col) or "") if rayon_col else ""
            uid = f"{allee_key}__{secteur_v}__{rayon_v}"
            desig = str(r.get(desig_col) or "").strip() if desig_col else ""
            if not desig or desig.lower() == "nan":
                desig = "(sans désignation)"
            try:
                qty = float(r.get(qty_col) or 0) if qty_col else 0.0
            except (ValueError, TypeError):
                qty = 0.0
            elem_v = r.get(elem_col) if elem_col else None
            if elem_v is None or (isinstance(elem_v, float) and math.isnan(elem_v)) or str(elem_v).strip() in ("", "nan"):
                elem_key = "(sans élément)"
            else:
                try:
                    fe = float(elem_v)
                    elem_key = str(int(fe)) if fe.is_integer() else str(elem_v)
                except (ValueError, TypeError):
                    elem_key = str(elem_v).strip()
            node = idx.setdefault(uid, {"uid": uid, "allee": allee_key, "secteur": secteur_v,
                                        "rayon": rayon_v, "totals": {}, "elements": {}, "types": {}})
            node["totals"][desig] = node["totals"].get(desig, 0.0) + qty
            if desig not in node["types"]:
                typ_v = str(r.get(type_col) or "").strip() if type_col else ""
                node["types"][desig] = "" if typ_v.lower() == "nan" else typ_v
            enode = node["elements"].setdefault(elem_key, {})
            enode[desig] = enode.get(desig, 0.0) + qty
        return idx

    def _products_list(totals: dict) -> list:
        return [{"designation": k, "qty": _r(v)} for k, v in sorted(totals.items(), key=lambda t: t[0].lower())]

    def _sa_families_off_for(a: dict, cfg_sa: dict) -> set:
        """Version standalone de _sa_families_off (utilisée hors _build_state)."""
        # (v27) Les Zones Saisonnières sont TOUJOURS posées par la VT.
        if (a or {}).get("is_seasonal"):
            return set()
        answered = bool((cfg_sa or {}).get("answered"))
        enabled = bool((cfg_sa or {}).get("enabled"))
        off = set()
        if answered and not enabled:
            for fam in ("sa_15", "sa_21_std", "sa_21_freezer", "sa_42"):
                val = a.get(fam)
                if fam == "sa_21_std" and (val is None or float(val or 0) == 0):
                    val = a.get("sa_21")
                if float(val or 0) > 0:
                    off.add(fam)
            return off
        if not enabled:
            return off
        inst = compute_node_sa_install(a, cfg_sa) if compute_node_sa_install else {}
        if not inst.get("sa_15") and float(a.get("sa_15") or 0) > 0:
            off.add("sa_15")
        if not inst.get("sa_21") and float(a.get("sa_21_std") or a.get("sa_21") or 0) > 0:
            off.add("sa_21_std")
        if not inst.get("freezer") and float(a.get("sa_21_freezer") or 0) > 0:
            off.add("sa_21_freezer")
        if not inst.get("sa_42") and float(a.get("sa_42") or 0) > 0:
            off.add("sa_42")
        return off

    def _filter_materiel_node(node: dict, mode: str, by_uid: dict, cfg_sa: dict) -> dict:
        """Filtre les produits d'un nœud matériel selon le mode :
         - "eeg" : exclut caméras/Captana, SA à ne pas poser, plan<=0
         - "cam" : ne conserve QUE les produits côté caméra (caméras + fixations Captana), plan>0
         - autre : renvoie le nœud tel quel (comportement legacy)."""
        if mode not in ("eeg", "cam"):
            return node
        uid = node.get("uid") or ""
        types = node.get("types") or {}
        totals = node.get("totals") or {}
        allee_node = by_uid.get(uid) or {}
        sa_off = _sa_families_off_for(allee_node, cfg_sa) if mode == "eeg" else set()
        new_totals = {}
        new_elems = {}
        for desig, qty in totals.items():
            if (qty or 0) <= 0:
                continue
            typ = types.get(desig) or ""
            cam_side = is_cam_side_product(desig, typ)
            if mode == "eeg":
                if cam_side:
                    continue
                fam = classify_family(typ, desig)
                if fam == "cameras" or fam in sa_off:
                    continue
            else:  # mode == "cam"
                if not cam_side:
                    continue
            new_totals[desig] = qty
        # Reconstruire les éléments en gardant les mêmes règles
        for elem_key, prods in (node.get("elements") or {}).items():
            kept = {}
            for desig, qty in prods.items():
                if desig in new_totals:
                    kept[desig] = qty
            if kept:
                new_elems[elem_key] = kept
        return {
            "uid": uid, "allee": node.get("allee"),
            "secteur": node.get("secteur"), "rayon": node.get("rayon"),
            "totals": new_totals, "elements": new_elems, "types": types,
        }

    def _eff_nights_map(d: dict, doc: dict, mode: str = "eeg") -> dict:
        """uid -> nuit effective (ABSOLUE, par rapport au planning global).
         - mode="eeg" : plan EEG (ES) + overrides nuit_reelle du suivi EEG.
         - mode="cam" : nuit caméra = cam.start_at_nuit + row.nuit - 1
                       + overrides nuit_reelle du suivi cam si présent."""
        ph = normalize_phasage(d.get("phasage"))
        out = {}
        if mode == "cam":
            cam = ph.get("cam") or {}
            start = int(cam.get("start_at_nuit") or 1)
            for row in (cam.get("rows") or []):
                n = row.get("nuit")
                if n:
                    out[str(row.get("allee") or row.get("id"))] = start + int(n) - 1
            for e in (doc.get("cam_allees") or []):
                nr = e.get("nuit_reelle")
                if nr and str(e.get("uid")) in out:
                    out[str(e.get("uid"))] = start + int(nr) - 1
            return out
        for row in (ph.get("es") or {}).get("rows") or []:
            n = row.get("nuit")
            if n:
                out[str(row.get("allee") or row.get("id"))] = int(n)
        for e in (doc.get("allees") or []):
            nr = e.get("nuit_reelle")
            if nr and str(e.get("uid")) in out:
                out[str(e.get("uid"))] = int(nr)
        return out

    def _materiel_context(d: dict) -> tuple:
        """Retourne (by_uid, cfg_sa) pour un dataset : nécessaire aux filtres SA.

        Inclut les Zones Saisonnières (v27) via `full_allee_index` (source de
        vérité du Phasage — voir server._full_allee_index)."""
        ph = normalize_phasage(d.get("phasage"))
        by_uid = {str(a.get("id")): a for a in (ph.get("es") or {}).get("rows") or []}
        # (v27) Injecte les ZS depuis la source de vérité du Phasage.
        if full_allee_index is not None:
            try:
                summary = compute_phasage_summary(d)
                for zid, node in full_allee_index(summary).items():
                    if node.get("is_seasonal"):
                        # `id` est utilisé par _sa_families_off_for qui lit `is_seasonal`
                        by_uid[zid] = {**node, "id": zid}
            except Exception as e:
                logger.warning(f"_materiel_context: seasonal_zones inject failed: {e}")
        cfg_sa = d.get("sa_install") or {}
        return by_uid, cfg_sa

    def _materiel_par_allee_with_zs(d: dict) -> dict:
        """Comme _materiel_par_allee mais avec les Zones Saisonnières injectées
        via la source de vérité du Phasage (`full_allee_index`)."""
        idx = _materiel_par_allee(d)
        try:
            summary = compute_phasage_summary(d)
            _apply_seasonal_zones(idx, {}, summary)
        except Exception as e:
            logger.warning(f"_materiel_par_allee_with_zs: inject failed: {e}")
        return idx

    def _materiel_overview(d: dict, doc: dict, mode: str = "eeg") -> dict:
        idx = _materiel_par_allee_with_zs(d)
        by_uid, cfg_sa = _materiel_context(d)
        nights_map = _eff_nights_map(d, doc, mode=mode)
        ph = normalize_phasage(d.get("phasage"))
        dates = ph.get("dates") or {}
        by_night = {}
        unassigned = {"totals": {}, "nb_allees": 0}
        for uid, node in idx.items():
            if mode in ("eeg", "cam") and uid not in nights_map:
                # En mode filtré, on ignore les allées qui ne relèvent pas de ce phasage.
                continue
            node = _filter_materiel_node(node, mode, by_uid, cfg_sa)
            if not node.get("totals"):
                continue
            n = nights_map.get(uid)
            if not n:
                unassigned["nb_allees"] += 1
                for k, v in node["totals"].items():
                    unassigned["totals"][k] = unassigned["totals"].get(k, 0.0) + v
                continue
            b = by_night.setdefault(n, {"nuit": n, "date": str(dates.get(str(n)) or ""), "nb_allees": 0, "totals": {}})
            b["nb_allees"] += 1
            for k, v in node["totals"].items():
                b["totals"][k] = b["totals"].get(k, 0.0) + v
        nights = []
        for n in sorted(by_night.keys()):
            b = by_night[n]
            nights.append({"nuit": n, "date": b["date"], "nb_allees": b["nb_allees"],
                           "products": _products_list(b["totals"])})
        return {
            "nights": nights,
            "unassigned": {"nb_allees": unassigned["nb_allees"],
                           "products": _products_list(unassigned["totals"])},
        }

    def _materiel_nuit(d: dict, doc: dict, nuit: int, mode: str = "eeg") -> dict:
        idx = _materiel_par_allee_with_zs(d)
        by_uid, cfg_sa = _materiel_context(d)
        nights_map = _eff_nights_map(d, doc, mode=mode)
        ph = normalize_phasage(d.get("phasage"))
        dates = ph.get("dates") or {}
        # Index des entrées de suivi pour construire l'écart plan vs réel
        eeg_entries = {str(e.get("uid")): e for e in (doc.get("allees") or [])}
        cam_entries = {str(e.get("uid")): e for e in (doc.get("cam_allees") or [])}

        def _elem_sort(t):
            try:
                return (0, float(str(t[0]).replace(",", ".")))
            except (ValueError, TypeError):
                return (1, str(t[0]))

        # Agrégats plan/réel/géoloc par désignation sur toute la nuit (v28)
        totals_plan = {}
        totals_reel = {}
        totals_geo = {}
        totals_type = {}
        # Statuts d'allée pour affichage (nb validées / à faire / bloquée)
        nb_val, nb_block, nb_todo = 0, 0, 0
        allees = []
        for uid, node_raw in idx.items():
            if nights_map.get(uid) != nuit:
                continue
            node = _filter_materiel_node(node_raw, mode, by_uid, cfg_sa)
            if not node.get("totals"):
                continue
            elements = [{"element": k, "products": _products_list(v)}
                        for k, v in sorted(node["elements"].items(), key=_elem_sort)]
            # Récupération du réel/géoloc selon le mode (v28)
            reel_by_desig = {}
            geo_by_desig = {}
            if mode == "cam":
                ce = cam_entries.get(uid) or {}
                # Le réel caméra est aggregé (cameras_reel + fixations_reel) — on le
                # répartit proportionnellement aux quantités prévues.
                plan_cam_tot, plan_fix_tot = 0.0, 0.0
                for dg, q in (node["totals"] or {}).items():
                    typ = (node["types"] or {}).get(dg) or ""
                    if (typ or "").strip().lower() in ("caméra", "camera"):
                        plan_cam_tot += float(q or 0)
                    else:
                        plan_fix_tot += float(q or 0)
                r_cam = float(ce.get("cameras_reel") or 0)
                r_fix = float(ce.get("fixations_reel") or 0)
                g_cam = float(ce.get("cameras_geo") or 0)   # (v28) géoloc caméras
                for dg, q in (node["totals"] or {}).items():
                    typ = (node["types"] or {}).get(dg) or ""
                    q = float(q or 0)
                    if q <= 0:
                        continue
                    if (typ or "").strip().lower() in ("caméra", "camera"):
                        if plan_cam_tot > 0:
                            reel_by_desig[dg] = r_cam * (q / plan_cam_tot)
                            geo_by_desig[dg] = g_cam * (q / plan_cam_tot)
                    else:
                        if plan_fix_tot > 0:
                            reel_by_desig[dg] = r_fix * (q / plan_fix_tot)
                            # Fixations Captana : pas de géoloc (v28)
                status_a = (ce or {}).get("status") or "a_faire"
            else:
                ee = eeg_entries.get(uid) or {}
                for p in (ee.get("products") or []):
                    dg = str(p.get("designation") or "")
                    if p.get("reel") is not None and dg in (node["totals"] or {}):
                        reel_by_desig[dg] = float(p.get("reel") or 0)
                    if p.get("geo") is not None and dg in (node["totals"] or {}):
                        geo_by_desig[dg] = float(p.get("geo") or 0)
                status_a = (ee or {}).get("status") or "a_faire"
            if status_a == "validee":
                nb_val += 1
            elif status_a == "bloquee":
                nb_block += 1
            else:
                nb_todo += 1
            # Agrégats nuit
            for dg, q in (node["totals"] or {}).items():
                totals_plan[dg] = totals_plan.get(dg, 0.0) + float(q or 0)
                totals_type[dg] = (node["types"] or {}).get(dg) or totals_type.get(dg, "")
                if dg in reel_by_desig:
                    totals_reel[dg] = totals_reel.get(dg, 0.0) + reel_by_desig[dg]
                if dg in geo_by_desig:
                    totals_geo[dg] = totals_geo.get(dg, 0.0) + geo_by_desig[dg]
            # Construction de l'écart au niveau allée (utile pour drill-down)
            allee_ecarts = []
            for dg in sorted(node["totals"].keys(), key=lambda s: s.lower()):
                pplan = float(node["totals"][dg] or 0)
                if pplan <= 0 and dg not in reel_by_desig:
                    continue
                preel = reel_by_desig.get(dg)
                if preel is None:
                    continue
                delta = preel - pplan
                pct = (abs(delta) / pplan) if pplan > 0 else (1.0 if preel > 0 else 0.0)
                if delta > 0 and pct > 0.05:
                    st = "bonus"
                elif delta < 0 and pct > 0.05:
                    st = "manque"
                else:
                    st = "conforme"
                typ = (node["types"] or {}).get(dg) or ""
                fam = classify_family(typ, dg) or ""
                # (v28) La géoloc est requise pour rails_es / sa_15 / sa_21_std (EEG)
                # et pour les caméras (mode cam). Elle est distincte du "posé".
                is_geo = (fam in GEO_KEYS) if mode == "eeg" else \
                         ((typ or "").strip().lower() in ("caméra", "camera"))
                pgeo = geo_by_desig.get(dg) if is_geo else None
                allee_ecarts.append({
                    "designation": dg, "plan": _r(pplan), "reel": _r(preel),
                    "geo": _r(pgeo) if pgeo is not None else None,
                    "family": fam, "is_geo": is_geo,
                    "delta": _r(delta), "status": st,
                })
            allees.append({"uid": uid, "allee": node["allee"], "secteur": node["secteur"],
                           "rayon": node["rayon"], "products": _products_list(node["totals"]),
                           "elements": elements, "ecarts": allee_ecarts,
                           "status": status_a})
        if not allees:
            raise HTTPException(status_code=404, detail=f"Aucune allée sur la nuit {nuit}")

        def _sk(x):
            try:
                return (0, float(str(x["allee"]).replace(",", ".")))
            except (ValueError, TypeError):
                return (1, str(x["allee"]))
        allees.sort(key=_sk)

        # Écart global de la nuit — un item par désignation posée au moins partiellement
        ecarts_nuit = []
        for dg in sorted(totals_plan.keys(), key=lambda s: s.lower()):
            pplan = totals_plan[dg]
            if dg not in totals_reel:
                continue
            preel = totals_reel[dg]
            delta = preel - pplan
            pct = (abs(delta) / pplan) if pplan > 0 else (1.0 if preel > 0 else 0.0)
            if delta > 0 and pct > 0.05:
                st = "bonus"
            elif delta < 0 and pct > 0.05:
                st = "manque"
            else:
                st = "conforme"
            typ = totals_type.get(dg, "")
            fam = classify_family(typ, dg) or ""
            # (v28) Même logique is_geo qu'au niveau allée
            is_geo = (fam in GEO_KEYS) if mode == "eeg" else \
                     ((typ or "").strip().lower() in ("caméra", "camera"))
            pgeo = totals_geo.get(dg) if is_geo else None
            ecarts_nuit.append({
                "designation": dg, "type": typ,
                "plan": _r(pplan), "reel": _r(preel),
                "geo": _r(pgeo) if pgeo is not None else None,
                "family": fam, "is_geo": is_geo,
                "delta": _r(delta), "status": st,
            })
        nb_bonus = sum(1 for e in ecarts_nuit if e["status"] == "bonus")
        nb_manque = sum(1 for e in ecarts_nuit if e["status"] == "manque")
        nb_conforme = sum(1 for e in ecarts_nuit if e["status"] == "conforme")

        return {
            "nuit": nuit, "date": str(dates.get(str(nuit)) or ""),
            "allees": allees,
            "ecarts": ecarts_nuit,
            "ecart_stats": {
                "nb_saisis": len(ecarts_nuit),
                "nb_conforme": nb_conforme,
                "nb_bonus": nb_bonus,
                "nb_manque": nb_manque,
                "nb_allees_validees": nb_val,
                "nb_allees_bloquees": nb_block,
                "nb_allees_a_faire": nb_todo,
                "complete": (nb_todo == 0 and nb_block == 0 and (nb_val > 0)),
            },
        }

    def _justifs_after_update(matnode: dict, entry: dict, fields: dict) -> list:
        """Produits EEG/rails avec écart > 5% après application du payload."""
        merged = {str(p.get("designation")): dict(p) for p in ((entry or {}).get("products") or [])}
        for item in (fields.get("products") or []):
            d0 = str(item.get("designation") or "")
            node = merged.setdefault(d0, {"designation": d0})
            if "reel" in item:
                node["reel"] = item["reel"]
        out = []
        totals = (matnode or {}).get("totals") or {}
        types = (matnode or {}).get("types") or {}
        for desig, plan in totals.items():
            fam = classify_family(types.get(desig) or "", desig)
            if fam not in JUSTIF_FAMILIES or not plan:
                continue
            reel = (merged.get(desig) or {}).get("reel")
            if reel is None:
                continue
            if abs(float(reel) - float(plan)) > JUSTIF_THRESHOLD * float(plan):
                out.append(desig)
        return out

    def _check_geoloc_gap(matnode: dict, entry: dict, fields: dict) -> list:
        """(F) Retourne la liste des produits géolocalisables où le nombre géolocalisé
        est strictement inférieur au nombre posé (après application du payload)."""
        merged = {str(p.get("designation")): dict(p) for p in ((entry or {}).get("products") or [])}
        for item in (fields.get("products") or []):
            d0 = str(item.get("designation") or "")
            node = merged.setdefault(d0, {"designation": d0})
            if "reel" in item:
                node["reel"] = item["reel"]
            if "geo" in item:
                node["geo"] = item["geo"]
        out = []
        totals = (matnode or {}).get("totals") or {}
        types = (matnode or {}).get("types") or {}
        for desig in totals.keys():
            typ = types.get(desig) or ""
            if is_camera_fixation(desig, typ):
                continue
            fam = classify_family(typ, desig)
            if fam not in GEO_KEYS:
                continue
            m = merged.get(desig) or {}
            reel = m.get("reel")
            geo = m.get("geo")
            if reel is None or float(reel or 0) <= 0:
                continue
            if geo is None or float(geo or 0) < float(reel):
                gap = float(reel) - float(geo or 0)
                out.append(f"{desig} : {int(gap) if gap.is_integer() else round(gap, 2)} posé(s) non géolocalisé(s)")
        return out

    async def _guarded_allee_update(d: dict, doc: dict, payload: AlleeUpdate, author: str):
        matnode = _materiel_par_allee_with_zs(d).get(payload.uid) or {}
        fields = payload.dict(exclude_unset=True)
        new_status = fields.get("status")
        # (G) Statut "non_faite" — commentaire obligatoire (nuit de rattrapage optionnelle)
        # Si nuit_rattrapage fournie : on déplace automatiquement l'allée sur cette nuit
        #   et on la remet en "a_faire" pour qu'elle soit prête à être travaillée.
        # Sinon : l'allée reste "non_faite" sur la nuit d'origine → visible "En attente".
        if new_status == "non_faite":
            entry_g = next((e for e in (doc.get("allees") or []) if str(e.get("uid")) == payload.uid), {})
            has_comment = bool((fields.get("comment") or entry_g.get("comment") or "").strip())
            if not has_comment:
                raise HTTPException(
                    status_code=400,
                    detail="Allée « non faite » : commentaire obligatoire (pourquoi ?)")
            # Si une nuit de rattrapage est spécifiée → déplacement auto + reset status
            nr = fields.get("nuit_rattrapage")
            if nr is not None and nr > 0:
                # Modifier le payload directement + forcer l'inclusion dans __fields_set__
                # (car _apply_allee_update relit payload.dict(exclude_unset=True))
                payload.status = "a_faire"
                payload.nuit_reelle = int(nr)
                payload.nuit_rattrapage = None
                payload.__fields_set__.add("status")
                payload.__fields_set__.add("nuit_reelle")
                payload.__fields_set__.add("nuit_rattrapage")
                new_status = "a_faire"
        if new_status == "validee":
            entry = next((e for e in (doc.get("allees") or []) if str(e.get("uid")) == payload.uid), {})
            # (F) Géoloc = nombre de produits posés (validation bloquante sauf explication)
            gap_details = _check_geoloc_gap(matnode, entry, fields)
            if gap_details:
                geo_comment = (fields.get("geoloc_comment") or entry.get("geoloc_comment") or "").strip()
                if not geo_comment:
                    raise HTTPException(
                        status_code=400,
                        detail="Écart de géolocalisation : " + " · ".join(gap_details)
                               + " → renseigne le commentaire de géolocalisation avant de valider")
            justifs = _justifs_after_update(matnode, entry, fields)
            if justifs and not (fields.get("justification") or "").strip() and not (entry.get("justification") or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="Justification requise : écart de plus de 5% sur " + ", ".join(justifs))
        valid = set((matnode.get("totals") or {}).keys())
        return await _apply_allee_update(doc["upload_id"], doc, payload, author,
                                         valid_designations=valid or None)

    # ================================================== ROUTES AUTHENTIFIÉES ====
    @router.get("/{upload_id}")
    async def get_suivi(upload_id: str, current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return _build_state(d, doc, upload_id)

    @router.patch("/{upload_id}/allee")
    async def update_allee(upload_id: str, payload: AlleeUpdate,
                           current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        uid = await _guarded_allee_update(d, doc, payload, current_user.get("email") or "")
        return {"ok": True, "uid": uid}

    @router.patch("/{upload_id}/allee-cam")
    async def update_cam_allee(upload_id: str, payload: CamAlleeUpdate,
                               current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        uid = await _apply_cam_update(upload_id, doc, payload, current_user.get("email") or "")
        return {"ok": True, "uid": uid}

    @router.get("/{upload_id}/materiel")
    async def get_materiel(upload_id: str, mode: str = "eeg",
                           current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return _materiel_overview(d, doc, mode=mode)

    @router.get("/{upload_id}/materiel/{nuit}")
    async def get_materiel_nuit(upload_id: str, nuit: int, mode: str = "eeg",
                                current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return _materiel_nuit(d, doc, nuit, mode=mode)

    async def _apply_stock_update(upload_id: str, doc: dict, payload: StockUpdate):
        arr = doc.get("stock_received")
        if not isinstance(arr, list):
            arr = []
        arr = [s for s in arr if str(s.get("designation")) != payload.designation]
        if payload.recu is not None:
            arr.append({"designation": payload.designation, "recu": float(payload.recu)})
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$set": {"stock_received": arr}})

    @router.patch("/{upload_id}/stock")
    async def update_stock(upload_id: str, payload: StockUpdate,
                           current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        await _apply_stock_update(upload_id, doc, payload)
        return {"ok": True}

    @router.post("/{upload_id}/incident")
    async def add_incident(upload_id: str, payload: IncidentCreate,
                           current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        await _get_doc(upload_id, str(current_user["_id"]))
        return await _create_incident(upload_id, payload, current_user.get("email") or "")

    @router.delete("/{upload_id}/incident/{incident_id}")
    async def delete_incident(upload_id: str, incident_id: str,
                              current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        await db.suivi_docs.update_one({"upload_id": upload_id},
                                       {"$pull": {"incidents": {"id": incident_id}}})
        return {"ok": True}

    @router.post("/{upload_id}/allee-photo")
    async def add_allee_photo(upload_id: str, uid: str = Form(...), file: UploadFile = File(...),
                              current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return await _add_photo(upload_id, doc, uid, file, current_user.get("email") or "")

    @router.get("/{upload_id}/photo/{photo_id}")
    async def get_allee_photo(upload_id: str, photo_id: str,
                              current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return _photo_response(doc, photo_id)

    @router.delete("/{upload_id}/photo/{photo_id}")
    async def del_allee_photo(upload_id: str, photo_id: str,
                              current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return await _delete_photo(upload_id, doc, photo_id)

    @router.get("/{upload_id}/rapport-nuit/{nuit}")
    async def rapport_nuit(upload_id: str, nuit: int,
                           current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return _rapport_response(d, doc, upload_id, nuit)

    @router.post("/{upload_id}/publish")
    async def publish_suivi(upload_id: str, payload: PublishUpdate,
                            current_user: dict = Depends(get_current_user)):
        """Publie/dépublie le magasin dans l'espace terrain commun (créateur du phasage)."""
        await _load(upload_id, current_user)
        await _get_doc(upload_id, str(current_user["_id"]))
        await db.suivi_docs.update_one(
            {"upload_id": upload_id},
            {"$set": {"published": payload.published,
                      "published_by": current_user.get("email") or "",
                      "published_at": datetime.now(timezone.utc).isoformat()}})
        return {"ok": True, "published": payload.published}

    @router.delete("/{upload_id}/reset")
    async def reset_suivi(upload_id: str, current_user: dict = Depends(get_current_user)):
        """Efface toutes les données du suivi (saisies, caméras, incidents, stock, photos).
        Réservé au créateur du phasage et à l'administrateur."""
        is_admin = (current_user.get("role") in ("admin", "superadmin"))
        d = await load_dataset(upload_id, user_id=None if is_admin else str(current_user["_id"]))
        if d is None:
            raise HTTPException(status_code=404, detail="Dataset introuvable")
        if not is_admin and str(d.get("user_id") or "") != str(current_user["_id"]):
            raise HTTPException(status_code=403,
                                detail="Seul le créateur du phasage ou l'administrateur peut effacer le suivi")
        await db.suivi_docs.update_one(
            {"upload_id": upload_id},
            {"$set": {"allees": [], "cam_allees": [], "incidents": [], "stock_received": {}}})
        return {"ok": True}

    @router.post("/{upload_id}/replan")
    async def replan(upload_id: str, payload: ReplanRequest,
                     current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        state = _build_state(d, doc, upload_id)
        st = state["stats"]
        if not st["rythme_reel"]:
            raise HTTPException(status_code=400,
                                detail="Aucune nuit terminée (toutes allées validées) : impossible d'estimer le rythme réel.")
        remaining = [x for x in state["allees"] if x["status"] != "validee"]
        if not remaining:
            raise HTTPException(status_code=400, detail="Toutes les allées sont déjà validées.")
        done_nights = [n["nuit"] for n in state["nights"] if n["complete"]]
        start_night = (max(done_nights) + 1) if done_nights else 1
        cap = min(MAX_EEG_PER_NIGHT, max(float(st["rythme_reel"]), float(st["rythme_prevu"] or 0)))
        old_nuit = {x["uid"]: x["nuit_plan"] for x in remaining}
        mapping = {}
        cur_n, cur_load = start_night, 0.0
        for x in remaining:
            w = float(x["eeg_plan"] or 0)
            if cur_load > 0 and cur_load + w > cap:
                cur_n += 1
                cur_load = 0.0
            mapping[x["uid"]] = cur_n
            cur_load += w
        new_last = max(mapping.values())
        nuits_gagnees = state["nb_nuits"] - new_last
        changed = sum(1 for u, n in mapping.items() if n != old_nuit.get(u))
        prev = {}
        for x in remaining:
            nn = mapping[x["uid"]]
            p = prev.setdefault(nn, {"nuit": nn, "date": state["dates"].get(str(nn)) or "",
                                     "nb_allees": 0, "eeg": 0.0, "allees": []})
            p["nb_allees"] += 1
            p["eeg"] = _r(p["eeg"] + (x["eeg_plan"] or 0))
            p["allees"].append(str(x["allee"]))
        preview = sorted(prev.values(), key=lambda p: p["nuit"])

        if payload.apply:
            ph = normalize_phasage(d.get("phasage"))
            try:
                await save_phasage_snapshot(upload_id, current_user, ph)
            except Exception as e:
                logger.warning(f"Snapshot avant replan échoué: {e}")
            for row in ph.get("es", {}).get("rows") or []:
                uidr = str(row.get("allee") or row.get("id"))
                if uidr in mapping:
                    row["nuit"] = mapping[uidr]
            d["phasage"] = ph
            await persist_phasage(upload_id, ph)
            arr = doc.get("allees") or []
            for e in arr:
                if str(e.get("uid")) in mapping:
                    e["nuit_reelle"] = None
            await db.suivi_docs.update_one({"upload_id": upload_id}, {"$set": {"allees": arr}})

        return {
            "ok": True,
            "applied": payload.apply,
            "start_night": start_night,
            "capacity": _r(cap),
            "rythme_reel": st["rythme_reel"],
            "rythme_prevu": st["rythme_prevu"],
            "nuits_gagnees": nuits_gagnees,
            "allees_deplacees": changed,
            "preview": preview,
        }

    # ============================================= ROUTES TERRAIN (SANS COMPTE) ====
    @terrain.get("/stores")
    async def terrain_stores():
        """Liste PUBLIQUE des magasins publiés au suivi terrain."""
        docs = await db.suivi_docs.find({"published": True},
                                        {"_id": 0, "upload_id": 1, "published_by": 1}).to_list(length=200)
        out = []
        for doc in docs:
            meta = await db.datasets.find_one(
                {"upload_id": doc["upload_id"]},
                {"_id": 0, "filename": 1, "label": 1, "store_name": 1, "store_code": 1, "uploaded_at": 1})
            if not meta:
                continue
            out.append({
                "upload_id": doc["upload_id"],
                "store_name": meta.get("store_name") or "",
                "store_code": meta.get("store_code") or "",
                "label": meta.get("label") or "",
                "filename": meta.get("filename") or "",
                "published_by": doc.get("published_by") or "",
            })
        out.sort(key=lambda s: (s["store_name"] or s["label"] or s["filename"]).lower())
        return {"stores": out}

    @terrain.get("/{upload_id}")
    async def terrain_state(upload_id: str):
        d, doc = await _resolve_terrain(upload_id)
        return _build_state(d, doc, doc["upload_id"], is_terrain=True)

    @terrain.patch("/{upload_id}/allee")
    async def terrain_update_allee(upload_id: str, payload: AlleeUpdate):
        d, doc = await _resolve_terrain(upload_id)
        uid = await _guarded_allee_update(d, doc, payload, "équipe terrain")
        return {"ok": True, "uid": uid}

    @terrain.post("/{upload_id}/incident")
    async def terrain_add_incident(upload_id: str, payload: IncidentCreate):
        d, doc = await _resolve_terrain(upload_id)
        return await _create_incident(doc["upload_id"], payload, "équipe terrain")

    @terrain.delete("/{upload_id}/incident/{incident_id}")
    async def terrain_del_incident(upload_id: str, incident_id: str):
        d, doc = await _resolve_terrain(upload_id)
        await db.suivi_docs.update_one({"upload_id": doc["upload_id"]},
                                       {"$pull": {"incidents": {"id": incident_id}}})
        return {"ok": True}

    @terrain.post("/{upload_id}/allee-photo")
    async def terrain_add_photo(upload_id: str, uid: str = Form(...), file: UploadFile = File(...)):
        d, doc = await _resolve_terrain(upload_id)
        return await _add_photo(doc["upload_id"], doc, uid, file, "équipe terrain")

    @terrain.get("/{upload_id}/photo/{photo_id}")
    async def terrain_get_photo(upload_id: str, photo_id: str):
        d, doc = await _resolve_terrain(upload_id)
        return _photo_response(doc, photo_id)

    @terrain.delete("/{upload_id}/photo/{photo_id}")
    async def terrain_del_photo(upload_id: str, photo_id: str):
        d, doc = await _resolve_terrain(upload_id)
        return await _delete_photo(doc["upload_id"], doc, photo_id)

    @terrain.get("/{upload_id}/rapport-nuit/{nuit}")
    async def terrain_rapport(upload_id: str, nuit: int):
        d, doc = await _resolve_terrain(upload_id)
        return _rapport_response(d, doc, doc["upload_id"], nuit)

    @terrain.patch("/{upload_id}/allee-cam")
    async def terrain_update_cam(upload_id: str, payload: CamAlleeUpdate):
        d, doc = await _resolve_terrain(upload_id)
        uid = await _apply_cam_update(doc["upload_id"], doc, payload, "équipe terrain")
        return {"ok": True, "uid": uid}

    @terrain.patch("/{upload_id}/stock")
    async def terrain_update_stock(upload_id: str, payload: StockUpdate):
        d, doc = await _resolve_terrain(upload_id)
        await _apply_stock_update(doc["upload_id"], doc, payload)
        return {"ok": True}

    @terrain.get("/{upload_id}/materiel")
    async def terrain_materiel(upload_id: str, mode: str = "eeg"):
        d, doc = await _resolve_terrain(upload_id)
        return _materiel_overview(d, doc, mode=mode)

    @terrain.get("/{upload_id}/materiel/{nuit}")
    async def terrain_materiel_nuit(upload_id: str, nuit: int, mode: str = "eeg"):
        d, doc = await _resolve_terrain(upload_id)
        return _materiel_nuit(d, doc, nuit, mode=mode)

    parent = APIRouter()
    parent.include_router(router)
    parent.include_router(terrain)
    return parent
