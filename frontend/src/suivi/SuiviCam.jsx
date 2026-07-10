import React, { useState } from "react";
import { toast } from "sonner";
import {
    ChevronDown, CheckCircle2, Ban, RotateCcw, Loader2,
    AlertTriangle, MoveRight, MapPin, Cctv,
} from "lucide-react";

const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));

export default function SuiviCam({ state, actions }) {
    const cam = state.cam || { nights: [], allees: [], start_at_nuit: 1 };
    const nights = cam.nights || [];
    const [open, setOpen] = useState(() => {
        const first = nights.find((n) => !n.complete && n.nb_allees > 0) || nights.find((n) => n.nb_allees > 0);
        return first ? first.nuit : null;
    });

    if (!nights.some((n) => n.nb_allees > 0)) {
        return (
            <div className="text-center py-20 text-slate-500 text-sm" data-testid="cam-empty">
                Aucune allée caméra assignée à une nuit.<br />
                Complétez le phasage caméras dans l'app Phasage.
            </div>
        );
    }

    return (
        <div className="space-y-3" data-testid="suivi-cam">
            <div className="rounded-xl bg-slate-900 border border-slate-800 p-3 text-xs text-slate-400 flex items-center gap-2">
                <Cctv className="w-4 h-4 text-sky-400 flex-shrink-0" />
                Phasage caméras — démarrage nuit {cam.start_at_nuit}. Saisissez posées + géolocalisées, puis validez chaque allée.
            </div>
            {nights.map((n) => (
                <CamNight key={n.nuit} night={n} cam={cam} actions={actions}
                    isOpen={open === n.nuit} onToggle={() => setOpen(open === n.nuit ? null : n.nuit)} />
            ))}
        </div>
    );
}

