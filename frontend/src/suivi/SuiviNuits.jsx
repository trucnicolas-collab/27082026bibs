import React, { useState, useRef } from "react";
import { toast } from "sonner";
import {
    ChevronDown, CheckCircle2, Ban, RotateCcw, Download, Loader2,
    AlertTriangle, MessageSquarePlus, Trash2, MoveRight, MapPin, Camera, X,
} from "lucide-react";
import { compressImage } from "./api";

const FAM_SHORT = {
    es_15: "ES 1.5", es_21: "ES 2.1", rails_es: "Rails",
    sa_15: "SA 1.5", sa_21_std: "SA 2.1", sa_21_freezer: "SA frz",
    sa_42: "SA 4.2", cameras: "Cam",
};
const FAMILY_KEYS = Object.keys(FAM_SHORT);
const GEO_KEYS = ["rails_es", "sa_15", "sa_21_std", "sa_21_freezer"];
const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));

export default function SuiviNuits({ state, actions, mode = "chef" }) {
    const nights = state.nights || [];
    const [open, setOpen] = useState(() => {
        const firstOpen = nights.find((n) => !n.complete && n.nb_allees > 0) || nights.find((n) => n.nb_allees > 0);
        return firstOpen ? firstOpen.nuit : (nights[0]?.nuit ?? null);
    });

    if (!nights.some((n) => n.nb_allees > 0)) {
        return (
            <div className="text-center py-20 text-slate-500 text-sm" data-testid="nuits-empty">
                Aucune allée assignée à une nuit.
                {mode === "chef" && (<><br />Complétez d'abord le phasage dans l'<a href="/" className="text-emerald-400 underline">app Phasage</a>.</>)}
            </div>
        );
    }

    return (
        <div className="space-y-3" data-testid="suivi-nuits">
            {nights.map((n) => (
                <NightBlock key={n.nuit} night={n} state={state} actions={actions} mode={mode}
                    isOpen={open === n.nuit} onToggle={() => setOpen(open === n.nuit ? null : n.nuit)} />
            ))}
        </div>
    );
}

