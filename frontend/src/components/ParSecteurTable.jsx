import React, { useMemo, useState } from "react";
import { Download } from "lucide-react";

function fmtNum(v) {
    if (v == null || v === "") return "";
    if (typeof v === "number") return v.toLocaleString("fr-FR");
    return v;
}

function findCol(columns, candidates) {
    const lower = columns.map((c) => c.toLowerCase());
    for (const cand of candidates) {
        const idx = lower.indexOf(cand.toLowerCase());
        if (idx !== -1) return columns[idx];
    }
    return null;
}

function cmpAllee(a, b) {
    if (a === b) return 0;
    const nA = typeof a === "number" ? a : parseFloat(String(a).replace(",", "."));
    const nB = typeof b === "number" ? b : parseFloat(String(b).replace(",", "."));
    if (!isNaN(nA) && !isNaN(nB)) return nA - nB;
    return String(a).localeCompare(String(b), "fr", { numeric: true });
}

export default function ParSecteurTable({ rows, columns, search, uploadId }) {
    const SECTEUR = findCol(columns, ["Secteur"]) || "Secteur";
    const RAYON = findCol(columns, ["Rayon"]) || "Rayon";
    const ALLEE = findCol(columns, ["N° allée", "N° allee", "Allée", "Allee"]) || "N° allée";
    // Colonne G du fichier original = identifiant unique de la gondole
    const ELEMENT =
        findCol(columns, ["Element", "Élément", "N° élément", "N° element", "N° gondole", "Gondole"]) ||
        (columns[6] /* col G fallback */ || null);
    const TYPE = findCol(columns, ["Type"]);
    const DESIG = findCol(columns, ["Désignation", "Designation"]);
    const QTY = findCol(columns, ["Quantité", "Quantite"]);

    const [filterSecteur, setFilterSecteur] = useState("");
    const [filterRayon, setFilterRayon] = useState("");
    const [mode, setMode] = useState("rayon"); // 'rayon' | 'global'

    // 1) Filtrer les lignes selon recherche/filtre
    const filteredRows = useMemo(() => {
        const q = (search || "").toLowerCase();
        return rows.filter((r) => {
            if (filterSecteur && String(r[SECTEUR] ?? "") !== filterSecteur) return false;
            if (filterRayon && String(r[RAYON] ?? "") !== filterRayon) return false;
            if (q && !columns.some((c) => r[c] != null && String(r[c]).toLowerCase().includes(q))) return false;
            return true;
        });
    }, [rows, columns, search, filterSecteur, filterRayon, SECTEUR, RAYON]);

    // 2) Liste globale des désignations (mode "Toutes désignations")
    const allDesignations = useMemo(() => {
        if (!DESIG) return [];
        const map = new Map(); // designation -> type (premier rencontré)
        for (const r of rows) {
            const d = r[DESIG] == null ? "" : String(r[DESIG]).trim();
            if (!d) continue;
            const t = TYPE ? String(r[TYPE] ?? "") : "";
            if (!map.has(d)) map.set(d, t);
        }
        return Array.from(map.entries())
            .sort((a, b) => a[1].localeCompare(b[1]) || a[0].localeCompare(b[0], "fr"))
            .map(([d]) => d);
    }, [rows, DESIG, TYPE]);

    // 3) Construire l'arbre Secteur > Rayon > Allée
    const tree = useMemo(() => {
        const sectMap = new Map();
        for (const r of filteredRows) {
            const s = r[SECTEUR] == null ? "—" : String(r[SECTEUR]);
            const ra = r[RAYON] == null ? "—" : String(r[RAYON]);
            const al = r[ALLEE] == null ? "—" : String(r[ALLEE]);
            const el = ELEMENT ? (r[ELEMENT] == null ? "" : String(r[ELEMENT])) : "";
            const desig = DESIG ? (r[DESIG] == null ? "" : String(r[DESIG]).trim()) : "";
            const qty = QTY ? Number(r[QTY]) || 0 : 0;
            const typ = TYPE ? String(r[TYPE] ?? "") : "";

            if (!sectMap.has(s)) sectMap.set(s, new Map());
            const rayMap = sectMap.get(s);
            if (!rayMap.has(ra)) rayMap.set(ra, { allees: new Map(), desigSet: new Map() });
            const rayNode = rayMap.get(ra);
            if (desig) {
                if (!rayNode.desigSet.has(desig)) rayNode.desigSet.set(desig, typ);
            }
            if (!rayNode.allees.has(al)) rayNode.allees.set(al, { elements: new Set(), byDesig: {} });
            const alNode = rayNode.allees.get(al);
            if (el) alNode.elements.add(el);
            if (desig) alNode.byDesig[desig] = (alNode.byDesig[desig] || 0) + qty;
        }

        return Array.from(sectMap.entries())
            .sort(([a], [b]) => a.localeCompare(b, "fr"))
            .map(([secteur, rayMap]) => {
                const rayons = Array.from(rayMap.entries())
                    .sort(([a], [b]) => a.localeCompare(b, "fr"))
                    .map(([rayon, node]) => {
                        const desigs = Array.from(node.desigSet.entries())
                            .sort((a, b) => a[1].localeCompare(b[1]) || a[0].localeCompare(b[0], "fr"))
                            .map(([d]) => d);
                        const allees = Array.from(node.allees.entries())
                            .sort(([a], [b]) => cmpAllee(a, b))
                            .map(([allee, data]) => ({
                                allee,
                                nbElements: data.elements.size,
                                byDesig: data.byDesig,
                            }));
                        return { rayon, allees, desigs };
                    });
                return { secteur, rayons };
            });
    }, [filteredRows, SECTEUR, RAYON, ALLEE, ELEMENT, DESIG, QTY, TYPE]);

    const secteurOptions = useMemo(() => {
        const set = new Set();
        rows.forEach((r) => r[SECTEUR] != null && set.add(String(r[SECTEUR])));
        return Array.from(set).sort();
    }, [rows, SECTEUR]);

    const rayonOptions = useMemo(() => {
        const set = new Set();
        rows.forEach((r) => {
            if (filterSecteur && String(r[SECTEUR]) !== filterSecteur) return;
            if (r[RAYON] != null) set.add(String(r[RAYON]));
        });
        return Array.from(set).sort();
    }, [rows, filterSecteur, SECTEUR, RAYON]);

    const handleExport = () => {
        if (!uploadId) return;
        const url = `${process.env.REACT_APP_BACKEND_URL}/api/export/${uploadId}?sheet=parsecteur`;
        window.location.href = url;
    };

    const totalAllees = useMemo(
        () => tree.reduce((a, s) => a + s.rayons.reduce((b, r) => b + r.allees.length, 0), 0),
        [tree]
    );

    return (
        <div className="h-full flex flex-col bg-white" data-testid="parsecteur-table">
            <div className="h-10 border-b border-gray-200 px-3 flex items-center gap-2 bg-gray-50 flex-shrink-0">
                <span className="text-xs font-medium text-gray-700 whitespace-nowrap">Filtres :</span>
                <select
                    value={filterSecteur}
                    onChange={(e) => {
                        setFilterSecteur(e.target.value);
                        setFilterRayon("");
                    }}
                    data-testid="parsecteur-filter-secteur"
                    className="h-7 px-2 text-sm border border-gray-300 rounded bg-white focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                >
                    <option value="">Tous les secteurs</option>
                    {secteurOptions.map((s) => (
                        <option key={s} value={s}>{s}</option>
                    ))}
                </select>
                <select
                    value={filterRayon}
                    onChange={(e) => setFilterRayon(e.target.value)}
                    data-testid="parsecteur-filter-rayon"
                    className="h-7 px-2 text-sm border border-gray-300 rounded bg-white focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                >
                    <option value="">Tous les rayons</option>
                    {rayonOptions.map((r) => (
                        <option key={r} value={r}>{r}</option>
                    ))}
                </select>

                <div className="ml-2 inline-flex rounded border border-gray-300 overflow-hidden" data-testid="parsecteur-mode-toggle">
                    <button
                        onClick={() => setMode("rayon")}
                        data-testid="mode-rayon"
                        className={`h-7 px-2.5 text-xs font-medium ${mode === "rayon" ? "bg-[#056839] text-white" : "bg-white text-gray-700 hover:bg-gray-100"}`}
                        title="Désignations du rayon uniquement"
                    >
                        Désignations rayon
                    </button>
                    <button
                        onClick={() => setMode("global")}
                        data-testid="mode-global"
                        className={`h-7 px-2.5 text-xs font-medium border-l border-gray-300 ${mode === "global" ? "bg-[#056839] text-white" : "bg-white text-gray-700 hover:bg-gray-100"}`}
                        title="Toutes les désignations du fichier"
                    >
                        Toutes désignations
                    </button>
                </div>

                <button
                    onClick={handleExport}
                    data-testid="export-parsecteur"
                    className="h-7 px-2.5 text-xs font-medium bg-[#056839] text-white rounded hover:bg-[#04502b] flex items-center gap-1.5"
                    title="Exporter l'onglet Par Secteur en Excel"
                >
                    <Download className="w-3.5 h-3.5" />
                    Exporter cette vue
                </button>
                <span className="ml-auto text-xs text-gray-500 whitespace-nowrap">
                    {totalAllees.toLocaleString("fr-FR")} allées
                </span>
            </div>

            <div className="flex-1 overflow-auto custom-scroll">
                {tree.map((s) => (
                    <div key={s.secteur} data-testid={`secteur-${s.secteur}`} className="mb-6">
                        <div className="px-3 py-1.5 bg-[#056839] text-white text-sm font-semibold sticky top-0 z-10">
                            Secteur : {s.secteur}
                        </div>
                        {s.rayons.map((r) => {
                            const productCols = mode === "global" ? allDesignations : r.desigs;
                            return (
                                <div key={r.rayon} className="mt-2 mb-4 px-3" data-testid={`rayon-${s.secteur}-${r.rayon}`}>
                                    <div className="text-sm font-medium text-emerald-900 bg-emerald-50 border-l-4 border-emerald-600 px-2 py-1 mb-1">
                                        Rayon : {r.rayon}
                                    </div>
                                    <div className="overflow-x-auto border border-gray-200 rounded">
                                        <table className="w-full text-xs">
                                            <thead className="bg-gray-50">
                                                <tr className="text-gray-700">
                                                    <th className="px-2 py-1.5 text-left font-semibold whitespace-nowrap sticky left-0 bg-gray-50 z-[1]">N° Allée</th>
                                                    <th className="px-2 py-1.5 text-right font-semibold whitespace-nowrap">Nbr éléments</th>
                                                    {productCols.map((d) => (
                                                        <th key={d} className="px-2 py-1.5 text-right font-semibold whitespace-nowrap text-gray-700">{d}</th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {r.allees.map((a, i) => (
                                                    <tr key={a.allee} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                                                        <td className="px-2 py-1 font-mono-data text-gray-800 sticky left-0 bg-inherit border-r border-gray-100">
                                                            {a.allee}
                                                        </td>
                                                        <td className="px-2 py-1 text-right font-mono-data font-semibold text-gray-900">
                                                            {fmtNum(a.nbElements)}
                                                        </td>
                                                        {productCols.map((d) => (
                                                            <td key={d} className="px-2 py-1 text-right font-mono-data text-gray-700">
                                                                {a.byDesig[d] ? fmtNum(a.byDesig[d]) : ""}
                                                            </td>
                                                        ))}
                                                    </tr>
                                                ))}
                                                {/* Ligne TOTAL Rayon */}
                                                <tr className="bg-yellow-50 font-semibold border-t-2 border-yellow-300">
                                                    <td className="px-2 py-1 text-gray-900 sticky left-0 bg-yellow-50">TOTAL</td>
                                                    <td className="px-2 py-1 text-right font-mono-data text-gray-900">
                                                        {fmtNum(r.allees.reduce((a, x) => a + x.nbElements, 0))}
                                                    </td>
                                                    {productCols.map((d) => {
                                                        const sum = r.allees.reduce((a, x) => a + (x.byDesig[d] || 0), 0);
                                                        return (
                                                            <td key={d} className="px-2 py-1 text-right font-mono-data text-gray-900">
                                                                {sum ? fmtNum(sum) : ""}
                                                            </td>
                                                        );
                                                    })}
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                ))}
                {tree.length === 0 && (
                    <div className="p-8 text-center text-sm text-gray-500">Aucun résultat</div>
                )}
            </div>
        </div>
    );
}
