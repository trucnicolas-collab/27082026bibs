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
    return `row_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// Palette de couleurs douces (1 par nuit, repeat après 10)
const NIGHT_COLORS = [
    { bg: "#FEF3C7", border: "#FCD34D" }, // 1 jaune
    { bg: "#DBEAFE", border: "#93C5FD" }, // 2 bleu
    { bg: "#D1FAE5", border: "#6EE7B7" }, // 3 vert
    { bg: "#FCE7F3", border: "#F9A8D4" }, // 4 rose
    { bg: "#E0E7FF", border: "#A5B4FC" }, // 5 indigo
    { bg: "#FED7AA", border: "#FDBA74" }, // 6 orange
    { bg: "#CCFBF1", border: "#5EEAD4" }, // 7 teal
    { bg: "#FAE8FF", border: "#E9D5FF" }, // 8 violet clair
    { bg: "#FFE4E6", border: "#FDA4AF" }, // 9 rouge clair
    { bg: "#ECFCCB", border: "#BEF264" }, // 10 lime
];
function nightColor(n) {
    if (!n) return null;
    return NIGHT_COLORS[(n - 1) % NIGHT_COLORS.length];
}

export default function PhasageTab({ uploadId }) {
    const [summary, setSummary] = useState(null); // { allees, totals, phasage, rails_es_patterns }
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [nbNuits, setNbNuits] = useState(3);
    const [rows, setRows] = useState([]);
    const [weeks, setWeeks] = useState([]); // ex: [5,3,6] ou [] (pas de découpage)
    const [saving, setSaving] = useState(false);

    // Charger summary
    useEffect(() => {
        if (!uploadId) return;
        let mounted = true;
        setLoading(true);
        axios.get(`${API}/dataset/${uploadId}/phasage-summary`)
            .then((res) => {
                if (!mounted) return;
                setSummary(res.data);
                const ph = res.data.phasage || {};
                const p = ph.es || { nb_nuits: 3, rows: [] };
                setNbNuits(p.nb_nuits || 3);
                setWeeks(Array.isArray(p.weeks) ? p.weeks : []);
                setRows((p.rows || []).map((r) => ({
                    id: r.id || newRowId(),
                    allee: r.allee || "",
                    nuit: r.nuit ?? null,
                })));
            })
            .catch((e) => mounted && setError(e.message))
            .finally(() => mounted && setLoading(false));
        return () => { mounted = false; };
    }, [uploadId]);

    // Auto-save (debounce) — préserve cam et suivi en relisant le phasage complet
    useEffect(() => {
        if (!summary || !uploadId) return;
        const t = setTimeout(() => {
            setSaving(true);
            const ph = summary.phasage || {};
            axios.patch(`${API}/dataset/${uploadId}/phasage`, {
                es: {
                    nb_nuits: nbNuits,
                    rows: rows.map((r) => ({ id: r.id, allee: r.allee, nuit: r.nuit })),
                    weeks: weeks.length > 0 ? weeks : null,
                },
                cam: ph.cam || { nb_nuits: 3, rows: [], start_at_nuit: 5 },
                suivi: ph.suivi || { rows: [] },
            }).catch((e) => console.error("Save phasage failed:", e))
              .finally(() => setSaving(false));
        }, 600);
        return () => clearTimeout(t);
    }, [nbNuits, rows, weeks, uploadId, summary]);

    const alleeIndex = useMemo(() => {
        if (!summary) return {};
        const map = {};
        summary.allees.forEach((a) => { map[String(a.allee)] = a; });
        return map;
    }, [summary]);

    // Liste triée des allées dispo
    const alleeOptions = useMemo(() => {
        if (!summary) return [];
        return summary.allees.map((a) => String(a.allee));
    }, [summary]);

    const updateRow = useCallback((id, patch) => {
        setRows((prev) => prev.map((r) => r.id === id ? { ...r, ...patch } : r));
    }, []);

    const addRow = useCallback(() => {
        setRows((prev) => [...prev, { id: newRowId(), allee: "", nuit: null }]);
    }, []);

    const deleteRow = useCallback((id) => {
        setRows((prev) => prev.filter((r) => r.id !== id));
    }, []);

    // Validation : ajuster nuits si nb_nuits diminue
    const onChangeNbNuits = useCallback((n) => {
        const v = Math.max(1, Math.min(30, Number(n) || 1));
        setNbNuits(v);
        setRows((prev) => prev.map((r) => r.nuit && r.nuit > v ? { ...r, nuit: null } : r));
    }, []);

    // Agrégation par nuit
    const nightTotals = useMemo(() => {
        const tot = {};
        for (let n = 1; n <= nbNuits; n++) tot[n] = { es_15: 0, es_21: 0, sa: 0, rails_es: 0, allees: [] };
        rows.forEach((r) => {
            if (!r.nuit) return;
            const node = alleeIndex[String(r.allee)];
            if (!node) return;
            tot[r.nuit].es_15 += node.es_15 || 0;
            tot[r.nuit].es_21 += node.es_21 || 0;
            tot[r.nuit].sa += node.sa || 0;
            tot[r.nuit].rails_es += node.rails_es || 0;
            tot[r.nuit].allees.push(String(r.allee));
        });
        // Tri "intelligent" via l'ordre déjà calculé côté serveur (summary.allees est trié smart).
        const orderIndex = new Map();
        (summary?.allees || []).forEach((a, i) => { orderIndex.set(String(a.allee), i); });
        Object.values(tot).forEach((t) => {
            t.allees.sort((a, b) => {
                const ia = orderIndex.has(a) ? orderIndex.get(a) : 9999;
                const ib = orderIndex.has(b) ? orderIndex.get(b) : 9999;
                if (ia !== ib) return ia - ib;
                return String(a).localeCompare(String(b), "fr", { numeric: true });
            });
        });
        return tot;
    }, [rows, nbNuits, alleeIndex, summary]);

    // Allées déjà utilisées (pour les exclure des selects)
    const usedAllees = useMemo(() => {
        const s = new Set();
        rows.forEach((r) => { if (r.allee) s.add(String(r.allee)); });
        return s;
    }, [rows]);

    // Totaux globaux du récap (ligne TOTAL) — mémoïsé pour éviter 4× reduce à chaque render
    const grandTotals = useMemo(() => {
        const values = Object.values(nightTotals);
        return {
            nbAllees: values.reduce((a, x) => a + (x.allees?.length || 0), 0),
            es: values.reduce((a, x) => a + (x.es_15 || 0) + (x.es_21 || 0), 0),
            rails: values.reduce((a, x) => a + (x.rails_es || 0), 0),
            sa: values.reduce((a, x) => a + (x.sa || 0), 0),
        };
    }, [nightTotals]);

    const handleExport = () => {
        window.location.href = `${API}/export/${uploadId}?sheet=phasage`;
    };

    if (loading) {
        return <div className="p-8 text-sm text-gray-500" data-testid="phasage-loading">Chargement…</div>;
    }
    if (error) {
        return <div className="p-8 text-sm text-red-600">Erreur : {error}</div>;
    }
    if (!summary) return null;

    const { totals, rails_es_patterns } = summary;
    const avg = nbNuits > 0 ? (totals.es_15 + totals.es_21) / nbNuits : 0;

    return (
        <div className="h-full flex flex-col bg-white" data-testid="phasage-tab">
            {/* Barre supérieure : nb nuits + moyenne + export */}
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-3 bg-gray-50 flex-shrink-0">
                <label className="text-xs font-medium text-gray-700 whitespace-nowrap">
                    Nombre de nuits :
                </label>
                <input
                    type="number"
                    min={1}
                    max={30}
                    value={nbNuits}
                    onChange={(e) => onChangeNbNuits(e.target.value)}
                    data-testid="phasage-nb-nuits"
                    className="h-7 w-16 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                />
                <div className="flex items-center gap-2 ml-2 px-3 py-1 bg-[#056839] text-white rounded text-xs font-medium" data-testid="phasage-moyenne">
                    Moyenne / nuit :
                    <span className="font-mono-data font-bold">{fmt(Math.round(avg))}</span>
                    <span className="opacity-80">ES</span>
                </div>
                <button
                    onClick={handleExport}
                    data-testid="phasage-export"
                    className="ml-auto h-7 px-2.5 text-xs font-medium bg-[#056839] text-white rounded hover:bg-[#04502b] flex items-center gap-1.5"
                >
                    <Download className="w-3.5 h-3.5" />
                    Exporter cette vue
                </button>
                {saving && <span className="text-xs text-gray-500">Sauvegarde…</span>}
            </div>

            {/* Découpage par semaine (optionnel) */}
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-2 bg-blue-50/40 flex-wrap flex-shrink-0" data-testid="phasage-weeks-bar">
                <label className="text-xs font-medium text-gray-700 whitespace-nowrap">
                    Découpage par semaine :
                </label>
                <label className="text-[11px] text-gray-600">Nb semaines :</label>
                <input
                    type="number"
                    min={0}
                    max={20}
                    value={weeks.length}
                    onChange={(e) => {
                        const n = Math.max(0, Math.min(20, Number(e.target.value) || 0));
                        if (n === 0) { setWeeks([]); return; }
                        const next = [...weeks];
                        while (next.length < n) next.push(Math.max(1, Math.round(nbNuits / n) || 1));
                        if (next.length > n) next.length = n;
                        setWeeks(next);
                        setNbNuits(next.reduce((a, x) => a + (x || 0), 0));
                    }}
                    data-testid="phasage-nb-semaines"
                    className="h-7 w-14 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                />
                {weeks.length === 0 && (
                    <span className="text-[11px] text-gray-500 italic ml-2">Pas de découpage (le tableau Excel reste en un seul bloc)</span>
                )}
                {weeks.map((w, i) => (
                    <div key={i} className="flex items-center gap-1" data-testid={`phasage-semaine-${i+1}`}>
                        <span className="text-[11px] text-gray-700">S{i + 1} :</span>
                        <input
                            type="number"
                            min={1}
                            max={30}
                            value={w}
                            onChange={(e) => {
                                const v = Math.max(1, Math.min(30, Number(e.target.value) || 1));
                                const next = [...weeks];
                                next[i] = v;
                                setWeeks(next);
                                setNbNuits(next.reduce((a, x) => a + (x || 0), 0));
                            }}
                            className="h-7 w-14 px-2 text-sm border border-blue-300 bg-white rounded text-right focus:ring-1 focus:ring-blue-500 outline-none"
                        />
                        <span className="text-[10px] text-gray-400">nuits</span>
                    </div>
                ))}
                {weeks.length > 0 && (
                    <span className="text-[11px] text-gray-600 ml-2">
                        Total nuits : <b className="font-mono-data">{weeks.reduce((a, x) => a + (x || 0), 0)}</b>
                    </span>
                )}
            </div>

            {/* Totaux globaux */}
            <div className="border-b border-gray-200 px-3 py-2 flex flex-wrap items-start gap-2 text-xs flex-shrink-0">
                <div className="px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded">
                    <span className="text-gray-600">Total ES :</span>{" "}
                    <span className="font-mono-data font-bold text-emerald-900" data-testid="total-es">{fmt((totals.es_15 || 0) + (totals.es_21 || 0))}</span>
                    <span className="text-gray-400 text-[10px] ml-1">(1.5 + 2.1)</span>
                </div>
                <div className="px-3 py-1.5 bg-amber-50 border border-amber-200 rounded">
                    <span className="text-gray-600">Total Rails ES :</span>{" "}
                    <span className="font-mono-data font-bold text-amber-900" data-testid="total-railses">{fmt(totals.rails_es)}</span>
                </div>
                <div className="px-3 py-1.5 bg-gray-50 border border-gray-200 rounded italic">
                    <span className="text-gray-500">Total SA (info) :</span>{" "}
                    <span className="font-mono-data font-bold text-gray-700" data-testid="total-sa">{fmt(totals.sa || 0)}</span>
                </div>
                {(rails_es_patterns || []).map((p) => (
                    <div key={p} className="px-2 py-1 bg-gray-50 border border-gray-200 rounded text-gray-700">
                        <span className="text-gray-500">{p} :</span>{" "}
                        <span className="font-mono-data">{fmt(totals.rails_es_by_desig?.[p] || 0)}</span>
                    </div>
                ))}
            </div>

            {/* 2 tableaux côte à côte */}
            <div className="flex-1 overflow-auto custom-scroll p-3">
                <div className="grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-4">
                    {/* ----- Tableau gauche ----- */}
                    <div data-testid="phasage-left-table">
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-semibold text-gray-800">Plan d'attribution par allée</h3>
                            <button
                                onClick={addRow}
                                data-testid="phasage-add-row"
                                className="h-7 px-2 text-xs font-medium bg-white border border-[#056839] text-[#056839] rounded hover:bg-emerald-50 flex items-center gap-1"
                            >
                                <Plus className="w-3.5 h-3.5" />
                                Ajouter une allée
                            </button>
                        </div>
                        <div className="border border-gray-200 rounded overflow-hidden">
                            <table className="w-full text-xs">
                                <thead className="bg-gray-50 text-gray-700">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-semibold">N° Allée</th>
                                        <th className="px-2 py-1.5 text-right font-semibold" title="Total ES 1.5 + ES 2.1">ES</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
                                        <th className="px-2 py-1.5 text-right font-semibold italic text-gray-500" title="Info : toutes étiquettes SA (SA 1.5, SA 2.1, SA 4.2, etc.) — non incluse dans les calculs">SA</th>
                                        <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                        <th className="px-2 py-1.5 w-8"></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.length === 0 && (
                                        <tr>
                                            <td colSpan={6} className="px-3 py-6 text-center text-gray-500 italic">
                                                Cliquez sur « Ajouter une allée » pour commencer
                                            </td>
                                        </tr>
                                    )}
                                    {rows.map((r) => {
                                        const node = alleeIndex[String(r.allee)];
                                        const color = nightColor(r.nuit);
                                        const rowStyle = color ? {
                                            backgroundColor: color.bg,
                                            borderLeft: `4px solid ${color.border}`,
                                        } : {};
                                        // Options de select : allées non utilisées + l'allée courante (pour pouvoir la changer)
                                        const availableAllees = alleeOptions.filter((a) =>
                                            !usedAllees.has(a) || a === String(r.allee)
                                        );
                                        return (
                                            <tr
                                                key={r.id}
                                                className="border-t border-gray-100"
                                                style={rowStyle}
                                                data-testid={`phasage-row-${r.id}`}
                                            >
                                                <td className="px-1 py-1">
                                                    <select
                                                        value={r.allee || ""}
                                                        onChange={(e) => updateRow(r.id, { allee: e.target.value })}
                                                        data-testid={`row-allee-${r.id}`}
                                                        className="w-full h-6 px-1.5 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none font-mono-data bg-white"
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
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt((node.es_15 || 0) + (node.es_21 || 0)) : ""}</td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt(node.rails_es) : ""}</td>
                                                <td className="px-2 py-1 text-right font-mono-data italic text-gray-500" title="Toutes étiquettes SA (info)">{node ? fmt(node.sa || 0) : ""}</td>
                                                <td className="px-1 py-1">
                                                    <select
                                                        value={r.nuit ?? ""}
                                                        onChange={(e) => updateRow(r.id, { nuit: e.target.value === "" ? null : Number(e.target.value) })}
                                                        data-testid={`row-nuit-${r.id}`}
                                                        className="w-full h-6 px-1 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none bg-white"
                                                    >
                                                        <option value="">—</option>
                                                        {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => (
                                                            <option key={n} value={n}>Nuit {n}</option>
                                                        ))}
                                                    </select>
                                                </td>
                                                <td className="px-1 py-1 text-center">
                                                    <button
                                                        onClick={() => deleteRow(r.id)}
                                                        data-testid={`row-delete-${r.id}`}
                                                        className="text-gray-400 hover:text-red-600 p-0.5"
                                                        title="Supprimer la ligne"
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

                    {/* ----- Tableau droite : par nuit ----- */}
                    <div data-testid="phasage-right-table">
                        <h3 className="text-sm font-semibold text-gray-800 mb-2">Récap par nuit</h3>
                        <div className="border border-gray-200 rounded overflow-hidden">
                            <table className="w-full text-xs">
                                <thead className="bg-gray-50 text-gray-700">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                        <th className="px-2 py-1.5 text-left font-semibold">Allées</th>
                                        <th className="px-2 py-1.5 text-right font-semibold" title="Total ES 1.5 + ES 2.1">ES</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
                                        <th className="px-2 py-1.5 text-right font-semibold italic text-gray-500" title="Info (non inclus dans Total ES)">SA</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                        const t = nightTotals[n] || { es_15: 0, es_21: 0, sa: 0, rails_es: 0, allees: [] };
                                        const totalES = (t.es_15 || 0) + (t.es_21 || 0);
                                        const color = nightColor(n);
                                        return (
                                            <tr
                                                key={n}
                                                className="border-t border-gray-100"
                                                style={color ? { backgroundColor: color.bg, borderLeft: `4px solid ${color.border}` } : {}}
                                                data-testid={`recap-nuit-${n}`}
                                            >
                                                <td className="px-2 py-1 font-medium text-gray-900">Nuit {n}</td>
                                                <td className="px-2 py-1 font-mono-data text-gray-700 text-[11px] max-w-[180px] truncate" title={t.allees.join(", ")}>
                                                    {t.allees.length ? t.allees.join(", ") : <span className="text-gray-400">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data font-bold text-gray-900" title="Total ES 1.5 + ES 2.1">
                                                    {fmt(Math.round(totalES))}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-600">{fmt(t.rails_es)}</td>
                                                <td className="px-2 py-1 text-right font-mono-data italic text-gray-500">{fmt(t.sa || 0)}</td>
                                            </tr>
                                        );
                                    })}
                                    <tr className="border-t-2 border-yellow-300 bg-yellow-50 font-semibold">
                                        <td className="px-2 py-1 text-gray-900">TOTAL</td>
                                        <td className="px-2 py-1 text-gray-500 text-[11px]">
                                            {grandTotals.nbAllees} allées
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(Math.round(grandTotals.es))}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(grandTotals.rails)}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data italic text-gray-600">
                                            {fmt(grandTotals.sa)}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {/* ----- Graphique répartition par nuit ----- */}
                <div className="mt-6" data-testid="phasage-chart">
                    <h3 className="text-sm font-semibold text-gray-800 mb-2">
                        Répartition par nuit
                    </h3>
                    <div className="border border-gray-200 rounded p-3 bg-gray-50/30" style={{ height: 320 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                                data={Array.from({ length: nbNuits }, (_, i) => {
                                    const n = i + 1;
                                    const t = nightTotals[n] || { es_15: 0, es_21: 0, sa: 0, rails_es: 0 };
                                    return {
                                        name: `Nuit ${n}`,
                                        "ES": Math.round((t.es_15 || 0) + (t.es_21 || 0)),
                                        "Rails ES": Math.round(t.rails_es || 0),
                                    };
                                })}
                                margin={{ top: 12, right: 16, left: 0, bottom: 4 }}
                            >
                                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                                <YAxis tick={{ fontSize: 11 }} />
                                <Tooltip
                                    contentStyle={{ fontSize: 12, borderRadius: 4 }}
                                    formatter={(v) => new Intl.NumberFormat("fr-FR").format(v)}
                                />
                                <Legend wrapperStyle={{ fontSize: 12 }} />
                                <Bar dataKey="ES" fill="#10B981" />
                                <Bar dataKey="Rails ES" fill="#F59E0B" />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </div>
    );
}
