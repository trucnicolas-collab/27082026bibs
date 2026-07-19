import React, { useState } from "react";
import { toast } from "sonner";
import {
    AlertTriangle, TrendingUp, TrendingDown, CheckCircle2, Ban,
    Zap, Turtle, Wand2, Loader2, X, Moon, ArrowRight, MapPin, MoveRight,
    HardHat, Copy, Link2, Trash2, MessageSquare, Camera, Flag,
} from "lucide-react";

const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));

export default function SuiviDashboard({ state, actions, goTab, mode = "chef", phaseKind = "eeg" }) {
    const [nightSummary, setNightSummary] = useState(null); // { night, allees } ou null
    if (phaseKind === "cam") {
        return <CamDashboard state={state} actions={actions} goTab={goTab} mode={mode} />;
    }
    const st = state.stats || {};
    const alerts = state.alerts || [];
    const ruptures = alerts.filter((a) => a.type === "rupture");
    const blocages = alerts.filter((a) => a.type === "blocage");
    const geolocs = alerts.filter((a) => a.type === "geoloc").filter((a) => a.family !== "cameras");
    const nonFaites = alerts.filter((a) => a.type === "non_faite");
    const pct = Math.min(100, st.pct || 0);
    const avance = st.avance_nuits;

    return (
        <div className="space-y-4" data-testid="suivi-dashboard">
            {/* Progression globale */}
            <section className="rounded-2xl bg-slate-900 border border-slate-800 p-5">
                <div className="flex items-end justify-between mb-3">
                    <div>
                        <div className="text-[11px] uppercase tracking-widest text-slate-500 font-semibold">Avancement pose EEG</div>
                        <div className="text-3xl font-bold mt-1" data-testid="dash-pct">
                            {pct.toLocaleString("fr-FR")}<span className="text-lg text-slate-400"> %</span>
                        </div>
                    </div>
                    <div className="text-right text-sm text-slate-400">
                        <span className="text-blue-400 font-semibold">{fmt(st.eeg_posees)}</span> / {fmt(st.eeg_prevues)} EEG
                    </div>
                </div>
                <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-700"
                        style={{ width: `${pct}%` }} />
                </div>
                {/* Double jauge Pose vs Géoloc (indicateurs distincts) */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
                    <div className="rounded-xl bg-slate-800/50 p-3" data-testid="dash-pose-progress">
                        <div className="flex items-center justify-between text-[11px] mb-1">
                            <span className="uppercase tracking-widest text-slate-500 font-semibold">Pose produits</span>
                            <span className="text-slate-300 font-semibold tabular-nums">{st.pose_saisis || 0} / {st.pose_total || 0} <span className="text-slate-500 ml-1">({(st.pose_pct || 0).toLocaleString("fr-FR")}%)</span></span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-900 overflow-hidden">
                            <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-500"
                                style={{ width: `${Math.min(100, st.pose_pct || 0)}%` }} />
                        </div>
                    </div>
                    <div className="rounded-xl bg-slate-800/50 p-3" data-testid="dash-geo-progress">
                        <div className="flex items-center justify-between text-[11px] mb-1">
                            <span className="uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><MapPin className="w-3 h-3" /> Géolocalisation</span>
                            <span className="text-slate-300 font-semibold tabular-nums">{st.geo_saisis || 0} / {st.geo_total || 0} <span className="text-slate-500 ml-1">({(st.geo_pct || 0).toLocaleString("fr-FR")}%)</span></span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-900 overflow-hidden">
                            <div className="h-full bg-gradient-to-r from-sky-600 to-sky-400 transition-all duration-500"
                                style={{ width: `${Math.min(100, st.geo_pct || 0)}%` }} />
                        </div>
                    </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
                    <Kpi label="Allées validées" value={`${st.allees_validees || 0} / ${st.allees_total || 0}`} icon={CheckCircle2} color="text-blue-400" testid="dash-allees" />
                    <Kpi label="Allées déplacées" value={st.allees_deplacees || 0} icon={MoveRight} color={st.allees_deplacees ? "text-orange-400" : "text-slate-400"} testid="dash-deplacees" />
                    <Kpi label="Nuits terminées" value={`${st.nuits_terminees || 0} / ${state.nb_nuits || 0}`} icon={Moon} color="text-sky-400" testid="dash-nuits" />
                    <Kpi label="Rythme réel / prévu" value={`${fmt(st.rythme_reel) || "—"} / ${fmt(st.rythme_prevu)}`} icon={TrendingUp} color="text-amber-400" testid="dash-rythme" />
                </div>
            </section>

            {/* Avance / retard */}
            <section className={`rounded-2xl border p-4 flex items-center gap-4
                ${avance === null || avance === undefined ? "bg-slate-900 border-slate-800"
                    : avance > 0 ? "bg-blue-950/50 border-blue-800/60"
                        : avance < 0 ? "bg-red-950/40 border-red-900/60" : "bg-slate-900 border-slate-800"}`}
                data-testid="dash-avance">
                {avance === null || avance === undefined ? (
                    <>
                        <Turtle className="w-8 h-8 text-slate-600 flex-shrink-0" />
                        <div>
                            <div className="font-semibold text-sm">Pas encore de rythme mesuré</div>
                            <div className="text-xs text-slate-400">Validez toutes les allées d'une nuit pour mesurer votre vitesse réelle.</div>
                        </div>
                    </>
                ) : avance > 0 ? (
                    <>
                        <Zap className="w-8 h-8 text-blue-400 flex-shrink-0" />
                        <div className="flex-1">
                            <div className="font-semibold text-sm text-blue-300">En avance d'environ {avance} nuit{avance > 1 ? "s" : ""} ⚡</div>
                            <div className="text-xs text-slate-400">
                                Restant estimé : {st.nuits_estimees_restantes} nuit(s) au rythme réel ({fmt(st.rythme_reel)} EEG/nuit).
                            </div>
                        </div>
                    </>
                ) : avance < 0 ? (
                    <>
                        <TrendingDown className="w-8 h-8 text-red-400 flex-shrink-0" />
                        <div className="flex-1">
                            <div className="font-semibold text-sm text-red-300">Retard estimé : {Math.abs(avance)} nuit{Math.abs(avance) > 1 ? "s" : ""}</div>
                            <div className="text-xs text-slate-400">
                                Il faudrait {st.nuits_estimees_restantes} nuit(s) au rythme actuel pour finir.
                            </div>
                        </div>
                    </>
                ) : (
                    <>
                        <CheckCircle2 className="w-8 h-8 text-blue-400 flex-shrink-0" />
                        <div className="font-semibold text-sm">Parfaitement dans le planning ✔</div>
                    </>
                )}
                {mode === "chef" && <ReplanButton actions={actions} canReplan={!!st.rythme_reel} />}
            </section>

            {/* Publication espace terrain + effacement (chef uniquement) */}
            {mode === "chef" && <PublishCard publication={state.publication} actions={actions} />}

            {/* Alertes */}
            <section data-testid="dash-alerts">
                <h3 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-2 flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5" /> Alertes ({alerts.length})
                </h3>
                {alerts.length === 0 ? (
                    <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 text-sm text-slate-500 flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-blue-500" /> Aucune alerte — tout est sous contrôle.
                    </div>
                ) : (
                    <div className="space-y-2">
                        {ruptures.map((a, i) => (
                            <button key={`r${i}`} onClick={() => goTab("stock")} data-testid={`alert-rupture-${a.family}`}
                                className="w-full text-left rounded-xl bg-red-950/40 border border-red-900/60 p-3.5 flex items-start gap-3 hover:border-red-700 transition-colors">
                                <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
                                <div className="text-sm text-red-200">
                                    <b className="text-red-100">Risque de manque</b> — {a.message}
                                </div>
                            </button>
                        ))}
                        {nonFaites.map((a, i) => (
                            <button key={`nf${i}`} onClick={() => goTab("nuits")} data-testid={`alert-non-faite-${i}`}
                                className={`w-full text-left rounded-xl p-3.5 flex items-start gap-3 transition-colors border
                                    ${a.en_attente ? "bg-orange-950/40 border-orange-800 hover:border-orange-700" : "bg-red-950/40 border-red-800 hover:border-red-700"}`}>
                                <Ban className={`w-4 h-4 mt-0.5 flex-shrink-0 ${a.en_attente ? "text-orange-400" : "text-red-400"}`} />
                                <div className={`text-sm ${a.en_attente ? "text-orange-200" : "text-red-200"}`}>
                                    {a.en_attente && <b className="text-orange-100">⏳ En attente</b>}{a.en_attente && " — "}
                                    {a.message}
                                </div>
                            </button>
                        ))}
                        {blocages.map((a, i) => (
                            <button key={`b${i}`} onClick={() => goTab("nuits")} data-testid={`alert-blocage-${i}`}
                                className="w-full text-left rounded-xl bg-amber-950/40 border border-amber-900/60 p-3.5 flex items-start gap-3 hover:border-amber-700 transition-colors">
                                <Ban className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
                                <div className="text-sm text-amber-200">{a.message}</div>
                            </button>
                        ))}
                        {geolocs.map((a, i) => (
                            <button key={`g${i}`} onClick={() => goTab("nuits")} data-testid={`alert-geoloc-${i}`}
                                className={`w-full text-left rounded-xl p-3.5 flex items-start gap-3 transition-colors border
                                    ${a.needs_explanation ? "bg-red-950/40 border-red-900/60 hover:border-red-700" : "bg-sky-950/40 border-sky-900/60 hover:border-sky-700"}`}>
                                <MapPin className={`w-4 h-4 mt-0.5 flex-shrink-0 ${a.needs_explanation ? "text-red-400" : "text-sky-400"}`} />
                                <div className={`text-sm ${a.needs_explanation ? "text-red-200" : "text-sky-200"}`}>{a.message}</div>
                            </button>
                        ))}
                    </div>
                )}
            </section>

            {/* Aperçu des nuits */}
            <section>
                <h3 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-2">Nuits</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {(state.nights || []).map((n) => {
                        // (v28 iter3) Détecte présence commentaires/photos/incidents dans la nuit
                        const nAllees = (state.allees || []).filter(a => a.nuit_eff === n.nuit);
                        const nbComments = nAllees.filter(a => (a.comment || "").trim().length > 0).length;
                        const nbPhotos = nAllees.reduce((s, a) => s + ((a.photos || []).length), 0);
                        const nbIncidents = (state.incidents || []).filter(i => i.nuit === n.nuit).length;
                        return (
                            <button key={n.nuit} onClick={() => setNightSummary(n)} data-testid={`dash-night-${n.nuit}`}
                                className={`rounded-xl border p-3 text-left transition-colors hover:border-blue-700
                                    ${n.complete ? "bg-blue-950/40 border-blue-900/60" : n.started ? "bg-slate-900 border-sky-900/60" : "bg-slate-900 border-slate-800"}`}>
                                <div className="flex items-center justify-between">
                                    <div className="text-sm font-semibold">
                                        Nuit {n.nuit}
                                        {n.date && <span className="text-slate-500 font-normal text-xs ml-2">{new Date(n.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                                    </div>
                                    {n.complete ? <CheckCircle2 className="w-4 h-4 text-blue-400" />
                                        : n.started ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/60 text-sky-300 font-semibold">EN COURS</span>
                                            : <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500">À VENIR</span>}
                                </div>
                                <div className="text-xs text-slate-400 mt-1 flex items-center gap-2 flex-wrap">
                                    {n.nb_validees}/{n.nb_allees} allées · {fmt(n.eeg_reel)} / {fmt(n.eeg_plan)} EEG
                                    {n.delta_eeg !== null && n.delta_eeg !== undefined && (
                                        <span className={n.delta_eeg > 0 ? "text-blue-400" : n.delta_eeg < 0 ? "text-red-400" : "text-slate-500"}>
                                            {n.delta_eeg > 0 ? "+" : ""}{fmt(n.delta_eeg)}
                                        </span>
                                    )}
                                </div>
                                {(nbComments > 0 || nbPhotos > 0 || nbIncidents > 0) && (
                                    <div className="mt-1.5 flex items-center gap-1.5 flex-wrap" data-testid={`dash-night-${n.nuit}-badges`}>
                                        {nbIncidents > 0 && (
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-950/60 text-red-300 font-semibold flex items-center gap-1"
                                                title={`${nbIncidents} incident(s) déclaré(s) sur cette nuit`}
                                                data-testid={`dash-night-${n.nuit}-incident-badge`}>
                                                <Flag className="w-2.5 h-2.5" />{nbIncidents}
                                            </span>
                                        )}
                                        {nbComments > 0 && (
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-300 font-semibold flex items-center gap-1"
                                                title={`${nbComments} allée(s) avec commentaire`}
                                                data-testid={`dash-night-${n.nuit}-comment-badge`}>
                                                <MessageSquare className="w-2.5 h-2.5" />{nbComments}
                                            </span>
                                        )}
                                        {nbPhotos > 0 && (
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-950/60 text-sky-300 font-semibold flex items-center gap-1"
                                                title={`${nbPhotos} photo(s) sur cette nuit`}
                                                data-testid={`dash-night-${n.nuit}-photo-badge`}>
                                                <Camera className="w-2.5 h-2.5" />{nbPhotos}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </button>
                        );
                    })}
                </div>
            </section>

            {nightSummary && (
                <NightSummaryModal night={nightSummary} state={state} onClose={() => setNightSummary(null)} goTab={goTab} actions={actions} />
            )}
        </div>
    );
}

function NightSummaryModal({ night, state, onClose, goTab, actions }) {
    const allees = (state.allees || []).filter((a) => a.nuit_eff === night.nuit);
    const eegRestant = Math.max(0, (night.eeg_plan || 0) - (night.eeg_reel || 0));
    // (v28 iter3) Agrégats commentaires/photos/incidents pour cette nuit
    const alleesAvecComment = allees.filter(a => (a.comment || "").trim().length > 0);
    const alleesAvecPhoto = allees.filter(a => (a.photos || []).length > 0);
    const nightIncidents = (state.incidents || []).filter(i => i.nuit === night.nuit);
    const [zoomPhoto, setZoomPhoto] = React.useState(null);
    return (
        <div className="fixed inset-0 z-50 bg-black/75 flex items-end sm:items-center justify-center p-3"
            data-testid={`night-summary-${night.nuit}`} onClick={onClose}>
            <div className="w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700 p-4 space-y-3 max-h-[85vh] flex flex-col"
                onClick={(e) => e.stopPropagation()}>
                <div className="flex items-start gap-2">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold flex-shrink-0
                        ${night.complete ? "bg-blue-600 text-white" : night.started ? "bg-sky-700 text-white" : "bg-slate-800 text-slate-400"}`}>
                        {night.nuit}
                    </div>
                    <div className="flex-1 min-w-0">
                        <h4 className="text-sm font-bold" data-testid="night-summary-title">
                            Résumé Nuit {night.nuit}
                            {night.date && <span className="text-slate-400 font-normal ml-2 text-xs">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR", { weekday: "long", day: "2-digit", month: "long" })}</span>}
                        </h4>
                        <div className="text-[11px] text-slate-400 mt-0.5">
                            {night.complete ? "Nuit terminée" : night.started ? "En cours" : "À venir"}
                        </div>
                    </div>
                    <button onClick={onClose} data-testid="night-summary-close"
                        className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400"><X className="w-4 h-4" /></button>
                </div>
                {/* KPI */}
                <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-lg bg-slate-800/50 p-2.5">
                        <div className="text-[10px] uppercase text-slate-500 font-semibold">Allées</div>
                        <div className="text-lg font-bold" data-testid="night-summary-allees">{night.nb_validees} / {night.nb_allees}</div>
                        {night.nb_bloquees > 0 && <div className="text-[10px] text-red-400">{night.nb_bloquees} bloquée(s)</div>}
                    </div>
                    <div className="rounded-lg bg-slate-800/50 p-2.5">
                        <div className="text-[10px] uppercase text-slate-500 font-semibold">EEG posées</div>
                        <div className="text-lg font-bold" data-testid="night-summary-eeg">{fmt(night.eeg_reel)} / {fmt(night.eeg_plan)}</div>
                        {night.delta_eeg !== null && night.delta_eeg !== undefined && (
                            <div className={`text-[10px] font-semibold ${night.delta_eeg > 0 ? "text-blue-400" : night.delta_eeg < 0 ? "text-red-400" : "text-slate-500"}`}>
                                {night.delta_eeg > 0 ? "+" : ""}{fmt(night.delta_eeg)}
                            </div>
                        )}
                    </div>
                </div>
                {eegRestant > 0 && !night.complete && (
                    <div className="rounded-lg bg-amber-950/40 border border-amber-900/60 p-2 text-[11px] text-amber-200">
                        Restant à poser : <b>{fmt(eegRestant)} EEG</b>
                    </div>
                )}
                {/* Mini-jauges Pose vs Géoloc spécifiques à cette nuit */}
                {(night.pose_total > 0 || night.geo_total > 0) && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="night-summary-gauges">
                        {night.pose_total > 0 && (() => {
                            const pctPose = Math.round(100 * (night.pose_saisis || 0) / (night.pose_total || 1));
                            const complete = (night.pose_saisis || 0) >= (night.pose_total || 0);
                            return (
                                <div className="rounded-lg bg-slate-800/50 p-2">
                                    <div className="flex items-center justify-between text-[10px] mb-1">
                                        <span className="uppercase tracking-widest text-slate-500 font-semibold">Pose</span>
                                        <span className={`tabular-nums font-semibold ${complete ? "text-blue-400" : "text-slate-300"}`}>
                                            {night.pose_saisis || 0}/{night.pose_total || 0} <span className="text-slate-500">({pctPose}%)</span>
                                        </span>
                                    </div>
                                    <div className="h-1.5 rounded-full bg-slate-900 overflow-hidden">
                                        <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-500"
                                            style={{ width: `${Math.min(100, pctPose)}%` }} />
                                    </div>
                                </div>
                            );
                        })()}
                        {night.geo_total > 0 && (() => {
                            const pctGeo = Math.round(100 * (night.geo_saisis || 0) / (night.geo_total || 1));
                            const complete = (night.geo_saisis || 0) >= (night.geo_total || 0);
                            return (
                                <div className="rounded-lg bg-slate-800/50 p-2">
                                    <div className="flex items-center justify-between text-[10px] mb-1">
                                        <span className="uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><MapPin className="w-2.5 h-2.5" /> Géoloc</span>
                                        <span className={`tabular-nums font-semibold ${complete ? "text-blue-400" : "text-sky-300"}`}>
                                            {night.geo_saisis || 0}/{night.geo_total || 0} <span className="text-slate-500">({pctGeo}%)</span>
                                        </span>
                                    </div>
                                    <div className="h-1.5 rounded-full bg-slate-900 overflow-hidden">
                                        <div className="h-full bg-gradient-to-r from-sky-600 to-sky-400 transition-all duration-500"
                                            style={{ width: `${Math.min(100, pctGeo)}%` }} />
                                    </div>
                                </div>
                            );
                        })()}
                    </div>
                )}
                {night.nb_a_finaliser > 0 && (
                    <div className="rounded-lg bg-red-950/40 border border-red-900/60 p-2 text-[11px] text-red-200 flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5" /> {night.nb_a_finaliser} allée(s) à finaliser une autre nuit
                    </div>
                )}
                {/* Liste des allées */}
                <div className="flex-1 overflow-y-auto -mx-1 px-1 space-y-3">
                    {/* (v28 iter3) Incidents de la nuit */}
                    {nightIncidents.length > 0 && (
                        <div className="space-y-1" data-testid="night-summary-incidents">
                            <div className="text-[10px] uppercase text-slate-500 font-semibold flex items-center gap-1">
                                <Flag className="w-2.5 h-2.5 text-red-400" /> Incidents ({nightIncidents.length})
                            </div>
                            {nightIncidents.map((inc) => (
                                <div key={inc.id} className="rounded-lg bg-red-950/30 border border-red-900/40 p-2 text-[11px] text-red-100"
                                    data-testid={`night-summary-incident-${inc.id}`}>
                                    <div className="text-red-300 font-semibold text-[10px] mb-0.5">
                                        {inc.author || "—"} · {inc.created_at ? new Date(inc.created_at).toLocaleString("fr-FR") : ""}
                                    </div>
                                    <div className="whitespace-pre-wrap">{inc.text}</div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* (v28 iter3) Commentaires par allée */}
                    {alleesAvecComment.length > 0 && (
                        <div className="space-y-1" data-testid="night-summary-comments">
                            <div className="text-[10px] uppercase text-slate-500 font-semibold flex items-center gap-1">
                                <MessageSquare className="w-2.5 h-2.5 text-amber-400" /> Commentaires ({alleesAvecComment.length})
                            </div>
                            {alleesAvecComment.map((a) => (
                                <div key={a.uid} className="rounded-lg bg-amber-950/30 border border-amber-900/40 p-2 text-[11px] text-amber-100"
                                    data-testid={`night-summary-comment-${a.uid}`}>
                                    <div className="text-amber-300 font-semibold text-[10px] mb-0.5">
                                        Allée {a.allee} · {a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}
                                    </div>
                                    <div className="whitespace-pre-wrap">{a.comment}</div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* (v28 iter3) Photos par allée */}
                    {alleesAvecPhoto.length > 0 && (
                        <div className="space-y-1" data-testid="night-summary-photos">
                            <div className="text-[10px] uppercase text-slate-500 font-semibold flex items-center gap-1">
                                <Camera className="w-2.5 h-2.5 text-sky-400" /> Photos ({alleesAvecPhoto.reduce((s, a) => s + a.photos.length, 0)})
                            </div>
                            {alleesAvecPhoto.map((a) => (
                                <div key={a.uid} className="rounded-lg bg-slate-800/40 p-2" data-testid={`night-summary-photos-${a.uid}`}>
                                    <div className="text-slate-400 text-[10px] font-semibold mb-1">
                                        Allée {a.allee} · {a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}
                                    </div>
                                    <div className="grid grid-cols-4 gap-1.5">
                                        {a.photos.map((p) => (
                                            <button key={p.id} onClick={() => setZoomPhoto(p.id)}
                                                data-testid={`night-summary-photo-${p.id}`}
                                                className="aspect-square rounded overflow-hidden bg-slate-900 border border-slate-700 hover:border-sky-500 transition-colors">
                                                <img src={actions?.photoUrl(p.id)} alt=""
                                                    loading="lazy"
                                                    className="w-full h-full object-cover" />
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    <div className="text-[10px] uppercase text-slate-500 font-semibold mb-1 pt-1">Allées de la nuit</div>
                    {allees.length === 0 && <div className="text-xs text-slate-500 italic">Aucune allée assignée.</div>}
                    {allees.map((a) => {
                        const status = a.status || "a_faire";
                        const color =
                            status === "validee" ? "text-blue-400 bg-blue-950/40" :
                            status === "bloquee" ? "text-red-400 bg-red-950/40" :
                            status === "a_finaliser" ? "text-red-300 bg-red-950/40" :
                            "text-slate-400 bg-slate-800/40";
                        const dot =
                            status === "validee" ? "bg-blue-500" :
                            status === "bloquee" ? "bg-red-500" :
                            status === "a_finaliser" ? "bg-red-400" :
                            "bg-slate-600";
                        const hasComment = (a.comment || "").trim().length > 0;
                        const hasPhotos = (a.photos || []).length > 0;
                        return (
                            <div key={a.uid}
                                className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 ${color}`}
                                data-testid={`night-summary-allee-${a.uid}`}>
                                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot}`} />
                                <span className="text-xs font-bold w-8 flex-shrink-0">{a.allee}</span>
                                <span className="text-[11px] flex-1 min-w-0 truncate text-slate-300">
                                    {a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}
                                </span>
                                {hasComment && <MessageSquare className="w-3 h-3 text-amber-400 flex-shrink-0" />}
                                {hasPhotos && <Camera className="w-3 h-3 text-sky-400 flex-shrink-0" />}
                                <span className="text-[10px] font-semibold tabular-nums">
                                    {a.nb_saisis}/{a.nb_produits}
                                </span>
                            </div>
                        );
                    })}
                </div>
                {zoomPhoto && (
                    <div className="fixed inset-0 z-[60] bg-black/95 flex items-center justify-center p-4"
                        data-testid="night-summary-photo-zoom" onClick={() => setZoomPhoto(null)}>
                        <img src={actions?.photoUrl(zoomPhoto)} alt="" className="max-w-full max-h-full rounded-xl" />
                        <button onClick={() => setZoomPhoto(null)}
                            className="absolute top-3 right-3 p-2 rounded-lg bg-black/50 hover:bg-black/80 text-white">
                            <X className="w-5 h-5" />
                        </button>
                    </div>
                )}
                <button onClick={() => { onClose(); goTab && goTab("nuits"); }} data-testid="night-summary-open"
                    className="w-full h-10 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold flex items-center justify-center gap-2 transition-colors">
                    Ouvrir la nuit <ArrowRight className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
}

function PublishCard({ publication, actions }) {
    const [busy, setBusy] = useState(false);
    const [confirmReset, setConfirmReset] = useState(false);
    const published = publication?.published;
    const link = `${window.location.origin}/suivi/terrain`;

    const toggle = async () => {
        setBusy(true);
        const res = await actions.publish(!published);
        setBusy(false);
        if (res) toast.success(res.published
            ? "Magasin publié — visible par les équipes terrain"
            : "Magasin retiré de l'espace terrain");
    };
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(link);
            toast.success("Lien de l'espace terrain copié (le même pour tous les magasins)");
        } catch { toast.error("Copie impossible"); }
    };
    const doReset = async () => {
        setBusy(true);
        await actions.resetSuivi();
        setBusy(false);
        setConfirmReset(false);
    };

    return (
        <section className="rounded-2xl bg-slate-900 border border-slate-800 p-4" data-testid="publish-card">
            <div className="flex items-center gap-3 flex-wrap">
                <div className="w-9 h-9 rounded-lg bg-amber-500/20 flex items-center justify-center flex-shrink-0">
                    <HardHat className="w-5 h-5 text-amber-400" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold flex items-center gap-2">
                        Espace équipe terrain
                        {published
                            ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 font-bold">PUBLIÉ</span>
                            : <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500 font-bold">NON PUBLIÉ</span>}
                    </div>
                    <div className="text-xs text-slate-400">
                        Publiez le magasin pour qu'il apparaisse sur <span className="text-slate-300">/suivi/terrain</span> (espace commun, sans compte).
                        {publication?.published_by && published && <span className="text-slate-500"> Publié par {publication.published_by}.</span>}
                    </div>
                </div>
                <button onClick={toggle} disabled={busy} data-testid="publish-toggle"
                    className={`h-8 px-3 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors
                        ${published ? "border border-slate-600 text-slate-300 hover:bg-slate-800" : "bg-amber-500 hover:bg-amber-400 text-slate-950"}`}>
                    {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Link2 className="w-3.5 h-3.5" />}
                    {published ? "Dépublier" : "Publier"}
                </button>
            </div>
            <div className="mt-3 flex items-center gap-2 flex-wrap">
                <code className="flex-1 min-w-[180px] truncate text-[11px] bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-2 text-blue-300" data-testid="terrain-link">
                    {link}
                </code>
                <button onClick={copy} data-testid="terrain-copy"
                    className="h-8 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-colors">
                    <Copy className="w-3.5 h-3.5" /> Copier
                </button>
                {!confirmReset ? (
                    <button onClick={() => setConfirmReset(true)} data-testid="reset-suivi-btn"
                        title="Efface toutes les saisies, photos et incidents du suivi (réservé au créateur du phasage et à l'admin)"
                        className="h-8 px-3 rounded-lg border border-red-900 text-red-400 text-xs font-semibold flex items-center gap-1.5 hover:bg-red-950/50 transition-colors">
                        <Trash2 className="w-3.5 h-3.5" /> Effacer le suivi
                    </button>
                ) : (
                    <span className="flex items-center gap-1.5">
                        <button onClick={doReset} disabled={busy} data-testid="reset-suivi-confirm"
                            className="h-8 px-3 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-bold flex items-center gap-1.5 transition-colors">
                            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />} Confirmer l'effacement
                        </button>
                        <button onClick={() => setConfirmReset(false)} data-testid="reset-suivi-cancel"
                            className="h-8 px-2.5 rounded-lg border border-slate-700 text-slate-400 text-xs hover:bg-slate-800 transition-colors">Annuler</button>
                    </span>
                )}
            </div>
        </section>
    );
}

function Kpi({ label, value, icon: Icon, color, testid }) {
    return (
        <div className="rounded-xl bg-slate-800/50 p-3" data-testid={testid}>
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
                <Icon className={`w-3.5 h-3.5 ${color}`} /> {label}
            </div>
            <div className="text-base font-bold mt-1">{value}</div>
        </div>
    );
}

export function ReplanButton({ actions, canReplan }) {
    const [busy, setBusy] = useState(false);
    const [preview, setPreview] = useState(null);

    const openPreview = async () => {
        setBusy(true);
        const res = await actions.replan(false);
        setBusy(false);
        if (res) setPreview(res);
    };
    const apply = async () => {
        setBusy(true);
        const res = await actions.replan(true);
        setBusy(false);
        if (res) setPreview(null);
    };

    return (
        <>
            <button onClick={openPreview} disabled={!canReplan || busy} data-testid="replan-button"
                title={canReplan ? "Recalculer le phasage restant selon le rythme réel" : "Terminez au moins une nuit d'abord"}
                className="flex-shrink-0 h-9 px-3 rounded-lg bg-violet-600/90 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold flex items-center gap-1.5 transition-colors">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
                <span className="hidden sm:inline">Replanifier</span>
            </button>

            {preview && (
                <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" data-testid="replan-modal">
                    <div className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl bg-slate-900 border border-slate-700 p-5">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="font-bold flex items-center gap-2"><Wand2 className="w-4 h-4 text-violet-400" /> Proposition de replanification</h3>
                            <button onClick={() => setPreview(null)} className="p-1 rounded hover:bg-slate-800 text-slate-400"><X className="w-4 h-4" /></button>
                        </div>
                        <div className="text-sm text-slate-300 mb-3 space-y-1">
                            <p>Rythme réel mesuré : <b className="text-blue-400">{Number(preview.rythme_reel).toLocaleString("fr-FR")} EEG/nuit</b> (prévu : {Number(preview.rythme_prevu).toLocaleString("fr-FR")}).</p>
                            <p>Capacité retenue : <b>{Number(preview.capacity).toLocaleString("fr-FR")} EEG/nuit</b> · {preview.allees_deplacees} allée(s) déplacée(s).</p>
                            {preview.nuits_gagnees > 0 ? (
                                <p className="text-blue-300 font-semibold">🎉 {preview.nuits_gagnees} nuit(s) gagnée(s) sur le planning initial !</p>
                            ) : preview.nuits_gagnees < 0 ? (
                                <p className="text-red-300 font-semibold">⚠️ {Math.abs(preview.nuits_gagnees)} nuit(s) supplémentaire(s) nécessaire(s).</p>
                            ) : (
                                <p className="text-slate-400">Même nombre de nuits, charge rééquilibrée.</p>
                            )}
                        </div>
                        <div className="space-y-1.5 mb-4">
                            {(preview.preview || []).map((p) => (
                                <div key={p.nuit} className="rounded-lg bg-slate-800/60 px-3 py-2 text-xs flex items-center justify-between">
                                    <span className="font-semibold">Nuit {p.nuit}{p.date ? ` · ${new Date(p.date + "T00:00:00").toLocaleDateString("fr-FR")}` : ""}</span>
                                    <span className="text-slate-400">{p.nb_allees} allées · {Number(p.eeg).toLocaleString("fr-FR")} EEG</span>
                                </div>
                            ))}
                        </div>
                        <p className="text-[11px] text-slate-500 mb-3">Une sauvegarde du phasage actuel est créée automatiquement (restaurable depuis l'app Phasage).</p>
                        <div className="flex gap-2 justify-end">
                            <button onClick={() => setPreview(null)} data-testid="replan-cancel"
                                className="h-9 px-4 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors">Annuler</button>
                            <button onClick={apply} disabled={busy} data-testid="replan-apply"
                                className="h-9 px-4 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold flex items-center gap-1.5 transition-colors">
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
                                Appliquer au phasage
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}


function CamDashboard({ state, goTab, mode }) {
    const cam = state.cam || { nights: [], allees: [], start_at_nuit: 1 };
    const nights = (cam.nights || []).filter((n) => n.nb_allees > 0);
    const allees = cam.allees || [];
    const totalPlan = allees.reduce((s, a) => s + (a.plan || 0), 0);
    const totalReel = allees.reduce((s, a) => s + (a.reel || 0), 0);
    const totalGeo = allees.reduce((s, a) => s + (a.geo || 0), 0);
    const totalFixPlan = allees.reduce((s, a) => s + (a.fix_plan || 0), 0);
    const totalFixReel = allees.reduce((s, a) => s + (a.fix_reel || 0), 0);
    const nbValid = allees.filter((a) => a.status === "validee").length;
    const nbBlock = allees.filter((a) => a.status === "bloquee").length;
    const alerts = (state.alerts || []).filter((a) => (a.family === "cameras") || (a.type === "geoloc" && a.family === "cameras"));
    const pct = totalPlan > 0 ? Math.min(100, Math.round(100 * totalReel / totalPlan)) : 0;
    const pctGeo = totalReel > 0 ? Math.min(100, Math.round(100 * totalGeo / totalReel)) : 0;
    const pctFix = totalFixPlan > 0 ? Math.min(100, Math.round(100 * totalFixReel / totalFixPlan)) : 0;

    return (
        <div className="space-y-4" data-testid="cam-dashboard">
            <section className="rounded-2xl bg-slate-900 border border-slate-800 p-5">
                <div className="flex items-end justify-between mb-3">
                    <div>
                        <div className="text-[11px] uppercase tracking-widest text-slate-500 font-semibold">Avancement pose caméras</div>
                        <div className="text-3xl font-bold mt-1" data-testid="cam-dash-pct">
                            {pct.toLocaleString("fr-FR")}<span className="text-lg text-slate-400"> %</span>
                        </div>
                    </div>
                    <div className="text-right text-sm text-slate-400">
                        <span className="text-sky-400 font-semibold">{fmt(totalReel)}</span> / {fmt(totalPlan)} caméras
                    </div>
                </div>
                <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-sky-600 to-sky-400 transition-all duration-700" style={{ width: `${pct}%` }} />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
                    <div className="rounded-xl bg-slate-800/50 p-3" data-testid="cam-dash-geo">
                        <div className="flex items-center justify-between text-[11px] mb-1">
                            <span className="uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><MapPin className="w-3 h-3" /> Géolocalisation</span>
                            <span className="text-slate-300 font-semibold tabular-nums">{fmt(totalGeo)} / {fmt(totalReel)} <span className="text-slate-500 ml-1">({pctGeo}%)</span></span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-900 overflow-hidden">
                            <div className="h-full bg-gradient-to-r from-sky-600 to-sky-400 transition-all duration-500" style={{ width: `${pctGeo}%` }} />
                        </div>
                    </div>
                    <div className="rounded-xl bg-slate-800/50 p-3" data-testid="cam-dash-fix">
                        <div className="flex items-center justify-between text-[11px] mb-1">
                            <span className="uppercase tracking-widest text-slate-500 font-semibold">Fixations spécifiques</span>
                            <span className="text-slate-300 font-semibold tabular-nums">{fmt(totalFixReel)} / {fmt(totalFixPlan)} <span className="text-slate-500 ml-1">({pctFix}%)</span></span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-900 overflow-hidden">
                            <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-500" style={{ width: `${pctFix}%` }} />
                        </div>
                    </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-4">
                    <Kpi label="Allées validées" value={`${nbValid} / ${allees.length}`} icon={CheckCircle2} color="text-blue-400" testid="cam-dash-valid" />
                    <Kpi label="Allées bloquées" value={nbBlock} icon={Ban} color={nbBlock ? "text-red-400" : "text-slate-400"} testid="cam-dash-block" />
                    <Kpi label="Nuits caméras" value={nights.length} icon={Moon} color="text-sky-400" testid="cam-dash-nights" />
                </div>
            </section>

            <section data-testid="cam-dash-alerts">
                <h3 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-2 flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5" /> Alertes caméras ({alerts.length})
                </h3>
                {alerts.length === 0 ? (
                    <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 text-sm text-slate-500 flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-blue-500" /> Aucune alerte côté caméras.
                    </div>
                ) : (
                    <div className="space-y-2">
                        {alerts.map((a, i) => (
                            <button key={i} onClick={() => goTab && goTab("cam")} data-testid={`cam-alert-${i}`}
                                className="w-full text-left rounded-xl bg-sky-950/40 border border-sky-900/60 p-3.5 flex items-start gap-3 hover:border-sky-700 transition-colors">
                                <MapPin className="w-4 h-4 text-sky-400 mt-0.5 flex-shrink-0" />
                                <div className="text-sm text-sky-200">{a.message}</div>
                            </button>
                        ))}
                    </div>
                )}
            </section>

            <section>
                <h3 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-2">Nuits caméras</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {nights.map((n) => (
                        <button key={n.nuit} onClick={() => goTab && goTab("cam")} data-testid={`cam-dash-night-${n.nuit}`}
                            className={`rounded-xl border p-3 text-left transition-colors hover:border-sky-700
                                ${n.complete ? "bg-blue-950/40 border-blue-900/60" : "bg-slate-900 border-slate-800"}`}>
                            <div className="flex items-center justify-between">
                                <div className="text-sm font-semibold">
                                    Nuit {n.nuit_abs}
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/60 text-sky-300 font-semibold ml-2">CAM {n.nuit}</span>
                                    {n.date && <span className="text-slate-500 font-normal text-xs ml-2">{new Date(n.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                                </div>
                                {n.complete && <CheckCircle2 className="w-4 h-4 text-blue-400" />}
                            </div>
                            <div className="text-xs text-slate-400 mt-1">
                                {n.nb_validees}/{n.nb_allees} allées · {fmt(n.cam_reel)} / {fmt(n.cam_plan)} caméras
                            </div>
                        </button>
                    ))}
                    {nights.length === 0 && (
                        <div className="text-sm text-slate-500 italic px-3 py-4">
                            Aucune nuit caméra planifiée. Complétez le phasage caméras dans l'app Phasage.
                        </div>
                    )}
                </div>
            </section>
        </div>
    );
}
