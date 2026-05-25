import React, { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { Plus, Trash2, Download } from "lucide-react";

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
                const p = res.data.phasage || { nb_nuits: 3, rows: [] };
                setNbNuits(p.nb_nuits || 3);
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

    // Auto-save (debounce)
    useEffect(() => {
        if (!summary || !uploadId) return;
        const t = setTimeout(() => {
            setSaving(true);
            axios.patch(`${API}/dataset/${uploadId}/phasage`, {
                nb_nuits: nbNuits,
                rows: rows.map((r) => ({ id: r.id, allee: r.allee, nuit: r.nuit })),
            }).catch((e) => console.error("Save phasage failed:", e))
              .finally(() => setSaving(false));
        }, 600);
        return () => clearTimeout(t);
    }, [nbNuits, rows, uploadId, summary]);

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
        for (let n = 1; n <= nbNuits; n++) tot[n] = { es_15: 0, es_21: 0, rails_es: 0, allees: [] };
        rows.forEach((r) => {
            if (!r.nuit) return;
            const node = alleeIndex[String(r.allee)];
            if (!node) return;
            tot[r.nuit].es_15 += node.es_15 || 0;
            tot[r.nuit].es_21 += node.es_21 || 0;
            tot[r.nuit].rails_es += node.rails_es || 0;
            tot[r.nuit].allees.push(String(r.allee));
        });
        // Tri numérique des allées par nuit
        Object.values(tot).forEach((t) => {
            t.allees.sort((a, b) => {
                const na = parseFloat(a), nb = parseFloat(b);
                if (!isNaN(na) && !isNaN(nb)) return na - nb;
                return String(a).localeCompare(String(b), "fr", { numeric: true });
            });
        });
        return tot;
    }, [rows, nbNuits, alleeIndex]);

    // Allées déjà utilisées (pour les exclure des selects)
    const usedAllees = useMemo(() => {
        const s = new Set();
        rows.forEach((r) => { if (r.allee) s.add(String(r.allee)); });
        return s;
    }, [rows]);

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
                    <span className="opacity-80">(ES 1.5 + ES 2.1)</span>
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

            {/* Totaux globaux */}
            <div className="border-b border-gray-200 px-3 py-2 flex flex-wrap items-start gap-2 text-xs flex-shrink-0">
                <div className="px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded">
                    <span className="text-gray-600">Total ES 1.5 :</span>{" "}
                    <span className="font-mono-data font-bold text-emerald-900" data-testid="total-es15">{fmt(totals.es_15)}</span>
                </div>
                <div className="px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded">
                    <span className="text-gray-600">Total ES 2.1 :</span>{" "}
                    <span className="font-mono-data font-bold text-emerald-900" data-testid="total-es21">{fmt(totals.es_21)}</span>
                </div>
                <div className="px-3 py-1.5 bg-amber-50 border border-amber-200 rounded">
                    <span className="text-gray-600">Total Rails ES :</span>{" "}
                    <span className="font-mono-data font-bold text-amber-900" data-testid="total-railses">{fmt(totals.rails_es)}</span>
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
                                        <th className="px-2 py-1.5 text-right font-semibold">ES 1.5</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">ES 2.1</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
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
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt(node.es_15) : ""}</td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt(node.es_21) : ""}</td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt(node.rails_es) : ""}</td>
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
                                        <th className="px-2 py-1.5 text-right font-semibold">ES 1.5</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">ES 2.1</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Total ES</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                        const t = nightTotals[n] || { es_15: 0, es_21: 0, rails_es: 0, allees: [] };
                                        const totalES = (t.es_15 || 0) + (t.es_21 || 0);
                                        const over = totalES > 4500;
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
                                                <td className="px-2 py-1 text-right font-mono-data">{fmt(t.es_15)}</td>
                                                <td className="px-2 py-1 text-right font-mono-data">{fmt(t.es_21)}</td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-600">{fmt(t.rails_es)}</td>
                                                <td className={`px-2 py-1 text-right font-mono-data font-bold ${over ? "text-red-600" : "text-emerald-700"}`} title="Objectif : ≤ 4500 ES par nuit">
                                                    {fmt(Math.round(totalES))}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                    <tr className="border-t-2 border-yellow-300 bg-yellow-50 font-semibold">
                                        <td className="px-2 py-1 text-gray-900">TOTAL</td>
                                        <td className="px-2 py-1 text-gray-500 text-[11px]">
                                            {Object.values(nightTotals).reduce((a, x) => a + (x.allees?.length || 0), 0)} allées
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(Object.values(nightTotals).reduce((a, x) => a + (x.es_15 || 0), 0))}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(Object.values(nightTotals).reduce((a, x) => a + (x.es_21 || 0), 0))}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(Object.values(nightTotals).reduce((a, x) => a + (x.rails_es || 0), 0))}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(Math.round(Object.values(nightTotals).reduce((a, x) => a + (x.es_15 || 0) + (x.es_21 || 0), 0)))}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <p className="text-[11px] text-gray-500 mt-1">
                            La colonne « Total ES » devient rouge si elle dépasse 4 500 (objectif/nuit).
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
}
