"""Suivi de déploiement — API de l'app séparée (/suivi).

Validation des allées (prévu VS réel posé VS géolocalisé), photos par allée,
stock & alertes rupture, incidents par nuit, rapport Excel par nuit (avec photos),
replanification automatique, accès équipe terrain sans compte (token).
"""
import io
import math
import os
import secrets
import uuid
import logging
from datetime import datetime, timezone, date
from typing import Optional, List

import requests as _requests
import xlsxwriter
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
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


# (v28 iter6) Produits masqués dans TOUT le module Suivi (matériel, stock,
# écrans allée, exports). Ces items ne se posent pas physiquement — ils sont
# commandés/livrés séparément et n'ont pas leur place dans le suivi terrain.
SUIVI_HIDDEN_DESIGNATIONS = {"batterie caméra", "software caméra"}


def is_hidden_in_suivi(desig: str) -> bool:
    """True si le produit doit être masqué de tous les écrans/exports du Suivi."""
    return (desig or "").strip().lower() in SUIVI_HIDDEN_DESIGNATIONS


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
    # (iter34+35) On CONSERVE le bonus rails → ES 1.5 (convention Phasage : « 1 rail
    # = +1 ES 1.5 »). Cela aligne les totaux Phasage et Suivi (ex : 92 403 EEG
    # dans les deux outils au lieu de 92 403 vs 82 263). Le posé compense en
    # ajoutant automatiquement +1 ES 1.5 pour chaque rail posé (voir
    # `_apply_rail_bonus_to_reel` plus bas), donc à 100% de pose on obtient
    # bien eeg_reel == eeg_plan.
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


def _rail_bonus_qty(desig: str, qty: float) -> float:
    """Retourne la qté de « bonus ES 1.5 » induite par la pose d'un rail.
    Convention Phasage : 1 rail (parmi RAILS_BONUS_ES15) = +1 ES 1.5 de même
    couleur. On l'ajoute côté posé pour garder la cohérence Phasage↔Suivi."""
    from server import RAILS_BONUS_ES15
    d = (desig or "").lower().strip()
    for pat, _color in RAILS_BONUS_ES15:
        if pat.lower() in d:
            return float(qty or 0)
    return 0.0


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
    justif_ok: Optional[bool] = None  # (iter36) case "Tout est OK" cochée par le poseur
                                       # → l'écart n'est plus considéré comme critique
    nuit_reelle: Optional[int] = None  # 0 → retour à la nuit planifiée
    nuit_rattrapage: Optional[int] = None  # nuit prévue pour rattraper une allée non faite


