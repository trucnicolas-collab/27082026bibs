import React, { useState } from "react";
import { toast } from "sonner";
import {
    ChevronDown, CheckCircle2, Ban, RotateCcw, Download, Loader2,
    AlertTriangle, MessageSquarePlus, Trash2, MoveRight,
} from "lucide-react";

const FAM_SHORT = {
    es_15: "ES 1.5", es_21: "ES 2.1", rails_es: "Rails",
    sa_15: "SA 1.5", sa_21_std: "SA 2.1", sa_21_freezer: "SA frz",
    sa_42: "SA 4.2", cameras: "Cam",
};
const FAMILY_KEYS = Object.keys(FAM_SHORT);
const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));

export default function SuiviNuits({ state, actions }) {
    const nights = state.nights || [];
    const [open, setOpen] = useState(() => {
        const firstOpen = nights.find((n) => !n.complete && n.nb_allees > 0) || nights.find((n) => n.nb_allees > 0);
        return firstOpen ? firstOpen.nuit : (nights[0]?.nuit ?? null);
    });

    if (!nights.some((n) => n.nb_allees > 0)) {
        return (
            <div className="text-center py-20 text-slate-500 text-sm" data-testid="nuits-empty">
                Aucune allée assignée à une nuit.<br />
                Complétez d'abord le phasage dans l'<a href="/" className="text-emerald-400 underline">app Phasage</a>.
            </div>
        );
    }

    return (
        <div className="space-y-3" data-testid="suivi-nuits">
            {nights.map((n) => (
                <NightBlock key={n.nuit} night={n} state={state} actions={actions}
                    isOpen={open === n.nuit} onToggle={() => setOpen(open === n.nuit ? null : n.nuit)} />
            ))}
        </div>
    );
}

function NightBlock({ night, state, actions, isOpen, onToggle }) {
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

                    {/* Incidents */}
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
    const [comment, setComment] = useState(a.comment || "");
    const [saving, setSaving] = useState(false);
    const fams = FAMILY_KEYS.filter((k) => (a.plan[k] || 0) > 0 || a.reel[k] !== null);

    const saveField = async (k) => {
        const raw = vals[k];
        const num = raw === "" ? null : Number(raw);
        if (raw !== "" && (isNaN(num) || num < 0)) { toast.error("Valeur invalide"); return; }
        if (num === (a.reel[k] ?? null)) return;
        await actions.patchAllee(a.uid, { [`${k}_reel`]: num });
    };

    const setStatus = async (status) => {
        setSaving(true);
        // Auto-remplissage : valider sans saisie = conforme au prévu
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

    const saveComment = async () => {
        if (comment === (a.comment || "")) return;
        await actions.patchAllee(a.uid, { comment });
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

            {/* prévu vs réel */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2.5">
                {fams.map((k) => {
                    const d = a.delta[k];
                    return (
                        <div key={k} className="rounded-lg bg-slate-900/70 p-2">
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
                                <input type="number" min="0" inputMode="numeric" placeholder="réel"
                                    value={vals[k]}
                                    onChange={(e) => setVals((s) => ({ ...s, [k]: e.target.value }))}
                                    onBlur={() => saveField(k)}
                                    data-testid={`allee-input-${k}-${a.uid}`}
                                    className="w-full h-7 px-1.5 rounded bg-slate-800 border border-slate-700 text-xs text-center focus:border-emerald-500 outline-none placeholder:text-slate-600" />
                            </div>
                        </div>
                    );
                })}
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
                <input value={comment} onChange={(e) => setComment(e.target.value)} onBlur={saveComment}
                    placeholder="Commentaire (manque produit, casse...)"
                    data-testid={`allee-comment-${a.uid}`}
                    className="flex-1 min-w-[140px] h-8 px-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs placeholder:text-slate-600 focus:border-emerald-600 outline-none" />
            </div>
        </div>
    );
}
