import React, { useState, useRef } from "react";
import { toast } from "sonner";
import {
    CheckCircle2, Ban, RotateCcw, Download, Loader2, AlertTriangle,
    MessageSquarePlus, Trash2, MoveRight, MapPin, Camera, X,
    ChevronRight, ArrowLeft, Moon, Plus, Zap, Sun,
} from "lucide-react";
import { useMobileBack } from "./useMobileBack";
import { compressImage } from "./api";

const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));
const STATUS_CHIP = {
    a_faire: ["À faire", "bg-slate-700 text-slate-200"],
    validee: ["Validée", "bg-blue-600 text-white"],
    bloquee: ["Bloquée", "bg-red-600 text-white"],
    a_finaliser: ["À finaliser", "bg-red-500 text-white"],
    non_faite: ["Non faite", "bg-red-700 text-white"],
};
const JUSTIF_FAMS = ["es_15", "es_21", "sa_15", "sa_21_std", "sa_21_freezer", "sa_42", "rails_es"];

// Suivi de pose : Nuits → Allées → Allée PLEIN ÉCRAN (saisie par produit)
export default function SuiviNuits({ state, actions, mode = "chef" }) {
    const [view, setView] = useState({ level: "nights", nuit: null, uid: null });
    const nights = (state.nights || []).filter((n) => n.nb_allees > 0);

    if (!nights.length) {
        return (
            <div className="text-center py-20 text-slate-500 text-sm" data-testid="nuits-empty">
                Aucune allée assignée à une nuit.
                {mode === "chef" && (<><br />Complétez d'abord le phasage dans l'<a href="/" className="text-blue-400 underline">app Phasage</a>.</>)}
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
                <Moon className="w-4 h-4 text-blue-400 flex-shrink-0" />
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
            ${night.nb_a_finaliser > 0 || night.nb_bloquees > 0 || night.nb_non_faites > 0 ? "border-red-800/80 bg-red-950/20" : night.complete ? "border-blue-900/70 bg-blue-950/20" : night.started ? "border-sky-900/70 bg-slate-900" : "border-slate-800 bg-slate-900"}`}
            data-testid={`night-block-${night.nuit}`}>
            <button onClick={onOpen} className="w-full flex items-center gap-3 px-4 py-3.5 text-left" data-testid={`night-open-${night.nuit}`}>
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold flex-shrink-0
                    ${night.nb_a_finaliser > 0 || night.nb_non_faites > 0 ? "bg-red-600 text-white" : night.complete ? "bg-blue-600 text-white" : night.started ? "bg-sky-700 text-white" : "bg-slate-800 text-slate-400"}`}>
                    {night.nuit}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold flex items-center gap-2">
                        Nuit {night.nuit}
                        {night.date && <span className="text-xs text-slate-500 font-normal">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })}</span>}
                        {night.complete && <CheckCircle2 className="w-4 h-4 text-blue-400" />}
                        {night.nb_bloquees > 0 && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 font-bold">{night.nb_bloquees} bloquée(s)</span>}
                        {night.nb_a_finaliser > 0 && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-600 text-white font-bold" data-testid={`night-a-finaliser-${night.nuit}`}>{night.nb_a_finaliser} à finaliser</span>}
                        {night.nb_non_faites > 0 && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-700 text-white font-bold" data-testid={`night-non-faites-${night.nuit}`}>{night.nb_non_faites} non faite(s)</span>}
                        {night.nb_rapatriees > 0 && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/90 text-slate-900 font-bold flex items-center gap-0.5"
                                data-testid={`night-rapatriees-${night.nuit}`}
                                title={`${night.nb_rapatriees} allée(s) rapatriée(s) en avance`}>
                                <Zap className="w-3 h-3" /> {night.nb_rapatriees} en avance
                            </span>
                        )}
                    </div>
                    <div className="text-xs text-slate-400">
                        {night.nb_validees}/{night.nb_allees} allées validées · {fmt(night.eeg_reel)} / {fmt(night.eeg_plan)} EEG
                        {night.delta_eeg !== null && night.delta_eeg !== undefined && (
                            <span className={`ml-1.5 font-semibold ${night.delta_eeg > 0 ? "text-blue-400" : night.delta_eeg < 0 ? "text-red-400" : "text-slate-500"}`}>
                                ({night.delta_eeg > 0 ? "+" : ""}{fmt(night.delta_eeg)})
                            </span>
                        )}
                    </div>
                </div>
                <span onClick={dl} role="button" data-testid={`night-report-${night.nuit}`}
                    title="Télécharger le rapport de la nuit"
                    className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-blue-400 transition-colors">
                    {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                </span>
                <ChevronRight className="w-4 h-4 text-slate-500" />
            </button>
        </section>
    );
}

// ---- Niveau 2 : allées de la nuit ----
function NightScreen({ night, state, actions, onBack, onOpenAllee }) {
    const readOnly = !!actions.readOnly;
    const n = night.nuit;
    // Bouton retour natif Android → remonte d'un cran
    useMobileBack(onBack, true);
    const goBack = () => window.history.back();
    const items = (state.allees || []).filter((x) => x.nuit_eff === n);
    const incidents = (state.incidents || []).filter((i) => i.nuit === n);
    const [incidentText, setIncidentText] = useState("");
    const [downloading, setDownloading] = useState(false);
    const [addPanel, setAddPanel] = useState(false);
    const [addBusy, setAddBusy] = useState(null);
    const [filter, setFilter] = useState("all"); // all | pose_todo | geo_todo | not_validated | validated

    const allItems = items;
    const filteredItems = allItems.filter((a) => {
        if (filter === "all") return true;
        if (filter === "pose_todo") return !a.pose_complete && a.status !== "validee";
        if (filter === "geo_todo") return (a.geo_total || 0) > 0 && !a.geo_complete && a.status !== "validee";
        if (filter === "not_validated") return a.status !== "validee";
        if (filter === "validated") return a.status === "validee";
        return true;
    });

    const filterCounts = {
        all: allItems.length,
        pose_todo: allItems.filter((a) => !a.pose_complete && a.status !== "validee").length,
        geo_todo: allItems.filter((a) => (a.geo_total || 0) > 0 && !a.geo_complete && a.status !== "validee").length,
        not_validated: allItems.filter((a) => a.status !== "validee").length,
        validated: allItems.filter((a) => a.status === "validee").length,
    };

    // Allées des nuits suivantes (candidates au rapatriement en avance)
    // Triées par nuit croissante puis par n° d'allée (ordre naturel)
    const laterAllees = (state.allees || [])
        .filter((x) => x.nuit_eff > n)
        .sort((a, b) =>
            a.nuit_eff !== b.nuit_eff
                ? a.nuit_eff - b.nuit_eff
                : String(a.allee).localeCompare(String(b.allee), "fr", { numeric: true })
        );

    const pullAllee = async (uid) => {
        setAddBusy(uid);
        const ok = await actions.patchAllee(uid, { nuit_reelle: n });
        setAddBusy(null);
        if (ok) toast.success(`Allée rapatriée dans la nuit ${n}`);
    };

    return (
        <div className="space-y-2.5" data-testid={`night-screen-${n}`}>
            <div className="flex items-center gap-2">
                <button onClick={goBack} data-testid="night-back"
                    className="flex items-center gap-1.5 text-sm text-blue-400 hover:text-blue-300 transition-colors">
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

            {/* Barre de filtres */}
            <div className="flex gap-1.5 overflow-x-auto -mx-1 px-1 pb-1" data-testid={`night-filters-${n}`}>
                {[
                    { k: "all", label: "Toutes", cls: "bg-slate-700 border-slate-600 text-slate-100" },
                    { k: "pose_todo", label: "Pose à finir", cls: "bg-blue-950/50 border-blue-800 text-blue-300" },
                    { k: "geo_todo", label: "Géoloc à finir", cls: "bg-sky-950/50 border-sky-800 text-sky-300" },
                    { k: "not_validated", label: "Non validées", cls: "bg-orange-950/50 border-orange-800 text-orange-300" },
                    { k: "validated", label: "Validées", cls: "bg-blue-950/40 border-blue-900 text-blue-400" },
                ].map((f) => {
                    const active = filter === f.k;
                    const count = filterCounts[f.k];
                    return (
                        <button key={f.k}
                            onClick={() => setFilter(f.k)}
                            data-testid={`filter-${f.k}`}
                            className={`h-7 px-2.5 rounded-full border text-[11px] font-semibold whitespace-nowrap flex items-center gap-1 transition-all
                                ${active ? f.cls + " ring-1 ring-white/20" : "bg-slate-900 border-slate-800 text-slate-500 hover:border-slate-700"}`}>
                            {f.label}
                            <span className={`text-[9px] px-1 rounded ${active ? "bg-black/30" : "bg-slate-800"}`}>{count}</span>
                        </button>
                    );
                })}
            </div>

            {filteredItems.length === 0 && (
                <div className="rounded-xl bg-slate-900 border border-slate-800 p-6 text-center text-xs text-slate-500">
                    Aucune allée ne correspond à ce filtre.
                </div>
            )}

            {filteredItems.map((a) => {
                const [lbl, cls] = STATUS_CHIP[a.status] || STATUS_CHIP.a_faire;
                const hasGap = Object.keys(a.geo_gap || {}).length > 0;
                const isDeplacee = a.is_deplacee && a.status !== "validee";
                const isSeasonal = a.secteur === "Zone saisonnier";
                return (
                    <button key={a.uid} onClick={() => onOpenAllee(a.uid)}
                        data-testid={`allee-open-${a.uid}`}
                        className={`w-full flex items-center gap-3 rounded-xl border p-3.5 text-left transition-colors hover:border-blue-700
                            ${a.status === "validee" ? "bg-blue-950/20 border-blue-900/60"
                                : isDeplacee ? "bg-orange-950/30 border-orange-700/60"
                                : a.status === "bloquee" || a.status === "a_finaliser" || a.status === "non_faite" ? "bg-red-950/20 border-red-900/60"
                                : isSeasonal ? "bg-amber-950/20 border-amber-800/60"
                                : "bg-slate-900 border-slate-800"}`}>
                        <span className={`px-2 py-1 rounded-md text-sm font-bold flex-shrink-0 flex items-center gap-1
                            ${isSeasonal ? "bg-amber-600 text-white"
                                : isDeplacee ? "bg-orange-700 text-white"
                                : "bg-slate-700 text-slate-100"}`}
                            data-testid={isSeasonal ? `allee-seasonal-badge-${a.uid}` : undefined}>
                            {isSeasonal && <Sun className="w-3.5 h-3.5" />}
                            {a.allee}
                        </span>
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 flex-wrap">
                                <span className="text-xs text-slate-300 truncate">{a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}</span>
                                {isSeasonal && (
                                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/90 text-slate-900" title="Zone saisonnière — posée par la VT (400 SA 1.5 + 1600 SA 2.1)">
                                        SAISON
                                    </span>
                                )}
                                {isDeplacee && (
                                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-orange-500/90 text-slate-900" title={`Planifiée nuit ${a.nuit_plan}, faite nuit ${a.nuit_eff}`}>
                                        DÉPLACÉE (plan N{a.nuit_plan})
                                    </span>
                                )}
                            </div>
                            <div className="text-[11px] text-slate-500 flex items-center gap-2 flex-wrap">
                                <span className={a.pose_complete ? "text-blue-400 font-semibold" : ""}>
                                    Pose {a.pose_saisis}/{a.pose_total}
                                </span>
                                {a.geo_total > 0 && (
                                    <span className={a.geo_complete ? "text-blue-400 font-semibold" : "text-sky-400"}>
                                        · Géoloc {a.geo_saisis}/{a.geo_total}
                                    </span>
                                )}
                                <span>· {fmt(a.eeg_reel)}/{fmt(a.eeg_plan)} EEG</span>
                            </div>
                        </div>
                        {hasGap && <MapPin className="w-4 h-4 text-red-400 flex-shrink-0" title="Géoloc incomplète" />}
                        {a.photos?.length > 0 && <Camera className="w-4 h-4 text-slate-500 flex-shrink-0" />}
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold flex-shrink-0 ${cls}`}>{lbl}</span>
                        <ChevronRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
                    </button>
                );
            })}

            {/* Ajouter une allée (rapatriement d'une nuit ultérieure — pour les avances) */}
            {!readOnly && (
                <button onClick={() => setAddPanel(true)}
                    disabled={laterAllees.length === 0}
                    data-testid={`night-add-allee-${n}`}
                    className="w-full h-11 rounded-xl border border-dashed border-blue-700/60 text-blue-400 text-sm font-semibold flex items-center justify-center gap-2 hover:bg-blue-950/30 hover:border-blue-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                    <Plus className="w-4 h-4" />
                    {laterAllees.length > 0
                        ? `Ajouter une allée (en avance) — ${laterAllees.length} disponible${laterAllees.length > 1 ? "s" : ""}`
                        : "Aucune allée à rapatrier (dernière nuit ou toutes déjà planifiées ici)"}
                </button>
            )}

            <div className="rounded-xl bg-slate-800/40 p-3" data-testid={`night-incidents-${n}`}>
                <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-2 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" /> Incidents de la nuit
                </div>
                {incidents.map((i) => (
                    <div key={i.id} className="flex items-start gap-2 text-xs text-slate-300 py-1">
                        <span className="flex-1">• {i.text}</span>
                        {!readOnly && (
                            <button onClick={() => actions.delIncident(i.id)} data-testid={`incident-del-${i.id}`}
                                className="text-slate-600 hover:text-red-400 transition-colors"><Trash2 className="w-3.5 h-3.5" /></button>
                        )}
                    </div>
                ))}
                {incidents.length === 0 && readOnly && (
                    <div className="text-[11px] text-slate-500 italic">Aucun incident signalé</div>
                )}
                {!readOnly && (
                    <div className="flex gap-2 mt-1.5">
                        <input value={incidentText} onChange={(e) => setIncidentText(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter" && incidentText.trim()) { actions.addIncident(n, incidentText); setIncidentText(""); } }}
                            placeholder="Signaler un incident (rupture, casse, accès...)"
                            data-testid={`incident-input-${n}`}
                            className="flex-1 h-8 px-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs placeholder:text-slate-600 focus:border-blue-600 outline-none" />
                        <button onClick={() => { if (incidentText.trim()) { actions.addIncident(n, incidentText); setIncidentText(""); } }}
                            data-testid={`incident-add-${n}`}
                            className="h-8 px-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-xs flex items-center gap-1 transition-colors">
                            <MessageSquarePlus className="w-3.5 h-3.5" /> Ajouter
                        </button>
                    </div>
                )}
            </div>

            {/* Modale de rapatriement d'allée */}
            {addPanel && (
                <div className="fixed inset-0 z-50 bg-black/75 flex items-end sm:items-center justify-center p-3"
                    data-testid={`add-allee-panel-${n}`} onClick={() => setAddPanel(false)}>
                    <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-slate-700 p-4 space-y-3 max-h-[85vh] flex flex-col"
                        onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-2">
                            <Plus className="w-5 h-5 text-blue-400" />
                            <h4 className="text-sm font-bold flex-1">Rapatrier une allée dans la nuit {n}</h4>
                            <button onClick={() => setAddPanel(false)} data-testid="add-allee-close"
                                className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400"><X className="w-4 h-4" /></button>
                        </div>
                        <div className="text-[11px] text-slate-400">
                            Sélectionnez une allée faite en avance (planifiée sur une nuit ultérieure) pour la rapatrier ici.
                        </div>
                        <div className="flex-1 overflow-y-auto -mx-1 px-1 space-y-1.5">
                            {laterAllees.map((x) => (
                                <button key={x.uid}
                                    onClick={() => pullAllee(x.uid)}
                                    disabled={addBusy === x.uid}
                                    data-testid={`add-allee-pick-${x.uid}`}
                                    className="w-full flex items-center gap-2.5 rounded-xl border border-slate-700 bg-slate-950/40 hover:border-blue-600 hover:bg-blue-950/20 p-2.5 text-left transition-colors disabled:opacity-50">
                                    <span className="w-8 h-8 rounded-md bg-slate-800 text-slate-200 text-xs font-bold flex items-center justify-center flex-shrink-0">
                                        N{x.nuit_eff}
                                    </span>
                                    <span className={`px-2 py-0.5 rounded-md text-sm font-bold flex-shrink-0 flex items-center gap-1 ${x.secteur === "Zone saisonnier" ? "bg-amber-600 text-white" : "bg-slate-700 text-slate-100"}`}>
                                        {x.secteur === "Zone saisonnier" && <Sun className="w-3.5 h-3.5" />}
                                        {x.allee}
                                    </span>
                                    <span className="flex-1 min-w-0 text-[11px] text-slate-400 truncate">
                                        {x.secteur}{x.rayon ? ` · ${x.rayon}` : ""}
                                    </span>
                                    {addBusy === x.uid
                                        ? <Loader2 className="w-4 h-4 animate-spin text-blue-400 flex-shrink-0" />
                                        : <MoveRight className="w-4 h-4 text-blue-400 flex-shrink-0" />}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

// ---- Niveau 3 : allée PLEIN ÉCRAN, saisie par produit ----
function AlleeScreen({ allee: a, state, actions, onBack }) {
    const readOnly = !!actions.readOnly;
    // Bouton retour natif Android → remonte à la liste des allées
    useMobileBack(onBack, true);
    const goBack = () => window.history.back();
    const [nonFaitPanel, setNonFaitPanel] = useState(false);
    const [nonFaitComment, setNonFaitComment] = useState("");
    const [nonFaitNuit, setNonFaitNuit] = useState("");
    const [vals, setVals] = useState(() => {
        const v = {};
        (a.products || []).forEach((p) => { v[p.designation] = { reel: p.reel ?? "", geo: p.geo ?? "" }; });
        return v;
    });
    const [comment, setComment] = useState(a.comment || "");
    const [geoComment, setGeoComment] = useState(a.geoloc_comment || "");
    const [saving, setSaving] = useState(false);
    const [panel, setPanel] = useState(false);
    const [justif, setJustif] = useState(a.justification || "");
    const [justifOk, setJustifOk] = useState(!!a.justif_ok);
    const [extras, setExtras] = useState(() =>
        (a.extra_products || []).map((x) => ({ designation: x.designation, qty: String(x.qty) })));
    const [uploading, setUploading] = useState(false);
    const [zoom, setZoom] = useState(null);
    const fileRef = useRef(null);
    const maxNight = Math.max(state.nb_nuits || 1, ...(state.nights || []).map((x) => x.nuit));
    const gapProducts = (a.products || []).filter((p) => p.gap > 0);
    const [lbl, cls] = STATUS_CHIP[a.status] || STATUS_CHIP.a_faire;

    // Écarts > 5% (EEG + rails ES) sur les valeurs saisies localement
    const justifProducts = (a.products || []).filter((p) => {
        if (!JUSTIF_FAMS.includes(p.family) || !p.plan) return false;
        const raw = vals[p.designation]?.reel;
        const reel = raw === "" || raw === undefined ? p.reel : Number(raw);
        if (reel === null || reel === undefined || isNaN(reel)) return false;
        return Math.abs(reel - p.plan) > 0.05 * p.plan;
    });

    const saveField = async (designation, field) => {
        if (a.status === "validee") return; // verrouillé : rouvrir l'allée d'abord
        const raw = vals[designation]?.[field];
        const num = raw === "" ? null : Number(raw);
        if (raw !== "" && (isNaN(num) || num < 0)) { toast.error("Valeur invalide"); return; }
        const p = a.products.find((x) => x.designation === designation);
        if (num === ((p && p[field]) ?? null)) return;
        await actions.patchAllee(a.uid, { products: [{ designation, [field]: num }] });
    };

    const setStatus = async (status) => {
        setSaving(true);
        const ok = await actions.patchAllee(a.uid, { status });
        if (ok && status === "bloquee") toast.warning(`Allée ${a.allee} bloquée`);
        if (ok && status === "a_finaliser") toast.warning(`Allée ${a.allee} à finaliser une autre nuit — la nuit passe en rouge`);
        setSaving(false);
    };

    const confirmValidate = async () => {
        // Blocage 1 : écart > 5% sur pose EEG / rails ES → justif_ok OU commentaire
        if (justifProducts.length > 0 && !justifOk && !justif.trim()) {
            toast.error("Cochez « Tout est OK » ou ajoutez un commentaire — écart POSE > 5%");
            return;
        }
        // Blocage 2 : produits posés non géolocalisés → commentaire géoloc obligatoire
        // (distinct du blocage pose : deux causes différentes → deux commentaires distincts)
        if (gapProducts.length > 0 && !geoComment.trim()) {
            toast.error("Commentaire de géolocalisation obligatoire — produits posés non géolocalisés");
            return;
        }
        setSaving(true);
        // Ne PAS auto-remplir posé = prévu si rien n'a été saisi : les valeurs vides restent nulles
        // (l'allée est validée mais les produits non saisis restent à 0 posé — visible dans le rapport)
        const fields = { status: "validee" };
        if (justifProducts.length > 0) {
            fields.justif_ok = justifOk;
            if (justifOk) fields.justification = "";  // vide le champ texte
            else if (justif.trim()) fields.justification = justif.trim();
        }
        if (geoComment.trim() && geoComment !== (a.geoloc_comment || "")) {
            fields.geoloc_comment = geoComment.trim();
        }
        fields.extra_products = extras
            .filter((x) => x.designation.trim() && Number(x.qty) > 0)
            .map((x) => ({ designation: x.designation.trim(), qty: Number(x.qty) }));
        const ok = await actions.patchAllee(a.uid, fields);
        if (ok) { toast.success(`Allée ${a.allee} validée`); setPanel(false); }
        setSaving(false);
    };

    const confirmNonFait = async () => {
        if (!nonFaitComment.trim()) {
            toast.error("Un commentaire est obligatoire pour marquer une allée non faite");
            return;
        }
        setSaving(true);
        const fields = {
            status: "non_faite",
            comment: nonFaitComment.trim(),
        };
        // Si une nuit de rattrapage est choisie → le backend déplace l'allée
        // Sinon → l'allée reste "non faite" en attente
        if (nonFaitNuit) fields.nuit_rattrapage = Number(nonFaitNuit);
        const ok = await actions.patchAllee(a.uid, fields);
        if (ok) {
            if (nonFaitNuit) toast.success(`Allée ${a.allee} déplacée sur la nuit ${nonFaitNuit}`);
            else toast.warning(`Allée ${a.allee} marquée non faite — en attente de rattrapage`);
            setNonFaitPanel(false);
        }
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
                <button onClick={goBack} data-testid="allee-back"
                    className="flex items-center gap-1.5 text-sm text-blue-400 hover:text-blue-300 transition-colors">
                    <ArrowLeft className="w-4 h-4" /> Nuit {a.nuit_eff}
                </button>
                <div className="flex-1" />
                {a.nuit_reelle && a.nuit_reelle !== a.nuit_plan && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-900/60 text-violet-300 font-semibold flex items-center gap-1">
                        <MoveRight className="w-3 h-3" /> plan N{a.nuit_plan}
                    </span>
                )}
                {readOnly ? (
                    <span className="h-7 rounded-lg bg-slate-900 border border-slate-800 text-[11px] px-2 flex items-center text-slate-400">
                        {"N" + a.nuit_eff}
                    </span>
                ) : (
                    <select value={a.nuit_eff} onChange={moveNight} data-testid={`allee-move-${a.uid}`}
                        title="Déplacer sur une autre nuit"
                        className="h-7 rounded-lg bg-slate-900 border border-slate-700 text-[11px] px-1.5 text-slate-300 focus:border-blue-600 outline-none cursor-pointer">
                        {Array.from({ length: maxNight }, (_, i) => i + 1).map((x) => (
                            <option key={x} value={x}>{"N" + x}</option>
                        ))}
                    </select>
                )}
            </div>
            <div className={`rounded-2xl border p-4 ${a.secteur === "Zone saisonnier" ? "bg-amber-950/20 border-amber-800/60" : "bg-slate-900 border-slate-800"}`}>
                <div className="flex items-center gap-2 flex-wrap">
                    <span className={`px-2.5 py-1 rounded-md text-base font-bold flex items-center gap-1.5 ${a.secteur === "Zone saisonnier" ? "bg-amber-600 text-white" : "bg-slate-700 text-slate-100"}`}
                        data-testid={a.secteur === "Zone saisonnier" ? `allee-screen-seasonal-badge-${a.uid}` : undefined}>
                        {a.secteur === "Zone saisonnier" && <Sun className="w-4 h-4" />}
                        {a.secteur === "Zone saisonnier" ? a.allee : `Allée ${a.allee}`}
                    </span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${cls}`}>{lbl}</span>
                    {a.secteur === "Zone saisonnier" && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/90 text-slate-900" title="Zone saisonnière — posée par la VT">
                            SAISON · VT
                        </span>
                    )}
                    <span className="text-xs text-slate-400 w-full sm:w-auto sm:flex-1 truncate">{a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}</span>
                    <span className="text-[11px] text-slate-500">{a.nb_saisis}/{a.nb_produits} produits saisis</span>
                </div>
            </div>

            {/* Produits — 1 ligne par produit : nom complet en haut, chiffres dessous */}
            <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden" data-testid={`allee-products-${a.uid}`}>
                {a.status === "validee" && (
                    <div className="px-3 py-2 bg-blue-950/40 border-b border-blue-900/60 text-[11px] text-blue-300 flex items-center gap-1.5">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Allée validée — rouvrez pour modifier
                    </div>
                )}
                {(a.products || []).map((p) => {
                    const locked = a.status === "validee" || readOnly;
                    return (
                    <div key={p.designation}
                        className={`px-3 py-2.5 border-b border-slate-800/60 last:border-0 space-y-1.5 ${p.gap ? "bg-red-950/20" : ""}`}
                        data-testid={`product-row-${a.uid}-${p.designation}`}>
                        {/* Ligne 1 : nom complet du produit */}
                        <div className="flex items-start gap-2">
                            <div className="text-xs text-slate-200 flex-1 min-w-0 break-words leading-snug" title={p.designation}>{p.designation}</div>
                            {p.is_geo && (
                                <span className="text-[9px] text-sky-400 flex items-center gap-0.5 flex-shrink-0 mt-0.5">
                                    <MapPin className="w-2.5 h-2.5" /> géoloc
                                </span>
                            )}
                        </div>
                        {/* Ligne 2 : Prévu / Posé / Géoloc / Δ */}
                        <div className="grid grid-cols-4 gap-1.5 items-center">
                            <div className="flex flex-col items-center">
                                <span className="text-[9px] uppercase text-slate-500 font-semibold">Prévu</span>
                                <span className="text-xs text-slate-300 tabular-nums font-semibold" data-testid={`product-plan-${p.designation}`}>{fmt(p.plan)}</span>
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-[9px] uppercase text-slate-500 font-semibold">Posé</span>
                                <input type="number" min="0" inputMode="numeric" placeholder="—"
                                    value={vals[p.designation]?.reel ?? ""}
                                    readOnly={locked}
                                    onChange={(e) => setVals((s) => ({ ...s, [p.designation]: { ...s[p.designation], reel: e.target.value } }))}
                                    onBlur={() => saveField(p.designation, "reel")}
                                    data-testid={`product-reel-${p.designation}`}
                                    className={`w-full h-8 px-1 rounded text-xs text-center outline-none placeholder:text-slate-600
                                        ${locked ? "bg-slate-950 border border-slate-800 text-slate-400 cursor-not-allowed"
                                                 : "bg-slate-800 border border-slate-700 focus:border-blue-500"}`} />
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-[9px] uppercase text-slate-500 font-semibold">Géoloc</span>
                                {p.is_geo ? (
                                    <input type="number" min="0" inputMode="numeric" placeholder="—"
                                        value={vals[p.designation]?.geo ?? ""}
                                        readOnly={locked}
                                        onChange={(e) => setVals((s) => ({ ...s, [p.designation]: { ...s[p.designation], geo: e.target.value } }))}
                                        onBlur={() => saveField(p.designation, "geo")}
                                        data-testid={`product-geo-${p.designation}`}
                                        className={`w-full h-8 px-1 rounded text-xs text-center outline-none placeholder:text-slate-600
                                            ${locked ? "bg-slate-950 border border-slate-800 text-slate-400 cursor-not-allowed"
                                                     : p.gap ? "bg-slate-800 border border-red-700 focus:border-red-500 text-red-300"
                                                             : "bg-slate-800 border border-slate-700 focus:border-sky-500"}`} />
                                ) : (
                                    <span className="text-slate-700 text-xs">—</span>
                                )}
                            </div>
                            <div className="flex flex-col items-center">
                                <span className="text-[9px] uppercase text-slate-500 font-semibold">Δ</span>
                                <span className={`text-xs font-bold tabular-nums
                                    ${p.delta === null || p.delta === undefined ? "text-slate-700" : p.delta === 0 ? "text-blue-400" : p.delta < 0 ? "text-red-400" : "text-amber-400"}`}
                                    data-testid={`product-delta-${p.designation}`}>
                                    {p.delta === null || p.delta === undefined ? "—" : (p.delta > 0 ? "+" : "") + fmt(p.delta)}
                                </span>
                            </div>
                        </div>
                    </div>
                    );
                })}
            </div>

            {/* Explication géoloc */}
            {gapProducts.length > 0 && (
                <div className="rounded-xl bg-red-950/40 border border-red-900/60 p-3" data-testid={`allee-geo-explain-${a.uid}`}>
                    <div className="text-[11px] text-red-300 font-semibold flex items-start gap-1.5 mb-1.5">
                        <MapPin className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                        <span>
                            <b className="text-red-100">Commentaire GÉOLOC</b> — {gapProducts.map((p) => `${p.designation} : ${fmt(p.gap)} posé(s) non géolocalisé(s)`).join(" · ")}
                            {!geoComment && " — explication demandée"}
                        </span>
                    </div>
                    <input value={geoComment} onChange={(e) => setGeoComment(e.target.value)}
                        readOnly={a.status === "validee" || readOnly}
                        onBlur={() => { if (geoComment !== (a.geoloc_comment || "")) actions.patchAllee(a.uid, { geoloc_comment: geoComment }); }}
                        placeholder="Pourquoi les produits ne sont pas géolocalisés ? (zone sans signal, scan à refaire...)"
                        data-testid={`allee-geo-comment-${a.uid}`}
                        className={`w-full h-9 px-2.5 rounded-lg border text-xs placeholder:text-slate-600 outline-none
                            ${(a.status === "validee" || readOnly) ? "bg-slate-950 border-slate-800 text-slate-400 cursor-not-allowed"
                                                     : "bg-slate-900 border-red-900/70 focus:border-red-500"}`} />
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
                            {!readOnly && (
                                <button onClick={() => actions.delPhoto(p.id)} data-testid={`photo-del-${p.id}`}
                                    className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-600 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                    <X className="w-3 h-3" />
                                </button>
                            )}
                        </div>
                    ))}
                    {!readOnly && (
                        <>
                            <button onClick={() => fileRef.current?.click()} disabled={uploading}
                                data-testid={`allee-add-photo-${a.uid}`}
                                className="w-16 h-16 rounded-lg border border-dashed border-slate-600 text-slate-500 hover:text-blue-400 hover:border-blue-600 flex flex-col items-center justify-center gap-0.5 transition-colors">
                                {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Camera className="w-4 h-4" />}
                                <span className="text-[9px]">Photo</span>
                            </button>
                            <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPhotoPick} />
                        </>
                    )}
                    {readOnly && (a.photos || []).length === 0 && (
                        <span className="text-[11px] text-slate-600 italic">Aucune photo</span>
                    )}
                </div>
            </div>

            {/* Écart > 5% détecté (avant validation) */}
            {justifProducts.length > 0 && a.status !== "validee" && (
                <div className="rounded-xl bg-amber-950/40 border border-amber-800/60 p-3" data-testid={`allee-justif-warn-${a.uid}`}>
                    <div className="text-[11px] text-amber-300 font-semibold flex items-start gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                        <span>
                            Écart de plus de 5% : {justifProducts.map((p) => p.designation).join(", ")}.
                            Une justification sera demandée à la validation.
                        </span>
                    </div>
                </div>
            )}
            {a.status === "validee" && a.justification && (
                <div className="rounded-xl bg-slate-900 border border-slate-800 p-3 text-[11px] text-slate-400" data-testid={`allee-justif-saved-${a.uid}`}>
                    <span className="font-semibold text-amber-400">Justification écart : </span>{a.justification}
                </div>
            )}
            {(a.extra_products || []).length > 0 && (
                <div className="rounded-xl bg-slate-900 border border-slate-800 p-3" data-testid={`allee-extras-saved-${a.uid}`}>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-1.5">Produits supplémentaires posés (non prévus)</div>
                    {(a.extra_products || []).map((x, i) => (
                        <div key={i} className="text-xs text-slate-300">• {x.designation} — <span className="font-bold text-blue-400">{fmt(x.qty)}</span></div>
                    ))}
                </div>
            )}

            {/* Commentaire pose + actions */}
            <div>
                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-1 flex items-center gap-1.5">
                    <MessageSquarePlus className="w-3 h-3" /> Commentaire POSE
                </div>
                <input value={comment} onChange={(e) => setComment(e.target.value)}
                    readOnly={a.status === "validee" || readOnly}
                    onBlur={() => { if (comment !== (a.comment || "")) actions.patchAllee(a.uid, { comment }); }}
                    placeholder="Manque de produit, casse, difficultés d'accès..."
                    data-testid={`allee-comment-${a.uid}`}
                    className={`w-full h-10 px-3 rounded-xl border text-xs placeholder:text-slate-600 outline-none
                        ${(a.status === "validee" || readOnly) ? "bg-slate-950 border-slate-800 text-slate-400 cursor-not-allowed"
                                                 : "bg-slate-900 border-slate-800 focus:border-blue-600"}`} />
            </div>
            {!readOnly && (
            <div className="flex items-center gap-2">
                {a.status !== "validee" ? (
                    <button onClick={() => setPanel(true)} disabled={saving} data-testid={`allee-validate-${a.uid}`}
                        className="flex-1 h-11 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold flex items-center justify-center gap-2 transition-colors">
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
            )}
            {!readOnly && (
            <div className="pb-4 space-y-2">
                {a.status !== "a_finaliser" && a.status !== "non_faite" ? (
                    a.status !== "validee" && (
                        <>
                            <button onClick={() => setStatus("a_finaliser")} disabled={saving} data-testid={`allee-finaliser-${a.uid}`}
                                className="w-full h-10 rounded-xl border border-red-700/70 text-red-300 text-xs font-semibold flex items-center justify-center gap-1.5 hover:bg-red-950/40 transition-colors">
                                <Moon className="w-3.5 h-3.5" /> Je vais finaliser cette allée une autre nuit
                            </button>
                            <button onClick={() => { setNonFaitComment(a.comment || ""); setNonFaitNuit(""); setNonFaitPanel(true); }}
                                disabled={saving} data-testid={`allee-non-fait-${a.uid}`}
                                className="w-full h-10 rounded-xl border border-red-800 bg-red-950/30 text-red-400 text-xs font-semibold flex items-center justify-center gap-1.5 hover:bg-red-950/60 transition-colors">
                                <Ban className="w-3.5 h-3.5" /> Allée non faite (préciser pourquoi + nuit de rattrapage)
                            </button>
                        </>
                    )
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`allee-reprendre-${a.uid}`}
                        className="w-full h-10 rounded-xl border border-slate-600 text-slate-300 text-xs font-semibold flex items-center justify-center gap-1.5 hover:bg-slate-800 transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Reprendre la saisie (annuler « {a.status === "non_faite" ? "non faite" : "à finaliser"} »)
                    </button>
                )}
                {a.status === "non_faite" && (
                    <div className="rounded-xl bg-red-950/40 border border-red-900/60 p-3 text-[11px] text-red-200" data-testid={`allee-non-fait-info-${a.uid}`}>
                        <div className="font-bold flex items-center gap-1.5"><Ban className="w-3.5 h-3.5" /> Allée non faite</div>
                        {a.nuit_rattrapage
                            ? <div className="mt-1">→ rattrapage prévu <b>nuit {a.nuit_rattrapage}</b></div>
                            : <div className="mt-1 text-orange-300">⏳ <b>En attente</b> — nuit de rattrapage à définir</div>}
                        {a.comment && <div className="mt-1 italic">« {a.comment} »</div>}
                    </div>
                )}
            </div>
            )}

            {/* Panneau de validation : justification >5% + produits supplémentaires */}
            {panel && (
                <div className="fixed inset-0 z-50 bg-black/75 flex items-end sm:items-center justify-center p-3" data-testid={`allee-validate-panel-${a.uid}`}>
                    <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-slate-700 p-4 space-y-3 max-h-[85vh] overflow-y-auto">
                        <div className="flex items-center gap-2">
                            <CheckCircle2 className="w-5 h-5 text-blue-400" />
                            <h4 className="text-sm font-bold flex-1">Valider l'allée {a.allee}</h4>
                            <button onClick={() => setPanel(false)} data-testid="validate-panel-close"
                                className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400"><X className="w-4 h-4" /></button>
                        </div>

                        {justifProducts.length > 0 && (
                            <div className={`rounded-xl p-3 space-y-2 border ${justifOk ? "bg-amber-950/40 border-amber-800/60" : "bg-red-950/40 border-red-900/60"}`}
                                data-testid={`validate-justif-${a.uid}`}>
                                <div className={`text-[11px] font-semibold flex items-start gap-1.5 ${justifOk ? "text-amber-300" : "text-red-300"}`}>
                                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                                    <span>Écart POSE de plus de 5% entre prévu et posé{justifOk ? " — validé par le poseur" : " — justification requise"} :</span>
                                </div>
                                {justifProducts.map((p) => {
                                    const raw = vals[p.designation]?.reel;
                                    const reel = raw === "" || raw === undefined ? p.reel : Number(raw);
                                    const pct = Math.round(Math.abs(reel - p.plan) / p.plan * 1000) / 10;
                                    return (
                                        <div key={p.designation} className="text-[11px] text-slate-300">
                                            • {p.designation} : prévu {fmt(p.plan)} → posé {fmt(reel)} <span className={`font-bold ${justifOk ? "text-amber-400" : "text-red-400"}`}>({pct}%)</span>
                                        </div>
                                    );
                                })}
                                {/* (iter36) Case "Tout est OK" pour ne pas stresser le client */}
                                <label className="flex items-center gap-2 cursor-pointer p-2 rounded-lg bg-slate-950/50 hover:bg-slate-950 transition-colors">
                                    <input type="checkbox" checked={justifOk}
                                        onChange={(e) => setJustifOk(e.target.checked)}
                                        data-testid={`validate-justif-ok-${a.uid}`}
                                        className="w-4 h-4 rounded accent-amber-500 cursor-pointer" />
                                    <span className="text-xs text-slate-200 font-semibold">
                                        ✅ Tout est OK — pas besoin de commentaire
                                    </span>
                                </label>
                                {!justifOk && (
                                    <textarea value={justif} onChange={(e) => setJustif(e.target.value)} rows={2}
                                        placeholder="Sinon, expliquer l'écart de POSE (rupture stock, casse, difficulté d'accès...)"
                                        data-testid={`validate-justif-input-${a.uid}`}
                                        className="w-full px-2.5 py-2 rounded-lg bg-slate-950 border border-red-900/70 text-xs placeholder:text-slate-600 focus:border-red-500 outline-none resize-none" />
                                )}
                            </div>
                        )}

                        {gapProducts.length > 0 && (
                            <div className="rounded-xl bg-sky-950/40 border border-sky-900/60 p-3 space-y-2" data-testid={`validate-geoloc-${a.uid}`}>
                                <div className="text-[11px] text-sky-300 font-semibold flex items-start gap-1.5">
                                    <MapPin className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                                    <span>Écart GÉOLOC — produits posés non géolocalisés — commentaire obligatoire :</span>
                                </div>
                                {gapProducts.map((p) => (
                                    <div key={p.designation} className="text-[11px] text-slate-300">
                                        • {p.designation} : <span className="text-sky-300 font-bold">{fmt(p.gap)}</span> posé(s) non géolocalisé(s)
                                    </div>
                                ))}
                                <textarea value={geoComment} onChange={(e) => setGeoComment(e.target.value)} rows={2}
                                    placeholder="Pourquoi cet écart de GÉOLOC ? (zone sans signal, scan à refaire...) — obligatoire"
                                    data-testid={`validate-geoloc-input-${a.uid}`}
                                    className="w-full px-2.5 py-2 rounded-lg bg-slate-950 border border-sky-900/70 text-xs placeholder:text-slate-600 focus:border-sky-500 outline-none resize-none" />
                            </div>
                        )}

                        <div className="rounded-xl bg-slate-800/50 border border-slate-700 p-3 space-y-2" data-testid={`validate-extras-${a.uid}`}>
                            <div className="text-[11px] text-slate-300 font-semibold">
                                Avez-vous posé des produits non prévus dans cette allée ?
                            </div>
                            {extras.map((x, i) => (
                                <div key={i} className="flex items-center gap-1.5">
                                    <input value={x.designation}
                                        onChange={(e) => setExtras((s) => s.map((y, j) => (j === i ? { ...y, designation: e.target.value } : y)))}
                                        placeholder="Désignation (ex: ES 1.5 blanc)"
                                        data-testid={`extra-desig-${i}`}
                                        className="flex-1 h-8 px-2 rounded-lg bg-slate-950 border border-slate-700 text-xs placeholder:text-slate-600 focus:border-blue-600 outline-none" />
                                    <input type="number" min="0" inputMode="numeric" value={x.qty}
                                        onChange={(e) => setExtras((s) => s.map((y, j) => (j === i ? { ...y, qty: e.target.value } : y)))}
                                        placeholder="Qté" data-testid={`extra-qty-${i}`}
                                        className="w-16 h-8 px-1 rounded-lg bg-slate-950 border border-slate-700 text-xs text-center placeholder:text-slate-600 focus:border-blue-600 outline-none" />
                                    <button onClick={() => setExtras((s) => s.filter((_, j) => j !== i))} data-testid={`extra-del-${i}`}
                                        className="p-1.5 text-slate-500 hover:text-red-400"><Trash2 className="w-3.5 h-3.5" /></button>
                                </div>
                            ))}
                            <button onClick={() => setExtras((s) => [...s, { designation: "", qty: "" }])}
                                data-testid="extra-add-btn"
                                className="text-[11px] text-blue-400 hover:text-blue-300 font-semibold">
                                + Ajouter un produit non prévu
                            </button>
                        </div>

                        <div className="flex items-center gap-2">
                            <button onClick={() => setPanel(false)} data-testid="validate-cancel"
                                className="h-10 px-4 rounded-xl border border-slate-600 text-slate-300 text-xs font-semibold hover:bg-slate-800 transition-colors">
                                Annuler
                            </button>
                            <button onClick={confirmValidate} disabled={saving} data-testid={`validate-confirm-${a.uid}`}
                                className="flex-1 h-10 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold flex items-center justify-center gap-2 transition-colors">
                                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} Confirmer la validation
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {nonFaitPanel && (
                <div className="fixed inset-0 z-50 bg-black/75 flex items-end sm:items-center justify-center p-3"
                    data-testid={`allee-non-fait-panel-${a.uid}`} onClick={() => setNonFaitPanel(false)}>
                    <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-red-900/60 p-4 space-y-3"
                        onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-2">
                            <Ban className="w-5 h-5 text-red-400" />
                            <h4 className="text-sm font-bold flex-1">Allée {a.allee} non faite</h4>
                            <button onClick={() => setNonFaitPanel(false)} data-testid="non-fait-close"
                                className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400"><X className="w-4 h-4" /></button>
                        </div>
                        <div>
                            <label className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Pourquoi cette allée n&apos;a pas été faite ? *</label>
                            <textarea rows={3} value={nonFaitComment}
                                onChange={(e) => setNonFaitComment(e.target.value)}
                                placeholder="Ex: temps insuffisant, secteur inaccessible, matériel manquant..."
                                data-testid="non-fait-comment"
                                className="mt-1 w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-xs placeholder:text-slate-600 focus:border-red-500 outline-none resize-none" />
                        </div>
                        <div>
                            <label className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Nuit de rattrapage</label>
                            <select value={nonFaitNuit} onChange={(e) => setNonFaitNuit(e.target.value)}
                                data-testid="non-fait-nuit"
                                className="mt-1 w-full h-10 px-2 rounded-lg bg-slate-800 border border-slate-700 text-xs focus:border-red-500 outline-none">
                                <option value="">⏳ En attente — je ne sais pas encore quand</option>
                                {(state.nights || []).filter((n) => n.nuit !== a.nuit_eff).map((n) => (
                                    <option key={n.nuit} value={n.nuit}>Nuit {n.nuit}{n.date ? ` (${new Date(n.date + "T00:00:00").toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })})` : ""}</option>
                                ))}
                            </select>
                            <div className="mt-1 text-[10px] text-slate-500">
                                {nonFaitNuit
                                    ? "→ L'allée sera automatiquement déplacée sur cette nuit."
                                    : "→ L'allée restera en attente (visible dans le dashboard et le rapport)."}
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <button onClick={() => setNonFaitPanel(false)} data-testid="non-fait-cancel"
                                className="h-10 px-4 rounded-xl border border-slate-600 text-slate-300 text-xs font-semibold hover:bg-slate-800 transition-colors">
                                Annuler
                            </button>
                            <button onClick={confirmNonFait} disabled={saving}
                                data-testid="non-fait-confirm"
                                className="flex-1 h-10 rounded-xl bg-red-600 hover:bg-red-500 text-white text-sm font-bold flex items-center justify-center gap-2 transition-colors">
                                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Ban className="w-4 h-4" />}
                                {nonFaitNuit ? "Déplacer sur nuit " + nonFaitNuit : "Marquer non faite (en attente)"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {zoom && (
                <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4" onClick={() => setZoom(null)} data-testid="photo-zoom">
                    <img src={actions.photoUrl(zoom)} alt="" className="max-w-full max-h-full rounded-xl" />
                    <button className="absolute top-4 right-4 p-2 rounded-full bg-slate-800 text-white"><X className="w-5 h-5" /></button>
                </div>
            )}
        </div>
    );
}
