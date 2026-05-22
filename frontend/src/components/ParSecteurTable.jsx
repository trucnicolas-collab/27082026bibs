import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown, Download } from "lucide-react";

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

function cmp(a, b) {
    if (a === b) return 0;
    if (a == null || a === "") return 1;
    if (b == null || b === "") return -1;
    const nA = typeof a === "number" ? a : parseFloat(String(a).replace(",", "."));
    const nB = typeof b === "number" ? b : parseFloat(String(b).replace(",", "."));
    if (!isNaN(nA) && !isNaN(nB)) return nA - nB;
    return String(a).localeCompare(String(b), "fr", { numeric: true });
}

function typeBreakdownToChips(byType) {
    return Object.entries(byType)
        .sort(([x], [y]) => x.localeCompare(y))
        .map(([t, n]) => `${t}: ${fmtNum(n)}`)
        .join(" · ");
}

export default function ParSecteurTable({ rows, columns, search, uploadId }) {
    const SECTEUR = findCol(columns, ["Secteur"]) || "Secteur";
    const RAYON = findCol(columns, ["Rayon"]) || "Rayon";
    const ALLEE = findCol(columns, ["N° allée", "N° allee", "Allée", "Allee"]) || "N° allée";
    const ELEMENT = findCol(columns, ["N° élément", "N° element", "Élément", "Element"]) || "N° élément";
    const TYPE = findCol(columns, ["Type"]);
    const DESIG = findCol(columns, ["Désignation", "Designation"]);
    const QTY = findCol(columns, ["Quantité", "Quantite"]);

    const [filterSecteur, setFilterSecteur] = useState("");
    const [filterRayon, setFilterRayon] = useState("");
    const [expanded, setExpanded] = useState({});

    const toggle = (key) => setExpanded((p) => ({ ...p, [key]: !p[key] }));

    // Tree: Secteur > Rayon > Allée > Element > Products
    const tree = useMemo(() => {
        const q = (search || "").toLowerCase();
        const map = new Map();
        for (const r of rows) {
            const s = r[SECTEUR] == null ? "—" : String(r[SECTEUR]);
            const ra = r[RAYON] == null ? "—" : String(r[RAYON]);
            const al = r[ALLEE] == null ? "—" : String(r[ALLEE]);
            const el = r[ELEMENT] == null ? "—" : String(r[ELEMENT]);
            if (filterSecteur && s !== filterSecteur) continue;
            if (filterRayon && ra !== filterRayon) continue;
            if (q && !columns.some((c) => r[c] != null && String(r[c]).toLowerCase().includes(q))) continue;

            if (!map.has(s)) map.set(s, new Map());
            const rayMap = map.get(s);
            if (!rayMap.has(ra)) rayMap.set(ra, new Map());
            const allMap = rayMap.get(ra);
            if (!allMap.has(al)) allMap.set(al, { elements: new Map(), byType: {}, total: 0 });
            const alNode = allMap.get(al);
            if (!alNode.elements.has(el)) alNode.elements.set(el, { products: [], byType: {}, total: 0 });
            const elNode = alNode.elements.get(el);

            const qty = QTY ? Number(r[QTY]) || 0 : 1;
            const typ = TYPE ? (r[TYPE] || "—") : "—";
            const desig = DESIG ? (r[DESIG] || "") : "";

            elNode.products.push({ type: typ, designation: desig, qty });
            elNode.total += qty;
            elNode.byType[typ] = (elNode.byType[typ] || 0) + qty;
            alNode.total += qty;
            alNode.byType[typ] = (alNode.byType[typ] || 0) + qty;
        }
        // Materialize sorted arrays
        return Array.from(map.entries())
            .sort(([a], [b]) => cmp(a, b))
            .map(([secteur, rayMap]) => {
                const rayons = Array.from(rayMap.entries())
                    .sort(([a], [b]) => cmp(a, b))
                    .map(([rayon, allMap]) => {
                        const allees = Array.from(allMap.entries())
                            .sort(([a], [b]) => cmp(a, b))
                            .map(([allee, data]) => {
                                const elements = Array.from(data.elements.entries())
                                    .sort(([a], [b]) => cmp(a, b))
                                    .map(([el, eData]) => ({ element: el, ...eData }));
                                return { allee, elements, byType: data.byType, total: data.total };
                            });
                        return {
                            rayon,
                            allees,
                            total: allees.reduce((acc, a) => acc + a.total, 0),
                            nbAllees: allees.length,
                            nbElements: allees.reduce((acc, a) => acc + a.elements.length, 0),
                        };
                    });
                return {
                    secteur,
                    rayons,
                    total: rayons.reduce((acc, r) => acc + r.total, 0),
                    nbElements: rayons.reduce((acc, r) => acc + r.nbElements, 0),
                };
            });
    }, [rows, columns, search, filterSecteur, filterRayon, SECTEUR, RAYON, ALLEE, ELEMENT, TYPE, DESIG, QTY]);

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

    // Export du fichier Excel global (inclut "Par Secteur" hiérarchique)
    const handleExportView = async () => {
        if (!uploadId) return;
        const url = `${process.env.REACT_APP_BACKEND_URL}/api/export/${uploadId}?sheet=parsecteur`;
        window.location.href = url;
    };

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
                <button
                    onClick={handleExportView}
                    data-testid="export-parsecteur"
                    className="h-7 px-2.5 text-xs font-medium bg-[#056839] text-white rounded hover:bg-[#04502b] flex items-center gap-1.5"
                    title="Exporter l'onglet Par Secteur en Excel (avec filtres natifs)"
                >
                    <Download className="w-3.5 h-3.5" />
                    Exporter cette vue
                </button>
                <span className="ml-auto text-xs text-gray-500 whitespace-nowrap">
                    {totalAllees.toLocaleString("fr-FR")} allées
                </span>
            </div>

            <div className="flex-1 overflow-auto custom-scroll">
                {tree.map((s) => {
                    const secKey = `s:${s.secteur}`;
                    const secOpen = expanded[secKey] !== false;
                    return (
                        <div key={s.secteur} data-testid={`secteur-block-${s.secteur}`}>
                            <button
                                onClick={() => toggle(secKey)}
                                className="w-full flex items-center gap-2 px-3 py-2 bg-[#056839] text-white text-sm font-semibold sticky top-0 z-10 hover:bg-[#04502b]"
                            >
                                {secOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                                <span>{s.secteur}</span>
                                <span className="ml-auto text-xs opacity-90">
                                    {s.rayons.length} rayon{s.rayons.length > 1 ? "s" : ""} · {fmtNum(s.nbElements)} gondoles · {fmtNum(s.total)} éléments
                                </span>
                            </button>
                            {secOpen && s.rayons.map((r) => {
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
                                                {r.allees.length} allée{r.allees.length > 1 ? "s" : ""} · {fmtNum(r.nbElements)} gondoles · {fmtNum(r.total)} éléments
                                            </span>
                                        </button>
                                        {rayOpen && r.allees.map((a) => {
                                            const allKey = `a:${s.secteur}|${r.rayon}|${a.allee}`;
                                            const allOpen = !!expanded[allKey];
                                            return (
                                                <div key={a.allee} className="border-b border-gray-100">
                                                    <button
                                                        onClick={() => toggle(allKey)}
                                                        className="w-full flex items-center gap-2 px-3 py-1.5 bg-white hover:bg-blue-50 text-sm pl-14 text-gray-800"
                                                        data-testid={`allee-${s.secteur}-${r.rayon}-${a.allee}`}
                                                    >
                                                        {allOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                                                        <span className="font-mono-data font-medium">Allée {a.allee}</span>
                                                        <span className="text-gray-500 text-xs">
                                                            — {a.elements.length} gondole{a.elements.length > 1 ? "s" : ""} · {fmtNum(a.total)} éléments
                                                        </span>
                                                        <span className="ml-auto text-xs text-gray-500 truncate max-w-[60%]">
                                                            {typeBreakdownToChips(a.byType)}
                                                        </span>
                                                    </button>
                                                    {allOpen && a.elements.map((e) => {
                                                        const elKey = `e:${s.secteur}|${r.rayon}|${a.allee}|${e.element}`;
                                                        const elOpen = !!expanded[elKey];
                                                        return (
                                                            <div key={e.element} className="bg-gray-50 border-t border-gray-200">
                                                                <button
                                                                    onClick={() => toggle(elKey)}
                                                                    className="w-full flex items-center gap-2 px-3 py-1 pl-20 text-xs text-gray-700 hover:bg-amber-50"
                                                                >
                                                                    {elOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                                                                    <span className="font-mono-data">Gondole {e.element}</span>
                                                                    <span className="text-gray-500">— {fmtNum(e.total)} éléments</span>
                                                                    <span className="ml-auto text-gray-500 truncate max-w-[55%]">
                                                                        {typeBreakdownToChips(e.byType)}
                                                                    </span>
                                                                </button>
                                                                {elOpen && (
                                                                    <div className="pl-28 bg-white border-t border-gray-200">
                                                                        <table className="w-full text-sm">
                                                                            <thead>
                                                                                <tr className="text-xs text-gray-600">
                                                                                    <th className="text-left py-1 pr-3 font-medium">Type</th>
                                                                                    <th className="text-left py-1 pr-3 font-medium">Désignation</th>
                                                                                    <th className="text-right py-1 pr-3 font-medium">Qté</th>
                                                                                </tr>
                                                                            </thead>
                                                                            <tbody>
                                                                                {e.products.map((p, idx) => (
                                                                                    <tr key={`${p.type}|${p.designation}|${idx}`} className="border-t border-gray-100">
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
