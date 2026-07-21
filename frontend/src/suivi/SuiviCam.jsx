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
            ${night.complete ? "border-blue-900/70 bg-blue-950/20" : "border-slate-800 bg-slate-900"}`}
            data-testid={`cam-night-${night.nuit}`}>
            <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-3 text-left" data-testid={`cam-night-toggle-${night.nuit}`}>
                <div className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm flex-shrink-0
                    ${night.complete ? "bg-blue-600 text-white" : "bg-sky-800 text-sky-200"}`}>
                    {night.nuit_abs}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold flex items-center gap-2">
                        Nuit {night.nuit_abs} <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/60 text-sky-300 font-semibold">CAM {night.nuit}</span>
                        {night.date && <span className="text-xs text-slate-500 font-normal">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                        {night.complete && <CheckCircle2 className="w-4 h-4 text-blue-400" />}
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
    const readOnly = !!actions.readOnly;
    const [comment, setComment] = useState(a.comment || "");
    const [geoComment, setGeoComment] = useState(a.geoloc_comment || "");
    const [saving, setSaving] = useState(false);
    // (v28 iter6) État local des saisies par produit — remplacé par grille dynamique
    const [prodVals, setProdVals] = useState({});
    React.useEffect(() => {
        const init = {};
        (a.products || []).forEach(p => {
            init[p.designation] = {
                reel: p.reel !== null && p.reel !== undefined ? String(p.reel) : "",
                geo: p.geo !== null && p.geo !== undefined ? String(p.geo) : "",
            };
        });
        setProdVals(init);
    }, [a.uid, a.products]);

    const gap = a.geo_gap || 0;

    const saveProductField = async (designation, field, raw, current) => {
        const num = raw === "" ? null : Number(raw);
        if (raw !== "" && (isNaN(num) || num < 0)) { toast.error("Valeur invalide"); return; }
        if (num === (current ?? null)) return;
        await actions.patchCamAllee(a.uid, { products: [{ designation, [field]: num }] });
    };

    const setStatus = async (status) => {
        setSaving(true);
        const fields = { status };
        // Si on valide et rien n'a été saisi, on remplit tous les produits au plan
        if (status === "validee" && (a.products || []).every(p => p.reel === null || p.reel === undefined)) {
            fields.products = (a.products || []).map(p => ({
                designation: p.designation,
                reel: p.plan || 0,
                ...(p.is_geo ? { geo: p.plan || 0 } : {}),
            }));
        }
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

    const border = a.status === "validee" ? "border-blue-800/70" : a.status === "bloquee" ? "border-red-800/70" : "border-slate-700/70";

    return (
        <div className={`rounded-xl bg-slate-800/50 border ${border} p-3`} data-testid={`cam-card-${a.uid}`}>
            <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-2 py-0.5 rounded-md text-sm font-bold
                    ${a.status === "validee" ? "bg-blue-600 text-white" : a.status === "bloquee" ? "bg-red-600 text-white" : "bg-sky-800 text-sky-100"}`}>
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
                {readOnly ? (
                    <span className="h-7 rounded-lg bg-slate-900 border border-slate-800 text-[11px] px-2 flex items-center text-slate-400">
                        {"N" + (cam.start_at_nuit + a.nuit_eff - 1)}
                    </span>
                ) : (
                    <select value={a.nuit_eff} onChange={moveNight} data-testid={`cam-move-${a.uid}`}
                        className="h-7 rounded-lg bg-slate-900 border border-slate-700 text-[11px] px-1.5 text-slate-300 focus:border-sky-500 outline-none cursor-pointer">
                        {Array.from({ length: maxNight }, (_, i) => i + 1).map((x) => (
                            <option key={x} value={x}>{"N" + (cam.start_at_nuit + x - 1)}</option>
                        ))}
                    </select>
                )}
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

            {/* (iter39) Cartes verticales par produit — même style que côté EEG :
                 nom complet du produit sur une ligne, compteurs Prévu/Posé/Géoloc/Δ dessous */}
            <div className="mt-2 rounded-lg bg-slate-900/40 border border-slate-800 divide-y divide-slate-800/60">
                {(a.products || []).map((p) => {
                    const vals = prodVals[p.designation] || { reel: "", geo: "" };
                    const dReel = (p.reel !== null && p.reel !== undefined) ? (p.reel - p.plan) : null;
                    const gapP = (p.is_geo && p.reel !== null && p.reel !== undefined
                                  && p.geo !== null && p.geo !== undefined && p.geo < p.reel) ? (p.reel - p.geo) : 0;
                    return (
                        <div key={p.designation}
                            className={`px-3 py-2.5 space-y-1.5 ${gapP ? "bg-red-950/20" : ""}`}
                            data-testid={`cam-prod-${a.uid}-${p.designation}`}>
                            {/* Ligne 1 : nom du produit + icône type + référence SKU */}
                            <div className="flex items-start gap-2">
                                <div className="text-xs text-slate-200 flex-1 min-w-0 break-words leading-snug flex items-center gap-1 flex-wrap" title={p.designation}>
                                    <span>{p.is_camera ? "📷" : "🔧"} {p.designation}</span>
                                    {p.reference && <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-blue-300 font-mono">#{p.reference}</span>}
                                </div>
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
                                    <span className="text-xs text-slate-300 tabular-nums font-semibold">{fmt(p.plan)}</span>
                                </div>
                                <div className="flex flex-col items-center">
                                    <span className="text-[9px] uppercase text-slate-500 font-semibold">Posé</span>
                                    <input type="number" min="0" inputMode="numeric" placeholder="—" value={vals.reel}
                                        readOnly={readOnly}
                                        onChange={(e) => setProdVals(s => ({ ...s, [p.designation]: { ...s[p.designation], reel: e.target.value } }))}
                                        onBlur={() => saveProductField(p.designation, "reel", vals.reel, p.reel)}
                                        data-testid={`cam-prod-reel-${a.uid}-${p.designation}`}
                                        className={`w-full h-8 px-1 rounded text-xs text-center outline-none placeholder:text-slate-600 ${readOnly ? "bg-slate-950 border border-slate-800 text-slate-400 cursor-not-allowed" : "bg-slate-800 border border-slate-700 focus:border-sky-500"}`} />
                                </div>
                                <div className="flex flex-col items-center">
                                    <span className="text-[9px] uppercase text-slate-500 font-semibold">Géoloc</span>
                                    {p.is_geo ? (
                                        <input type="number" min="0" inputMode="numeric" placeholder="—" value={vals.geo}
                                            readOnly={readOnly}
                                            onChange={(e) => setProdVals(s => ({ ...s, [p.designation]: { ...s[p.designation], geo: e.target.value } }))}
                                            onBlur={() => saveProductField(p.designation, "geo", vals.geo, p.geo)}
                                            data-testid={`cam-prod-geo-${a.uid}-${p.designation}`}
                                            className={`w-full h-8 px-1 rounded text-xs text-center outline-none placeholder:text-slate-600 ${readOnly ? "bg-slate-950 border border-slate-800 text-slate-400 cursor-not-allowed" : gapP ? "bg-slate-800 border border-red-700 text-red-300 focus:border-red-500" : "bg-slate-800 border border-slate-700 focus:border-sky-500"}`} />
                                    ) : (
                                        <span className="text-slate-700 text-xs">—</span>
                                    )}
                                </div>
                                <div className="flex flex-col items-center">
                                    <span className="text-[9px] uppercase text-slate-500 font-semibold">Δ</span>
                                    <span className={`text-xs font-bold tabular-nums ${dReel === null ? "text-slate-700" : dReel >= 0 ? "text-emerald-400" : "text-amber-400"}`}>
                                        {dReel === null ? "—" : (dReel > 0 ? "+" : "") + fmt(dReel)}
                                    </span>
                                </div>
                            </div>
                        </div>
                    );
                })}
                {(a.products || []).length === 0 && (
                    <div className="px-2 py-2 text-[11px] text-slate-600 italic text-center">Aucun produit caméra sur cette allée</div>
                )}
            </div>

            {gap > 0 && (
                <div className="mt-2 rounded-lg bg-red-950/40 border border-red-900/60 p-2" data-testid={`cam-geo-explain-${a.uid}`}>
                    <div className="text-[11px] text-red-300 font-semibold flex items-center gap-1.5 mb-1">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        {fmt(gap)} caméra(s) posée(s) non géolocalisée(s){!geoComment && !readOnly && " — explication demandée"}
                    </div>
                    <input value={geoComment} onChange={(e) => setGeoComment(e.target.value)}
                        readOnly={readOnly}
                        onBlur={() => { if (geoComment !== (a.geoloc_comment || "")) actions.patchCamAllee(a.uid, { geoloc_comment: geoComment }); }}
                        placeholder="Pourquoi ? (ex: pas de signal, config à finir...)"
                        data-testid={`cam-geo-comment-${a.uid}`}
                        className={`w-full h-8 px-2.5 rounded-lg border text-xs placeholder:text-slate-600 outline-none ${readOnly ? "bg-slate-950 border-slate-800 text-slate-400 cursor-not-allowed" : "bg-slate-900 border-red-900/70 focus:border-red-500"}`} />
                </div>
            )}

            <div className="flex items-center gap-2 mt-2.5 flex-wrap">
                {!readOnly && (a.status !== "validee" ? (
                    <button onClick={() => setStatus("validee")} disabled={saving} data-testid={`cam-validate-${a.uid}`}
                        className="h-8 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-colors">
                        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />} Valider
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`cam-reopen-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-slate-600 text-slate-300 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-700 transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Rouvrir
                    </button>
                ))}
                {!readOnly && (a.status !== "bloquee" ? (
                    <button onClick={() => setStatus("bloquee")} disabled={saving} data-testid={`cam-block-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-red-800 text-red-400 text-xs font-semibold flex items-center gap-1.5 hover:bg-red-950/50 transition-colors">
                        <Ban className="w-3.5 h-3.5" /> Bloquer
                    </button>
                ) : (
                    <button onClick={() => setStatus("a_faire")} disabled={saving} data-testid={`cam-unblock-${a.uid}`}
                        className="h-8 px-3 rounded-lg border border-slate-600 text-slate-300 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-700 transition-colors">
                        <RotateCcw className="w-3.5 h-3.5" /> Débloquer
                    </button>
                ))}
                {readOnly && (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${a.status === "validee" ? "bg-blue-600 text-white" : a.status === "bloquee" ? "bg-red-600 text-white" : "bg-slate-700 text-slate-200"}`}>
                        {a.status === "validee" ? "Validée" : a.status === "bloquee" ? "Bloquée" : "À faire"}
                    </span>
                )}
                <input value={comment} onChange={(e) => setComment(e.target.value)}
                    readOnly={readOnly}
                    onBlur={() => { if (comment !== (a.comment || "")) actions.patchCamAllee(a.uid, { comment }); }}
                    placeholder={readOnly && !comment ? "—" : "Commentaire"}
                    data-testid={`cam-comment-${a.uid}`}
                    className={`flex-1 min-w-[140px] h-8 px-2.5 rounded-lg border text-xs placeholder:text-slate-600 outline-none ${readOnly ? "bg-slate-950 border-slate-800 text-slate-400 cursor-not-allowed" : "bg-slate-900 border-slate-700 focus:border-sky-500"}`} />
            </div>
        </div>
    );
}
