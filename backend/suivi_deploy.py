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
from typing import Optional

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
GEO_KEYS = ["rails_es", "sa_15", "sa_21_std", "sa_21_freezer"]
MAX_EEG_PER_NIGHT = 4900.0
MAX_PHOTO_BYTES = 8 * 1024 * 1024

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


class AlleeUpdate(BaseModel):
    uid: str
    es_15_reel: Optional[float] = Field(default=None, ge=0)
    es_21_reel: Optional[float] = Field(default=None, ge=0)
    rails_es_reel: Optional[float] = Field(default=None, ge=0)
    sa_15_reel: Optional[float] = Field(default=None, ge=0)
    sa_21_std_reel: Optional[float] = Field(default=None, ge=0)
    sa_21_freezer_reel: Optional[float] = Field(default=None, ge=0)
    sa_42_reel: Optional[float] = Field(default=None, ge=0)
    cameras_reel: Optional[float] = Field(default=None, ge=0)
    rails_es_geo: Optional[float] = Field(default=None, ge=0)
    sa_15_geo: Optional[float] = Field(default=None, ge=0)
    sa_21_std_geo: Optional[float] = Field(default=None, ge=0)
    sa_21_freezer_geo: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None  # a_faire | validee | bloquee
    comment: Optional[str] = None
    geoloc_comment: Optional[str] = None
    nuit_reelle: Optional[int] = None  # 0 → retour à la nuit planifiée


class StockUpdate(BaseModel):
    family: str
    recu: Optional[float] = None


class IncidentCreate(BaseModel):
    nuit: int
    text: str


class ReplanRequest(BaseModel):
    apply: bool = False


class TerrainShareUpdate(BaseModel):
    enabled: bool


