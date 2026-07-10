"""Suivi de déploiement — API de l'app séparée (/suivi).

Validation des allées (prévu VS réel), stock & alertes rupture,
incidents par nuit, rapport Excel par nuit, replanification automatique.
"""
import io
import math
import uuid
from datetime import datetime, timezone, date
from typing import Optional

import xlsxwriter
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

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
MAX_EEG_PER_NIGHT = 4900.0


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
    status: Optional[str] = None  # a_faire | validee | bloquee
    comment: Optional[str] = None
    nuit_reelle: Optional[int] = None  # 0 → retour à la nuit planifiée


class StockUpdate(BaseModel):
    family: str
    recu: Optional[float] = None  # None → retour au théorique (prévu)


class IncidentCreate(BaseModel):
    nuit: int
    text: str


class ReplanRequest(BaseModel):
    apply: bool = False


def build_suivi_router(db, load_dataset, get_current_user, compute_phasage_summary,
                       normalize_phasage, save_phasage_snapshot, persist_phasage):
    router = APIRouter(prefix="/suivi")

    async def _load(upload_id: str, current_user: dict) -> dict:
        d = await load_dataset(upload_id, user_id=str(current_user["_id"]))
        if d is None:
            raise HTTPException(status_code=404, detail="Dataset introuvable")
        return d

    async def _get_doc(upload_id: str, user_id: str) -> dict:
        doc = await db.suivi_docs.find_one({"upload_id": upload_id})
        if not doc:
            doc = {
                "upload_id": upload_id, "user_id": user_id,
                "allees": [], "stock_received": {}, "incidents": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.suivi_docs.insert_one(dict(doc))
            doc.pop("_id", None)
            return doc
        doc.pop("_id", None)
        return doc

    def _build_state(d: dict, doc: dict) -> dict:
        summary = compute_phasage_summary(d)
        ph = normalize_phasage(d.get("phasage"))
        es = ph.get("es") or {}
        nb_nuits = int(es.get("nb_nuits") or 0)
        weeks = es.get("weeks") or []
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
            nuit_reelle = e.get("nuit_reelle")
            eff = int(nuit_reelle) if nuit_reelle else nuit_plan
            delta = {k: (None if reel[k] is None else _r(reel[k] - plan[k])) for k in FAMILY_KEYS}
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

        incidents = sorted(doc.get("incidents") or [], key=lambda i: (i.get("nuit") or 0, i.get("created_at") or ""))

        return {
            "upload_id": d.get("upload_id") or "",
            "store_name": d.get("store_name") or "",
            "store_code": d.get("store_code") or "",
            "filename": d.get("filename") or "",
            "nb_nuits": nb_nuits,
            "weeks": weeks,
            "dates": {str(k): v for k, v in dates.items()},
            "allees": allees,
            "nights": nights,
            "stock": stock,
            "alerts": alerts,
            "incidents": incidents,
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

    # ------------------------------------------------------------------ GET état
    @router.get("/{upload_id}")
    async def get_suivi(upload_id: str, current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        state = _build_state(d, doc)
        state["upload_id"] = upload_id
        return state

    # -------------------------------------------------------- PATCH allée (réel)
    @router.patch("/{upload_id}/allee")
    async def update_allee(upload_id: str, payload: AlleeUpdate,
                           current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
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
        entry["updated_by"] = current_user.get("email") or ""
        if fields.get("status") == "validee":
            entry["validated_at"] = entry["updated_at"]
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$set": {"allees": arr}})
        return {"ok": True, "uid": uid}

    # ------------------------------------------------------------- PATCH stock
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

    # -------------------------------------------------------------- Incidents
    @router.post("/{upload_id}/incident")
    async def add_incident(upload_id: str, payload: IncidentCreate,
                           current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        await _get_doc(upload_id, str(current_user["_id"]))
        inc = {
            "id": str(uuid.uuid4())[:8],
            "nuit": payload.nuit,
            "text": payload.text.strip(),
            "author": current_user.get("email") or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not inc["text"]:
            raise HTTPException(status_code=400, detail="Texte vide")
        await db.suivi_docs.update_one({"upload_id": upload_id}, {"$push": {"incidents": inc}})
        return {"ok": True, "incident": inc}

    @router.delete("/{upload_id}/incident/{incident_id}")
    async def delete_incident(upload_id: str, incident_id: str,
                              current_user: dict = Depends(get_current_user)):
        await _load(upload_id, current_user)
        await db.suivi_docs.update_one({"upload_id": upload_id},
                                       {"$pull": {"incidents": {"id": incident_id}}})
        return {"ok": True}

    # ------------------------------------------------- Rapport Excel par nuit
    @router.get("/{upload_id}/rapport-nuit/{nuit}")
    async def rapport_nuit(upload_id: str, nuit: int,
                           current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        state = _build_state(d, doc)
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
        f_tot = wb.add_format({"bold": True, "border": 1, "align": "center", "bg_color": "#E5E7EB"})
        f_kpi_l = wb.add_format({"bold": True})

        store = state["store_name"] or state["filename"]
        ws.write(0, 0, f"Rapport de pose — Nuit {nuit}", f_title)
        ws.write(1, 0, f"{store}" + (f" · {state['store_code']}" if state["store_code"] else "")
                 + (f" · {night.get('date')}" if night.get("date") else ""), f_sub)
        ws.write(2, 0, f"Généré le {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC", f_sub)

        # KPIs rythme
        row = 4
        st = state["stats"]
        delta_n = night.get("delta_eeg")
        kpis = [
            ("EEG prévues cette nuit", night.get("eeg_plan", 0)),
            ("EEG posées cette nuit", night.get("eeg_reel", 0)),
            ("Écart cette nuit", delta_n if delta_n is not None else "—"),
            ("Allées validées", f"{night.get('nb_validees', 0)} / {night.get('nb_allees', 0)}"),
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

        # Tableau des allées
        headers = ["Allée", "Secteur", "Rayon"]
        for k in fams:
            headers += [f"{FAMILY_LABELS[k]} prévu", f"{FAMILY_LABELS[k]} réel", "Δ"]
        headers += ["Statut", "Commentaire"]
        for c, h in enumerate(headers):
            ws.write(row, c, h, f_h)
        ws.set_column(0, 0, 8)
        ws.set_column(1, 2, 18)
        ws.set_column(3, 3 + len(fams) * 3, 10)
        ws.set_column(len(headers) - 1, len(headers) - 1, 32)
        row += 1
        status_lbl = {"a_faire": "À faire", "validee": "Validée", "bloquee": "BLOQUÉE"}
        tot_plan = {k: 0.0 for k in fams}
        tot_reel = {k: 0.0 for k in fams}
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
                if dv is None:
                    ws.write(row, c, "", f_c)
                else:
                    ws.write(row, c, dv, f_ok if dv == 0 else (f_neg if dv < 0 else f_pos))
                c += 1
            stx = x["status"]
            ws.write(row, c, status_lbl.get(stx, stx),
                     f_ok if stx == "validee" else (f_neg if stx == "bloquee" else f_c)); c += 1
            ws.write(row, c, x["comment"], f_cl)
            row += 1
        # Totaux
        ws.write(row, 0, "TOTAL", f_tot)
        ws.write(row, 1, "", f_tot)
        ws.write(row, 2, "", f_tot)
        c = 3
        for k in fams:
            ws.write(row, c, _r(tot_plan[k]), f_tot); c += 1
            ws.write(row, c, _r(tot_reel[k]), f_tot); c += 1
            dv = _r(tot_reel[k] - tot_plan[k])
            ws.write(row, c, dv, f_tot); c += 1
        ws.write(row, c, "", f_tot)
        ws.write(row, c + 1, "", f_tot)
        row += 2

        # Incidents de la nuit
        incs = [i for i in state["incidents"] if i.get("nuit") == nuit]
        if incs:
            ws.write(row, 0, "Incidents de la nuit", f_title)
            row += 1
            for i in incs:
                ws.write(row, 0, f"• {i.get('text')}", f_cl)
                ws.write(row, 4, i.get("author") or "", f_sub)
                row += 1

        wb.close()
        buf.seek(0)
        safe_store = "".join(ch for ch in store if ch.isalnum() or ch in " -_")[:40].strip().replace(" ", "_")
        fname = f"Rapport_nuit_{nuit}_{safe_store}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # ------------------------------------------------ Replanification automatique
    @router.post("/{upload_id}/replan")
    async def replan(upload_id: str, payload: ReplanRequest,
                     current_user: dict = Depends(get_current_user)):
        d = await _load(upload_id, current_user)
        doc = await _get_doc(upload_id, str(current_user["_id"]))
        state = _build_state(d, doc)
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
                import logging
                logging.getLogger(__name__).warning(f"Snapshot avant replan échoué: {e}")
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

    return router
