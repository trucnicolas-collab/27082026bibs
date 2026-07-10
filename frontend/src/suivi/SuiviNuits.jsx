import React, { useState, useRef } from "react";
import { toast } from "sonner";
import {
    CheckCircle2, Ban, RotateCcw, Download, Loader2, AlertTriangle,
    MessageSquarePlus, Trash2, MoveRight, MapPin, Camera, X,
    ChevronRight, ArrowLeft, Moon,
} from "lucide-react";
import { compressImage } from "./api";

const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));
const STATUS_CHIP = {
    a_faire: ["À faire", "bg-slate-700 text-slate-200"],
    validee: ["Validée", "bg-emerald-600 text-white"],
    bloquee: ["Bloquée", "bg-red-600 text-white"],
};

// Suivi de pose : Nuits → Allées → Allée PLEIN ÉCRAN (saisie par produit)
export default function SuiviNuits({ state, actions, mode = "chef" }) {
    const [view, setView] = useState({ level: "nights", nuit: null, uid: null });
    const nights = (state.nights || []).filter((n) => n.nb_allees > 0);

    if (!nights.length) {
        return (
            <div className="text-center py-20 text-slate-500 text-sm" data-testid="nuits-empty">
                Aucune allée assignée à une nuit.
                {mode === "chef" && (<><br />Complétez d'abord le phasage dans l'<a href="/" className="text-emerald-400 underline">app Phasage</a>.</>)}
            </div>
        );
    }

    if (view.level === "allee") {
        const a = (state.allees || []).find((x) => x.uid === view.uid);
        if (!a) { setView({ level: "allees", nuit: view.nuit, uid: null }); return null; }
        return <AlleeScreen allee={a} state={state} actions={actions}
            onBack={() => setView({ level: "allees", nuit: view.nuit, uid: null })} />;
    }

    if (view.level === "allees") {
        const night = (state.nights || []).find((n) => n.nuit === view.nuit);
        if (!night) { setView({ level: "nights", nuit: null, uid: null }); return null; }
        return <NightScreen night={night} state={state} actions={actions}
            onBack={() => setView({ level: "nights", nuit: null, uid: null })}
            onOpenAllee={(uid) => setView({ level: "allee", nuit: view.nuit, uid })} />;
    }

    return (
        <div className="space-y-2.5" data-testid="suivi-nuits">
            <div className="rounded-xl bg-slate-900 border border-slate-800 p-3 text-xs text-slate-400 flex items-center gap-2">
                <Moon className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                Touchez une nuit, puis une allée, pour saisir la pose produit par produit.
            </div>
            {nights.map((n) => <NightRow key={n.nuit} night={n} actions={actions}
                onOpen={() => setView({ level: "allees", nuit: n.nuit, uid: null })} />)}
        </div>
    );
}

