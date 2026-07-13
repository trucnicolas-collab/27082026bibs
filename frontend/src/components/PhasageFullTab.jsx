import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Download } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function fmt(n) {
    if (n == null) return "";
    if (typeof n === "number") return n.toLocaleString("fr-FR");
    return n;
}

// Palette FIXE par position dans la semaine (1..4) — identique aux autres onglets
const WEEK_COLORS = [
    { bg: "#DBEAFE", border: "#60A5FA" }, // 1 bleu doux
    { bg: "#FEF3C7", border: "#F59E0B" }, // 2 jaune doux
    { bg: "#FEE2E2", border: "#EF4444" }, // 3 rouge doux
    { bg: "#DCFCE7", border: "#22C55E" }, // 4 vert doux
];
function nightPositionInWeek(nuit, weeks) {
    if (!nuit) return 0;
    if (!weeks || weeks.length === 0) return nuit;
    let remaining = nuit;
    for (const w of weeks) {
        const ww = w || 0;
        if (remaining <= ww) return remaining;
        remaining -= ww;
    }
    return remaining;
}
function nightColor(n, weeks) {
    if (!n) return null;
    const pos = nightPositionInWeek(n, weeks);
    return pos ? WEEK_COLORS[(pos - 1) % WEEK_COLORS.length] : null;
}

const TYPE_BADGE = {
    "ES": { bg: "#DBEAFE", text: "#065F46" },
    "Caméras": { bg: "#EDE9FE", text: "#5B21B6" },
    "Mixte": { bg: "#FEF3C7", text: "#92400E" },
};