function NightBlock({ night, state, actions, mode, isOpen, onToggle }) {
    const n = night.nuit;
    const items = (state.allees || []).filter((x) => x.nuit_eff === n);
    const incidents = (state.incidents || []).filter((i) => i.nuit === n);
    const [downloading, setDownloading] = useState(false);
    const [incidentText, setIncidentText] = useState("");
    const maxNight = Math.max(state.nb_nuits || 1, ...(state.nights || []).map((x) => x.nuit));

    const dl = async (e) => {
        e.stopPropagation();
        setDownloading(true);
        await actions.downloadReport(n);
        setDownloading(false);
    };

    return (
        <section className={`rounded-2xl border overflow-hidden transition-colors
            ${night.complete ? "border-emerald-900/70 bg-emerald-950/20" : night.started ? "border-sky-900/70 bg-slate-900" : "border-slate-800 bg-slate-900"}`}
            data-testid={`night-block-${n}`}>
            <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-3 text-left" data-testid={`night-toggle-${n}`}>
                <div className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm flex-shrink-0
                    ${night.complete ? "bg-emerald-600 text-white" : night.started ? "bg-sky-700 text-white" : "bg-slate-800 text-slate-400"}`}>
                    {n}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold flex items-center gap-2">
                        Nuit {n}
                        {night.date && <span className="text-xs text-slate-500 font-normal">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })}</span>}
                        {night.complete && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                        {night.nb_bloquees > 0 && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 font-bold">{night.nb_bloquees} bloquée(s)</span>}
                    </div>
                    <div className="text-xs text-slate-400">
                        {night.nb_validees}/{night.nb_allees} allées · {fmt(night.eeg_reel)} / {fmt(night.eeg_plan)} EEG
                        {night.delta_eeg !== null && night.delta_eeg !== undefined && (
                            <span className={`ml-1.5 font-semibold ${night.delta_eeg > 0 ? "text-emerald-400" : night.delta_eeg < 0 ? "text-red-400" : "text-slate-500"}`}>
                                ({night.delta_eeg > 0 ? "+" : ""}{fmt(night.delta_eeg)})
                            </span>
                        )}
                    </div>
                </div>
                {night.nb_allees > 0 && (
                    <span onClick={dl} role="button" data-testid={`night-report-${n}`}
                        title="Télécharger le rapport de la nuit"
                        className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-emerald-400 transition-colors">
                        {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    </span>
                )}
                <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </button>

            {isOpen && (
                <div className="border-t border-slate-800/80 px-3 pb-3 pt-2 space-y-2">
                    {items.length === 0 && <div className="text-xs text-slate-500 py-4 text-center">Aucune allée sur cette nuit.</div>}
                    {items.map((a) => (
                        <AlleeCard key={a.uid} allee={a} actions={actions} maxNight={maxNight} />
                    ))}

                    <div className="rounded-xl bg-slate-800/40 p-3 mt-2" data-testid={`night-incidents-${n}`}>
                        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-2 flex items-center gap-1.5">
                            <AlertTriangle className="w-3.5 h-3.5" /> Incidents de la nuit
                        </div>
                        {incidents.map((i) => (
                            <div key={i.id} className="flex items-start gap-2 text-xs text-slate-300 py-1">
                                <span className="flex-1">• {i.text}</span>
                                <button onClick={() => actions.delIncident(i.id)} data-testid={`incident-del-${i.id}`}
                                    className="text-slate-600 hover:text-red-400 transition-colors"><Trash2 className="w-3.5 h-3.5" /></button>
                            </div>
                        ))}
                        <div className="flex gap-2 mt-1.5">
                            <input value={incidentText} onChange={(e) => setIncidentText(e.target.value)}
                                onKeyDown={(e) => { if (e.key === "Enter" && incidentText.trim()) { actions.addIncident(n, incidentText); setIncidentText(""); } }}
                                placeholder="Signaler un incident (rupture, casse, accès...)"
                                data-testid={`incident-input-${n}`}
                                className="flex-1 h-8 px-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs placeholder:text-slate-600 focus:border-emerald-600 outline-none" />
                            <button onClick={() => { if (incidentText.trim()) { actions.addIncident(n, incidentText); setIncidentText(""); } }}
                                data-testid={`incident-add-${n}`}
                                className="h-8 px-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-xs flex items-center gap-1 transition-colors">
                                <MessageSquarePlus className="w-3.5 h-3.5" /> Ajouter
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </section>
    );
}

function AlleeCard({ allee: a, actions, maxNight }) {
    const [vals, setVals] = useState(() => {
        const v = {};
        FAMILY_KEYS.forEach((k) => { v[k] = a.reel[k] ?? ""; });
        return v;
    });
    const [geoVals, setGeoVals] = useState(() => {
        const v = {};
        GEO_KEYS.forEach((k) => { v[k] = (a.geo && a.geo[k] !== null && a.geo[k] !== undefined) ? a.geo[k] : ""; });
        return v;
    });
    const [comment, setComment] = useState(a.comment || "");
    const [geoComment, setGeoComment] = useState(a.geoloc_comment || "");
    const [saving, setSaving] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [zoom, setZoom] = useState(null);
    const fileRef = useRef(null);
    const fams = FAMILY_KEYS.filter((k) => (a.plan[k] || 0) > 0 || a.reel[k] !== null);
    const hasGeoGap = Object.values(a.geo_gap || {}).some((v) => v > 0);

    const saveField = async (k) => {
        const raw = vals[k];
        const num = raw === "" ? null : Number(raw);
        if (raw !== "" && (isNaN(num) || num < 0)) { toast.error("Valeur invalide"); return; }
        if (num === (a.reel[k] ?? null)) return;
        await actions.patchAllee(a.uid, { [`${k}_reel`]: num });
    };

    const saveGeo = async (k) => {
        const raw = geoVals[k];
        const num = raw === "" ? null : Number(raw);
        if (raw !== "" && (isNaN(num) || num < 0)) { toast.error("Valeur invalide"); return; }
        if (num === ((a.geo && a.geo[k]) ?? null)) return;
        await actions.patchAllee(a.uid, { [`${k}_geo`]: num });
    };

    const setStatus = async (status) => {
        setSaving(true);
        const fields = { status };
        if (status === "validee") {
            fams.forEach((k) => {
                if (vals[k] === "" && a.reel[k] === null) {
                    fields[`${k}_reel`] = a.plan[k] || 0;
                }
            });
        }
        const ok = await actions.patchAllee(a.uid, fields);
        if (ok && status === "validee") toast.success(`Allée ${a.allee} validée`);
        if (ok && status === "bloquee") toast.warning(`Allée ${a.allee} bloquée`);
        setSaving(false);
    };

    const moveNight = async (e) => {
        const v = Number(e.target.value);
        await actions.patchAllee(a.uid, { nuit_reelle: v === a.nuit_plan ? 0 : v });
        toast.success(v === a.nuit_plan ? `Allée ${a.allee} → nuit planifiée ${a.nuit_plan}` : `Allée ${a.allee} déplacée en nuit ${v}`);
    };

    const onPhotoPick = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        setUploading(true);
        try {
            const blob = await compressImage(file);
            await actions.uploadPhoto(a.uid, blob);
        } catch {
            toast.error("Photo illisible");
        } finally { setUploading(false); }
    };

    const border = a.status === "validee" ? "border-emerald-800/70" : a.status === "bloquee" ? "border-red-800/70" : "border-slate-700/70";

    return (
        <div className={`rounded-xl bg-slate-800/50 border ${border} p-3`} data-testid={`allee-card-${a.uid}`}>
            <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-2 py-0.5 rounded-md text-sm font-bold
                    ${a.status === "validee" ? "bg-emerald-600 text-white" : a.status === "bloquee" ? "bg-red-600 text-white" : "bg-slate-700 text-slate-200"}`}>
                    Allée {a.allee}
                </span>
                <span className="text-xs text-slate-400 truncate flex-1 min-w-0">{a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}</span>
                {hasGeoGap && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/70 text-red-300 font-bold flex items-center gap-1" data-testid={`allee-geo-warn-${a.uid}`}>
                        <MapPin className="w-3 h-3" /> Géoloc incomplète
                    </span>
                )}
                {a.nuit_reelle && a.nuit_reelle !== a.nuit_plan && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-900/60 text-violet-300 font-semibold flex items-center gap-1">
                        <MoveRight className="w-3 h-3" /> plan N{a.nuit_plan}
                    </span>
                )}
                <select value={a.nuit_eff} onChange={moveNight} data-testid={`allee-move-${a.uid}`}
                    title="Déplacer sur une autre nuit"
                    className="h-7 rounded-lg bg-slate-900 border border-slate-700 text-[11px] px-1.5 text-slate-300 focus:border-emerald-600 outline-none cursor-pointer">
                    {Array.from({ length: maxNight }, (_, i) => i + 1).map((x) => (
                        <option key={x} value={x}>{"N" + x}</option>
                    ))}
                </select>
            </div>

            {/* prévu → réel posé (+ géolocalisé pour rails/SA) */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2.5">
                {fams.map((k) => {
                    const d = a.delta[k];
                    const isGeo = GEO_KEYS.includes(k);
                    const gap = (a.geo_gap || {})[k];
                    return (
                        <div key={k} className={`rounded-lg bg-slate-900/70 p-2 ${gap ? "ring-1 ring-red-800" : ""}`}>
                            <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold flex items-center justify-between">
                                {FAM_SHORT[k]}
                                {d !== null && d !== undefined && (
                                    <span className={`font-bold ${d === 0 ? "text-emerald-400" : d < 0 ? "text-red-400" : "text-amber-400"}`}>
                                        {d > 0 ? "+" : ""}{fmt(d)}
                                    </span>
                                )}
                            </div>
                            <div className="flex items-center gap-1.5 mt-1">
                                <span className="text-xs text-slate-400 w-10 text-right" title="Prévu">{fmt(a.plan[k])}</span>
                                <span className="text-slate-600 text-xs">→</span>
                                <input type="number" min="0" inputMode="numeric" placeholder="posé"
                                    value={vals[k]}
                                    onChange={(e) => setVals((s) => ({ ...s, [k]: e.target.value }))}
                                    onBlur={() => saveField(k)}
                                    data-testid={`allee-input-${k}-${a.uid}`}
                                    className="w-full h-7 px-1.5 rounded bg-slate-800 border border-slate-700 text-xs text-center focus:border-emerald-500 outline-none placeholder:text-slate-600" />
                            </div>
                            {isGeo && (
                                <div className="flex items-center gap-1.5 mt-1">
                                    <span className="w-10 flex justify-end" title="Géolocalisé">
                                        <MapPin className={`w-3.5 h-3.5 ${gap ? "text-red-400" : "text-sky-400"}`} />
                                    </span>
                                    <span className="text-slate-600 text-xs">→</span>
                                    <input type="number" min="0" inputMode="numeric" placeholder="géo"
                                        value={geoVals[k]}
                                        onChange={(e) => setGeoVals((s) => ({ ...s, [k]: e.target.value }))}
                                        onBlur={() => saveGeo(k)}
                                        data-testid={`allee-geo-${k}-${a.uid}`}
                                        className={`w-full h-7 px-1.5 rounded bg-slate-800 border text-xs text-center outline-none placeholder:text-slate-600
                                            ${gap ? "border-red-700 focus:border-red-500 text-red-300" : "border-slate-700 focus:border-sky-500"}`} />
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Explication demandée si géoloc < posé */}
            {hasGeoGap && (
                <div className="mt-2 rounded-lg bg-red-950/40 border border-red-900/60 p-2" data-testid={`allee-geo-explain-${a.uid}`}>
                    <div className="text-[11px] text-red-300 font-semibold flex items-center gap-1.5 mb-1">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        {Object.entries(a.geo_gap).filter(([, v]) => v > 0).map(([k, v]) => `${FAM_SHORT[k]} : ${fmt(v)} posé(s) non géolocalisé(s)`).join(" · ")}
                        {!geoComment && " — explication demandée"}
                    </div>
                    <input value={geoComment} onChange={(e) => setGeoComment(e.target.value)}
                        onBlur={() => { if (geoComment !== (a.geoloc_comment || "")) actions.patchAllee(a.uid, { geoloc_comment: geoComment }); }}
                        placeholder="Pourquoi ? (ex: zone sans signal, scan à refaire demain...)"
                        data-testid={`allee-geo-comment-${a.uid}`}
                        className="w-full h-8 px-2.5 rounded-lg bg-slate-900 border border-red-900/70 text-xs placeholder:text-slate-600 focus:border-red-500 outline-none" />
                </div>
            )}

            {/* Photos */}
            <div className="flex items-center gap-2 mt-2.5 flex-wrap" data-testid={`allee-photos-${a.uid}`}>
                {(a.photos || []).map((p) => (
                    <div key={p.id} className="relative group">
                        <img src={actions.photoUrl(p.id)} alt="" loading="lazy"
                            onClick={() => setZoom(p.id)}
                            className="w-14 h-14 object-cover rounded-lg border border-slate-700 cursor-zoom-in" />
                        <button onClick={() => actions.delPhoto(p.id)} data-testid={`photo-del-${p.id}`}
                            className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-600 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                            <X className="w-3 h-3" />
                        </button>
                    </div>
                ))}
                <button onClick={() => fileRef.current?.click()} disabled={uploading}
                    data-testid={`allee-add-photo-${a.uid}`}
                    className="w-14 h-14 rounded-lg border border-dashed border-slate-600 text-slate-500 hover:text-emerald-400 hover:border-emerald-600 flex flex-col items-center justify-center gap-0.5 transition-colors">
                    {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Camera className="w-4 h-4" />}
                    <span className="text-[9px]">Photo</span>
                </button>
                <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPhotoPick} />
            </div>

            {/* actions + commentaire */}
            <div className="flex items-center gap-2 mt-2.5 flex-wrap">
                {a.status !== "validee" ? (
                    <button onClick={() => setStatus("validee")} disabled={saving} data-testid={`allee-validate-${a.uid}`}
                        className="h-8 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-colors">
                        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />} Valider
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`allee-reopen-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-slate-600 text-slate-300 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-700 transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Rouvrir
                    </button>
                )}
                {a.status !== "bloquee" ? (
                    <button onClick={() => setStatus("bloquee")} disabled={saving} data-testid={`allee-block-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-red-800 text-red-400 text-xs font-semibold flex items-center gap-1.5 hover:bg-red-950/50 transition-colors">
                        <Ban className="w-3.5 h-3.5" /> Bloquer
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`allee-unblock-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-slate-600 text-slate-300 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-700 transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Débloquer
                    </button>
                )}
                <input value={comment} onChange={(e) => setComment(e.target.value)}
                    onBlur={() => { if (comment !== (a.comment || "")) actions.patchAllee(a.uid, { comment }); }}
                    placeholder="Commentaire (manque produit, casse...)"
                    data-testid={`allee-comment-${a.uid}`}
                    className="flex-1 min-w-[140px] h-8 px-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs placeholder:text-slate-600 focus:border-emerald-600 outline-none" />
            </div>

            {zoom && (
                <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4" onClick={() => setZoom(null)} data-testid="photo-zoom">
                    <img src={actions.photoUrl(zoom)} alt="" className="max-w-full max-h-full rounded-xl" />
                    <button className="absolute top-4 right-4 p-2 rounded-full bg-slate-800 text-white"><X className="w-5 h-5" /></button>
                </div>
            )}
        </div>
    );
}
