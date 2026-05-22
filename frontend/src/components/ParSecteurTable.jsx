import React, { useMemo, useState } from "react";
import { FixedSizeList as List } from "react-window";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";

const ROW_HEIGHT = 32;
const COL_WIDTH = 140;

function formatCell(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "number") {
        if (Number.isInteger(value)) return value.toLocaleString("fr-FR");
        return value.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }
    return String(value);
}

// Tri intelligent (numérique si possible, sinon localeCompare)
function compareValues(a, b) {
    if (a === b) return 0;
    if (a == null || a === "") return 1;
    if (b == null || b === "") return -1;
    const numA = typeof a === "number" ? a : parseFloat(String(a).replace(",", "."));
    const numB = typeof b === "number" ? b : parseFloat(String(b).replace(",", "."));
    if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
    return String(a).localeCompare(String(b), "fr", { numeric: true });
}

// Détection souple du nom de colonne
function findCol(columns, candidates) {
    const lower = columns.map((c) => c.toLowerCase());
    for (const cand of candidates) {
        const idx = lower.indexOf(cand.toLowerCase());
        if (idx !== -1) return columns[idx];
    }
    return null;
}

export default function ParSecteurTable({ rows, columns, search }) {
    const SECTEUR_COL = findCol(columns, ["Secteur"]) || "Secteur";
    const RAYON_COL = findCol(columns, ["Rayon"]) || "Rayon";
    const ALLEE_COL = findCol(columns, ["N° allée", "N° allee", "Allée", "Allee"]) || "N° allée";
    const TYPE_COL = findCol(columns, ["Type"]);

    const [filterSecteur, setFilterSecteur] = useState("");
    const [filterRayon, setFilterRayon] = useState("");
    const [filterAllee, setFilterAllee] = useState("");
    const [filterType, setFilterType] = useState("");
    const [sortConfig, setSortConfig] = useState({ key: null, dir: "asc" });

    const handleSort = (key) => {
        setSortConfig((prev) => {
            if (prev.key !== key) return { key, dir: "asc" };
            if (prev.dir === "asc") return { key, dir: "desc" };
            return { key: null, dir: "asc" };
        });
    };

    const secteurOptions = useMemo(() => {
        const set = new Set();
        rows.forEach((r) => r[SECTEUR_COL] != null && set.add(r[SECTEUR_COL]));
        return Array.from(set).map(String).sort();
    }, [rows, SECTEUR_COL]);

    const rayonOptions = useMemo(() => {
        const set = new Set();
        rows.forEach((r) => {
            if (filterSecteur && String(r[SECTEUR_COL]) !== filterSecteur) return;
            if (r[RAYON_COL] != null) set.add(r[RAYON_COL]);
        });
        return Array.from(set).map(String).sort();
    }, [rows, filterSecteur, SECTEUR_COL, RAYON_COL]);

    const alleeOptions = useMemo(() => {
        const set = new Set();
        rows.forEach((r) => {
            if (filterSecteur && String(r[SECTEUR_COL]) !== filterSecteur) return;
            if (filterRayon && String(r[RAYON_COL]) !== filterRayon) return;
            if (r[ALLEE_COL] != null) set.add(r[ALLEE_COL]);
        });
        return Array.from(set)
            .map(String)
            .sort((a, b) => compareValues(a, b));
    }, [rows, filterSecteur, filterRayon, SECTEUR_COL, RAYON_COL, ALLEE_COL]);

    const typeOptions = useMemo(() => {
        if (!TYPE_COL) return [];
        const set = new Set();
        rows.forEach((r) => r[TYPE_COL] != null && set.add(r[TYPE_COL]));
        return Array.from(set).map(String).sort();
    }, [rows, TYPE_COL]);

    const filtered = useMemo(() => {
        const q = (search || "").toLowerCase();
        // 1) filtrer
        let res = rows.filter((r) => {
            if (filterSecteur && String(r[SECTEUR_COL]) !== filterSecteur) return false;
            if (filterRayon && String(r[RAYON_COL]) !== filterRayon) return false;
            if (filterAllee && String(r[ALLEE_COL]) !== filterAllee) return false;
            if (filterType && TYPE_COL && String(r[TYPE_COL]) !== filterType) return false;
            if (!q) return true;
            return columns.some((c) => {
                const v = r[c];
                return v != null && String(v).toLowerCase().includes(q);
            });
        });
        // 2) trier : par défaut Secteur > Rayon > Allée ; sinon par la colonne cliquée
        if (sortConfig.key) {
            const k = sortConfig.key;
            const sign = sortConfig.dir === "asc" ? 1 : -1;
            res = [...res].sort((a, b) => sign * compareValues(a[k], b[k]));
        } else {
            res = [...res].sort((a, b) => {
                let c = compareValues(a[SECTEUR_COL], b[SECTEUR_COL]);
                if (c !== 0) return c;
                c = compareValues(a[RAYON_COL], b[RAYON_COL]);
                if (c !== 0) return c;
                return compareValues(a[ALLEE_COL], b[ALLEE_COL]);
            });
        }
        return res;
    }, [rows, columns, search, filterSecteur, filterRayon, filterAllee, filterType, sortConfig, SECTEUR_COL, RAYON_COL, ALLEE_COL, TYPE_COL]);

    const clearFilters = () => {
        setFilterSecteur("");
        setFilterRayon("");
        setFilterAllee("");
        setFilterType("");
        setSortConfig({ key: null, dir: "asc" });
    };

    const totalWidth = columns.length * COL_WIDTH;

    const Row = ({ index, style }) => {
        const r = filtered[index];
        return (
            <div
                style={style}
                className={`flex border-b border-gray-200 ${index % 2 === 0 ? "bg-white" : "bg-gray-50"} hover:bg-blue-50`}
                data-testid={`parsecteur-row-${index}`}
            >
                {columns.map((c, i) => (
                    <div
                        key={i}
                        className="px-3 py-1.5 text-sm border-r border-gray-200 last:border-r-0 truncate font-mono-data"
                        style={{ width: COL_WIDTH, minWidth: COL_WIDTH }}
                        title={formatCell(r[c])}
                    >
                        {formatCell(r[c])}
                    </div>
                ))}
            </div>
        );
    };

    return (
        <div className="h-full flex flex-col bg-white" data-testid="parsecteur-table">
            <div className="h-10 border-b border-gray-200 px-3 flex items-center gap-2 bg-gray-50 flex-shrink-0 overflow-x-auto">
                <span className="text-xs font-medium text-gray-700 whitespace-nowrap">Filtres :</span>
                <select
                    value={filterSecteur}
                    onChange={(e) => {
                        setFilterSecteur(e.target.value);
                        setFilterRayon("");
                        setFilterAllee("");
                    }}
                    data-testid="parsecteur-filter-secteur"
                    className="h-7 px-2 text-sm border border-gray-300 rounded bg-white focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                >
                    <option value="">Tous les secteurs</option>
                    {secteurOptions.map((s) => (
                        <option key={s} value={s}>
                            {s}
                        </option>
                    ))}
                </select>
                <select
                    value={filterRayon}
                    onChange={(e) => {
                        setFilterRayon(e.target.value);
                        setFilterAllee("");
                    }}
                    data-testid="parsecteur-filter-rayon"
                    className="h-7 px-2 text-sm border border-gray-300 rounded bg-white focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                >
                    <option value="">Tous les rayons</option>
                    {rayonOptions.map((r) => (
                        <option key={r} value={r}>
                            {r}
                        </option>
                    ))}
                </select>
                <select
                    value={filterAllee}
                    onChange={(e) => setFilterAllee(e.target.value)}
                    data-testid="parsecteur-filter-allee"
                    className="h-7 px-2 text-sm border border-gray-300 rounded bg-white focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                >
                    <option value="">Toutes les allées</option>
                    {alleeOptions.map((a) => (
                        <option key={a} value={a}>
                            {a}
                        </option>
                    ))}
                </select>
                {TYPE_COL && (
                    <select
                        value={filterType}
                        onChange={(e) => setFilterType(e.target.value)}
                        data-testid="parsecteur-filter-type"
                        className="h-7 px-2 text-sm border border-gray-300 rounded bg-white focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                    >
                        <option value="">Tous les types</option>
                        {typeOptions.map((t) => (
                            <option key={t} value={t}>
                                {t}
                            </option>
                        ))}
                    </select>
                )}
                {(filterSecteur || filterRayon || filterAllee || filterType || sortConfig.key) && (
                    <button
                        onClick={clearFilters}
                        data-testid="parsecteur-clear-filters"
                        className="text-xs text-gray-600 hover:text-gray-900 underline whitespace-nowrap"
                    >
                        Effacer
                    </button>
                )}
                <span className="ml-auto text-xs text-gray-500 whitespace-nowrap">
                    {filtered.length.toLocaleString("fr-FR")} / {rows.length.toLocaleString("fr-FR")} lignes
                </span>
            </div>

            <div className="flex-1 overflow-auto custom-scroll">
                <div style={{ minWidth: totalWidth }}>
                    <div className="flex sticky top-0 z-10 bg-gray-100 thead-sticky">
                        {columns.map((c, i) => {
                            const isActive = sortConfig.key === c;
                            const Icon = isActive ? (sortConfig.dir === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown;
                            return (
                                <div
                                    key={i}
                                    onClick={() => handleSort(c)}
                                    data-testid={`parsecteur-sort-${c}`}
                                    className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 last:border-r-0 truncate cursor-pointer select-none hover:bg-gray-200 flex items-center gap-1"
                                    style={{ width: COL_WIDTH, minWidth: COL_WIDTH }}
                                    title={c}
                                >
                                    <span className="truncate">{c}</span>
                                    <Icon className={`w-3 h-3 flex-shrink-0 ${isActive ? "text-[#056839]" : "text-gray-400"}`} />
                                </div>
                            );
                        })}
                    </div>
                    <List
                        height={Math.max(window.innerHeight - 56 - 40 - 40 - 28, 300)}
                        itemCount={filtered.length}
                        itemSize={ROW_HEIGHT}
                        width={totalWidth}
                    >
                        {Row}
                    </List>
                </div>
            </div>
            <div className="h-7 border-t border-gray-200 px-3 flex items-center text-xs text-gray-600 bg-gray-50 flex-shrink-0">
                <span data-testid="parsecteur-row-count">
                    {filtered.length.toLocaleString("fr-FR")} ligne{filtered.length > 1 ? "s" : ""}
                    {!sortConfig.key && <span className="ml-2 text-gray-500">· trié par Secteur → Rayon → Allée</span>}
                    {sortConfig.key && (
                        <span className="ml-2 text-gray-500">
                            · trié par {sortConfig.key} {sortConfig.dir === "asc" ? "↑" : "↓"}
                        </span>
                    )}
                </span>
            </div>
        </div>
    );
}
