import React, { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, Save, PackagePlus } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const BRAND = "#056839";
const key = (secteur, rayon) => `${secteur}|||${rayon}`;

// Somme des SA à installer selon la config (utilisée aussi par PhasageTab).
export function computeSaToInstall(breakdown, cfg) {
    const res = { sa_15: 0, sa_21: 0, freezer: 0 };
    if (!cfg || !cfg.enabled || !breakdown) return res;
    const sel15 = cfg.selection?.sa_15 || [];
    const sel21 = cfg.selection?.sa_21 || [];
    for (const sec of breakdown) {
        for (const r of sec.rayons || []) {
            const k = key(sec.secteur, r.rayon);
            if (cfg.toutes) {
                res.sa_15 += r.sa_15 || 0;
                res.sa_21 += r.sa_21_std || 0;
                res.freezer += r.sa_21_freezer || 0;
            } else {
                if (cfg.sa_15 && sel15.includes(k)) res.sa_15 += r.sa_15 || 0;
                if (cfg.sa_21 && sel21.includes(k)) res.sa_21 += r.sa_21_std || 0;
                if (cfg.freezer) res.freezer += r.sa_21_freezer || 0;
            }
        }
    }
    return res;
}

const fmt = (n) => (n || 0).toLocaleString("fr-FR");

