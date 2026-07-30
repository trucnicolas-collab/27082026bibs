import React, { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, Save, PackagePlus, ArrowRight } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const BRAND = "#005BAB";
const key = (secteur, rayon, allee) =>
    allee != null && allee !== undefined
        ? `${secteur}|||${rayon}|||${allee}`
        : `${secteur}|||${rayon}`;

// Somme des SA à installer selon la config (utilisée aussi par PhasageTab).
export function computeSaToInstall(breakdown, cfg) {
    const res = { sa_15: 0, sa_21: 0, freezer: 0, sa_42: 0 };
    if (!cfg || !cfg.enabled || !breakdown) return res;
    const sel15 = new Set(cfg.selection?.sa_15 || []);
    const sel21 = new Set(cfg.selection?.sa_21 || []);
    for (const sec of breakdown) {
        for (const r of sec.rayons || []) {
            for (const a of r.allees || []) {
                const k = key(sec.secteur, r.rayon, a.allee);
                if (cfg.toutes) {
                    res.sa_15 += a.sa_15 || 0;
                    res.sa_21 += a.sa_21_std || 0;
                    res.freezer += a.sa_21_freezer || 0;
                    res.sa_42 += a.sa_42 || 0;
                } else {
                    if (cfg.sa_15 && sel15.has(k)) res.sa_15 += a.sa_15 || 0;
                    if (cfg.sa_21 && sel21.has(k)) res.sa_21 += a.sa_21_std || 0;
                    if (cfg.freezer) res.freezer += a.sa_21_freezer || 0;
                    if (cfg.sa_42) res.sa_42 += a.sa_42 || 0;
                }
            }
        }
    }
    return res;
}

// SA à installer POUR UNE ALLÉE (node) selon la config du panneau.
// Retourne { sa_15, sa_21, freezer } = quantités que NOUS posons en VT.
// La clé secteur|||rayon doit matcher le breakdown backend (défauts "(Sans …)").
export function computeNodeSaInstall(node, cfg) {
    const res = { sa_15: 0, sa_21: 0, freezer: 0, sa_42: 0 };
    if (!node) return res;
    // (v27+iter48i) Zones Saisonnières = SA installées par la VT (400 SA 1.5 + 1600 SA 2.1).
    // Chaque zone (ZS1/ZS2/ZS3) ET/OU chaque type (SA 1.5, SA 2.1) peut être
    // décoché individuellement via cfg.seasonal. Absence de config = retro-compat (tout coché).
    if (node.is_seasonal) {
        const zoneId = String(node.uid || node.allee || "");
        const seasonalCfg = cfg?.seasonal || {};
        const zonesCfg = seasonalCfg.zones || {};
        const allFlag = seasonalCfg.all !== false; // default true
        const zCfg = zonesCfg[zoneId] || {};
        const defaultTake = allFlag;
        const take15 = zCfg.sa_15 != null ? Boolean(zCfg.sa_15) : defaultTake;
        const take21 = zCfg.sa_21 != null ? Boolean(zCfg.sa_21) : defaultTake;
        return {
            sa_15: take15 ? (node.sa_15 || 0) : 0,
            sa_21: take21 ? (node.sa_21_std != null ? node.sa_21_std : (node.sa_21 || 0)) : 0,
            freezer: 0, sa_42: 0,
        };
    }
    if (!cfg || !cfg.enabled) return res;
    const n15 = node.sa_15 || 0;
    const n21 = node.sa_21_std != null
        ? node.sa_21_std
        : Math.max(0, (node.sa_21 || 0) - (node.sa_21_freezer || 0));
    const nfz = node.sa_21_freezer || 0;
    const n42 = node.sa_42 || 0;
    if (cfg.toutes) return { sa_15: n15, sa_21: n21, freezer: nfz, sa_42: n42 };
    const sec = node.secteur || "(Sans secteur)";
    const ray = node.rayon || "(Sans rayon)";
    const k = key(sec, ray, node.allee);
    const sel15 = new Set(cfg.selection?.sa_15 || []);
    const sel21 = new Set(cfg.selection?.sa_21 || []);
    if (cfg.sa_15 && sel15.has(k)) res.sa_15 = n15;
    if (cfg.sa_21 && sel21.has(k)) res.sa_21 = n21;
    if (cfg.freezer) res.freezer = nfz;
    if (cfg.sa_42) res.sa_42 = n42;
    return res;
}

