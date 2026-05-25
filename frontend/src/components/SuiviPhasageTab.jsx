import React, { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { Download } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function fmt(n) {
    if (n == null || n === "") return "";
    if (typeof n === "number") return n.toLocaleString("fr-FR");
    return n;
}

const NIGHT_COLORS = [
    { bg: "#FEF3C7", border: "#FCD34D" },
    { bg: "#DBEAFE", border: "#93C5FD" },
    { bg: "#D1FAE5", border: "#6EE7B7" },
    { bg: "#FCE7F3", border: "#F9A8D4" },
    { bg: "#E0E7FF", border: "#A5B4FC" },
    { bg: "#FED7AA", border: "#FDBA74" },
    { bg: "#CCFBF1", border: "#5EEAD4" },
    { bg: "#FAE8FF", border: "#E9D5FF" },
    { bg: "#FFE4E6", border: "#FDA4AF" },
    { bg: "#ECFCCB", border: "#BEF264" },
];
const nightColor = (n) => (!n ? null : NIGHT_COLORS[(n - 1) % NIGHT_COLORS.length]);

export default function SuiviPhasageTab({ uploadId }) {
    const [summary, setSummary] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [suivi, setSuivi] = useState({}); // {nuit: {es_reel, cam_reel, rails_geoloc}}
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!uploadId) return;
        let mounted = true;
        setLoading(true);
        axios.get(`${API}/dataset/${uploadId}/phasage-summary`)
            .then((res) => {
                if (!mounted) return;
                setSummary(res.data);
                const ph = res.data.phasage || {};
                const s = ph.suivi || { rows: [] };
                const idx = {};
                (s.rows || []).forEach((r) => {
                    if (r.nuit != null) idx[Number(r.nuit)] = {
                        es_reel: r.es_reel ?? "",
                        cam_reel: r.cam_reel ?? "",
                        rails_geoloc: r.rails_geoloc ?? "",
                    };
                });
                setSuivi(idx);
            })
            .catch((e) => mounted && setError(e.message))
            .finally(() => mounted && setLoading(false));
        return () => { mounted = false; };
    }, [uploadId]);

    // Consolidé local (même logique que PhasageFullTab)
    const consolidated = useMemo(() => {
        if (!summary) return [];
        const ph = summary.phasage || {};
        const es = ph.es || { rows: [] };
        const cam = ph.cam || { rows: [], start_at_nuit: 5 };
        const startAt = cam.start_at_nuit || 5;
        const idx = {};
        (summary.allees || []).forEach((a) => { idx[String(a.allee)] = a; });
        const nuits = {};
        (es.rows || []).forEach((r) => {
            const n = r.nuit, a = String(r.allee || "").trim();
            if (!n || !a) return;
            const node = idx[a]; if (!node) return;
            const gn = Number(n);
            if (!nuits[gn]) nuits[gn] = { type: "ES", allees: new Set(), es: 0, cam: 0 };
            nuits[gn].allees.add(a);
            nuits[gn].es += (node.es_15 || 0) + (node.es_21 || 0);
        });
        (cam.rows || []).forEach((r) => {
            const n = r.nuit, a = String(r.allee || "").trim();
            if (!n || !a) return;
            const node = idx[a]; if (!node) return;
            const gn = startAt + Number(n) - 1;
            if (!nuits[gn]) {
                nuits[gn] = { type: "Caméras", allees: new Set(), es: 0, cam: 0 };
            } else if (nuits[gn].es > 0) {
                nuits[gn].type = "Mixte";
            }
            nuits[gn].allees.add(a);
            nuits[gn].cam += (node.cameras || 0);
        });
        const orderIndex = new Map();
        (summary.allees || []).forEach((a, i) => orderIndex.set(String(a.allee), i));
        const sortedKeys = Object.keys(nuits).map(Number).sort((a, b) => a - b);
        return sortedKeys.map((gn) => ({
            nuit: gn,
            type: nuits[gn].type,
            allees: Array.from(nuits[gn].allees).sort((a, b) => (orderIndex.get(a) ?? 9999) - (orderIndex.get(b) ?? 9999)),
            es: Math.round(nuits[gn].es),
            cam: Math.round(nuits[gn].cam),
        }));
    }, [summary]);

    // Auto-save
    useEffect(() => {
        if (!summary || !uploadId) return;
        const t = setTimeout(() => {
            setSaving(true);
            const ph = summary.phasage || {};
            const rows = Object.entries(suivi).map(([nuit, v]) => ({
                nuit: Number(nuit),
                es_reel: v.es_reel === "" ? null : Number(v.es_reel),
                cam_reel: v.cam_reel === "" ? null : Number(v.cam_reel),
                rails_geoloc: v.rails_geoloc === "" ? null : Number(v.rails_geoloc),
            }));
            axios.patch(`${API}/dataset/${uploadId}/phasage`, {
                es: ph.es || { nb_nuits: 3, rows: [] },
                cam: ph.cam || { nb_nuits: 3, rows: [], start_at_nuit: 5 },
                suivi: { rows },
            }).catch((e) => console.error("Save suivi failed:", e))
              .finally(() => setSaving(false));
        }, 600);
        return () => clearTimeout(t);
    }, [suivi, uploadId, summary]);

    const updateSuivi = useCallback((nuit, key, value) => {
        setSuivi((prev) => ({
            ...prev,
            [nuit]: { ...(prev[nuit] || { es_reel: "", cam_reel: "", rails_geoloc: "" }), [key]: value },
        }));
    }, []);

    const toNum = (v) => (v === "" || v == null ? null : Number(v));
    const diff = (reel, prevu) => {
        const r = toNum(reel);
        if (r == null) return null;
        return r - prevu;
    };

    const totals = useMemo(() => {
        let es = 0, cam = 0, esReel = 0, camReel = 0, rails = 0;
        consolidated.forEach((r) => {
            es += r.es; cam += r.cam;
            const sv = suivi[r.nuit] || {};
            esReel += Number(sv.es_reel) || 0;
            camReel += Number(sv.cam_reel) || 0;
            rails += Number(sv.rails_geoloc) || 0;
        });
        return { es, cam, esReel, camReel, rails };
    }, [consolidated, suivi]);

    const handleExport = () => {
        window.location.href = `${API}/export/${uploadId}?sheet=suivi`;
    };

    if (loading) return <div className="p-8 text-sm text-gray-500" data-testid="suivi-loading">Chargement…</div>;
    if (error) return <div className="p-8 text-sm text-red-600">Erreur : {error}</div>;
    if (!summary) return null;

    return (
        <div className="h-full flex flex-col bg-white" data-testid="suivi-phasage-tab">
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-3 bg-cyan-50/40 flex-shrink-0">
                <h2 className="text-sm font-semibold text-gray-800">Suivi phasage — Prévu vs Réalité</h2>
                <span className="text-[11px] italic text-gray-500">
                    Saisis les nombres réellement posés ; la différence se calcule automatiquement.
                </span>
                <button
                    onClick={handleExport}
                    data-testid="suivi-export"
                    className="ml-auto h-7 px-2.5 text-xs font-medium bg-cyan-700 text-white rounded hover:bg-cyan-800 flex items-center gap-1.5"
                >
                    <Download className="w-3.5 h-3.5" /> Exporter cette vue
                </button>
                {saving && <span className="text-xs text-gray-500">Sauvegarde…</span>}
            </div>

            <div className="flex-1 overflow-auto custom-scroll p-3">
                <div className="border border-gray-200 rounded overflow-hidden">
                    <table className="w-full text-xs">
                        <thead className="bg-gray-50 text-gray-700 sticky top-0">
                            <tr>
                                <th rowSpan={2} className="px-2 py-1.5 text-left font-semibold border-b">Nuit</th>
                                <th rowSpan={2} className="px-2 py-1.5 text-left font-semibold border-b">Type</th>
                                <th rowSpan={2} className="px-2 py-1.5 text-left font-semibold border-b">Allées</th>
                                <th colSpan={3} className="px-2 py-1 text-center font-semibold bg-emerald-50 border-l border-b">ES</th>
                                <th colSpan={3} className="px-2 py-1 text-center font-semibold bg-purple-50 border-l border-b">Caméras</th>
                                <th rowSpan={2} className="px-2 py-1.5 text-right font-semibold border-l border-b bg-amber-50">Rails ES géoloc.</th>
                            </tr>
                            <tr>
                                <th className="px-2 py-1 text-right font-semibold bg-emerald-50 border-l">Prévu</th>
                                <th className="px-2 py-1 text-right font-semibold bg-emerald-50">Réel</th>
                                <th className="px-2 py-1 text-right font-semibold bg-emerald-50">Diff</th>
                                <th className="px-2 py-1 text-right font-semibold bg-purple-50 border-l">Prévue</th>
                                <th className="px-2 py-1 text-right font-semibold bg-purple-50">Réelle</th>
                                <th className="px-2 py-1 text-right font-semibold bg-purple-50">Diff</th>
                            </tr>
                        </thead>
                        <tbody>
                            {consolidated.length === 0 && (
                                <tr><td colSpan={10} className="px-3 py-8 text-center text-gray-500 italic">
                                    Aucune nuit planifiée. Renseigne « Phasage de pose » ou « Phasage caméras » d'abord.
                                </td></tr>
                            )}
                            {consolidated.map((r) => {
                                const sv = suivi[r.nuit] || { es_reel: "", cam_reel: "", rails_geoloc: "" };
                                const color = nightColor(r.nuit);
                                const dEs = diff(sv.es_reel, r.es);
                                const dCam = diff(sv.cam_reel, r.cam);
                                const diffColor = (v) => {
                                    if (v == null) return "text-gray-400";
                                    if (v > 0) return "text-emerald-700";
                                    if (v < 0) return "text-red-700";
                                    return "text-gray-700";
                                };
                                return (
                                    <tr key={r.nuit} className="border-t border-gray-100"
                                        style={color ? { backgroundColor: color.bg, borderLeft: `4px solid ${color.border}` } : {}}
                                        data-testid={`suivi-nuit-${r.nuit}`}>
                                        <td className="px-2 py-1 font-medium text-gray-900">Nuit {r.nuit}</td>
                                        <td className="px-2 py-1 text-gray-700 text-[11px]">{r.type}</td>
                                        <td className="px-2 py-1 font-mono-data text-gray-700 text-[11px] max-w-[200px] truncate" title={r.allees.join(", ")}>
                                            {r.allees.join(", ")}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data text-gray-700">{r.es > 0 ? fmt(r.es) : "—"}</td>
                                        <td className="px-1 py-1">
                                            <input
                                                type="number"
                                                value={sv.es_reel}
                                                onChange={(e) => updateSuivi(r.nuit, "es_reel", e.target.value)}
                                                data-testid={`suivi-es-reel-${r.nuit}`}
                                                className="w-20 h-6 px-1 text-xs border border-yellow-300 bg-yellow-50 rounded text-right font-mono-data focus:ring-1 focus:ring-yellow-500 outline-none"
                                            />
                                        </td>
                                        <td className={`px-2 py-1 text-right font-mono-data font-bold ${diffColor(dEs)}`} data-testid={`suivi-es-diff-${r.nuit}`}>
                                            {dEs == null ? "—" : (dEs > 0 ? `+${fmt(dEs)}` : fmt(dEs))}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data text-gray-700 border-l">{r.cam > 0 ? fmt(r.cam) : "—"}</td>
                                        <td className="px-1 py-1">
                                            <input
                                                type="number"
                                                value={sv.cam_reel}
                                                onChange={(e) => updateSuivi(r.nuit, "cam_reel", e.target.value)}
                                                data-testid={`suivi-cam-reel-${r.nuit}`}
                                                className="w-20 h-6 px-1 text-xs border border-yellow-300 bg-yellow-50 rounded text-right font-mono-data focus:ring-1 focus:ring-yellow-500 outline-none"
                                            />
                                        </td>
                                        <td className={`px-2 py-1 text-right font-mono-data font-bold ${diffColor(dCam)}`} data-testid={`suivi-cam-diff-${r.nuit}`}>
                                            {dCam == null ? "—" : (dCam > 0 ? `+${fmt(dCam)}` : fmt(dCam))}
                                        </td>
                                        <td className="px-1 py-1 border-l">
                                            <input
                                                type="number"
                                                value={sv.rails_geoloc}
                                                onChange={(e) => updateSuivi(r.nuit, "rails_geoloc", e.target.value)}
                                                data-testid={`suivi-rails-${r.nuit}`}
                                                className="w-24 h-6 px-1 text-xs border border-yellow-300 bg-yellow-50 rounded text-right font-mono-data focus:ring-1 focus:ring-yellow-500 outline-none"
                                            />
                                        </td>
                                    </tr>
                                );
                            })}
                            {consolidated.length > 0 && (
                                <tr className="border-t-2 border-yellow-300 bg-yellow-50 font-semibold">
                                    <td className="px-2 py-1 text-gray-900" colSpan={3}>TOTAL ({consolidated.length} nuits)</td>
                                    <td className="px-2 py-1 text-right font-mono-data">{fmt(totals.es)}</td>
                                    <td className="px-2 py-1 text-right font-mono-data">{fmt(totals.esReel)}</td>
                                    <td className="px-2 py-1 text-right font-mono-data">{fmt(totals.esReel - totals.es)}</td>
                                    <td className="px-2 py-1 text-right font-mono-data border-l">{fmt(totals.cam)}</td>
                                    <td className="px-2 py-1 text-right font-mono-data">{fmt(totals.camReel)}</td>
                                    <td className="px-2 py-1 text-right font-mono-data">{fmt(totals.camReel - totals.cam)}</td>
                                    <td className="px-2 py-1 text-right font-mono-data border-l">{fmt(totals.rails)}</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