def build_suivi_router(db, load_dataset, get_current_user, compute_phasage_summary,
                       normalize_phasage, save_phasage_snapshot, persist_phasage):
    router = APIRouter(prefix="/suivi")
    terrain = APIRouter(prefix="/suivi-terrain")

    async def _load(upload_id: str, current_user: dict) -> dict:
        d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
        if d is None:
            raise HTTPException(status_code=404, detail="Dataset introuvable")
        return d

    async def _get_doc(upload_id: str, user_id: str = "") -> dict:
        doc = await db.suivi_docs.find_one({"upload_id": upload_id})
        if not doc:
            doc = {
                "upload_id": upload_id, "user_id": user_id,
                "allees": [], "stock_received": {}, "incidents": [],
                "terrain_token": None, "terrain_enabled": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.suivi_docs.insert_one(dict(doc))
        doc.pop("_id", None)
        return doc

    async def _resolve_terrain(token: str):
        doc = await db.suivi_docs.find_one({"terrain_token": token, "terrain_enabled": True})
        if not doc:
            raise HTTPException(status_code=404, detail="Lien terrain invalide ou désactivé")
        doc.pop("_id", None)
        d = await load_dataset(doc["upload_id"])
        if d is None:
            raise HTTPException(status_code=404, detail="Dataset introuvable")
        return d, doc

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

        allees = []
        for uid, nuit_plan in nuit_by_uid.items():
            a = by_uid.get(uid) or {}
            e = entries.get(uid) or {}
            plan = _plan_for_allee(a)
            reel, has_reel = {}, False
            for k in FAMILY_KEYS:
                v = e.get(f"{k}_reel")
                reel[k] = None if v is None else _r(v)
                if v is not None:
                    has_reel = True
            geo = {}
            for k in GEO_KEYS:
                v = e.get(f"{k}_geo")
                geo[k] = None if v is None else _r(v)
            geo_gap = {}
            for k in GEO_KEYS:
                pose_k = reel.get(k)
                if geo[k] is not None and pose_k is not None and geo[k] < pose_k:
                    geo_gap[k] = _r(pose_k - geo[k])
            nuit_reelle = e.get("nuit_reelle")
            eff = int(nuit_reelle) if nuit_reelle else nuit_plan
            delta = {k: (None if reel[k] is None else _r(reel[k] - plan[k])) for k in FAMILY_KEYS}
            photos = [{"id": p.get("id"), "author": p.get("author") or "",
                       "created_at": p.get("created_at") or ""}
                      for p in (e.get("photos") or [])]
            allees.append({
                "uid": uid,
                "allee": a.get("allee") or uid.split("__")[0],
                "secteur": a.get("secteur") or "",
                "rayon": a.get("rayon") or "",
                "nuit_plan": nuit_plan,
                "nuit_reelle": nuit_reelle,
                "nuit_eff": eff,
                "plan": plan,
                "reel": reel,
                "delta": delta,
                "geo": geo,
                "geo_gap": geo_gap,
                "geoloc_comment": e.get("geoloc_comment") or "",
                "photos": photos,
                "eeg_plan": _r(_eeg_sum(plan)),
                "eeg_reel": _r(_eeg_sum({k: (reel[k] or 0) for k in FAMILY_KEYS})) if has_reel else None,
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
            started = any(x["has_reel"] or x["status"] != "a_faire" for x in items)
            complete = bool(items) and validated == len(items)
            date_n = str(dates.get(str(n)) or dates.get(n) or "")
            nights.append({
                "nuit": n, "date": date_n,
                "nb_allees": len(items),
                "nb_validees": validated, "nb_bloquees": blocked,
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

        stock_received = doc.get("stock_received") or {}
        stock, alerts = [], []
        for k in FAMILY_KEYS:
            prevu = sum(float(x["plan"].get(k) or 0) for x in allees)
            pose = sum(float(x["reel"].get(k) or 0) for x in allees if x["reel"].get(k) is not None)
            restant_a_poser = sum(float(x["plan"].get(k) or 0) for x in allees if x["status"] != "validee")
            recu = stock_received.get(k)
            recu_eff = float(recu) if recu is not None else prevu
            restant_stock = recu_eff - pose
            manque = max(0.0, restant_a_poser - max(0.0, restant_stock))
            stock.append({
                "family": k, "label": FAMILY_LABELS[k],
                "prevu": _r(prevu),
                "recu": (None if recu is None else _r(recu)),
                "recu_theorique": recu is None,
                "pose": _r(pose),
                "restant_stock": _r(restant_stock),
                "restant_a_poser": _r(restant_a_poser),
                "manque": _r(manque), "alert": manque > 0 and prevu > 0,
            })
            if manque > 0 and prevu > 0:
                alerts.append({
                    "type": "rupture", "family": k, "label": FAMILY_LABELS[k],
                    "manque": _r(manque),
                    "message": (f"{FAMILY_LABELS[k]} : il manque {_r(manque)} unité(s) pour finir la pose "
                                f"(stock restant {_r(restant_stock)}, encore {_r(restant_a_poser)} à poser)"),
                })
        for x in allees:
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
            "stats": {
                "eeg_prevues": total_eeg_plan,
                "eeg_posees": total_eeg_reel,
                "pct": _r(100.0 * total_eeg_reel / total_eeg_plan) if total_eeg_plan else 0,
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
            state["terrain"] = {
                "enabled": bool(doc.get("terrain_enabled")),
                "token": doc.get("terrain_token") or "",
            }
        return state

    # ------------------------------------------------------- mutations partagées
    async def _apply_allee_update(upload_id: str, doc: dict, payload: AlleeUpdate, author: str):
        fields = payload.dict(exclude_unset=True)
        uid = fields.pop("uid")
        if "status" in fields and fields["status"] not in (None, "a_faire", "validee", "bloquee"):
            raise HTTPException(status_code=400, detail="Statut invalide")
        if fields.get("nuit_reelle") == 0:
            fields["nuit_reelle"] = None
        arr = doc.get("allees") or []
        entry = next((e for e in arr if str(e.get("uid")) == uid), None)
        if entry is None:
            entry = {"uid": uid}
            arr.append(entry)
        entry.update(fields)
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
        f_title = wb.add_format({"bold": True, "font_size": 14, "font_color": "#056839"})
        f_sub = wb.add_format({"font_size": 10, "font_color": "#666666"})
        f_h = wb.add_format({"bold": True, "bg_color": "#056839", "font_color": "white",
                             "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
        f_c = wb.add_format({"border": 1, "align": "center"})
        f_cl = wb.add_format({"border": 1})
        f_ok = wb.add_format({"border": 1, "align": "center", "bg_color": "#D1FAE5"})
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
        if isinstance(delta_n, (int, float)):
            verdict = ("⚡ Plus rapide que prévu" if delta_n > 0 else
                       ("🐢 Plus lent que prévu" if delta_n < 0 else "✔ Conforme au prévisionnel"))
            ws.write(row, 0, "Verdict", f_kpi_l)
            ws.write(row, 2, verdict)
            row += 1
        row += 1

        # Tableau des allées (prévu / réel / géo / Δ)
        headers = ["Allée", "Secteur", "Rayon"]
        col_plan = {}
        for k in fams:
            col_plan[k] = len(headers)
            headers += [f"{FAMILY_LABELS[k]} prévu", f"{FAMILY_LABELS[k]} réel"]
            if k in GEO_KEYS:
                headers.append("Géoloc")
            headers.append("Δ")
        headers += ["Statut", "Commentaire", "Explication géoloc"]
        for c, h in enumerate(headers):
            ws.write(row, c, h, f_h)
        ws.set_column(0, 0, 8)
        ws.set_column(1, 2, 16)
        ws.set_column(3, len(headers) - 4, 9)
        ws.set_column(len(headers) - 2, len(headers) - 1, 28)
        row += 1
        status_lbl = {"a_faire": "À faire", "validee": "Validée", "bloquee": "BLOQUÉE"}
        tot_plan = {k: 0.0 for k in fams}
        tot_reel = {k: 0.0 for k in fams}
        tot_geo = {k: 0.0 for k in fams}
        for x in items:
            c = 0
            ws.write(row, c, x["allee"], f_c); c += 1
            ws.write(row, c, x["secteur"], f_cl); c += 1
            ws.write(row, c, x["rayon"], f_cl); c += 1
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
                     f_ok if stx == "validee" else (f_neg if stx == "bloquee" else f_c)); c += 1
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

        wb.close()
        buf.seek(0)
        safe_store = "".join(ch for ch in store if ch.isalnum() or ch in " -_")[:40].strip().replace(" ", "_")
        fname = f"Rapport_nuit_{nuit}_{safe_store}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # ================================================== ROUTES AUTHENTIFIÉES ====
    @router.get("/{upload_id}")
    async def get_suivi(upload_id: str, current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        return _build_state(d, doc, upload_id)

    @router.patch("/{upload_id}/allee")
    async def update_allee(upload_id: str, payload: AlleeUpdate,
                           current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        uid = await _apply_allee_update(upload_id, doc, payload, current_user.get("email") or "")
        return {"ok": True, "uid": uid}

    @router.patch("/{upload_id}/stock")
    async def update_stock(upload_id: str, payload: StockUpdate,
                           current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        await _get_doc(upload_id, str(current_user["_id"]))
        if payload.family not in FAMILY_KEYS:
            raise HTTPException(status_code=400, detail="Famille inconnue")
        if payload.recu is None:
            await db.suivi_docs.update_one({"upload_id": upload_id},
                                           {"$unset": {f"stock_received.{payload.family}": ""}})
        else:
            await db.suivi_docs.update_one({"upload_id": upload_id},
                                           {"$set": {f"stock_received.{payload.family}": float(payload.recu)}})
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

    @router.post("/{upload_id}/terrain-share")
    async def terrain_share(upload_id: str, payload: TerrainShareUpdate,
                            current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        token = doc.get("terrain_token") or uuid.uuid4().hex
        await db.suivi_docs.update_one(
            {"upload_id": upload_id},
            {"$set": {"terrain_token": token, "terrain_enabled": payload.enabled}})
        return {"ok": True, "enabled": payload.enabled, "token": token}

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
    @terrain.get("/{token}")
    async def terrain_state(token: str):
        d, doc = await _resolve_terrain(token)
        return _build_state(d, doc, doc["upload_id"], is_terrain=True)

    @terrain.patch("/{token}/allee")
    async def terrain_update_allee(token: str, payload: AlleeUpdate):
        d, doc = await _resolve_terrain(token)
        uid = await _apply_allee_update(doc["upload_id"], doc, payload, "équipe terrain")
        return {"ok": True, "uid": uid}

    @terrain.post("/{token}/incident")
    async def terrain_add_incident(token: str, payload: IncidentCreate):
        d, doc = await _resolve_terrain(token)
        return await _create_incident(doc["upload_id"], payload, "équipe terrain")

    @terrain.delete("/{token}/incident/{incident_id}")
    async def terrain_del_incident(token: str, incident_id: str):
        d, doc = await _resolve_terrain(token)
        await db.suivi_docs.update_one({"upload_id": doc["upload_id"]},
                                       {"$pull": {"incidents": {"id": incident_id}}})
        return {"ok": True}

    @terrain.post("/{token}/allee-photo")
    async def terrain_add_photo(token: str, uid: str = Form(...), file: UploadFile = File(...)):
        d, doc = await _resolve_terrain(token)
        return await _add_photo(doc["upload_id"], doc, uid, file, "équipe terrain")

    @terrain.get("/{token}/photo/{photo_id}")
    async def terrain_get_photo(token: str, photo_id: str):
        d, doc = await _resolve_terrain(token)
        return _photo_response(doc, photo_id)

    @terrain.delete("/{token}/photo/{photo_id}")
    async def terrain_del_photo(token: str, photo_id: str):
        d, doc = await _resolve_terrain(token)
        return await _delete_photo(doc["upload_id"], doc, photo_id)

    @terrain.get("/{token}/rapport-nuit/{nuit}")
    async def terrain_rapport(token: str, nuit: int):
        d, doc = await _resolve_terrain(token)
        return _rapport_response(d, doc, doc["upload_id"], nuit)

    parent = APIRouter()
    parent.include_router(router)
    parent.include_router(terrain)
    return parent