// Sélection en cascade secteur → rayon pour un type de SA donné.
function CascadeSelect({ breakdown, field, selected, onChange }) {
    const [openSec, setOpenSec] = useState({});
    // Ne garder que les secteurs/rayons ayant ce type de SA
    const sectors = useMemo(() =>
        (breakdown || [])
            .map((s) => ({ ...s, rayons: (s.rayons || []).filter((r) => (r[field] || 0) > 0) }))
            .filter((s) => s.rayons.length > 0)
    , [breakdown, field]);

    const selSet = useMemo(() => new Set(selected || []), [selected]);

    const toggleRayon = useCallback((k) => {
        const next = new Set(selSet);
        if (next.has(k)) next.delete(k); else next.add(k);
        onChange([...next]);
    }, [selSet, onChange]);

    const toggleSecteur = useCallback((sec) => {
        const keys = sec.rayons.map((r) => key(sec.secteur, r.rayon));
        const allOn = keys.every((k) => selSet.has(k));
        const next = new Set(selSet);
        keys.forEach((k) => { if (allOn) next.delete(k); else next.add(k); });
        onChange([...next]);
    }, [selSet, onChange]);

    if (sectors.length === 0) {
        return <div className="text-[11px] text-gray-400 italic pl-6 py-1">Aucun rayon avec ce type de SA.</div>;
    }

    return (
        <div className="pl-6 py-1 space-y-1">
            {sectors.map((sec) => {
                const keys = sec.rayons.map((r) => key(sec.secteur, r.rayon));
                const on = keys.filter((k) => selSet.has(k)).length;
                const allOn = on === keys.length;
                const someOn = on > 0 && !allOn;
                const total = sec.rayons.reduce((a, r) => a + (r[field] || 0), 0);
                const open = openSec[sec.secteur];
                return (
                    <div key={sec.secteur} className="text-xs">
                        <div className="flex items-center gap-1.5">
                            <button onClick={() => setOpenSec((p) => ({ ...p, [sec.secteur]: !open }))} className="text-gray-400 hover:text-gray-600">
                                {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                            </button>
                            <input
                                type="checkbox"
                                checked={allOn}
                                ref={(el) => { if (el) el.indeterminate = someOn; }}
                                onChange={() => toggleSecteur(sec)}
                                className="w-3.5 h-3.5 accent-emerald-700"
                                data-testid={`sa-sec-${field}-${sec.secteur}`}
                            />
                            <span className="font-medium text-gray-800">{sec.secteur}</span>
                            <span className="text-gray-400">({fmt(total)})</span>
                        </div>
                        {open && (
                            <div className="pl-7 mt-0.5 space-y-0.5">
                                {sec.rayons.map((r) => {
                                    const k = key(sec.secteur, r.rayon);
                                    return (
                                        <label key={k} className="flex items-center gap-1.5 text-gray-700 cursor-pointer">
                                            <input
                                                type="checkbox"
                                                checked={selSet.has(k)}
                                                onChange={() => toggleRayon(k)}
                                                className="w-3.5 h-3.5 accent-emerald-700"
                                                data-testid={`sa-ray-${field}-${sec.secteur}-${r.rayon}`}
                                            />
                                            <span>{r.rayon}</span>
                                            <span className="text-gray-400">({fmt(r[field] || 0)})</span>
                                        </label>
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

export default function SaInstallPanel({ uploadId, breakdown, initialConfig, onSaved }) {
    const [cfg, setCfg] = useState(() => {
        const ic = initialConfig || {};
        return {
            enabled: false, toutes: false, sa_15: false, sa_21: false, freezer: false,
            ...ic,
            selection: { sa_15: [], sa_21: [], ...(ic.selection || {}) },
        };
    });
    const [saving, setSaving] = useState(false);
    const [collapsed, setCollapsed] = useState(true);

    useEffect(() => {
        if (initialConfig) {
            setCfg((prev) => ({
                ...prev, ...initialConfig,
                selection: { sa_15: [], sa_21: [], ...(initialConfig.selection || {}) },
            }));
            if (initialConfig.enabled) setCollapsed(false);
        }
    }, [initialConfig]);

    const totals = useMemo(() => computeSaToInstall(breakdown, cfg), [breakdown, cfg]);
    const grandTotal = totals.sa_15 + totals.sa_21 + totals.freezer;

    const set = (patch) => setCfg((p) => ({ ...p, ...patch }));

    const save = useCallback(async () => {
        setSaving(true);
        try {
            const payload = {
                enabled: cfg.enabled,
                toutes: cfg.enabled && cfg.toutes,
                sa_15: cfg.enabled && !cfg.toutes && cfg.sa_15,
                sa_21: cfg.enabled && !cfg.toutes && cfg.sa_21,
                freezer: cfg.enabled && (cfg.toutes ? false : cfg.freezer),
                selection: { sa_15: cfg.selection?.sa_15 || [], sa_21: cfg.selection?.sa_21 || [] },
            };
            const res = await axios.patch(`${API}/dataset/${uploadId}/sa-install`, payload);
            toast.success("Configuration SA enregistrée");
            if (onSaved) onSaved(res.data.sa_install);
        } catch (err) {
            toast.error(err.response?.data?.detail || "Échec de l'enregistrement");
        } finally {
            setSaving(false);
        }
    }, [cfg, uploadId, onSaved]);

    return (
        <div className="border-b border-gray-200 bg-emerald-50/30 flex-shrink-0" data-testid="sa-install-panel">
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
                <div className="px-4 pb-3 space-y-3">
                    <div className="flex items-center gap-4">
                        <span className="text-sm text-gray-700">Devez-vous installer des EEG SA autres que celles de la zone saisonnière ?</span>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => set({ enabled: true })}
                                className="px-3 py-1 text-xs font-medium rounded-md border"
                                style={cfg.enabled ? { backgroundColor: BRAND, borderColor: BRAND, color: "#fff" } : { borderColor: "#d1d5db", color: "#6b7280" }}
                                data-testid="sa-enabled-oui"
                            >Oui</button>
                            <button
                                onClick={() => set({ enabled: false })}
                                className="px-3 py-1 text-xs font-medium rounded-md border"
                                style={!cfg.enabled ? { backgroundColor: "#374151", borderColor: "#374151", color: "#fff" } : { borderColor: "#d1d5db", color: "#6b7280" }}
                                data-testid="sa-enabled-non"
                            >Non</button>
                        </div>
                    </div>

                    {cfg.enabled && (
                        <div className="space-y-2">
                            <div className="flex flex-wrap items-center gap-4 text-sm">
                                <label className="flex items-center gap-1.5 cursor-pointer">
                                    <input type="checkbox" checked={cfg.toutes} onChange={(e) => set({ toutes: e.target.checked })} className="w-4 h-4 accent-emerald-700" data-testid="sa-type-toutes" />
                                    <span className="font-medium">Toutes</span>
                                </label>
                                <label className={`flex items-center gap-1.5 ${cfg.toutes ? "opacity-40" : "cursor-pointer"}`}>
                                    <input type="checkbox" disabled={cfg.toutes} checked={cfg.sa_15} onChange={(e) => set({ sa_15: e.target.checked })} className="w-4 h-4 accent-emerald-700" data-testid="sa-type-15" />
                                    <span>SA 1.5</span>
                                </label>
                                <label className={`flex items-center gap-1.5 ${cfg.toutes ? "opacity-40" : "cursor-pointer"}`}>
                                    <input type="checkbox" disabled={cfg.toutes} checked={cfg.sa_21} onChange={(e) => set({ sa_21: e.target.checked })} className="w-4 h-4 accent-emerald-700" data-testid="sa-type-21" />
                                    <span>SA 2.1</span>
                                </label>
                                <label className={`flex items-center gap-1.5 ${cfg.toutes ? "opacity-40" : "cursor-pointer"}`}>
                                    <input type="checkbox" disabled={cfg.toutes} checked={cfg.freezer} onChange={(e) => set({ freezer: e.target.checked })} className="w-4 h-4 accent-emerald-700" data-testid="sa-type-freezer" />
                                    <span>Freezer (SA 2.1)</span>
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

                            <div className="flex items-center gap-3 pt-1">
                                <div className="text-xs text-gray-600">
                                    À installer : <b>SA 1.5</b> {fmt(totals.sa_15)} · <b>SA 2.1</b> {fmt(totals.sa_21)} · <b>Freezer</b> {fmt(totals.freezer)}
                                    <span className="ml-2 font-semibold" style={{ color: BRAND }}>= +{fmt(grandTotal)} EEG</span>
                                </div>
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
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