function NightRow({ night, actions, onOpen }) {
    const [downloading, setDownloading] = useState(false);
    const dl = async (e) => {
        e.stopPropagation();
        setDownloading(true);
        await actions.downloadReport(night.nuit);
        setDownloading(false);
    };
    return (
        <section className={`rounded-2xl border overflow-hidden transition-colors
            ${night.complete ? "border-emerald-900/70 bg-emerald-950/20" : night.started ? "border-sky-900/70 bg-slate-900" : "border-slate-800 bg-slate-900"}`}
            data-testid={`night-block-${night.nuit}`}>
            <button onClick={onOpen} className="w-full flex items-center gap-3 px-4 py-3.5 text-left" data-testid={`night-open-${night.nuit}`}>
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold flex-shrink-0
                    ${night.complete ? "bg-emerald-600 text-white" : night.started ? "bg-sky-700 text-white" : "bg-slate-800 text-slate-400"}`}>
                    {night.nuit}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold flex items-center gap-2">
                        Nuit {night.nuit}
                        {night.date && <span className="text-xs text-slate-500 font-normal">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })}</span>}
                        {night.complete && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                        {night.nb_bloquees > 0 && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 font-bold">{night.nb_bloquees} bloquée(s)</span>}
                    </div>
                    <div className="text-xs text-slate-400">
                        {night.nb_validees}/{night.nb_allees} allées validées · {fmt(night.eeg_reel)} / {fmt(night.eeg_plan)} EEG
                        {night.delta_eeg !== null && night.delta_eeg !== undefined && (
                            <span className={`ml-1.5 font-semibold ${night.delta_eeg > 0 ? "text-emerald-400" : night.delta_eeg < 0 ? "text-red-400" : "text-slate-500"}`}>
                                ({night.delta_eeg > 0 ? "+" : ""}{fmt(night.delta_eeg)})
                            </span>
                        )}
                    </div>
                </div>
                <span onClick={dl} role="button" data-testid={`night-report-${night.nuit}`}
                    title="Télécharger le rapport de la nuit"
                    className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-emerald-400 transition-colors">
                    {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                </span>
                <ChevronRight className="w-4 h-4 text-slate-500" />
            </button>
        </section>
    );
}

// ---- Niveau 2 : allées de la nuit ----
function NightScreen({ night, state, actions, onBack, onOpenAllee }) {
    const n = night.nuit;
    const items = (state.allees || []).filter((x) => x.nuit_eff === n);
    const incidents = (state.incidents || []).filter((i) => i.nuit === n);
    const [incidentText, setIncidentText] = useState("");
    const [downloading, setDownloading] = useState(false);

    return (
        <div className="space-y-2.5" data-testid={`night-screen-${n}`}>
            <div className="flex items-center gap-2">
                <button onClick={onBack} data-testid="night-back"
                    className="flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300 transition-colors">
                    <ArrowLeft className="w-4 h-4" /> Nuits
                </button>
                <div className="flex-1" />
                <button onClick={async () => { setDownloading(true); await actions.downloadReport(n); setDownloading(false); }}
                    data-testid={`night-report-detail-${n}`}
                    className="h-8 px-3 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-colors">
                    {downloading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Rapport
                </button>
            </div>
            <h3 className="text-base font-bold flex items-center gap-2">
                <Moon className="w-4 h-4 text-sky-400" /> Nuit {n}
                {night.date && <span className="text-xs text-slate-500 font-normal">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                <span className="text-xs text-slate-400 font-normal">· {night.nb_validees}/{night.nb_allees} validées</span>
            </h3>

            {items.map((a) => {
                const [lbl, cls] = STATUS_CHIP[a.status] || STATUS_CHIP.a_faire;
                const hasGap = Object.keys(a.geo_gap || {}).length > 0;
                return (
                    <button key={a.uid} onClick={() => onOpenAllee(a.uid)}
                        data-testid={`allee-open-${a.uid}`}
                        className={`w-full flex items-center gap-3 rounded-xl border p-3.5 text-left transition-colors hover:border-emerald-700
                            ${a.status === "validee" ? "bg-emerald-950/20 border-emerald-900/60" : a.status === "bloquee" ? "bg-red-950/20 border-red-900/60" : "bg-slate-900 border-slate-800"}`}>
                        <span className="px-2 py-1 rounded-md bg-slate-700 text-slate-100 text-sm font-bold flex-shrink-0">
                            {a.allee}
                        </span>
                        <div className="flex-1 min-w-0">
                            <div className="text-xs text-slate-300 truncate">{a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}</div>
                            <div className="text-[11px] text-slate-500">
                                {a.nb_saisis}/{a.nb_produits} produits saisis · {fmt(a.eeg_reel)} / {fmt(a.eeg_plan)} EEG
                            </div>
                        </div>
                        {hasGap && <MapPin className="w-4 h-4 text-red-400 flex-shrink-0" title="Géoloc incomplète" />}
                        {a.photos?.length > 0 && <Camera className="w-4 h-4 text-slate-500 flex-shrink-0" />}
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold flex-shrink-0 ${cls}`}>{lbl}</span>
                        <ChevronRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
                    </button>
                );
            })}

            <div className="rounded-xl bg-slate-800/40 p-3" data-testid={`night-incidents-${n}`}>
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
    );
}