function CamNight({ night, cam, actions, isOpen, onToggle }) {
    const items = (cam.allees || []).filter((x) => x.nuit_eff === night.nuit);
    const maxNight = Math.max(cam.nb_nuits || 1, ...(cam.nights || []).map((x) => x.nuit));
    return (
        <section className={`rounded-2xl border overflow-hidden transition-colors
            ${night.complete ? "border-emerald-900/70 bg-emerald-950/20" : "border-slate-800 bg-slate-900"}`}
            data-testid={`cam-night-${night.nuit}`}>
            <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-3 text-left" data-testid={`cam-night-toggle-${night.nuit}`}>
                <div className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm flex-shrink-0
                    ${night.complete ? "bg-emerald-600 text-white" : "bg-sky-800 text-sky-200"}`}>
                    {night.nuit_abs}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold flex items-center gap-2">
                        Nuit {night.nuit_abs} <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/60 text-sky-300 font-semibold">CAM {night.nuit}</span>
                        {night.date && <span className="text-xs text-slate-500 font-normal">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                        {night.complete && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                        {night.nb_bloquees > 0 && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 font-bold">{night.nb_bloquees} bloquée(s)</span>}
                    </div>
                    <div className="text-xs text-slate-400">
                        {night.nb_validees}/{night.nb_allees} allées · {fmt(night.cam_reel)} / {fmt(night.cam_plan)} caméras
                    </div>
                </div>
                <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </button>
            {isOpen && (
                <div className="border-t border-slate-800/80 px-3 pb-3 pt-2 space-y-2">
                    {items.map((a) => <CamAlleeCard key={a.uid} allee={a} cam={cam} actions={actions} maxNight={maxNight} />)}
                </div>
            )}
        </section>
    );
}

function CamAlleeCard({ allee: a, cam, actions, maxNight }) {
    const [reel, setReel] = useState(a.reel ?? "");
    const [geo, setGeo] = useState(a.geo ?? "");
    const [fix, setFix] = useState(a.fix_reel ?? "");
    const [comment, setComment] = useState(a.comment || "");
    const [geoComment, setGeoComment] = useState(a.geoloc_comment || "");
    const [saving, setSaving] = useState(false);
    const gap = a.geo_gap || 0;

    const saveNum = async (field, raw, current) => {
        const num = raw === "" ? null : Number(raw);
        if (raw !== "" && (isNaN(num) || num < 0)) { toast.error("Valeur invalide"); return; }
        if (num === (current ?? null)) return;
        await actions.patchCamAllee(a.uid, { [field]: num });
    };

    const setStatus = async (status) => {
        setSaving(true);
        const fields = { status };
        if (status === "validee" && reel === "" && a.reel === null) fields.cameras_reel = a.plan || 0;
        const ok = await actions.patchCamAllee(a.uid, fields);
        if (ok && status === "validee") toast.success(`Allée ${a.allee} (caméras) validée`);
        setSaving(false);
    };

    const moveNight = async (e) => {
        const v = Number(e.target.value);
        await actions.patchCamAllee(a.uid, { nuit_reelle: v === a.nuit_plan ? 0 : v });
        toast.success(`Allée ${a.allee} déplacée`);
    };

    // Doublons d'éléments = plusieurs caméras sur le même élément
    const elemCounts = {};
    (a.elements || []).forEach((el) => { elemCounts[el] = (elemCounts[el] || 0) + 1; });

    const border = a.status === "validee" ? "border-emerald-800/70" : a.status === "bloquee" ? "border-red-800/70" : "border-slate-700/70";

    return (
        <div className={`rounded-xl bg-slate-800/50 border ${border} p-3`} data-testid={`cam-card-${a.uid}`}>
            <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-2 py-0.5 rounded-md text-sm font-bold
                    ${a.status === "validee" ? "bg-emerald-600 text-white" : a.status === "bloquee" ? "bg-red-600 text-white" : "bg-sky-800 text-sky-100"}`}>
                    Allée {a.allee}
                </span>
                <span className="text-xs text-slate-400 truncate flex-1 min-w-0">{a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}</span>
                {gap > 0 && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/70 text-red-300 font-bold flex items-center gap-1" data-testid={`cam-geo-warn-${a.uid}`}>
                        <MapPin className="w-3 h-3" /> Géoloc incomplète
                    </span>
                )}
                {a.nuit_reelle && a.nuit_reelle !== a.nuit_plan && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-900/60 text-violet-300 font-semibold flex items-center gap-1">
                        <MoveRight className="w-3 h-3" /> plan N{cam.start_at_nuit + a.nuit_plan - 1}
                    </span>
                )}
                <select value={a.nuit_eff} onChange={moveNight} data-testid={`cam-move-${a.uid}`}
                    className="h-7 rounded-lg bg-slate-900 border border-slate-700 text-[11px] px-1.5 text-slate-300 focus:border-sky-500 outline-none cursor-pointer">
                    {Array.from({ length: maxNight }, (_, i) => i + 1).map((x) => (
                        <option key={x} value={x}>{"N" + (cam.start_at_nuit + x - 1)}</option>
                    ))}
                </select>
            </div>

            {/* Éléments caméras */}
            <div className="flex items-center gap-1.5 mt-2 flex-wrap" data-testid={`cam-elements-${a.uid}`}>
                <span className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">Éléments :</span>
                {Object.entries(elemCounts).map(([el, count]) => (
                    <span key={el} className={`text-[11px] px-1.5 py-0.5 rounded font-mono
                        ${count > 1 ? "bg-red-900/60 text-red-300 font-bold" : "bg-slate-900 text-slate-300 border border-slate-700"}`}
                        title={count > 1 ? `${count} caméras sur cet élément` : ""}>
                        {el}{count > 1 ? ` ×${count}` : ""}
                    </span>
                ))}
                {(a.elements || []).length === 0 && <span className="text-[11px] text-slate-600">aucun</span>}
            </div>

            {/* posé / géolocalisé */}
            <div className="grid grid-cols-2 gap-2 mt-2">
                <div className="rounded-lg bg-slate-900/70 p-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold flex items-center justify-between">
                        Caméras posées
                        {a.delta !== null && a.delta !== undefined && (
                            <span className={`font-bold ${a.delta === 0 ? "text-emerald-400" : a.delta < 0 ? "text-red-400" : "text-amber-400"}`}>
                                {a.delta > 0 ? "+" : ""}{fmt(a.delta)}
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-1">
                        <span className="text-xs text-slate-400 w-8 text-right" title="Prévu">{fmt(a.plan)}</span>
                        <span className="text-slate-600 text-xs">→</span>
                        <input type="number" min="0" inputMode="numeric" placeholder="posé" value={reel}
                            onChange={(e) => setReel(e.target.value)}
                            onBlur={() => saveNum("cameras_reel", reel, a.reel)}
                            data-testid={`cam-input-reel-${a.uid}`}
                            className="w-full h-7 px-1.5 rounded bg-slate-800 border border-slate-700 text-xs text-center focus:border-sky-500 outline-none placeholder:text-slate-600" />
                    </div>
                </div>
                <div className={`rounded-lg bg-slate-900/70 p-2 ${gap ? "ring-1 ring-red-800" : ""}`}>
                    <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold flex items-center gap-1">
                        <MapPin className={`w-3 h-3 ${gap ? "text-red-400" : "text-sky-400"}`} /> Géolocalisées
                    </div>
                    <div className="flex items-center gap-1.5 mt-1">
                        <span className="w-8" />
                        <span className="text-slate-600 text-xs">→</span>
                        <input type="number" min="0" inputMode="numeric" placeholder="géo" value={geo}
                            onChange={(e) => setGeo(e.target.value)}
                            onBlur={() => saveNum("cameras_geo", geo, a.geo)}
                            data-testid={`cam-input-geo-${a.uid}`}
                            className={`w-full h-7 px-1.5 rounded bg-slate-800 border text-xs text-center outline-none placeholder:text-slate-600
                                ${gap ? "border-red-700 focus:border-red-500 text-red-300" : "border-slate-700 focus:border-sky-500"}`} />
                    </div>
                </div>
                <div className="rounded-lg bg-slate-900/70 p-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold flex items-center justify-between">
                        Fixations posées
                        {a.fix_delta !== null && a.fix_delta !== undefined && (
                            <span className={`font-bold ${a.fix_delta === 0 ? "text-emerald-400" : a.fix_delta < 0 ? "text-red-400" : "text-amber-400"}`}>
                                {a.fix_delta > 0 ? "+" : ""}{fmt(a.fix_delta)}
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-1">
                        <span className="text-xs text-slate-400 w-8 text-right" title="Prévu">{a.fix_plan !== null && a.fix_plan !== undefined ? fmt(a.fix_plan) : "—"}</span>
                        <span className="text-slate-600 text-xs">→</span>
                        <input type="number" min="0" inputMode="numeric" placeholder="fixations" value={fix}
                            onChange={(e) => setFix(e.target.value)}
                            onBlur={() => saveNum("fixations_reel", fix, a.fix_reel)}
                            data-testid={`cam-input-fix-${a.uid}`}
                            className="w-full h-7 px-1.5 rounded bg-slate-800 border border-slate-700 text-xs text-center focus:border-sky-500 outline-none placeholder:text-slate-600" />
                    </div>
                </div>
            </div>

            {gap > 0 && (
                <div className="mt-2 rounded-lg bg-red-950/40 border border-red-900/60 p-2" data-testid={`cam-geo-explain-${a.uid}`}>
                    <div className="text-[11px] text-red-300 font-semibold flex items-center gap-1.5 mb-1">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        {fmt(gap)} caméra(s) posée(s) non géolocalisée(s){!geoComment && " — explication demandée"}
                    </div>
                    <input value={geoComment} onChange={(e) => setGeoComment(e.target.value)}
                        onBlur={() => { if (geoComment !== (a.geoloc_comment || "")) actions.patchCamAllee(a.uid, { geoloc_comment: geoComment }); }}
                        placeholder="Pourquoi ? (ex: pas de signal, config à finir...)"
                        data-testid={`cam-geo-comment-${a.uid}`}
                        className="w-full h-8 px-2.5 rounded-lg bg-slate-900 border border-red-900/70 text-xs placeholder:text-slate-600 focus:border-red-500 outline-none" />
                </div>
            )}

            <div className="flex items-center gap-2 mt-2.5 flex-wrap">
                {a.status !== "validee" ? (
                    <button onClick={() => setStatus("validee")} disabled={saving} data-testid={`cam-validate-${a.uid}`}
                        className="h-8 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-colors">
                        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />} Valider
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`cam-reopen-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-slate-600 text-slate-300 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-700 transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Rouvrir
                    </button>
                )}
                {a.status !== "bloquee" ? (
                    <button onClick={() => setStatus("bloquee")} disabled={saving} data-testid={`cam-block-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-red-800 text-red-400 text-xs font-semibold flex items-center gap-1.5 hover:bg-red-950/50 transition-colors">
                        <Ban className="w-3.5 h-3.5" /> Bloquer
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`cam-unblock-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-slate-600 text-slate-300 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-700 transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Débloquer
                    </button>
                )}
                <input value={comment} onChange={(e) => setComment(e.target.value)}
                    onBlur={() => { if (comment !== (a.comment || "")) actions.patchCamAllee(a.uid, { comment }); }}
                    placeholder="Commentaire"
                    data-testid={`cam-comment-${a.uid}`}
                    className="flex-1 min-w-[140px] h-8 px-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs placeholder:text-slate-600 focus:border-sky-500 outline-none" />
            </div>
        </div>
    );
}