class CamAlleeUpdate(BaseModel):
    uid: str
    # (v28 iter6) Saisie par produit — même modèle que le côté EEG.
    # Chaque produit a `reel` (posé), `geo` (géolocalisé, uniquement pour caméras).
    products: Optional[List[ProductEntry]] = None
    # Champs LEGACY (deprecated) — encore acceptés pour rétrocompat client mais
    # convertis automatiquement en `products` côté backend. À supprimer dès que
    # tous les clients seront migrés.
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
                    # (iter35) Bonus rail → ES 1.5 : si le produit posé est un rail
                    # de RAILS_BONUS_ES15, on incrémente automatiquement es_15 du
                    # même montant, pour être cohérent avec la logique Phasage
                    # qui compte "1 rail = +1 ES 1.5" dans le prévu.
                    bonus = _rail_bonus_qty(desig, preel) if fam == "rails_es" else 0.0
                    if bonus > 0:
                        reel_fam["es_15"] = _r((reel_fam["es_15"] or 0) + bonus)
                if pgeo is not None and is_geo:
                    geo_fam[fam] = _r((geo_fam[fam] or 0) + pgeo)
                pgap = 0
                if is_geo and preel is not None and pgeo is not None and pgeo < preel:
                    pgap = _r(preel - pgeo)
                    gap_fam[fam] = _r(gap_fam[fam] + pgap)
                products.append({
                    "designation": desig, "type": typ, "family": fam,
                    "reference": (mat.get("refs") or {}).get(desig) or "",  # (iter40) SKU/référence
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
                "justif_ok": bool(e.get("justif_ok")),  # (iter36) case "Tout est OK" cochée
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
            # (iter34) Géoloc en UNITÉS (rails_es + sa_15 + sa_21_std)
            geo_eeg_plan_night = sum(sum(float((x.get("plan") or {}).get(k) or 0) for k in GEO_KEYS) for x in items)
            geo_eeg_reel_night = sum(sum(float((x.get("geo") or {}).get(k) or 0) for k in GEO_KEYS) for x in items)
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
                # (iter34) Unités géoloc EEG par nuit (utilisé par le dashboard)
                "geo_eeg_prevues": _r(geo_eeg_plan_night),
                "geo_eeg_posees": _r(geo_eeg_reel_night),
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
        # (iter40) On garde la référence produit (SKU) pour l'afficher côté stock
        prod_agg = {}
        # Construit un index désignation → référence globale (première non-vide trouvée)
        refs_by_desig = {}
        for uid_x, node in matidx.items():
            for dg, rf in (node.get("refs") or {}).items():
                if rf and dg not in refs_by_desig:
                    refs_by_desig[dg] = rf
        for x in allees:
            not_valid = x["status"] != "validee"
            for p in x["products"]:
                g = prod_agg.setdefault(p["designation"], {
                    "designation": p["designation"], "type": p["type"], "family": p["family"],
                    "reference": refs_by_desig.get(p["designation"]) or "",
                    "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0})
                g["prevu"] += p["plan"] or 0
                g["pose"] += p["reel"] or 0
                if not_valid:
                    g["restant_a_poser"] += max(0.0, (p["plan"] or 0) - (p["reel"] or 0))
            for ep in x["extra_products"]:
                g = prod_agg.setdefault(ep["designation"], {
                    "designation": ep["designation"], "type": "", "family": None,
                    "reference": refs_by_desig.get(ep["designation"]) or "",
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
        # (v28 iter2) Fusion des Zones Saisonnières + Flèches + Signalétique
        # dans les SA/ES (noir/blanc) correspondants — POUR L'AFFICHAGE STOCK
        # UNIQUEMENT. Les autres écrans (matériel/allée) gardent les désignations
        # séparées pour la traçabilité. Les poseurs reçoivent UNE seule livraison
        # de SA 1.5 noir, SA 2.1 noir, ES 1.5 noir, ES 1.5 blanc.
        _RAILS_BONUS_COLORS = [
            ("1187 mm (noir)", "noir"), ("1187 mm (blanc)", "blanc"),
            ("1240 mm (noir)", "noir"), ("1320 mm (blanc)", "blanc"),
            ("1320 mm (noir)", "noir"), ("535 mm (noir)", "noir"),
            ("650 mm (noir)", "noir"), ("990 mm (blanc)", "blanc"),
            ("990 mm (noir)", "noir"),
        ]

        def _signaletique_color(dg: str) -> str | None:
            dl = (dg or "").lower()
            for pat, col in _RAILS_BONUS_COLORS:
                if pat in dl:
                    return col
            return None

        def _is_fleche_line(dg: str, typ: str) -> bool:
            import unicodedata
            for s in (dg, typ):
                norm = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
                if "fleche" in norm:
                    return True
            return False

        def _find_target(prefix: str, color: str | None = None) -> str | None:
            """Cherche une désignation cible dans prod_agg matchant un préfixe
            et une couleur optionnelle. Ex: prefix='sa 1.5', color='noir'
            → 'SA 1.5 (noir)' ou 'SA 1.5 noir'."""
            pref_l = prefix.lower()
            for dg in prod_agg.keys():
                dgl = dg.lower()
                if not dgl.startswith(pref_l):
                    continue
                if "saisonn" in dgl:
                    continue  # évite de rediriger vers la ZS synthétique
                if color and color not in dgl:
                    continue
                return dg
            return None

        def _merge_into(source_desig: str, target_desig: str):
            src = prod_agg.pop(source_desig, None)
            if not src:
                return
            if target_desig in prod_agg:
                tgt = prod_agg[target_desig]
                tgt["prevu"] += src["prevu"]
                tgt["pose"] += src["pose"]
                tgt["restant_a_poser"] += src["restant_a_poser"]
            else:
                src["designation"] = target_desig
                prod_agg[target_desig] = src

        # 1) Zones Saisonnières → SA (noir)
        for zs_desig, prefix in (("SA 1.5 (Zone saisonnier)", "sa 1.5"),
                                 ("SA 2.1 (Zone saisonnier)", "sa 2.1")):
            if zs_desig not in prod_agg:
                continue
            target = _find_target(prefix, color="noir") or f"{prefix.upper().replace('SA', 'SA')} (noir)"
            _merge_into(zs_desig, target)

        # 2) Flèches → ES 1.5 (noir) [détection sur désignation OU type]
        fleche_desigs = [
            dg for dg, g in prod_agg.items()
            if _is_fleche_line(dg, g.get("type", ""))
        ]
        target_es15_noir = _find_target("es 1.5", color="noir") or "ES 1.5 (noir)"
        for dg in fleche_desigs:
            _merge_into(dg, target_es15_noir)

        # 3) Signalétique NON-rail → ES 1.5 (couleur).
        # (iter41) Les Rails ES (family=="rails_es") restent VISIBLES comme lignes
        # distinctes dans le stock — l'équipe terrain gère la livraison des rails
        # séparément de celle des étiquettes ES 1.5. Une signalétique non-rail
        # (rare) matcherait ici pour être absorbée.
        signal_by_color = {"noir": [], "blanc": []}
        for dg in list(prod_agg.keys()):
            fam_dg = (prod_agg[dg] or {}).get("family")
            if fam_dg == "rails_es":
                continue  # on garde les rails ES en ligne distincte
            col = _signaletique_color(dg)
            if col:
                signal_by_color[col].append(dg)
        for col, desigs in signal_by_color.items():
            if not desigs:
                continue
            target = _find_target("es 1.5", color=col) or f"ES 1.5 ({col})"
            for dg in desigs:
                _merge_into(dg, target)

        # 4) Bonus rails → ES 1.5 (couleur) SANS retirer les rails du stock.
        # (iter42) Reprend EXACTEMENT la règle de l'outil de phasage (voir
        # server.compute_phasage_summary lignes 2718-2736 + PhasageTab.jsx :
        # `es_15_bonus_noir/blanc`). Source de vérité : tout produit dont le
        # type est "Rail" ET dont la désignation matche RAILS_BONUS_ES15 ajoute
        # sa quantité à l'ES 1.5 de sa couleur. Le rail reste visible sur sa
        # propre ligne — pas de fusion. Ces deux produits physiques distincts
        # sont livrés séparément : le rail + l'étiquette ES 1.5 posée dessus.
        # NB : ce périmètre inclut "1187 mm (blanc)" (dans RAILS_BONUS_ES15 mais
        # PAS dans RAILS_ES_PATTERNS) — comme dans le recap commande.
        rail_bonus_by_color = {
            "noir": {"prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0},
            "blanc": {"prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0},
        }
        for dg, g in prod_agg.items():
            typ_g = ((g or {}).get("type") or "").strip().lower()
            fam_g = (g or {}).get("family")
            # Aligné phasage : rail = (type=="rail") OU family=="rails_es"
            if typ_g != "rail" and fam_g != "rails_es":
                continue
            col = _signaletique_color(dg)  # utilise _RAILS_BONUS_COLORS
            if col not in rail_bonus_by_color:
                continue
            rail_bonus_by_color[col]["prevu"] += float(g.get("prevu") or 0)
            rail_bonus_by_color[col]["pose"] += float(g.get("pose") or 0)
            rail_bonus_by_color[col]["restant_a_poser"] += float(g.get("restant_a_poser") or 0)
        for col, bonus in rail_bonus_by_color.items():
            if bonus["prevu"] <= 0 and bonus["pose"] <= 0:
                continue
            target = _find_target("es 1.5", color=col) or f"ES 1.5 ({col})"
            tgt = prod_agg.get(target)
            if tgt is None:
                tgt = {"designation": target, "type": "", "family": "es_15",
                       "reference": refs_by_desig.get(target) or "",
                       "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0}
                prod_agg[target] = tgt
            tgt["prevu"] += bonus["prevu"]
            tgt["pose"] += bonus["pose"]
            tgt["restant_a_poser"] += bonus["restant_a_poser"]

        # 5) Bonus flèches fixe → ES 1.5 (noir) prévu uniquement.
        # (iter42) Correspond à server.FLECHE_FIXED_ES15_NOIR (=600) : réserve
        # commande qui n'est pas posée physiquement (pas de pose ni de reste
        # à poser). Le "reçu" étant théorique = prévu, ces 600 apparaissent
        # comme surplus naturel dans "reste stock".
        try:
            from server import FLECHE_FIXED_ES15_NOIR as _FL_FIX
        except ImportError:
            _FL_FIX = 0
        if _FL_FIX and _FL_FIX > 0:
            target = _find_target("es 1.5", color="noir") or "ES 1.5 (noir)"
            tgt = prod_agg.get(target)
            if tgt is None:
                tgt = {"designation": target, "type": "", "family": "es_15",
                       "reference": refs_by_desig.get(target) or "",
                       "prevu": 0.0, "pose": 0.0, "restant_a_poser": 0.0}
                prod_agg[target] = tgt
            tgt["prevu"] += float(_FL_FIX)

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
                "reference": g.get("reference") or "",  # (iter40) SKU produit
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
            # (v28 iter6) Liste détaillée des produits cam AVEC saisie par produit.
            entry_products = {p.get("designation"): p for p in (e.get("products") or []) if p.get("designation")}
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
                # Saisie par produit (reel, geo pour caméras uniquement)
                pentry = entry_products.get(dg) or {}
                p_reel = pentry.get("reel")
                p_geo = pentry.get("geo") if is_camera_device else None
                p_reel_r = None if p_reel is None else _r(float(p_reel))
                p_geo_r = None if p_geo is None else _r(float(p_geo))
                p_geo_gap = (_r(p_reel_r - p_geo_r) if (is_camera_device and p_reel_r is not None
                             and p_geo_r is not None and p_geo_r < p_reel_r) else 0)
                cam_products.append({
                    "designation": dg,
                    "type": tdg,
                    "reference": (matc.get("refs") or {}).get(dg) or "",  # (iter40) SKU
                    "is_camera": is_camera_device,
                    "is_fixation": (not is_camera_device),
                    "plan": pr,
                    "reel": p_reel_r,
                    "geo": p_geo_r,
                    "geo_gap": p_geo_gap,
                    "is_geo": is_camera_device,
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

        # Totaux unitaires géoloc EEG (rails_es + sa_15 + sa_21_std uniquement)
        geo_eeg_plan = _r(sum(sum(float((x.get("plan") or {}).get(k) or 0) for k in GEO_KEYS) for x in allees))
        geo_eeg_reel = _r(sum(sum(float((x.get("geo") or {}).get(k) or 0) for k in GEO_KEYS) for x in allees))
        # Totaux caméras (unités posées + géolocalisées)
        cam_total_plan = _r(sum(float(x.get("plan") or 0) for x in cam_allees))
        cam_total_reel = _r(sum(float(x.get("reel") or 0) for x in cam_allees))
        cam_total_geo = _r(sum(float(x.get("geo") or 0) for x in cam_allees))

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
                # --- POSE EEG (unités) --- (calcul consistant plan == reel@100%)
                "eeg_prevues": total_eeg_plan,
                "eeg_posees": total_eeg_reel,
                "pct": _r(100.0 * total_eeg_reel / total_eeg_plan) if total_eeg_plan else 0,
                # --- GÉOLOCALISATION EEG (unités) --- (rails_es + sa_15 + sa_21_std)
                "geo_eeg_prevues": geo_eeg_plan,
                "geo_eeg_posees": geo_eeg_reel,
                "geo_eeg_pct": _r(100.0 * geo_eeg_reel / geo_eeg_plan) if geo_eeg_plan else 0,
                # --- POSE CAMÉRA (unités) ---
                "cam_prevues": cam_total_plan,
                "cam_posees": cam_total_reel,
                "cam_pct": _r(100.0 * cam_total_reel / cam_total_plan) if cam_total_plan else 0,
                # --- GÉOLOCALISATION CAMÉRA (unités) ---
                "cam_geo_prevues": cam_total_reel,  # on ne géoloc que ce qui est posé
                "cam_geo_posees": cam_total_geo,
                "cam_geo_pct": _r(100.0 * cam_total_geo / cam_total_reel) if cam_total_reel else 0,
                # --- Divers (allées / retards / …) ---
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

        # ═══════════════════════════════════════════════════════════════
        # PALETTE COULEURS — bleu Carrefour comme couleur principale
        # ═══════════════════════════════════════════════════════════════
        C_BLUE = "#005BAB"        # Carrefour blue
        C_BLUE_LIGHT = "#DBEAFE"
        C_BLUE_ULTRA = "#EFF6FF"
        C_SUCCESS = "#059669"      # vert émeraude
        C_SUCCESS_BG = "#D1FAE5"
        C_WARNING = "#D97706"      # orange
        C_WARNING_BG = "#FEF3C7"
        C_DANGER = "#DC2626"       # rouge
        C_DANGER_BG = "#FEE2E2"
        C_NEUTRAL = "#6B7280"      # gris
        C_ZEBRA = "#F9FAFB"

        # Formats de base
        f_title = wb.add_format({"bold": True, "font_size": 22, "font_color": "white",
                                 "bg_color": C_BLUE, "align": "center", "valign": "vcenter"})
        f_subtitle = wb.add_format({"font_size": 12, "font_color": "white",
                                    "bg_color": C_BLUE, "align": "center", "valign": "vcenter"})
        f_sub = wb.add_format({"font_size": 10, "font_color": C_NEUTRAL, "italic": True})
        f_section = wb.add_format({"bold": True, "font_size": 14, "font_color": C_BLUE,
                                   "bottom": 2, "bottom_color": C_BLUE})
        f_h = wb.add_format({"bold": True, "bg_color": C_BLUE, "font_color": "white",
                             "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
        f_c = wb.add_format({"border": 1, "align": "center", "valign": "vcenter"})
        f_cl = wb.add_format({"border": 1, "valign": "vcenter"})
        f_c_zebra = wb.add_format({"border": 1, "align": "center", "valign": "vcenter", "bg_color": C_ZEBRA})
        f_cl_zebra = wb.add_format({"border": 1, "valign": "vcenter", "bg_color": C_ZEBRA})
        f_ok = wb.add_format({"border": 1, "align": "center", "bg_color": C_BLUE_LIGHT, "bold": True, "font_color": C_BLUE})
        # (iter43) Vert pour les cellules « pose conforme ou dépassement » — utilisé
        # dans les tableaux d'écart (delta EEG). Le rouge est réservé aux vrais
        # problèmes (bloqué, à finaliser). Un écart négatif sans commentaire = orange.
        f_delta_ok = wb.add_format({"border": 1, "align": "center", "bg_color": C_SUCCESS_BG, "font_color": C_SUCCESS, "bold": True})
        f_neg = wb.add_format({"border": 1, "align": "center", "bg_color": C_DANGER_BG, "font_color": C_DANGER, "bold": True})
        # (iter36) écart validé "Tout est OK" — orange doux au lieu de rouge alarmant
        f_neg_soft = wb.add_format({"border": 1, "align": "center", "bg_color": C_WARNING_BG, "font_color": C_WARNING, "bold": True})
        f_pos = wb.add_format({"border": 1, "align": "center", "bg_color": C_WARNING_BG, "font_color": C_WARNING, "bold": True})
        f_geo_bad = wb.add_format({"border": 1, "align": "center", "bg_color": C_DANGER_BG, "font_color": C_DANGER, "bold": True})
        f_tot = wb.add_format({"bold": True, "border": 2, "align": "center", "bg_color": "#E0E7FF", "font_color": C_BLUE})
        f_kpi_l = wb.add_format({"bold": True, "font_size": 11})
        # KPI cards colorées
        f_kpi_card_label = wb.add_format({"font_size": 10, "font_color": "white", "bg_color": C_BLUE,
                                          "align": "center", "valign": "vcenter", "text_wrap": True,
                                          "top": 2, "left": 2, "right": 2, "top_color": C_BLUE, "left_color": C_BLUE, "right_color": C_BLUE})
        f_kpi_card_val = wb.add_format({"font_size": 20, "bold": True, "font_color": C_BLUE,
                                        "align": "center", "valign": "vcenter", "bg_color": "white",
                                        "bottom": 2, "left": 2, "right": 2, "bottom_color": C_BLUE, "left_color": C_BLUE, "right_color": C_BLUE})
        f_kpi_success_val = wb.add_format({"font_size": 20, "bold": True, "font_color": C_SUCCESS,
                                           "align": "center", "valign": "vcenter", "bg_color": C_SUCCESS_BG,
                                           "bottom": 2, "left": 2, "right": 2, "bottom_color": C_SUCCESS, "left_color": C_SUCCESS, "right_color": C_SUCCESS})
        f_kpi_success_lbl = wb.add_format({"font_size": 10, "font_color": "white", "bg_color": C_SUCCESS,
                                           "align": "center", "valign": "vcenter", "text_wrap": True,
                                           "top": 2, "left": 2, "right": 2, "top_color": C_SUCCESS, "left_color": C_SUCCESS, "right_color": C_SUCCESS})
        f_kpi_warn_val = wb.add_format({"font_size": 20, "bold": True, "font_color": C_WARNING,
                                        "align": "center", "valign": "vcenter", "bg_color": C_WARNING_BG,
                                        "bottom": 2, "left": 2, "right": 2, "bottom_color": C_WARNING, "left_color": C_WARNING, "right_color": C_WARNING})
        f_kpi_warn_lbl = wb.add_format({"font_size": 10, "font_color": "white", "bg_color": C_WARNING,
                                        "align": "center", "valign": "vcenter", "text_wrap": True,
                                        "top": 2, "left": 2, "right": 2, "top_color": C_WARNING, "left_color": C_WARNING, "right_color": C_WARNING})
        f_kpi_danger_val = wb.add_format({"font_size": 20, "bold": True, "font_color": C_DANGER,
                                          "align": "center", "valign": "vcenter", "bg_color": C_DANGER_BG,
                                          "bottom": 2, "left": 2, "right": 2, "bottom_color": C_DANGER, "left_color": C_DANGER, "right_color": C_DANGER})
        f_kpi_danger_lbl = wb.add_format({"font_size": 10, "font_color": "white", "bg_color": C_DANGER,
                                          "align": "center", "valign": "vcenter", "text_wrap": True,
                                          "top": 2, "left": 2, "right": 2, "top_color": C_DANGER, "left_color": C_DANGER, "right_color": C_DANGER})
        # Verdict
        f_verdict = wb.add_format({"font_size": 16, "bold": True, "align": "center", "valign": "vcenter",
                                   "text_wrap": True, "border": 2})
        # Sections colorées
        f_alert_title = wb.add_format({"bold": True, "font_size": 13, "font_color": "white",
                                       "bg_color": C_DANGER, "align": "left", "valign": "vcenter",
                                       "left": 2, "right": 2, "top": 2, "bottom": 2, "left_color": C_DANGER,
                                       "right_color": C_DANGER, "top_color": C_DANGER, "bottom_color": C_DANGER})
        f_comment_title = wb.add_format({"bold": True, "font_size": 13, "font_color": "white",
                                         "bg_color": C_WARNING, "align": "left", "valign": "vcenter",
                                         "left": 2, "right": 2, "top": 2, "bottom": 2, "left_color": C_WARNING,
                                         "right_color": C_WARNING, "top_color": C_WARNING, "bottom_color": C_WARNING})
        f_info_title = wb.add_format({"bold": True, "font_size": 13, "font_color": "white",
                                      "bg_color": C_BLUE, "align": "left", "valign": "vcenter",
                                      "left": 2, "right": 2, "top": 2, "bottom": 2, "left_color": C_BLUE,
                                      "right_color": C_BLUE, "top_color": C_BLUE, "bottom_color": C_BLUE})

        # ═══════════════════════════════════════════════════════════════
        # FEUILLE 1 — RÉSUMÉ VISUEL
        # ═══════════════════════════════════════════════════════════════
        ws = wb.add_worksheet(f"Résumé N{nuit}")
        ws.set_column(0, 11, 12)
        ws.set_row(0, 32)
        ws.set_row(1, 22)

        store = state["store_name"] or state["filename"]
        ws.merge_range(0, 0, 0, 11, f"⚡ RAPPORT DE NUIT N°{nuit}", f_title)
        subtitle_txt = f"{store}"
        if state["store_code"]:
            subtitle_txt += f"  ·  Code {state['store_code']}"
        if night.get("date"):
            try:
                dt = datetime.strptime(night["date"], "%Y-%m-%d")
                subtitle_txt += f"  ·  {dt.strftime('%A %d %B %Y')}"
            except Exception:
                subtitle_txt += f"  ·  {night['date']}"
        ws.merge_range(1, 0, 1, 11, subtitle_txt, f_subtitle)
        ws.write(2, 0, f"Généré le {datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M')} UTC", f_sub)

        # ---- Cartes KPI (grille 4×2) ----
        row = 4
        st = state["stats"]
        delta_n = night.get("delta_eeg")
        geo_gap_total = _r(sum(sum(x["geo_gap"].values()) for x in items if x["geo_gap"]))
        eeg_plan = int(night.get("eeg_plan") or 0)
        eeg_reel = int(night.get("eeg_reel") or 0)
        pct_pose = round(100 * eeg_reel / eeg_plan, 1) if eeg_plan > 0 else 0
        nb_val = night.get("nb_validees", 0)
        nb_all = night.get("nb_allees", 0)
        pct_val = round(100 * nb_val / nb_all, 1) if nb_all > 0 else 0

        # Choix des couleurs KPI en fonction des perfs
        def _card_style(pct):
            if pct >= 95:
                return (f_kpi_success_lbl, f_kpi_success_val)
            if pct >= 75:
                return (f_kpi_card_label, f_kpi_card_val)
            if pct >= 50:
                return (f_kpi_warn_lbl, f_kpi_warn_val)
            return (f_kpi_danger_lbl, f_kpi_danger_val)

        def _draw_kpi(r, col_start, col_end, label, value, style=(f_kpi_card_label, f_kpi_card_val)):
            lbl_fmt, val_fmt = style
            ws.set_row(r, 26)
            ws.set_row(r + 1, 42)
            ws.merge_range(r, col_start, r, col_end, label, lbl_fmt)
            ws.merge_range(r + 1, col_start, r + 1, col_end, value, val_fmt)

        # Ligne 1 : EEG posé, EEG prévu, Pose %, Écart
        _draw_kpi(row, 0, 2, "🎯 EEG POSÉES", f"{eeg_reel:,}".replace(",", " "),
                  _card_style(pct_pose))
        _draw_kpi(row, 3, 5, "📊 EEG PRÉVUES", f"{eeg_plan:,}".replace(",", " "))
        _draw_kpi(row, 6, 8, "⚡ TAUX DE POSE", f"{pct_pose}%",
                  _card_style(pct_pose))
        # ÉCART VS PRÉVU : vert si ≥ 0 (posé conforme ou dépassement),
        # orange si < 0 (simple écart entre comptage et pose, validé par le
        # poseur — pas un vrai retard). Le rouge est réservé aux vrais
        # problèmes (allées bloquées / retards justifiés par un commentaire).
        delta_str = f"{'+' if isinstance(delta_n, (int, float)) and delta_n > 0 else ''}{int(delta_n)}" if isinstance(delta_n, (int, float)) else "—"
        delta_style = (f_kpi_success_lbl, f_kpi_success_val) if isinstance(delta_n, (int, float)) and delta_n >= 0 else \
                      (f_kpi_warn_lbl, f_kpi_warn_val) if isinstance(delta_n, (int, float)) else \
                      (f_kpi_card_label, f_kpi_card_val)
        _draw_kpi(row, 9, 11, "📈 ÉCART VS PRÉVU", delta_str, delta_style)

        row += 3
        # Ligne 2 : Allées validées, à finaliser, non faites, géoloc manquante
        nb_a_fin = night.get("nb_a_finaliser", 0)
        nb_non_faites = sum(1 for x in items if x["status"] == "non_faite")
        _draw_kpi(row, 0, 2, "✅ ALLÉES VALIDÉES", f"{nb_val}/{nb_all}",
                  _card_style(pct_val))
        _draw_kpi(row, 3, 5, "⏳ À FINALISER", str(nb_a_fin),
                  (f_kpi_warn_lbl, f_kpi_warn_val) if nb_a_fin > 0 else (f_kpi_success_lbl, f_kpi_success_val))
        _draw_kpi(row, 6, 8, "🚫 NON FAITES", str(nb_non_faites),
                  (f_kpi_danger_lbl, f_kpi_danger_val) if nb_non_faites > 0 else (f_kpi_success_lbl, f_kpi_success_val))
        _draw_kpi(row, 9, 11, "📍 POSÉS SANS GÉOLOC", str(int(geo_gap_total)),
                  (f_kpi_warn_lbl, f_kpi_warn_val) if geo_gap_total > 0 else (f_kpi_success_lbl, f_kpi_success_val))
        row += 3

        # ---- Verdict de la nuit ----
        # (iter43) Un écart négatif entre EEG prévues et posées n'est PAS un
        # retard : c'est une différence entre le moment du comptage (par le
        # brief) et le moment de la pose (validé par le poseur sur le terrain).
        # Les VRAIS retards sont ceux justifiés par un commentaire du poseur
        # (retard de pose ou retard de géolocalisation) — voir sections
        # dédiées « Écarts > 5% justifiés » et « Écarts GÉOLOC » plus bas.
        # Rouge réservé aux vrais problèmes : allées bloquées ou retards
        # explicitement commentés.
        real_pose_delays = [
            x for x in items
            if x.get("justif_products")
            and not x.get("justif_ok")
            and (x.get("justification") or "").strip()
        ]
        real_geo_delays = [
            x for x in items
            if any((x.get("geo_gap") or {}).values())
            and (x.get("geoloc_comment") or "").strip()
        ]
        nb_bloq = sum(1 for x in items if x["status"] == "bloquee")
        if isinstance(delta_n, (int, float)):
            if delta_n > 500:
                verdict_txt = f"⚡🎉  BRAVO ! Nuit +{int(delta_n)} EEG au-dessus du prévisionnel"
                verdict_bg, verdict_fg = C_SUCCESS_BG, C_SUCCESS
            elif delta_n >= 0:
                verdict_txt = f"✅  Nuit conforme (+{int(delta_n)} EEG)"
                verdict_bg, verdict_fg = C_BLUE_LIGHT, C_BLUE
            else:
                # Écart négatif — orange par défaut (simple écart de comptage
                # validé par le poseur), pas de mention « retard ».
                verdict_txt = f"ℹ️  Écart de comptage vs pose ({int(delta_n)} EEG) — validé par le poseur"
                verdict_bg, verdict_fg = C_WARNING_BG, C_WARNING
        else:
            verdict_txt = "⏳  Nuit en cours"
            verdict_bg, verdict_fg = "#F3F4F6", C_NEUTRAL
        f_verdict_dyn = wb.add_format({"font_size": 16, "bold": True, "align": "center", "valign": "vcenter",
                                       "text_wrap": True, "bg_color": verdict_bg, "font_color": verdict_fg,
                                       "border": 2, "border_color": verdict_fg})
        ws.set_row(row, 40)
        ws.merge_range(row, 0, row, 11, verdict_txt, f_verdict_dyn)
        row += 2

        # ---- Bandeau(x) séparés pour VRAIS retards (avec commentaire) ----
        # (iter43) Retard de POSE et retard de GÉOLOC affichés séparément —
        # rouge uniquement s'il y a un commentaire ou une allée bloquée.
        if nb_bloq > 0:
            f_bloc_banner = wb.add_format({"font_size": 14, "bold": True, "align": "center",
                                           "valign": "vcenter", "text_wrap": True,
                                           "bg_color": C_DANGER_BG, "font_color": C_DANGER,
                                           "border": 2, "border_color": C_DANGER})
            ws.set_row(row, 30)
            ws.merge_range(row, 0, row, 11,
                           f"🚨  {nb_bloq} allée(s) BLOQUÉE(S) — intervention requise",
                           f_bloc_banner)
            row += 2
        if real_pose_delays:
            f_pose_banner = wb.add_format({"font_size": 14, "bold": True, "align": "center",
                                           "valign": "vcenter", "text_wrap": True,
                                           "bg_color": C_DANGER_BG, "font_color": C_DANGER,
                                           "border": 2, "border_color": C_DANGER})
            ws.set_row(row, 30)
            ws.merge_range(row, 0, row, 11,
                           f"🚨  Retard de pose EEG justifié : {len(real_pose_delays)} allée(s) — voir détail plus bas",
                           f_pose_banner)
            row += 2
        if real_geo_delays:
            f_geo_banner = wb.add_format({"font_size": 14, "bold": True, "align": "center",
                                          "valign": "vcenter", "text_wrap": True,
                                          "bg_color": C_DANGER_BG, "font_color": C_DANGER,
                                          "border": 2, "border_color": C_DANGER})
            ws.set_row(row, 30)
            ws.merge_range(row, 0, row, 11,
                           f"🚨  Retard de géolocalisation : {len(real_geo_delays)} allée(s) — voir détail plus bas",
                           f_geo_banner)
            row += 2

        # ---- Info bandeau écart cumulé uniquement ----
        # (iter38) Rythme moyen/prévu et avance/retard estimé retirés (jugés stressants
        # et peu fiables sur les premières nuits par l'utilisateur).
        ws.merge_range(row, 0, row, 11, "📊  Contexte de la campagne", f_info_title)
        ws.set_row(row, 22)
        row += 1
        info_lines = [
            ("Écart cumulé (nuits terminées)", st.get("cumul_delta_eeg")),
        ]
        for label, val in info_lines:
            ws.write(row, 0, "  " + label, f_kpi_l)
            ws.merge_range(row, 4, row, 5, val, f_c)
            row += 1
        row += 1

        # ---- Alertes stock ----
        stock_alerts = [s for s in (state.get("stock") or []) if s.get("alert")]
        if stock_alerts:
            ws.merge_range(row, 0, row, 11, f"⚠️  RISQUE MANQUE DE STOCK ({len(stock_alerts)} produit(s))", f_alert_title)
            ws.set_row(row, 22)
            row += 1
            for c, h in enumerate(["Produit", "Prévu", "Reçu", "Posé", "Restant stock", "Restant à poser", "Manque"]):
                if c == 0:
                    ws.merge_range(row, 0, row, 5, h, f_h)
                elif c == 1:
                    ws.write(row, 6, h, f_h)
                elif c == 2:
                    ws.write(row, 7, h, f_h)
                elif c == 3:
                    ws.write(row, 8, h, f_h)
                elif c == 4:
                    ws.write(row, 9, h, f_h)
                elif c == 5:
                    ws.write(row, 10, h, f_h)
                elif c == 6:
                    ws.write(row, 11, h, f_h)
            row += 1
            for i, s in enumerate(stock_alerts):
                fmtl = f_cl_zebra if i % 2 else f_cl
                fmtc = f_c_zebra if i % 2 else f_c
                ws.merge_range(row, 0, row, 5, s["designation"], fmtl)
                ws.write(row, 6, s["prevu"], fmtc)
                ws.write(row, 7, s["recu"] if s.get("recu") is not None else "—", fmtc)
                ws.write(row, 8, s["pose"], fmtc)
                ws.write(row, 9, s["restant_stock"], fmtc)
                ws.write(row, 10, s["restant_a_poser"], fmtc)
                ws.write(row, 11, s["manque"], f_geo_bad)
                row += 1
            row += 1

        # ---- Incidents ----
        incs = [i for i in state["incidents"] if i.get("nuit") == nuit]
        if incs:
            ws.merge_range(row, 0, row, 11, f"🚨  INCIDENTS ({len(incs)})", f_alert_title)
            ws.set_row(row, 22)
            row += 1
            for i in incs:
                text = f"• {i.get('text')}"
                author = i.get("author") or ""
                created = ""
                if i.get("created_at"):
                    try:
                        created = datetime.fromisoformat(str(i["created_at"]).replace("Z", "+00:00")).strftime("%d/%m %H:%M")
                    except Exception:
                        pass
                subline = f"— {author} · {created}" if author or created else ""
                ws.merge_range(row, 0, row, 8, text, f_cl)
                ws.merge_range(row, 9, row, 11, subline, f_sub)
                row += 1
            row += 1

        # ---- (iter37) NOTES & PHOTOS regroupées par allée : un seul bloc lisible ----
        entries_map = {str(e.get("uid")): e for e in (doc.get("allees") or [])}
        # Une allée entre dans le bloc si elle a commentaire, geoloc_comment ou photos
        notes_rows = []
        for x in items:
            entry = entries_map.get(x["uid"], {}) or {}
            phs = entry.get("photos") or []
            has_comment = bool((x.get("comment") or "").strip())
            has_geoc = bool((x.get("geoloc_comment") or "").strip())
            if has_comment or has_geoc or phs:
                notes_rows.append((x, phs, has_comment, has_geoc))

        if notes_rows:
            nb_photos_tot = sum(len(p) for _, p, _, _ in notes_rows)
            ws.merge_range(row, 0, row, 11,
                           f"📝  NOTES & PHOTOS PAR ALLÉE ({len(notes_rows)} allée(s), {nb_photos_tot} photo(s))",
                           f_info_title)
            ws.set_row(row, 22)
            row += 1
            try:
                from PIL import Image as PILImage
                PIL_OK = True
            except Exception:
                PIL_OK = False

            for x, photos, has_comment, has_geoc in notes_rows:
                # En-tête allée
                header = f"Allée {x['allee']} · {x['secteur']}"
                if x.get("rayon"):
                    header += f" · {x['rayon']}"
                if photos:
                    header += f"  ·  📸 {len(photos)} photo{'s' if len(photos) > 1 else ''}"
                ws.merge_range(row, 0, row, 11, header, f_kpi_l)
                ws.set_row(row, 20)
                row += 1
                # Commentaire POSE
                if has_comment:
                    ws.merge_range(row, 0, row, 1, "💬 Commentaire", f_h)
                    ws.merge_range(row, 2, row, 11, x["comment"], f_cl)
                    row += 1
                # Commentaire GÉOLOC
                if has_geoc:
                    ws.merge_range(row, 0, row, 1, "📍 Géoloc", f_h)
                    ws.merge_range(row, 2, row, 11, x["geoloc_comment"], f_cl)
                    row += 1
                # Photos (grille 4 col, sous les commentaires de la même allée)
                if photos and PIL_OK:
                    col_starts = [0, 3, 6, 9]
                    photo_h_max = 0
                    grid_start_row = row
                    for i, p in enumerate(photos[:16]):  # max 16 photos par allée
                        try:
                            data, _ct = _get_object(p["path"])
                            im = PILImage.open(io.BytesIO(data))
                            w, h = im.size
                            scale = min(1.0, 200.0 / float(w))
                            ci = i % 4
                            if ci == 0 and i > 0:
                                row = grid_start_row + photo_h_max
                                photo_h_max = 0
                                grid_start_row = row
                            ws.insert_image(grid_start_row, col_starts[ci], f"{p['id']}.jpg",
                                            {"image_data": io.BytesIO(data),
                                             "x_scale": scale, "y_scale": scale,
                                             "x_offset": 4, "y_offset": 4})
                            rows_needed = int((h * scale) / 20) + 2
                            photo_h_max = max(photo_h_max, rows_needed)
                        except Exception as pe:
                            logger.warning(f"Photo embed failed ({p.get('id')}): {pe}")
                            continue
                    row = grid_start_row + photo_h_max
                # Séparateur entre allées
                row += 1
            row += 1

        # ---- Justifications d'écart > 5% (dans le résumé pour transparence) ----
        justif_rows = [x for x in items if x.get("justif_products")]
        if justif_rows:
            ws.merge_range(row, 0, row, 11, "📌  ÉCARTS > 5% JUSTIFIÉS", f_comment_title)
            ws.set_row(row, 22)
            row += 1
            for c, h in enumerate(["Allée", "Produit", "Prévu", "Posé", "%", "Justification"]):
                if c == 0:
                    ws.write(row, 0, h, f_h)
                elif c == 1:
                    ws.merge_range(row, 1, row, 4, h, f_h)
                elif c == 2:
                    ws.write(row, 5, h, f_h)
                elif c == 3:
                    ws.write(row, 6, h, f_h)
                elif c == 4:
                    ws.write(row, 7, h, f_h)
                elif c == 5:
                    ws.merge_range(row, 8, row, 11, h, f_h)
            row += 1
            i = 0
            for x in justif_rows:
                for jp in x["justif_products"]:
                    fmtc = f_c_zebra if i % 2 else f_c
                    fmtl = f_cl_zebra if i % 2 else f_cl
                    # (iter36) Coloration : orange si "Tout est OK" coché par le poseur (écart validé), rouge sinon
                    ok = bool(x.get("justif_ok"))
                    fmt_pct = f_neg_soft if ok else f_neg
                    ws.write(row, 0, x["allee"], fmtc)
                    ws.merge_range(row, 1, row, 4, jp["designation"], fmtl)
                    ws.write(row, 5, jp["plan"], fmtc)
                    ws.write(row, 6, jp["reel"], fmtc)
                    ws.write(row, 7, jp["ecart_pct"], fmt_pct)
                    justif_txt = x.get("justification") or ("✅ OK poseur — validé" if ok else "⚠ manquante")
                    ws.merge_range(row, 8, row, 11, justif_txt, fmtl)
                    row += 1
                    i += 1
            row += 1

        # ---- Statut détaillé des allées (mini-liste couleur) ----
        ws.merge_range(row, 0, row, 11, f"📋  DÉTAIL DES {len(items)} ALLÉES DE LA NUIT", f_info_title)
        ws.set_row(row, 22)
        row += 1
        for c, h in enumerate(["Allée", "Secteur / Rayon", "Statut", "Pose", "Géoloc", "EEG posés"]):
            if c == 0:
                ws.write(row, 0, h, f_h)
            elif c == 1:
                ws.merge_range(row, 1, row, 5, h, f_h)
            elif c == 2:
                ws.merge_range(row, 6, row, 7, h, f_h)
            elif c == 3:
                ws.write(row, 8, h, f_h)
            elif c == 4:
                ws.write(row, 9, h, f_h)
            elif c == 5:
                ws.merge_range(row, 10, row, 11, h, f_h)
        row += 1
        status_lbl = {"a_faire": "⏳ À faire", "validee": "✅ Validée", "bloquee": "🚫 Bloquée",
                      "a_finaliser": "⚠️ À finaliser", "non_faite": "🚫 Non faite"}
        for i, x in enumerate(items):
            fmtc = f_c_zebra if i % 2 else f_c
            fmtl = f_cl_zebra if i % 2 else f_cl
            st_key = x["status"]
            st_fmt = f_ok if st_key == "validee" else (f_neg if st_key in ("bloquee", "a_finaliser", "non_faite") else fmtc)
            ws.write(row, 0, x["allee"], fmtc)
            ws.merge_range(row, 1, row, 5,
                           f"{x['secteur']}" + (f" · {x['rayon']}" if x['rayon'] else ""), fmtl)
            ws.merge_range(row, 6, row, 7, status_lbl.get(st_key, st_key), st_fmt)
            pose_str = f"{x.get('pose_saisis') or 0}/{x.get('pose_total') or 0}"
            ws.write(row, 8, pose_str, fmtc if x.get("pose_complete") else f_geo_bad)
            if (x.get("geo_total") or 0) > 0:
                geo_str = f"{x.get('geo_saisis') or 0}/{x.get('geo_total') or 0}"
                ws.write(row, 9, geo_str, fmtc if x.get("geo_complete") else f_geo_bad)
            else:
                ws.write(row, 9, "—", fmtc)
            eeg_a = sum(x["reel"].get(k) or 0 for k in ("es_15", "es_21", "rails_es", "sa_15", "sa_21_std"))
            ws.merge_range(row, 10, row, 11, int(eeg_a), fmtc)
            row += 1
        row += 1

        # (iter37) La section STORYBOARD PHOTOS a été fusionnée avec les commentaires
        # dans le bloc « NOTES & PHOTOS PAR ALLÉE » plus haut : chaque allée a
        # désormais son propre bloc avec ses commentaires + photos regroupés.

        # ═══════════════════════════════════════════════════════════════
        # FEUILLE 2 — DÉTAIL PAR ALLÉE (le tableau complet historique)
        # ═══════════════════════════════════════════════════════════════
        ws = wb.add_worksheet("Détail allées")
        ws.merge_range(0, 0, 0, 6, f"Détail complet des allées — Nuit {nuit}", f_section)
        ws.set_row(0, 26)  # (iter36) hauteur suffisante pour le titre
        row = 2

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
        ws.set_row(row, 30)  # (iter36) header lisible même avec libellés longs
        ws.set_column(0, 0, 8)
        ws.set_column(1, 2, 20)  # Secteur & Rayon
        ws.set_column(3, len(headers) - 5, 11)  # colonnes numériques élargies
        ws.set_column(len(headers) - 4, len(headers) - 4, 14)  # Statut
        ws.set_column(len(headers) - 3, len(headers) - 1, 32)  # justif + commentaires
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

        # (iter34) Section dédiée : produits posés non géolocalisés + commentaires GÉOLOC
        # — deux causes = deux sections distinctes, ne pas mélanger avec les écarts pose
        geo_rows = [x for x in items if any((x.get("geo_gap") or {}).values())]
        if geo_rows:
            ws.write(row, 0, "Écarts GÉOLOC (posés non géolocalisés) et commentaires", f_title)
            row += 1
            for c0, h in enumerate(["Allée", "Famille", "Posé", "Géoloc", "Non géoloc", "Commentaire géoloc"]):
                ws.write(row, c0, h, f_h)
            ws.set_column(5, 5, 40)
            row += 1
            for x in geo_rows:
                geo_gap = x.get("geo_gap") or {}
                first = True
                for k, gap in geo_gap.items():
                    if not gap:
                        continue
                    reel_k = (x.get("reel") or {}).get(k) or 0
                    geo_k = (x.get("geo") or {}).get(k) or 0
                    ws.write(row, 0, x["allee"] if first else "", f_c)
                    ws.write(row, 1, k, f_cl)
                    ws.write(row, 2, reel_k, f_c)
                    ws.write(row, 3, geo_k, f_c)
                    ws.write(row, 4, gap, f_neg)
                    if first:
                        ws.write(row, 5, x.get("geoloc_comment") or "⚠ manquant", f_cl)
                    else:
                        ws.write(row, 5, "", f_cl)
                    first = False
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

        # Photos : voir feuille « Résumé N{n} » (storyboard groupé par allée)

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
                    ws2.write(rr, 7, dv, f_delta_ok if dv >= 0 else f_neg_soft)
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
            ws_ec.merge_range(0, 0, 0, 6, f"Écart phasage vs réel — Nuit {nuit}", f_title)
            ws_ec.merge_range(1, 0, 1, 6, "Comparaison quantités prévues (phasage) vs réel posé, par produit. "
                              "Bonus > +5%, Manque < -5%.", f_sub)
            ws_ec.set_row(0, 32)  # (iter36) hauteur suffisante pour le titre
            ws_ec.set_row(1, 22)
            ws_ec.set_column(0, 0, 48)   # Désignation
            ws_ec.set_column(1, 1, 14)   # Type
            ws_ec.set_column(2, 6, 13)   # colonnes numériques et Statut
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
            ("Avancement Pose EEG (%)", st["pct"]),
            ("Géoloc EEG prévues (unités)", st.get("geo_eeg_prevues", 0)),
            ("Géoloc EEG effectuées (unités)", st.get("geo_eeg_posees", 0)),
            ("Avancement Géoloc EEG (%)", st.get("geo_eeg_pct", 0)),
            ("Caméras prévues (total)", st.get("cam_prevues", 0)),
            ("Caméras posées (total)", st.get("cam_posees", 0)),
            ("Avancement Pose Caméra (%)", st.get("cam_pct", 0)),
            ("Géoloc Caméras effectuées", st.get("cam_geo_posees", 0)),
            ("Avancement Géoloc Caméra (%)", st.get("cam_geo_pct", 0)),
            ("Allées validées", f"{st['allees_validees']} / {st['allees_total']}"),
            ("Allées bloquées", st["allees_bloquees"]),
            ("Nuits terminées", f"{st['nuits_terminees']} / {state['nb_nuits']}"),
            # (iter38) Rythme réel/prévu et retard estimé retirés du rapport à la
            # demande utilisateur (jugés stressants et peu fiables les premières nuits).
            ("EEG restant à poser", st["eeg_restant"]),
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
                      f_c if dv is None else (f_delta_ok if dv >= 0 else f_neg_soft))
            ws3.write(r3, 9, stat, f_stat)
            r3 += 1

        wb.close()
        buf.seek(0)
        from server import _display_store  # lazy import (évite dep circulaire)
        # (iter37) Nom du fichier propre demandé par l'utilisateur :
        # « ST PIERRE DES CORPS (H7351) - Nuit 1.xlsx » (au lieu du long
        # « Export ... DD-MM-YYYY HH-MM_Rapport_nuit_1.xlsx »)
        fname = f"{_display_store(d)} - Nuit {nuit}.xlsx"
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
            entry = {"uid": uid, "products": []}
            arr.append(entry)
        # (v28 iter6) Traite `products` séparément (merge par désignation).
        if "products" in fields:
            products_in = fields.pop("products") or []
            existing = list(entry.get("products") or [])
            by_dg = {p.get("designation"): p for p in existing if p.get("designation")}
            for p in products_in:
                dg = p.get("designation")
                if not dg:
                    continue
                cur = by_dg.get(dg) or {"designation": dg}
                if "reel" in p:
                    cur["reel"] = p["reel"]
                if "geo" in p:
                    cur["geo"] = p["geo"]
                by_dg[dg] = cur
            entry["products"] = list(by_dg.values())
        entry.update(fields)
        # Recompute aggregates for legacy consumers (dashboards, exports)
        prods = entry.get("products") or []
        cam_reel = 0.0
        cam_geo = 0.0
        fix_reel = 0.0
        has_cam_reel = has_cam_geo = has_fix_reel = False
        for p in prods:
            desig = (p.get("designation") or "").lower()
            is_cam_dev = desig.startswith("caméra") or desig.startswith("camera")
            r = p.get("reel")
            g = p.get("geo")
            if r is not None:
                if is_cam_dev:
                    cam_reel += float(r); has_cam_reel = True
                else:
                    fix_reel += float(r); has_fix_reel = True
            if g is not None and is_cam_dev:
                cam_geo += float(g); has_cam_geo = True
        entry["cameras_reel"] = cam_reel if has_cam_reel else None
        entry["cameras_geo"] = cam_geo if has_cam_geo else None
        entry["fixations_reel"] = fix_reel if has_fix_reel else None
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
        # (iter40) Colonne référence produit (SKU) pour l'afficher à côté du nom
        ref_col = next((c for c in ["Référence", "Reference", "Réf.", "Ref"] if c in cols), None)
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
            # (v28 iter6) Masquer batterie/software caméra dans tout le Suivi.
            if is_hidden_in_suivi(desig):
                continue
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
                                        "rayon": rayon_v, "totals": {}, "elements": {}, "types": {}, "refs": {}})
            node["totals"][desig] = node["totals"].get(desig, 0.0) + qty
            if desig not in node["types"]:
                typ_v = str(r.get(type_col) or "").strip() if type_col else ""
                node["types"][desig] = "" if typ_v.lower() == "nan" else typ_v
            # (iter40) Capture la première référence non-vide rencontrée pour ce produit
            if ref_col and desig not in node["refs"]:
                ref_v = str(r.get(ref_col) or "").strip()
                if ref_v and ref_v.lower() != "nan":
                    node["refs"][desig] = ref_v
            enode = node["elements"].setdefault(elem_key, {})
            enode[desig] = enode.get(desig, 0.0) + qty
        return idx

    def _products_list(totals: dict, refs: dict = None) -> list:
        refs = refs or {}
        return [{"designation": k, "qty": _r(v), "reference": refs.get(k) or ""}
                for k, v in sorted(totals.items(), key=lambda t: t[0].lower())]

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
            "refs": node.get("refs") or {},  # (iter40) préserve les références SKU
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
        unassigned = {"totals": {}, "nb_allees": 0, "refs": {}}
        for uid, node in idx.items():
            if mode in ("eeg", "cam") and uid not in nights_map:
                # En mode filtré, on ignore les allées qui ne relèvent pas de ce phasage.
                continue
            node = _filter_materiel_node(node, mode, by_uid, cfg_sa)
            if not node.get("totals"):
                continue
            node_refs = node.get("refs") or {}
            n = nights_map.get(uid)
            if not n:
                unassigned["nb_allees"] += 1
                for k, v in node["totals"].items():
                    unassigned["totals"][k] = unassigned["totals"].get(k, 0.0) + v
                    if k not in unassigned["refs"] and node_refs.get(k):
                        unassigned["refs"][k] = node_refs[k]
                continue
            b = by_night.setdefault(n, {"nuit": n, "date": str(dates.get(str(n)) or ""), "nb_allees": 0, "totals": {}, "refs": {}})
            b["nb_allees"] += 1
            for k, v in node["totals"].items():
                b["totals"][k] = b["totals"].get(k, 0.0) + v
                if k not in b["refs"] and node_refs.get(k):
                    b["refs"][k] = node_refs[k]
        nights = []
        for n in sorted(by_night.keys()):
            b = by_night[n]
            nights.append({"nuit": n, "date": b["date"], "nb_allees": b["nb_allees"],
                           "products": _products_list(b["totals"], refs=b["refs"])})
        return {
            "nights": nights,
            "unassigned": {"nb_allees": unassigned["nb_allees"],
                           "products": _products_list(unassigned["totals"], refs=unassigned["refs"])},
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
        totals_refs = {}  # (iter40) référence SKU par désignation
        # Statuts d'allée pour affichage (nb validées / à faire / bloquée)
        nb_val, nb_block, nb_todo = 0, 0, 0
        allees = []
        for uid, node_raw in idx.items():
            if nights_map.get(uid) != nuit:
                continue
            node = _filter_materiel_node(node_raw, mode, by_uid, cfg_sa)
            if not node.get("totals"):
                continue
            elements = [{"element": k, "products": _products_list(v, refs=node.get("refs") or {})}
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
                if dg not in totals_refs:
                    rf = (node.get("refs") or {}).get(dg)
                    if rf:
                        totals_refs[dg] = rf
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
                    "reference": (node.get("refs") or {}).get(dg) or "",  # (iter40) SKU
                    "geo": _r(pgeo) if pgeo is not None else None,
                    "family": fam, "is_geo": is_geo,
                    "delta": _r(delta), "status": st,
                })
            allees.append({"uid": uid, "allee": node["allee"], "secteur": node["secteur"],
                           "rayon": node["rayon"], "products": _products_list(node["totals"], refs=node.get("refs") or {}),
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
                "reference": totals_refs.get(dg) or "",  # (iter40) SKU
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
            # (iter36) La case "Tout est OK" cochée par le poseur exempte du
            # commentaire textuel — l'écart reste tracé (statut orange dans
            # dashboard/Excel), mais on considère qu'il n'est pas critique.
            justif_ok = bool(fields.get("justif_ok") if "justif_ok" in fields else entry.get("justif_ok"))
            has_text = bool((fields.get("justification") or "").strip()
                            or (entry.get("justification") or "").strip())
            if justifs and not justif_ok and not has_text:
                raise HTTPException(
                    status_code=400,
                    detail="Justification requise : écart de plus de 5% sur " + ", ".join(justifs)
                           + " — cochez « Tout est OK » ou renseignez un commentaire")
        valid = set((matnode.get("totals") or {}).keys())
        return await _apply_allee_update(doc["upload_id"], doc, payload, author,
                                         valid_designations=valid or None)

    # ================================================== ROUTES AUTHENTIFIÉES ====
    # ============================================= LIEN LECTURE SEULE (CLIENT) ====
    # Un TOKEN GLOBAL unique (stocké en base collection `settings`) donne accès
    # à un lien /suivi/view?token=... qui expose uniquement les endpoints GET
    # de ce fichier. Aucune route d'écriture n'existe côté /suivi-view →
    # sécurité par CONSTRUCTION (impossible de patcher, publier, effacer, etc).
    async def _get_viewer_token(create: bool = True) -> str:
        rec = await db.settings.find_one({"key": "suivi_viewer_token"})
        if rec and rec.get("value"):
            return rec["value"]
        if not create:
            return ""
        token = secrets.token_urlsafe(24)
        await db.settings.update_one(
            {"key": "suivi_viewer_token"},
            {"$set": {"value": token, "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        return token

    async def _verify_viewer_token(token: str):
        real = await _get_viewer_token(create=False)
        if not real or not secrets.compare_digest(token or "", real):
            raise HTTPException(status_code=401, detail="Lien de partage invalide")

    # NB : ces routes littérales sont enregistrées AVANT `/{upload_id}` sinon
    # FastAPI matcherait "viewer-link" comme un upload_id.
    @router.get("/viewer-link")
    async def get_viewer_link(current_user: dict = Depends(get_current_user)):
        """Retourne le token global de partage lecture-seule (crée si absent).
        Accès : tout utilisateur connecté du back-office."""
        token = await _get_viewer_token(create=True)
        return {"token": token}

    @router.post("/viewer-link/rotate")
    async def rotate_viewer_link(current_user: dict = Depends(get_current_user)):
        """Régénère le token (invalide tous les anciens liens partagés).
        Réservé aux admins et superadmins."""
        if current_user.get("role") not in ("admin", "superadmin"):
            raise HTTPException(status_code=403,
                                detail="Seul un administrateur peut régénérer le lien de partage")
        token = secrets.token_urlsafe(24)
        await db.settings.update_one(
            {"key": "suivi_viewer_token"},
            {"$set": {"value": token,
                      "rotated_at": datetime.now(timezone.utc).isoformat(),
                      "rotated_by": current_user.get("email") or ""}},
            upsert=True,
        )
        return {"token": token}

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

    # ============================================= ROUTES LECTURE SEULE (CLIENTS) ====
    viewer = APIRouter(prefix="/suivi-view")

    async def _resolve_viewer(upload_id: str, token: str):
        await _verify_viewer_token(token)
        doc = await db.suivi_docs.find_one({"upload_id": upload_id, "published": True})
        if not doc:
            raise HTTPException(status_code=404, detail="Magasin non publié")
        doc.pop("_id", None)
        d = await load_dataset(upload_id)
        if d is None:
            raise HTTPException(status_code=404, detail="Dataset introuvable")
        return d, doc

    @viewer.get("/stores")
    async def viewer_stores(token: str = Query(...)):
        await _verify_viewer_token(token)
        docs = await db.suivi_docs.find({"published": True},
                                        {"_id": 0, "upload_id": 1, "published_by": 1}).to_list(length=500)
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

    @viewer.get("/{upload_id}")
    async def viewer_state(upload_id: str, token: str = Query(...)):
        d, doc = await _resolve_viewer(upload_id, token)
        return _build_state(d, doc, doc["upload_id"], is_terrain=True)

    @viewer.get("/{upload_id}/materiel")
    async def viewer_materiel(upload_id: str, mode: str = "eeg", token: str = Query(...)):
        d, doc = await _resolve_viewer(upload_id, token)
        return _materiel_overview(d, doc, mode=mode)

    @viewer.get("/{upload_id}/materiel/{nuit}")
    async def viewer_materiel_nuit(upload_id: str, nuit: int, mode: str = "eeg", token: str = Query(...)):
        d, doc = await _resolve_viewer(upload_id, token)
        return _materiel_nuit(d, doc, nuit, mode=mode)

    @viewer.get("/{upload_id}/photo/{photo_id}")
    async def viewer_photo(upload_id: str, photo_id: str, token: str = Query(...)):
        d, doc = await _resolve_viewer(upload_id, token)
        return _photo_response(doc, photo_id)

    @viewer.get("/{upload_id}/rapport-nuit/{nuit}")
    async def viewer_rapport(upload_id: str, nuit: int, token: str = Query(...)):
        d, doc = await _resolve_viewer(upload_id, token)
        return _rapport_response(d, doc, doc["upload_id"], nuit)

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
    parent.include_router(viewer)
    parent.include_router(terrain)
    return parent