// SA totales d'une allée (toutes variantes) — sert à calculer le reste "par le magasin".
export function nodeSaTotal(node) {
    if (!node) return 0;
    // (v27) ZS : SA total = sa_15 + sa_21 (posées par la VT)
    if (node.is_seasonal) {
        const s21 = node.sa_21_std != null ? node.sa_21_std : (node.sa_21 || 0);
        return (node.sa_15 || 0) + s21;
    }
    const n21 = node.sa_21_std != null
        ? node.sa_21_std
        : Math.max(0, (node.sa_21 || 0) - (node.sa_21_freezer || 0));
    return (node.sa_15 || 0) + n21 + (node.sa_21_freezer || 0) + (node.sa_42 || 0);
}

const fmt = (n) => (n || 0).toLocaleString("fr-FR");

// Toutes les clés secteur|||rayon|||allée ayant ce type de SA (> 0).
export function allKeysForField(breakdown, field) {
    const keys = [];
    for (const s of breakdown || []) {
        for (const r of s.rayons || []) {
            for (const a of r.allees || []) {
                if ((a[field] || 0) > 0) keys.push(key(s.secteur, r.rayon, a.allee));
            }
        }
    }
    return keys;
}

// Sélection en cascade secteur → rayon → allée pour un type de SA donné.
function CascadeSelect({ breakdown, field, selected, onChange }) {
    const [openSec, setOpenSec] = useState({});
    const [openRay, setOpenRay] = useState({});
    // Ne garder que les secteurs/rayons/allées ayant ce type de SA
    const sectors = useMemo(() =>
        (breakdown || [])
            .map((s) => ({
                ...s,
                rayons: (s.rayons || [])
                    .map((r) => ({ ...r, allees: (r.allees || []).filter((a) => (a[field] || 0) > 0) }))
                    .filter((r) => r.allees.length > 0),
            }))
            .filter((s) => s.rayons.length > 0)
    , [breakdown, field]);

    const selSet = useMemo(() => new Set(selected || []), [selected]);

    const rayonKeys = useCallback((sec, r) => r.allees.map((a) => key(sec.secteur, r.rayon, a.allee)), []);
    const sectorKeys = useCallback((sec) => sec.rayons.flatMap((r) => rayonKeys(sec, r)), [rayonKeys]);

    const toggleKeys = useCallback((keys, turnOn) => {
        const next = new Set(selSet);
        keys.forEach((k) => { if (turnOn) next.add(k); else next.delete(k); });
        onChange([...next]);
    }, [selSet, onChange]);

    if (sectors.length === 0) {
        return <div className="text-[11px] text-gray-400 italic pl-6 py-1">Aucune allée avec ce type de SA.</div>;
    }

    return (
        <div className="pl-6 py-1 space-y-1">
            {sectors.map((sec) => {
                const skeys = sectorKeys(sec);
                const sOn = skeys.filter((k) => selSet.has(k)).length;
                const sAll = sOn === skeys.length;
                const sSome = sOn > 0 && !sAll;
                const total = sec.rayons.reduce((acc, r) => acc + r.allees.reduce((x, a) => x + (a[field] || 0), 0), 0);
                const open = openSec[sec.secteur];
                return (
                    <div key={sec.secteur} className="text-xs">
                        <div className="flex items-center gap-1.5">
                            <button onClick={() => setOpenSec((p) => ({ ...p, [sec.secteur]: !open }))} className="text-gray-400 hover:text-gray-600">
                                {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                            </button>
                            <input
                                type="checkbox"
                                checked={sAll}
                                ref={(el) => { if (el) el.indeterminate = sSome; }}
                                onChange={() => toggleKeys(skeys, !sAll)}
                                className="w-3.5 h-3.5 accent-blue-700"
                                data-testid={`sa-sec-${field}-${sec.secteur}`}
                            />
                            <span className="font-medium text-gray-800">{sec.secteur}</span>
                            <span className="text-gray-400">({fmt(total)})</span>
                        </div>
                        {open && (
                            <div className="pl-7 mt-0.5 space-y-0.5">
                                {sec.rayons.map((r) => {
                                    const rkeys = rayonKeys(sec, r);
                                    const rOn = rkeys.filter((k) => selSet.has(k)).length;
                                    const rAll = rOn === rkeys.length;
                                    const rSome = rOn > 0 && !rAll;
                                    const rk = `${field}|${sec.secteur}|${r.rayon}`;
                                    const rOpen = openRay[rk];
                                    const rTotal = r.allees.reduce((x, a) => x + (a[field] || 0), 0);
                                    return (
                                        <div key={rk}>
                                            <div className="flex items-center gap-1.5 text-gray-700">
                                                <button
                                                    onClick={() => setOpenRay((p) => ({ ...p, [rk]: !rOpen }))}
                                                    className="text-gray-400 hover:text-gray-600"
                                                    data-testid={`sa-ray-toggle-${field}-${sec.secteur}-${r.rayon}`}
                                                >
                                                    {rOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                                                </button>
                                                <input
                                                    type="checkbox"
                                                    checked={rAll}
                                                    ref={(el) => { if (el) el.indeterminate = rSome; }}
                                                    onChange={() => toggleKeys(rkeys, !rAll)}
                                                    className="w-3.5 h-3.5 accent-blue-700"
                                                    data-testid={`sa-ray-${field}-${sec.secteur}-${r.rayon}`}
                                                />
                                                <span>{r.rayon}</span>
                                                <span className="text-gray-400">({fmt(rTotal)})</span>
                                            </div>
                                            {rOpen && (
                                                <div className="pl-8 mt-0.5 flex flex-wrap gap-x-3 gap-y-1">
                                                    {r.allees.map((a, i) => {
                                                        const ak = key(sec.secteur, r.rayon, a.allee);
                                                        return (
                                                            <label
                                                                key={`${a.allee}-${i}`}
                                                                className="flex items-center gap-1 cursor-pointer text-[11px] text-gray-600"
                                                            >
                                                                <input
                                                                    type="checkbox"
                                                                    checked={selSet.has(ak)}
                                                                    onChange={() => toggleKeys([ak], !selSet.has(ak))}
                                                                    className="w-3 h-3 accent-blue-700"
                                                                    data-testid={`sa-allee-${field}-${sec.secteur}-${r.rayon}-${a.allee}`}
                                                                />
                                                                Allée {a.allee || "—"} <span className="text-gray-400">({fmt(a[field] || 0)})</span>
                                                            </label>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

export default function SaInstallPanel({ uploadId, breakdown, seasonalZones, initialConfig, onSaved, mode = "inline", onContinue }) {
    const isIntro = mode === "intro";
    const [cfg, setCfg] = useState(() => {
        const ic = initialConfig || {};
        return {
            enabled: false, toutes: false, sa_15: false, sa_21: false, freezer: false, sa_42: false, answered: false,
            ...ic,
            selection: { sa_15: [], sa_21: [], ...(ic.selection || {}) },
            // (iter48i) Config zones saisonnières — défaut = tout coché (retro-compat)
            seasonal: {
                all: true,
                zones: {},
                ...(ic.seasonal || {}),
            },
        };
    });
    const [saving, setSaving] = useState(false);
    const [collapsed, setCollapsed] = useState(true);
    // En mode intro : l'utilisateur doit répondre Oui/Non avant de continuer.
    const [answered, setAnswered] = useState(() => !!(initialConfig && initialConfig.answered));

    useEffect(() => {
        if (initialConfig) {
            setCfg((prev) => ({
                ...prev, ...initialConfig,
                selection: { sa_15: [], sa_21: [], ...(initialConfig.selection || {}) },
            }));
            if (initialConfig.enabled) setCollapsed(false);
            if (initialConfig.answered) setAnswered(true);
        }
    }, [initialConfig]);

    const totals = useMemo(() => computeSaToInstall(breakdown, cfg), [breakdown, cfg]);
    const grandTotal = totals.sa_15 + totals.sa_21 + totals.freezer + totals.sa_42;

    const set = (patch) => setCfg((p) => ({ ...p, ...patch }));

    const buildPayload = (markAnswered) => ({
        enabled: cfg.enabled,
        toutes: cfg.enabled && cfg.toutes,
        sa_15: cfg.enabled && !cfg.toutes && cfg.sa_15,
        sa_21: cfg.enabled && !cfg.toutes && cfg.sa_21,
        freezer: cfg.enabled && (cfg.toutes ? false : cfg.freezer),
        sa_42: cfg.enabled && (cfg.toutes ? false : cfg.sa_42),
        selection: { sa_15: cfg.selection?.sa_15 || [], sa_21: cfg.selection?.sa_21 || [] },
        answered: markAnswered || !!cfg.answered,
    });

    const save = useCallback(async () => {
        setSaving(true);
        try {
            const payload = buildPayload(false);
            const res = await axios.patch(`${API}/dataset/${uploadId}/sa-install`, payload);
            toast.success("Configuration SA enregistrée");
            if (onSaved) onSaved(res.data.sa_install);
        } catch (err) {
            toast.error(err.response?.data?.detail || "Échec de l'enregistrement");
        } finally {
            setSaving(false);
        }
    }, [cfg, uploadId, onSaved]);

    // Intro : enregistre (answered=true) puis passe au phasage.
    const saveAndContinue = useCallback(async () => {
        setSaving(true);
        try {
            const res = await axios.patch(`${API}/dataset/${uploadId}/sa-install`, buildPayload(true));
            if (onSaved) onSaved(res.data.sa_install);
            if (onContinue) onContinue(res.data.sa_install);
        } catch (err) {
            toast.error(err.response?.data?.detail || "Échec de l'enregistrement");
        } finally {
            setSaving(false);
        }
    }, [cfg, uploadId, onSaved, onContinue]);

    // (iter48i) Helpers pour la config des zones saisonnières
    const zoneCfgFor = (zid) => (cfg.seasonal?.zones || {})[zid] || {};
    const zoneTake = (zid, field) => {
        const z = zoneCfgFor(zid);
        if (z[field] != null) return Boolean(z[field]);
        return cfg.seasonal?.all !== false;
    };
    const setZoneField = (zid, field, val) => {
        setCfg((p) => {
            const zones = { ...(p.seasonal?.zones || {}) };
            zones[zid] = { ...(zones[zid] || {}), [field]: val };
            return { ...p, seasonal: { ...(p.seasonal || {}), zones } };
        });
    };
    const setAllZones = (checked) => {
        // Case globale : reset zones (utilise all=checked comme défaut partout)
        setCfg((p) => ({ ...p, seasonal: { all: checked, zones: {} } }));
    };
    const seasonalAllOn = !seasonalZones || seasonalZones.length === 0
        ? true
        : seasonalZones.every((z) => zoneTake(z.id, "sa_15") && zoneTake(z.id, "sa_21"));
    const seasonalAllOff = seasonalZones && seasonalZones.length > 0
        && seasonalZones.every((z) => !zoneTake(z.id, "sa_15") && !zoneTake(z.id, "sa_21"));
    const seasonalSome = !seasonalAllOn && !seasonalAllOff;

    // ── Contenu commun (question Oui/Non + sélection) ──────────────────────
    const questionBlock = (
        <div className={isIntro ? "space-y-4" : "px-4 pb-3 space-y-3"}>
            {/* (iter48i) Bloc Zones Saisonnières — toujours visible avant la question */}
            {seasonalZones && seasonalZones.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 space-y-2" data-testid="sa-seasonal-block">
                    <label className="flex items-center gap-2 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={seasonalAllOn}
                            ref={(el) => { if (el) el.indeterminate = seasonalSome; }}
                            onChange={(e) => setAllZones(e.target.checked)}
                            className="w-4 h-4 accent-amber-600"
                            data-testid="sa-seasonal-all"
                        />
                        <span className="text-sm font-semibold text-gray-800">Zone(s) saisonnière(s) — posée(s) par la VT</span>
                        <span className="text-[11px] text-gray-500">Décochez pour laisser le magasin poser</span>
                    </label>
                    <div className="pl-6 grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                        {seasonalZones.map((z) => {
                            const t15 = zoneTake(z.id, "sa_15");
                            const t21 = zoneTake(z.id, "sa_21");
                            return (
                                <div key={z.id} className="flex items-center gap-3 text-[12px] text-gray-700 bg-white/70 rounded px-2 py-1 border border-amber-100" data-testid={`sa-seasonal-zone-${z.id}`}>
                                    <span className="font-semibold text-gray-800 w-14">{z.id}</span>
                                    <label className="flex items-center gap-1 cursor-pointer">
                                        <input type="checkbox" checked={t15}
                                            onChange={(e) => setZoneField(z.id, "sa_15", e.target.checked)}
                                            className="w-3.5 h-3.5 accent-amber-600"
                                            data-testid={`sa-seasonal-zone-${z.id}-15`} />
                                        SA 1.5 <span className="text-gray-400">({fmt(z.sa_15 || 0)})</span>
                                    </label>
                                    <label className="flex items-center gap-1 cursor-pointer">
                                        <input type="checkbox" checked={t21}
                                            onChange={(e) => setZoneField(z.id, "sa_21", e.target.checked)}
                                            className="w-3.5 h-3.5 accent-amber-600"
                                            data-testid={`sa-seasonal-zone-${z.id}-21`} />
                                        SA 2.1 <span className="text-gray-400">({fmt(z.sa_21 || 0)})</span>
                                    </label>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            <div className="flex items-center gap-4 flex-wrap">
                <span className={isIntro ? "text-base font-medium text-gray-800" : "text-sm text-gray-700"}>
                    Devez-vous installer des EEG SA autres que celles de la zone saisonnière ?
                </span>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => { set({ enabled: true }); setAnswered(true); }}
                        className="px-3 py-1 text-xs font-medium rounded-md border transition-colors"
                        style={cfg.enabled ? { backgroundColor: BRAND, borderColor: BRAND, color: "#fff" } : { borderColor: "#d1d5db", color: "#6b7280" }}
                        data-testid="sa-enabled-oui"
                    >Oui</button>
                    <button
                        onClick={() => { set({ enabled: false }); setAnswered(true); }}
                        className="px-3 py-1 text-xs font-medium rounded-md border transition-colors"
                        style={!cfg.enabled && answered ? { backgroundColor: "#374151", borderColor: "#374151", color: "#fff" } : { borderColor: "#d1d5db", color: "#6b7280" }}
                        data-testid="sa-enabled-non"
                    >Non</button>
                </div>
            </div>

            {cfg.enabled && (
                <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-4 text-sm">
                        <label className="flex items-center gap-1.5 cursor-pointer">
                            <input type="checkbox" checked={cfg.toutes} onChange={(e) => set({ toutes: e.target.checked })} className="w-4 h-4 accent-blue-700" data-testid="sa-type-toutes" />
                            <span className="font-medium">Toutes</span>
                        </label>
                        <label className={`flex items-center gap-1.5 ${cfg.toutes ? "opacity-40" : "cursor-pointer"}`}>
                            <input type="checkbox" disabled={cfg.toutes} checked={cfg.sa_15} onChange={(e) => {
                                const checked = e.target.checked;
                                setCfg((p) => ({ ...p, sa_15: checked, selection: { ...p.selection, sa_15: checked ? allKeysForField(breakdown, "sa_15") : [] } }));
                            }} className="w-4 h-4 accent-blue-700" data-testid="sa-type-15" />
                            <span>SA 1.5</span>
                        </label>
                        <label className={`flex items-center gap-1.5 ${cfg.toutes ? "opacity-40" : "cursor-pointer"}`}>
                            <input type="checkbox" disabled={cfg.toutes} checked={cfg.sa_21} onChange={(e) => {
                                const checked = e.target.checked;
                                setCfg((p) => ({ ...p, sa_21: checked, selection: { ...p.selection, sa_21: checked ? allKeysForField(breakdown, "sa_21_std") : [] } }));
                            }} className="w-4 h-4 accent-blue-700" data-testid="sa-type-21" />
                            <span>SA 2.1</span>
                        </label>
                        <label className={`flex items-center gap-1.5 ${cfg.toutes ? "opacity-40" : "cursor-pointer"}`}>
                            <input type="checkbox" disabled={cfg.toutes} checked={cfg.freezer} onChange={(e) => set({ freezer: e.target.checked })} className="w-4 h-4 accent-blue-700" data-testid="sa-type-freezer" />
                            <span>Freezer (SA 2.1)</span>
                        </label>
                        <label className={`flex items-center gap-1.5 ${cfg.toutes ? "opacity-40" : "cursor-pointer"}`}>
                            <input type="checkbox" disabled={cfg.toutes} checked={cfg.sa_42} onChange={(e) => set({ sa_42: e.target.checked })} className="w-4 h-4 accent-blue-700" data-testid="sa-type-42" />
                            <span>4.2/4.2 WP</span>
                        </label>
                    </div>

                    {!cfg.toutes && cfg.sa_15 && (
                        <div>
                            <div className="text-xs font-semibold text-gray-600 mt-1">SA 1.5 — sélection par secteur / rayon</div>
                            <CascadeSelect breakdown={breakdown} field="sa_15" selected={cfg.selection?.sa_15} onChange={(sel) => setCfg((p) => ({ ...p, selection: { ...p.selection, sa_15: sel } }))} />
                        </div>
                    )}
                    {!cfg.toutes && cfg.sa_21 && (
                        <div>
                            <div className="text-xs font-semibold text-gray-600 mt-1">SA 2.1 — sélection par secteur / rayon</div>
                            <CascadeSelect breakdown={breakdown} field="sa_21_std" selected={cfg.selection?.sa_21} onChange={(sel) => setCfg((p) => ({ ...p, selection: { ...p.selection, sa_21: sel } }))} />
                        </div>
                    )}
                    {!cfg.toutes && cfg.freezer && (
                        <div className="text-[11px] text-gray-500 pl-6">Toutes les SA 2.1 Freezer seront ajoutées ({fmt(totals.freezer)}).</div>
                    )}
                    {!cfg.toutes && cfg.sa_42 && (
                        <div className="text-[11px] text-gray-500 pl-6">Toutes les 4.2/4.2 WP seront ajoutées ({fmt(totals.sa_42)}).</div>
                    )}

                    <div className="text-xs text-gray-600 pt-1">
                        À installer : <b>SA 1.5</b> {fmt(totals.sa_15)} · <b>SA 2.1</b> {fmt(totals.sa_21)} · <b>Freezer</b> {fmt(totals.freezer)} · <b>4.2/4.2 WP</b> {fmt(totals.sa_42)}
                        <span className="ml-2 font-semibold" style={{ color: BRAND }}>= +{fmt(grandTotal)} EEG</span>
                    </div>
                </div>
            )}
        </div>
    );

    // ── Mode INTRO : écran plein, question puis « Continuer vers le phasage » ─
    if (isIntro) {
        return (
            <div className="flex-1 overflow-auto bg-gray-50 p-8" data-testid="sa-install-intro">
                <div className="max-w-2xl mx-auto bg-white border border-gray-200 rounded-xl shadow-sm p-6 space-y-5 eeg-fade-in">
                    <div className="flex items-center gap-2">
                        <PackagePlus className="w-5 h-5" style={{ color: BRAND }} />
                        <h2 className="text-lg font-semibold text-gray-900">Étiquettes SA à poser</h2>
                    </div>
                    <p className="text-sm text-gray-500 -mt-2">
                        Avant de construire le phasage, indiquez les EEG SA à installer (hors zone saisonnière).
                    </p>
                    {questionBlock}
                    <div className="flex items-center justify-end gap-3 pt-2 border-t border-gray-100">
                        {!answered && (
                            <span className="text-xs text-amber-600 mr-auto">Répondez Oui ou Non pour continuer.</span>
                        )}
                        <button
                            onClick={saveAndContinue}
                            disabled={!answered || saving}
                            className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold text-white rounded-md disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition-all"
                            style={{ backgroundColor: BRAND }}
                            data-testid="sa-intro-continue"
                        >
                            {saving ? "Enregistrement…" : "Continuer vers le phasage"}
                            <ArrowRight className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // ── Mode INLINE (existant) : bandeau repliable ─────────────────────────
    return (
        <div className="border-b border-gray-200 bg-blue-50/30 flex-shrink-0" data-testid="sa-install-panel">
            <button
                onClick={() => setCollapsed((c) => !c)}
                className="w-full flex items-center gap-2 px-3 py-2 text-left"
                data-testid="sa-install-toggle"
            >
                <PackagePlus className="w-4 h-4" style={{ color: BRAND }} />
                <span className="text-sm font-semibold text-gray-800">Installer des EEG SA (hors zone saisonnière)</span>
                {cfg.enabled && grandTotal > 0 && (
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full text-white" style={{ backgroundColor: BRAND }}>
                        +{fmt(grandTotal)} EEG SA
                    </span>
                )}
                {collapsed ? <ChevronRight className="w-4 h-4 text-gray-400 ml-auto" /> : <ChevronDown className="w-4 h-4 text-gray-400 ml-auto" />}
            </button>

            {!collapsed && (
                <>
                    {questionBlock}
                    <div className="px-4 pb-3 flex items-center">
                        <button
                            onClick={save}
                            disabled={saving}
                            className="ml-auto flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-white rounded-md disabled:opacity-50"
                            style={{ backgroundColor: BRAND }}
                            data-testid="sa-install-save"
                        >
                            <Save className="w-3.5 h-3.5" /> {saving ? "Enregistrement…" : "Enregistrer"}
                        </button>
                    </div>
                </>
            )}
        </div>
    );
}