export default function PhasageFullTab({ uploadId }) {
    const [summary, setSummary] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!uploadId) return;
        let mounted = true;
        setLoading(true);
        axios.get(`${API}/dataset/${uploadId}/phasage-summary`)
            .then((res) => mounted && setSummary(res.data))
            .catch((e) => mounted && setError(e.message))
            .finally(() => mounted && setLoading(false));
        return () => { mounted = false; };
    }, [uploadId]);

    // Construire le planning consolidé côté frontend (même logique que le backend)
    const consolidated = useMemo(() => {
        if (!summary) return [];
        const ph = summary.phasage || {};
        const es = ph.es || { rows: [] };
        const cam = ph.cam || { rows: [], start_at_nuit: 5 };
        const startAt = cam.start_at_nuit || 5;
        const idx = {};
        (summary.allees || []).forEach((a) => { idx[String(a.uid || a.allee)] = a; });
        const nuits = {}; // globalNuit -> {type, allees:Set, es, cam, secteur_rayon:Set}

        (es.rows || []).forEach((r) => {
            const n = r.nuit, a = String(r.allee || "").trim();
            if (!n || !a) return;
            const node = idx[a]; if (!node) return;
            const gn = Number(n);
            if (!nuits[gn]) nuits[gn] = { type: "ES", allees: new Set(), es: 0, cam: 0, secteur_rayon: new Set() };
            nuits[gn].allees.add(a);
            nuits[gn].es += (node.es_15 || 0) + (node.es_21 || 0);
            if (node.secteur || node.rayon) nuits[gn].secteur_rayon.add(`${node.secteur || ""}${node.rayon ? ":" + node.rayon : ""}`);
        });
        (cam.rows || []).forEach((r) => {
            const n = r.nuit, a = String(r.allee || "").trim();
            if (!n || !a) return;
            const node = idx[a]; if (!node) return;
            const gn = startAt + Number(n) - 1;
            if (!nuits[gn]) {
                nuits[gn] = { type: "Caméras", allees: new Set(), es: 0, cam: 0, secteur_rayon: new Set() };
            } else if (nuits[gn].es > 0) {
                nuits[gn].type = "Mixte";
            }
            nuits[gn].allees.add(a);
            nuits[gn].cam += (node.cameras || 0);
            if (node.secteur || node.rayon) nuits[gn].secteur_rayon.add(`${node.secteur || ""}${node.rayon ? ":" + node.rayon : ""}`);
        });

        // Tri smart des allées
        const orderIndex = new Map();
        (summary.allees || []).forEach((a, i) => orderIndex.set(String(a.uid || a.allee), i));
        const sortedKeys = Object.keys(nuits).map(Number).sort((a, b) => a - b);
        return sortedKeys.map((gn) => {
            const allees = Array.from(nuits[gn].allees).sort((a, b) => {
                const ia = orderIndex.has(a) ? orderIndex.get(a) : 9999;
                const ib = orderIndex.has(b) ? orderIndex.get(b) : 9999;
                return ia - ib;
            });
            return { nuit: gn, type: nuits[gn].type, allees, es: Math.round(nuits[gn].es), cam: Math.round(nuits[gn].cam), secteur_rayon: Array.from(nuits[gn].secteur_rayon) };
        });
    }, [summary]);

    const dates = summary?.phasage?.dates || {};

    const totals = useMemo(() => {
        return consolidated.reduce(
            (acc, r) => ({ es: acc.es + r.es, cam: acc.cam + r.cam, nuits: acc.nuits + 1 }),
            { es: 0, cam: 0, nuits: 0 }
        );
    }, [consolidated]);

    const handleExport = () => {
        window.location.href = `${API}/export/${uploadId}?sheet=phasage_full`;
    };

    if (loading) return <div className="p-8 text-sm text-gray-500" data-testid="phasagefull-loading">Chargement…</div>;
    if (error) return <div className="p-8 text-sm text-red-600">Erreur : {error}</div>;
    if (!summary) return null;

    return (
        <div className="h-full flex flex-col bg-white" data-testid="phasage-full-tab">
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-3 bg-blue-50/40 flex-shrink-0">
                <h2 className="text-sm font-semibold text-gray-800">Phasage full — Planning consolidé (ES + Caméras)</h2>
                <span className="text-[11px] italic text-gray-500">Vue agrégée des nuits planifiées dans « Phasage de pose » et « Phasage caméras »</span>
            </div>

            <div className="border-b border-gray-200 px-3 py-2 flex flex-wrap gap-2 text-xs flex-shrink-0">
                <div className="px-3 py-1.5 bg-gray-50 border border-gray-200 rounded">
                    Nuits planifiées : <span className="font-mono-data font-bold">{totals.nuits}</span>
                </div>
                <div className="px-3 py-1.5 bg-blue-50 border border-blue-200 rounded">
                    Total ES : <span className="font-mono-data font-bold text-blue-900" data-testid="full-total-es">{fmt(totals.es)}</span>
                </div>
                <div className="px-3 py-1.5 bg-purple-50 border border-purple-200 rounded">
                    Total Caméras : <span className="font-mono-data font-bold text-purple-900" data-testid="full-total-cam">{fmt(totals.cam)}</span>
                </div>
            </div>

            <div className="flex-1 overflow-auto custom-scroll p-3">
                <div className="border border-gray-200 rounded overflow-hidden">
                    <table className="w-full text-xs">
                        <thead className="bg-gray-50 text-gray-700 sticky top-0">
                            <tr>
                                <th className="px-3 py-2 text-left font-semibold w-16">Nuit</th>
                                <th className="px-3 py-2 text-left font-semibold w-20 whitespace-nowrap">Date</th>
                                <th className="px-3 py-2 text-left font-semibold w-24">Type</th>
                                <th className="px-3 py-2 text-left font-semibold text-[10px] text-gray-600 w-40">Secteur/Rayon</th>
                                <th className="px-3 py-2 text-left font-semibold">Allées</th>
                                <th className="px-3 py-2 text-right font-semibold w-24">ES</th>
                                <th className="px-3 py-2 text-right font-semibold w-24">Caméras</th>
                            </tr>
                        </thead>
                        <tbody>
                            {consolidated.length === 0 && (
                                <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-500 italic">
                                    Aucune nuit planifiée. Renseigne « Phasage de pose » ou « Phasage caméras » d'abord.
                                </td></tr>
                            )}
                            {consolidated.map((r) => {
                                const color = nightColor(r.nuit, (summary?.phasage?.es?.weeks) || []);
                                const tb = TYPE_BADGE[r.type] || TYPE_BADGE["ES"];
                                const dateStr = dates[String(r.nuit)];
                                return (
                                    <tr key={r.nuit} className="border-t border-gray-100"
                                        style={color ? { backgroundColor: color.bg, borderLeft: `4px solid ${color.border}` } : {}}
                                        data-testid={`full-nuit-${r.nuit}`}>
                                        <td className="px-3 py-1.5 font-medium text-gray-900">Nuit {r.nuit}</td>
                                        <td className="px-3 py-1.5 text-[10.5px] text-gray-700 whitespace-nowrap font-mono-data">
                                            {dateStr ? new Date(dateStr + "T00:00:00").toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : <span className="text-gray-300">—</span>}
                                        </td>
                                        <td className="px-3 py-1.5">
                                            <span className="inline-block px-2 py-0.5 rounded text-[10px] font-semibold"
                                                  style={{ backgroundColor: tb.bg, color: tb.text }}>
                                                {r.type}
                                            </span>
                                        </td>
                                        <td className="px-3 py-1.5 text-[10px] text-gray-600 truncate max-w-[200px]" title={r.secteur_rayon.join(" / ")}>
                                            {r.secteur_rayon.length ? r.secteur_rayon.join(" / ") : <span className="text-gray-300">—</span>}
                                        </td>
                                        <td className="px-3 py-1.5 font-mono-data text-gray-700 text-[11px]" title={r.allees.join(", ")}>
                                            {r.allees.join(", ")}
                                        </td>
                                        <td className="px-3 py-1.5 text-right font-mono-data font-bold">{r.es > 0 ? fmt(r.es) : <span className="text-gray-300">—</span>}</td>
                                        <td className="px-3 py-1.5 text-right font-mono-data font-bold">{r.cam > 0 ? fmt(r.cam) : <span className="text-gray-300">—</span>}</td>
                                    </tr>
                                );
                            })}
                            {consolidated.length > 0 && (
                                <tr className="border-t-2 border-yellow-300 bg-yellow-50 font-semibold">
                                    <td className="px-3 py-1.5 text-gray-900">TOTAL</td>
                                    <td className="px-3 py-1.5 text-gray-300">—</td>
                                    <td className="px-3 py-1.5"></td>
                                    <td className="px-3 py-1.5 text-gray-300">—</td>
                                    <td className="px-3 py-1.5 text-gray-600 text-[11px]">{totals.nuits} nuits</td>
                                    <td className="px-3 py-1.5 text-right font-mono-data">{fmt(totals.es)}</td>
                                    <td className="px-3 py-1.5 text-right font-mono-data">{fmt(totals.cam)}</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