// ---- Niveau 3 : allée PLEIN ÉCRAN, saisie par produit ----
function AlleeScreen({ allee: a, state, actions, onBack }) {
    const [vals, setVals] = useState(() => {
        const v = {};
        (a.products || []).forEach((p) => { v[p.designation] = { reel: p.reel ?? "", geo: p.geo ?? "" }; });
        return v;
    });
    const [comment, setComment] = useState(a.comment || "");
    const [geoComment, setGeoComment] = useState(a.geoloc_comment || "");
    const [saving, setSaving] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [zoom, setZoom] = useState(null);
    const fileRef = useRef(null);
    const maxNight = Math.max(state.nb_nuits || 1, ...(state.nights || []).map((x) => x.nuit));
    const gapProducts = (a.products || []).filter((p) => p.gap > 0);
    const [lbl, cls] = STATUS_CHIP[a.status] || STATUS_CHIP.a_faire;

    const saveField = async (designation, field) => {
        const raw = vals[designation]?.[field];
        const num = raw === "" ? null : Number(raw);
        if (raw !== "" && (isNaN(num) || num < 0)) { toast.error("Valeur invalide"); return; }
        const p = a.products.find((x) => x.designation === designation);
        if (num === ((p && p[field]) ?? null)) return;
        await actions.patchAllee(a.uid, { products: [{ designation, [field]: num }] });
    };

    const setStatus = async (status) => {
        setSaving(true);
        const fields = { status };
        if (status === "validee") {
            const fill = (a.products || [])
                .filter((p) => p.reel === null && (vals[p.designation]?.reel ?? "") === "")
                .map((p) => ({ designation: p.designation, reel: p.plan || 0 }));
            if (fill.length) fields.products = fill;
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
        } catch { toast.error("Photo illisible"); }
        finally { setUploading(false); }
    };

    return (
        <div className="space-y-3" data-testid={`allee-screen-${a.uid}`}>
            {/* En-tête */}
            <div className="flex items-center gap-2">
                <button onClick={onBack} data-testid="allee-back"
                    className="flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300 transition-colors">
                    <ArrowLeft className="w-4 h-4" /> Nuit {a.nuit_eff}
                </button>
                <div className="flex-1" />
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
            <div className="rounded-2xl bg-slate-900 border border-slate-800 p-4">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="px-2.5 py-1 rounded-md bg-slate-700 text-slate-100 text-base font-bold">Allée {a.allee}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${cls}`}>{lbl}</span>
                    <span className="text-xs text-slate-400 w-full sm:w-auto sm:flex-1 truncate">{a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}</span>
                    <span className="text-[11px] text-slate-500">{a.nb_saisis}/{a.nb_produits} produits saisis</span>
                </div>
            </div>

            {/* Produits */}
            <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden" data-testid={`allee-products-${a.uid}`}>
                <div className="grid grid-cols-[1fr_52px_64px_64px_44px] gap-1 px-3 py-2 text-[10px] uppercase tracking-wider text-slate-500 font-semibold border-b border-slate-800">
                    <span>Produit</span><span className="text-center">Prévu</span>
                    <span className="text-center">Posé</span><span className="text-center">Géoloc</span><span className="text-center">Δ</span>
                </div>
                {(a.products || []).map((p) => (
                    <div key={p.designation}
                        className={`grid grid-cols-[1fr_52px_64px_64px_44px] gap-1 items-center px-3 py-2 border-b border-slate-800/60 last:border-0 ${p.gap ? "bg-red-950/20" : ""}`}
                        data-testid={`product-row-${a.uid}-${p.designation}`}>
                        <div className="min-w-0">
                            <div className="text-xs text-slate-200 truncate" title={p.designation}>{p.designation}</div>
                            {p.is_geo && <div className="text-[9px] text-sky-500 flex items-center gap-0.5"><MapPin className="w-2.5 h-2.5" /> à géolocaliser</div>}
                        </div>
                        <div className="text-xs text-slate-400 text-center tabular-nums">{fmt(p.plan)}</div>
                        <input type="number" min="0" inputMode="numeric" placeholder="—"
                            value={vals[p.designation]?.reel ?? ""}
                            onChange={(e) => setVals((s) => ({ ...s, [p.designation]: { ...s[p.designation], reel: e.target.value } }))}
                            onBlur={() => saveField(p.designation, "reel")}
                            data-testid={`product-reel-${p.designation}`}
                            className="h-8 px-1 rounded bg-slate-800 border border-slate-700 text-xs text-center focus:border-emerald-500 outline-none placeholder:text-slate-600" />
                        {p.is_geo ? (
                            <input type="number" min="0" inputMode="numeric" placeholder="—"
                                value={vals[p.designation]?.geo ?? ""}
                                onChange={(e) => setVals((s) => ({ ...s, [p.designation]: { ...s[p.designation], geo: e.target.value } }))}
                                onBlur={() => saveField(p.designation, "geo")}
                                data-testid={`product-geo-${p.designation}`}
                                className={`h-8 px-1 rounded bg-slate-800 border text-xs text-center outline-none placeholder:text-slate-600
                                    ${p.gap ? "border-red-700 focus:border-red-500 text-red-300" : "border-slate-700 focus:border-sky-500"}`} />
                        ) : (
                            <div className="text-center text-slate-700 text-xs">—</div>
                        )}
                        <div className={`text-xs text-center font-bold tabular-nums
                            ${p.delta === null || p.delta === undefined ? "text-slate-700" : p.delta === 0 ? "text-emerald-400" : p.delta < 0 ? "text-red-400" : "text-amber-400"}`}>
                            {p.delta === null || p.delta === undefined ? "" : (p.delta > 0 ? "+" : "") + fmt(p.delta)}
                        </div>
                    </div>
                ))}
            </div>

            {/* Explication géoloc */}
            {gapProducts.length > 0 && (
                <div className="rounded-xl bg-red-950/40 border border-red-900/60 p-3" data-testid={`allee-geo-explain-${a.uid}`}>
                    <div className="text-[11px] text-red-300 font-semibold flex items-start gap-1.5 mb-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                        <span>
                            {gapProducts.map((p) => `${p.designation} : ${fmt(p.gap)} posé(s) non géolocalisé(s)`).join(" · ")}
                            {!geoComment && " — explication demandée"}
                        </span>
                    </div>
                    <input value={geoComment} onChange={(e) => setGeoComment(e.target.value)}
                        onBlur={() => { if (geoComment !== (a.geoloc_comment || "")) actions.patchAllee(a.uid, { geoloc_comment: geoComment }); }}
                        placeholder="Pourquoi ? (ex: zone sans signal, scan à refaire demain...)"
                        data-testid={`allee-geo-comment-${a.uid}`}
                        className="w-full h-9 px-2.5 rounded-lg bg-slate-900 border border-red-900/70 text-xs placeholder:text-slate-600 focus:border-red-500 outline-none" />
                </div>
            )}

            {/* Photos */}
            <div className="rounded-2xl bg-slate-900 border border-slate-800 p-3" data-testid={`allee-photos-${a.uid}`}>
                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-2">Photos</div>
                <div className="flex items-center gap-2 flex-wrap">
                    {(a.photos || []).map((p) => (
                        <div key={p.id} className="relative group">
                            <img src={actions.photoUrl(p.id)} alt="" loading="lazy"
                                onClick={() => setZoom(p.id)}
                                className="w-16 h-16 object-cover rounded-lg border border-slate-700 cursor-zoom-in" />
                            <button onClick={() => actions.delPhoto(p.id)} data-testid={`photo-del-${p.id}`}
                                className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-600 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                <X className="w-3 h-3" />
                            </button>
                        </div>
                    ))}
                    <button onClick={() => fileRef.current?.click()} disabled={uploading}
                        data-testid={`allee-add-photo-${a.uid}`}
                        className="w-16 h-16 rounded-lg border border-dashed border-slate-600 text-slate-500 hover:text-emerald-400 hover:border-emerald-600 flex flex-col items-center justify-center gap-0.5 transition-colors">
                        {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Camera className="w-4 h-4" />}
                        <span className="text-[9px]">Photo</span>
                    </button>
                    <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPhotoPick} />
                </div>
            </div>

            {/* Commentaire + actions */}
            <input value={comment} onChange={(e) => setComment(e.target.value)}
                onBlur={() => { if (comment !== (a.comment || "")) actions.patchAllee(a.uid, { comment }); }}
                placeholder="Commentaire (manque produit, casse...)"
                data-testid={`allee-comment-${a.uid}`}
                className="w-full h-10 px-3 rounded-xl bg-slate-900 border border-slate-800 text-xs placeholder:text-slate-600 focus:border-emerald-600 outline-none" />
            <div className="flex items-center gap-2 pb-4">
                {a.status !== "validee" ? (
                    <button onClick={() => setStatus("validee")} disabled={saving} data-testid={`allee-validate-${a.uid}`}
                        className="flex-1 h-11 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold flex items-center justify-center gap-2 transition-colors">
                        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} Valider l'allée
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`allee-reopen-${a.uid}`}
                        className="flex-1 h-11 rounded-xl border border-slate-600 text-slate-300 text-sm font-bold flex items-center justify-center gap-2 hover:bg-slate-800 transition-colors">
                        <RotateCcw className="w-4 h-4" /> Rouvrir
                    </button>
                )}
                {a.status !== "bloquee" ? (
                    <button onClick={() => setStatus("bloquee")} disabled={saving} data-testid={`allee-block-${a.uid}`}
                        className="h-11 px-4 rounded-xl border border-red-800 text-red-400 text-sm font-semibold flex items-center gap-1.5 hover:bg-red-950/50 transition-colors">
                        <Ban className="w-4 h-4" /> Bloquer
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`allee-unblock-${a.uid}`}
                        className="h-11 px-4 rounded-xl border border-slate-600 text-slate-300 text-sm font-semibold flex items-center gap-1.5 hover:bg-slate-800 transition-colors">
                        <RotateCcw className="w-4 h-4" /> Débloquer
                    </button>
                )}
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
