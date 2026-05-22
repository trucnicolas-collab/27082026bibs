import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";

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

// Compare numérique puis string
function cmp(a, b) {
    if (a === b) return 0;
    if (a == null || a === "") return 1;
    if (b == null || b === "") return -1;
    const nA = typeof a === "number" ? a : parseFloat(String(a).replace(",", "."));
    const nB = typeof b === "number" ? b : parseFloat(String(b).replace(",", "."));
    if (!isNaN(nA) && !isNaN(nB)) return nA - nB;
    return String(a).localeCompare(String(b), "fr", { numeric: true });
}

export default function ParSecteurTable({ rows, columns, search }) {
    const SECTEUR = findCol(columns, ["Secteur"]) || "Secteur";
    const RAYON = findCol(columns, ["Rayon"]) || "Rayon";
    const ALLEE = findCol(columns, ["N° allée", "N° allee", "Allée", "Allee"]) || "N° allée";
    const TYPE = findCol(columns, ["Type"]);
    const DESIG = findCol(columns, ["Désignation", "Designation"]);
    const QTY = findCol(columns, ["Quantité", "Quantite"]);

    const [filterSecteur, setFilterSecteur] = useState("");
    const [filterRayon, setFilterRayon] = useState("");
    const [expanded, setExpanded] = useState({}); // key -> bool

    const toggle = (key) => setExpanded((p) => ({ ...p, [key]: !p[key] }));

    // Construire l'arbre : Secteur > Rayon > Allée > Produits
    const tree = useMemo(() => {
        const q = (search || "").toLowerCase();
        const map = new Map(); // secteur -> Map(rayon -> Map(allee -> { total, byType, products: [] }))
        for (const r of rows) {
            const s = r[SECTEUR] == null ? "—" : String(r[SECTEUR]);
            const ra = r[RAYON] == null ? "—" : String(r[RAYON]);
            const al = r[ALLEE] == null ? "—" : String(r[ALLEE]);
            if (filterSecteur && s !== filterSecteur) continue;
            if (filterRayon && ra !== filterRayon) continue;
            if (q && !columns.some((c) => r[c] != null && String(r[c]).toLowerCase().includes(q))) continue;

            if (!map.has(s)) map.set(s, new Map());
            const rayMap = map.get(s);
            if (!rayMap.has(ra)) rayMap.set(ra, new Map());
            const allMap = rayMap.get(ra);
            if (!allMap.has(al)) allMap.set(al, { total: 0, byType: {}, products: [] });
            const node = allMap.get(al);
            const qty = QTY ? Number(r[QTY]) || 0 : 1;
            node.total += qty;
            const typ = TYPE ? (r[TYPE] || "—") : "—";
            node.byType[typ] = (node.byType[typ] || 0) + qty;
            node.products.push({
                type: typ,
                designation: DESIG ? (r[DESIG] || "") : "",
                qty,
            });
        }
        // Convertir en tableau trié pour rendu
        const secteurs = Array.from(map.entries())
            .sort(([a], [b]) => cmp(a, b))
            .map(([secteur, rayMap]) => {
                const rayons = Array.from(rayMap.entries())
                    .sort(([a], [b]) => cmp(a, b))
                    .map(([rayon, allMap]) => {
                        const allees = Array.from(allMap.entries())
                            .sort(([a], [b]) => cmp(a, b))
                            .map(([allee, data]) => ({ allee, ...data }));
                        const rayonTotal = allees.reduce((acc, a) => acc + a.total, 0);
                        return { rayon, allees, total: rayonTotal };
                    });
                const secteurTotal = rayons.reduce((acc, r) => acc + r.total, 0);
                return { secteur, rayons, total: secteurTotal };
            });
        return secteurs;
    }, [rows, columns, search, filterSecteur, filterRayon, SECTEUR, RAYON, ALLEE, TYPE, DESIG, QTY]);

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
                <button
                    onClick={() => {
                        // Tout déplier : marquer chaque secteur + rayon ouvert
                        const next = {};
                        tree.forEach((s) => {
                            next[`s:${s.secteur}`] = true;
                            s.rayons.forEach((r) => (next[`r:${s.secteur}|${r.rayon}`] = true));
                        });
                        setExpanded(next);
                    }}
                    data-testid="expand-all"
                    className="h-7 px-2 text-xs text-gray-700 border border-gray-300 rounded hover:bg-gray-100"
                >
                    Tout déplier
                </button>
                <button
                    onClick={() => setExpanded({})}
                    data-testid="collapse-all"
                    className="h-7 px-2 text-xs text-gray-700 border border-gray-300 rounded hover:bg-gray-100"
                >
                    Tout replier
                </button>
                <span className="ml-auto text-xs text-gray-500 whitespace-nowrap">
                    {totalAllees.toLocaleString("fr-FR")} allées
                </span>
            </div>

            <div className="flex-1 overflow-auto custom-scroll">
                {tree.map((s) => {
                    const secKey = `s:${s.secteur}`;
                    const secOpen = expanded[secKey] !== false; // ouvert par défaut
                    return (
                        <div key={s.secteur} data-testid={`secteur-block-${s.secteur}`}>
                            <button
                                onClick={() => toggle(secKey)}
                                className="w-full flex items-center gap-2 px-3 py-2 bg-[#056839] text-white text-sm font-semibold sticky top-0 z-10 hover:bg-[#04502b]"
                            >
                                {secOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                                <span>{s.secteur}</span>
                                <span className="ml-auto text-xs opacity-90">
                                    {s.rayons.length} rayon{s.rayons.length > 1 ? "s" : ""} · {fmtNum(s.total)} éléments
                                </span>
                            </button>
                            {secOpen &&
                                s.rayons.map((r) => {
                                    const rayKey = `r:${s.secteur}|${r.rayon}`;
                                    const rayOpen = expanded[rayKey] !== false;
                                    return (
                                        <div key={r.rayon}>
                                            <button
                                                onClick={() => toggle(rayKey)}
                                                className="w-full flex items-center gap-2 px-3 py-1.5 bg-emerald-100 text-emerald-900 text-sm font-medium pl-8 hover:bg-emerald-200 border-b border-emerald-200"
                                            >
                                                {rayOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                                                <span>{r.rayon}</span>
                                                <span className="ml-auto text-xs text-emerald-800">
                                                    {r.allees.length} allée{r.allees.length > 1 ? "s" : ""} · {fmtNum(r.total)} éléments
                                                </span>
                                            </button>
                                            {rayOpen &&
                                                r.allees.map((a) => {
                                                    const allKey = `a:${s.secteur}|${r.rayon}|${a.allee}`;
                                                    const allOpen = !!expanded[allKey];
                                                    const typeChips = Object.entries(a.byType)
                                                        .sort(([x], [y]) => x.localeCompare(y))
                                                        .map(([t, n]) => `${t}: ${fmtNum(n)}`)
                                                        .join(" · ");
                                                    return (
                                                        <div key={a.allee} className="border-b border-gray-100">
                                                            <button
                                                                onClick={() => toggle(allKey)}
                                                                className="w-full flex items-center gap-2 px-3 py-1.5 bg-white hover:bg-blue-50 text-sm pl-14 text-gray-800"
                                                                data-testid={`allee-${s.secteur}-${r.rayon}-${a.allee}`}
                                                            >
                                                                {allOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                                                                <span className="font-mono-data font-medium">Allée {a.allee}</span>
                                                                <span className="text-gray-500 text-xs">— {fmtNum(a.total)} éléments</span>
                                                                <span className="ml-auto text-xs text-gray-500 truncate">{typeChips}</span>
                                                            </button>
                                                            {allOpen && (
                                                                <div className="pl-20 bg-gray-50 border-t border-gray-200">
                                                                    <table className="w-full text-sm">
                                                                        <thead>
                                                                            <tr className="text-xs text-gray-600">
                                                                                <th className="text-left py-1 pr-3 font-medium">Type</th>
                                                                                <th className="text-left py-1 pr-3 font-medium">Désignation</th>
                                                                                <th className="text-right py-1 pr-3 font-medium">Qté</th>
                                                                            </tr>
                                                                        </thead>
                                                                        <tbody>
                                                                            {a.products.map((p, idx) => (
                                                                                <tr key={`${p.type}|${p.designation}|${idx}`} className="border-t border-gray-200">
                                                                                    <td className="py-1 pr-3 text-gray-700">{p.type}</td>
                                                                                    <td className="py-1 pr-3 text-gray-800">{p.designation}</td>
                                                                                    <td className="py-1 pr-3 text-right font-mono-data text-gray-700">{fmtNum(p.qty)}</td>
                                                                                </tr>
                                                                            ))}
                                                                        </tbody>
                                                                    </table>
                                                                </div>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                        </div>
                                    );
                                })}
                        </div>
                    );
                })}
                {tree.length === 0 && (
                    <div className="p-8 text-center text-sm text-gray-500">Aucun résultat</div>
                )}
            </div>
        </div>
    );
}
