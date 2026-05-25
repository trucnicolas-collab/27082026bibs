import React, { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { Plus, Trash2, Download } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ResponsiveContainer } from "recharts";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function fmt(n) {
    if (n == null) return "";
    if (typeof n === "number") return n.toLocaleString("fr-FR");
    return n;
}
function newRowId() {
    return `cam_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
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

export default function PhasageCamTab({ uploadId }) {
    const [summary, setSummary] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [nbNuits, setNbNuits] = useState(3);
    const [startAt, setStartAt] = useState(5);
    const [rows, setRows] = useState([]);
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
                const c = ph.cam || { nb_nuits: 3, rows: [], start_at_nuit: 5 };
                setNbNuits(c.nb_nuits || 3);
                setStartAt(c.start_at_nuit || 5);
                setRows((c.rows || []).map((r) => ({
                    id: r.id || newRowId(),
                    allee: r.allee || "",
                    nuit: r.nuit ?? null,
                })));
            })
            .catch((e) => mounted && setError(e.message))
            .finally(() => mounted && setLoading(false));
        return () => { mounted = false; };
    }, [uploadId]);

    // Auto-save
    useEffect(() => {
        if (!summary || !uploadId) return;
        const t = setTimeout(() => {
            setSaving(true);
            const ph = summary.phasage || {};
            axios.patch(`${API}/dataset/${uploadId}/phasage`, {
                es: ph.es || { nb_nuits: 3, rows: [] },
                cam: {
                    nb_nuits: nbNuits,
                    start_at_nuit: startAt,
                    rows: rows.map((r) => ({ id: r.id, allee: r.allee, nuit: r.nuit })),
                },
                suivi: ph.suivi || { rows: [] },
            }).catch((e) => console.error("Save cam failed:", e))
              .finally(() => setSaving(false));
        }, 600);
        return () => clearTimeout(t);
    }, [nbNuits, startAt, rows, uploadId, summary]);

    // Allées avec caméras > 0 uniquement
    const alleeOptions = useMemo(() => {
        if (!summary) return [];
        return summary.allees.filter((a) => (a.cameras || 0) > 0).map((a) => String(a.allee));
    }, [summary]);

    const alleeIndex = useMemo(() => {
        if (!summary) return {};
        const map = {};
        summary.allees.forEach((a) => { map[String(a.allee)] = a; });
        return map;
    }, [summary]);

    const usedAllees = useMemo(() => {
        const s = new Set();
        rows.forEach((r) => { if (r.allee) s.add(String(r.allee)); });
        return s;
    }, [rows]);

    const updateRow = useCallback((id, patch) => {
        setRows((prev) => prev.map((r) => r.id === id ? { ...r, ...patch } : r));
    }, []);
    const addRow = useCallback(() => {
        setRows((prev) => [...prev, { id: newRowId(), allee: "", nuit: null }]);
    }, []);
    const deleteRow = useCallback((id) => {
        setRows((prev) => prev.filter((r) => r.id !== id));
    }, []);

    const onChangeNbNuits = useCallback((n) => {
        const v = Math.max(1, Math.min(30, Number(n) || 1));
        setNbNuits(v);
        setRows((prev) => prev.map((r) => r.nuit && r.nuit > v ? { ...r, nuit: null } : r));
    }, []);

    const nightTotals = useMemo(() => {
        const tot = {};
        for (let n = 1; n <= nbNuits; n++) tot[n] = { cameras: 0, allees: [] };
        rows.forEach((r) => {
            if (!r.nuit) return;
            const node = alleeIndex[String(r.allee)];
            if (!node) return;
            tot[r.nuit].cameras += node.cameras || 0;
            tot[r.nuit].allees.push(String(r.allee));
        });
        const orderIndex = new Map();
        (summary?.allees || []).forEach((a, i) => { orderIndex.set(String(a.allee), i); });
        Object.values(tot).forEach((t) => {
            t.allees.sort((a, b) => {
                const ia = orderIndex.has(a) ? orderIndex.get(a) : 9999;
                const ib = orderIndex.has(b) ? orderIndex.get(b) : 9999;
                return ia - ib;
            });
        });
        return tot;
    }, [rows, nbNuits, alleeIndex, summary]);

    const handleExport = () => {
        window.location.href = `${API}/export/${uploadId}?sheet=phasage_cam`;
    };

    // Totaux globaux du récap (ligne TOTAL) — mémoïsé
    const grandTotals = useMemo(() => {
        const values = Object.values(nightTotals);
        return {
            nbAllees: values.reduce((a, x) => a + (x.allees?.length || 0), 0),
            cameras: values.reduce((a, x) => a + (x.cameras || 0), 0),
        };
    }, [nightTotals]);

    if (loading) return <div className="p-8 text-sm text-gray-500" data-testid="phasagecam-loading">Chargement…</div>;
    if (error) return <div className="p-8 text-sm text-red-600">Erreur : {error}</div>;
    if (!summary) return null;

    const totalCameras = summary.totals?.cameras || 0;
    const moyenne = nbNuits > 0 ? Math.round(totalCameras / nbNuits) : 0;

    if (alleeOptions.length === 0) {
        return (
            <div className="p-8 text-sm text-gray-500" data-testid="phasagecam-empty">
                Aucune caméra (noire ou blanche) détectée dans ce fichier.
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-white" data-testid="phasage-cam-tab">
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-3 bg-purple-50/40 flex-shrink-0">
                <label className="text-xs font-medium text-gray-700 whitespace-nowrap">Nombre de nuits :</label>
                <input
                    type="number" min={1} max={30} value={nbNuits}
                    onChange={(e) => onChangeNbNuits(e.target.value)}
                    data-testid="phasagecam-nb-nuits"
                    className="h-7 w-16 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-purple-600 focus:border-purple-600 outline-none"
                />
                <label className="text-xs font-medium text-gray-700 whitespace-nowrap ml-2">Démarre à la nuit :</label>
                <input
                    type="number" min={1} max={60} value={startAt}
                    onChange={(e) => setStartAt(Math.max(1, Number(e.target.value) || 1))}
                    data-testid="phasagecam-start-at"
                    className="h-7 w-16 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-purple-600 focus:border-purple-600 outline-none"
                />
                <div className="flex items-center gap-2 ml-2 px-3 py-1 bg-purple-700 text-white rounded text-xs font-medium" data-testid="phasagecam-moyenne">
                    Moyenne / nuit :
                    <span className="font-mono-data font-bold">{fmt(moyenne)}</span>
                    <span className="opacity-80">caméras</span>
                </div>
                <span className="ml-2 text-[11px] italic text-gray-500">Indicatif ~300 / nuit</span>
                <button
                    onClick={handleExport}
                    data-testid="phasagecam-export"
                    className="ml-auto h-7 px-2.5 text-xs font-medium bg-purple-700 text-white rounded hover:bg-purple-800 flex items-center gap-1.5"
                >
                    <Download className="w-3.5 h-3.5" /> Exporter cette vue
                </button>
                {saving && <span className="text-xs text-gray-500">Sauvegarde…</span>}
            </div>

            <div className="border-b border-gray-200 px-3 py-2 flex flex-wrap items-start gap-2 text-xs flex-shrink-0">
                <div className="px-3 py-1.5 bg-purple-50 border border-purple-200 rounded">
                    <span className="text-gray-600">Total Caméras :</span>{" "}
                    <span className="font-mono-data font-bold text-purple-900" data-testid="total-cameras">{fmt(totalCameras)}</span>
                </div>
                <div className="px-3 py-1.5 bg-gray-50 border border-gray-200 rounded">
                    <span className="text-gray-600">Allées avec caméras :</span>{" "}
                    <span className="font-mono-data font-bold text-gray-900">{alleeOptions.length}</span>
                </div>
            </div>

            <div className="flex-1 overflow-auto custom-scroll p-3">
                <div className="grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-4">
                    {/* Gauche */}
                    <div data-testid="phasagecam-left-table">
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-semibold text-gray-800">Plan d'attribution caméras par allée</h3>
                            <button
                                onClick={addRow}
                                data-testid="phasagecam-add-row"
                                className="h-7 px-2 text-xs font-medium bg-white border border-purple-700 text-purple-700 rounded hover:bg-purple-50 flex items-center gap-1"
                            >
                                <Plus className="w-3.5 h-3.5" /> Ajouter une allée
                            </button>
                        </div>
                        <div className="border border-gray-200 rounded overflow-hidden">
                            <table className="w-full text-xs">
                                <thead className="bg-gray-50 text-gray-700">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-semibold">N° Allée</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Caméras</th>
                                        <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                        <th className="px-2 py-1.5 w-8"></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.length === 0 && (
                                        <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-500 italic">
                                            Cliquez sur « Ajouter une allée » pour commencer
                                        </td></tr>
                                    )}
                                    {rows.map((r) => {
                                        const node = alleeIndex[String(r.allee)];
                                        const color = nightColor(r.nuit);
                                        const rowStyle = color ? { backgroundColor: color.bg, borderLeft: `4px solid ${color.border}` } : {};
                                        const availableAllees = alleeOptions.filter((a) => !usedAllees.has(a) || a === String(r.allee));
                                        return (
                                            <tr key={r.id} className="border-t border-gray-100" style={rowStyle} data-testid={`phasagecam-row-${r.id}`}>
                                                <td className="px-1 py-1">
                                                    <select
                                                        value={r.allee || ""}
                                                        onChange={(e) => updateRow(r.id, { allee: e.target.value })}
                                                        data-testid={`camrow-allee-${r.id}`}
                                                        className="w-full h-6 px-1.5 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-purple-600 outline-none font-mono-data bg-white"
                                                    >
                                                        <option value="">Sélectionner…</option>
                                                        {availableAllees.map((a) => (
                                                            <option key={a} value={a}>
                                                                {a}
                                                                {alleeIndex[a]?.secteur ? ` (${alleeIndex[a].secteur}${alleeIndex[a].rayon ? " · " + alleeIndex[a].rayon : ""})` : ""}
                                                            </option>
                                                        ))}
                                                    </select>
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt(node.cameras) : ""}</td>
                                                <td className="px-1 py-1">
                                                    <select
                                                        value={r.nuit ?? ""}
                                                        onChange={(e) => updateRow(r.id, { nuit: e.target.value === "" ? null : Number(e.target.value) })}
                                                        data-testid={`camrow-nuit-${r.id}`}
                                                        className="w-full h-6 px-1 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-purple-600 outline-none bg-white"
                                                    >
                                                        <option value="">—</option>
                                                        {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => (
                                                            <option key={n} value={n}>Nuit {startAt + n - 1}</option>
                                                        ))}
                                                    </select>
                                                </td>
                                                <td className="px-1 py-1 text-center">
                                                    <button
                                                        onClick={() => deleteRow(r.id)}
                                                        data-testid={`camrow-delete-${r.id}`}
                                                        className="text-gray-400 hover:text-red-600 p-0.5"
                                                    >
                                                        <Trash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    {/* Droite */}
                    <div data-testid="phasagecam-right-table">
                        <h3 className="text-sm font-semibold text-gray-800 mb-2">Récap par nuit</h3>
                        <div className="border border-gray-200 rounded overflow-hidden">
                            <table className="w-full text-xs">
                                <thead className="bg-gray-50 text-gray-700">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                        <th className="px-2 py-1.5 text-left font-semibold">Allées</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Caméras</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                        const t = nightTotals[n] || { cameras: 0, allees: [] };
                                        const color = nightColor(n);
                                        return (
                                            <tr key={n} className="border-t border-gray-100"
                                                style={color ? { backgroundColor: color.bg, borderLeft: `4px solid ${color.border}` } : {}}
                                                data-testid={`camrecap-nuit-${n}`}>
                                                <td className="px-2 py-1 font-medium text-gray-900">Nuit {startAt + n - 1}</td>
                                                <td className="px-2 py-1 font-mono-data text-gray-700 text-[11px] max-w-[180px] truncate" title={t.allees.join(", ")}>
                                                    {t.allees.length ? t.allees.join(", ") : <span className="text-gray-400">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data font-bold text-gray-900">
                                                    {fmt(Math.round(t.cameras))}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                    <tr className="border-t-2 border-yellow-300 bg-yellow-50 font-semibold">
                                        <td className="px-2 py-1 text-gray-900">TOTAL</td>
                                        <td className="px-2 py-1 text-gray-500 text-[11px]">
                                            {grandTotals.nbAllees} allées
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(Math.round(grandTotals.cameras))}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <div className="mt-6" data-testid="phasagecam-chart">
                    <h3 className="text-sm font-semibold text-gray-800 mb-2">Répartition caméras par nuit</h3>
                    <div className="border border-gray-200 rounded p-3 bg-gray-50/30" style={{ height: 280 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                                data={Array.from({ length: nbNuits }, (_, i) => {
                                    const n = i + 1;
                                    const t = nightTotals[n] || { cameras: 0 };
                                    return { name: `Nuit ${startAt + n - 1}`, Caméras: Math.round(t.cameras || 0) };
                                })}
                                margin={{ top: 12, right: 16, left: 0, bottom: 4 }}
                            >
                                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                                <YAxis tick={{ fontSize: 11 }} />
                                <Tooltip contentStyle={{ fontSize: 12 }} formatter={(v) => new Intl.NumberFormat("fr-FR").format(v)} />
                                <Legend wrapperStyle={{ fontSize: 12 }} />
                                <Bar dataKey="Caméras" fill="#7C3AED" />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </div>
    );
}
