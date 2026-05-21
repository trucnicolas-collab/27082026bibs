import React, { useMemo, useState } from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";

function fmtNum(v) {
    if (v === "" || v === null || v === undefined) return "";
    if (typeof v === "number") {
        if (Number.isInteger(v)) return v.toLocaleString("fr-FR");
        return v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }
    return v;
}

// Tri intelligent : nombres > strings (compatible avec allee qui est string mais représente un nombre)
function compareValues(a, b) {
    if (a === b) return 0;
    if (a == null || a === "") return 1;
    if (b == null || b === "") return -1;
    const numA = typeof a === "number" ? a : parseFloat(String(a).replace(",", "."));
    const numB = typeof b === "number" ? b : parseFloat(String(b).replace(",", "."));
    if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
    return String(a).localeCompare(String(b), "fr", { numeric: true });
}

function SortableHeader({ label, sortKey, sortConfig, onSort, align = "left", className = "" }) {
    const isActive = sortConfig.key === sortKey;
    const Icon = isActive ? (sortConfig.dir === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown;
    return (
        <th
            onClick={() => onSort(sortKey)}
            data-testid={`sort-${sortKey}`}
            className={`px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 whitespace-nowrap cursor-pointer select-none hover:bg-gray-200 ${className}`}
        >
            <span className={`flex items-center gap-1 ${align === "right" ? "justify-end" : ""}`}>
                {label}
                <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? "text-[#056839]" : "text-gray-400"}`} />
            </span>
        </th>
    );
}

export default function SecteurTable({ rows, search }) {
    const [filterSecteur, setFilterSecteur] = useState("");
    const [filterRayon, setFilterRayon] = useState("");
    const [sortConfig, setSortConfig] = useState({ key: null, dir: "asc" });

    const handleSort = (key) => {
        setSortConfig((prev) => {
            if (prev.key !== key) return { key, dir: "asc" };
            if (prev.dir === "asc") return { key, dir: "desc" };
            return { key: null, dir: "asc" }; // 3e clic = reset
        });
    };

    const secteurOptions = useMemo(() => {
        const set = new Set();
        rows.forEach((r) => r.secteur && set.add(r.secteur));
        return Array.from(set).sort();
    }, [rows]);

    const rayonOptions = useMemo(() => {
        const set = new Set();
        rows.forEach((r) => {
            if (filterSecteur && r.secteur !== filterSecteur) return;
            if (r.rayon) set.add(r.rayon);
        });
        return Array.from(set).sort();
    }, [rows, filterSecteur]);

    const filtered = useMemo(() => {
        const q = search.toLowerCase();
        let res = rows.filter((r) => {
            if (filterSecteur && r.secteur !== filterSecteur) return false;
            if (filterRayon && r.rayon !== filterRayon) return false;
            if (!q) return true;
            return (
                (r.secteur && r.secteur.toLowerCase().includes(q)) ||
                (r.rayon && r.rayon.toLowerCase().includes(q)) ||
                (r.allee && String(r.allee).toLowerCase().includes(q))
            );
        });
        if (sortConfig.key) {
            const k = sortConfig.key;
            const sign = sortConfig.dir === "asc" ? 1 : -1;
            res = [...res].sort((a, b) => sign * compareValues(a[k], b[k]));
        }
        return res;
    }, [rows, search, filterSecteur, filterRayon, sortConfig]);

    const totals = useMemo(() => {
        return filtered.reduce(
            (acc, r) => {
                acc.es += r.nb_eeg_es || 0;
                acc.sa += r.nb_eeg_sa || 0;
                acc.rail += r.nb_rail || 0;
                acc.cam += r.nb_camera || 0;
                return acc;
            },
            { es: 0, sa: 0, rail: 0, cam: 0 }
        );
    }, [filtered]);

    const clearFilters = () => {
        setFilterSecteur("");
        setFilterRayon("");
        setSortConfig({ key: null, dir: "asc" });
    };

    return (
        <div className="h-full flex flex-col bg-white" data-testid="secteur-table">
            <div className="h-10 border-b border-gray-200 px-3 flex items-center gap-3 bg-gray-50 flex-shrink-0">
                <span className="text-xs font-medium text-gray-700">Filtres :</span>
                <select
                    value={filterSecteur}
                    onChange={(e) => {
                        setFilterSecteur(e.target.value);
                        setFilterRayon("");
                    }}
                    data-testid="filter-secteur"
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
                    onChange={(e) => setFilterRayon(e.target.value)}
                    data-testid="filter-rayon"
                    className="h-7 px-2 text-sm border border-gray-300 rounded bg-white focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                >
                    <option value="">Tous les rayons</option>
                    {rayonOptions.map((r) => (
                        <option key={r} value={r}>
                            {r}
                        </option>
                    ))}
                </select>
                {(filterSecteur || filterRayon || sortConfig.key) && (
                    <button
                        onClick={clearFilters}
                        data-testid="clear-filters"
                        className="text-xs text-gray-600 hover:text-gray-900 underline"
                    >
                        Effacer
                    </button>
                )}
                <span className="ml-auto text-xs text-gray-500">
                    {filtered.length.toLocaleString("fr-FR")} / {rows.length.toLocaleString("fr-FR")} allées
                </span>
            </div>

            <div className="flex-1 overflow-auto custom-scroll">
                <table className="border-collapse text-left">
                    <thead className="sticky top-0 z-10 bg-gray-100 thead-sticky">
                        <tr>
                            <SortableHeader label="Secteur" sortKey="secteur" sortConfig={sortConfig} onSort={handleSort} />
                            <SortableHeader label="Rayon" sortKey="rayon" sortConfig={sortConfig} onSort={handleSort} />
                            <SortableHeader label="N° Allée" sortKey="allee" sortConfig={sortConfig} onSort={handleSort} align="right" />
                            <SortableHeader label="EEG ES" sortKey="nb_eeg_es" sortConfig={sortConfig} onSort={handleSort} align="right" />
                            <SortableHeader label="EEG SA" sortKey="nb_eeg_sa" sortConfig={sortConfig} onSort={handleSort} align="right" />
                            <SortableHeader label="Rails" sortKey="nb_rail" sortConfig={sortConfig} onSort={handleSort} align="right" />
                            <SortableHeader label="Caméras" sortKey="nb_camera" sortConfig={sortConfig} onSort={handleSort} align="right" className="border-r-0" />
                            <th className="w-full" />
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((r, i) => (
                            <tr
                                key={i}
                                className={`${i % 2 === 0 ? "bg-white" : "bg-gray-50"} hover:bg-blue-50 border-b border-gray-200`}
                                data-testid={`secteur-row-${i}`}
                            >
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 whitespace-nowrap">{r.secteur}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 whitespace-nowrap">{r.rayon}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data text-right whitespace-nowrap">{r.allee}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data text-right whitespace-nowrap">{fmtNum(r.nb_eeg_es)}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data text-right whitespace-nowrap">{fmtNum(r.nb_eeg_sa)}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data text-right whitespace-nowrap">{fmtNum(r.nb_rail)}</td>
                                <td className="px-3 py-1.5 text-sm font-mono-data text-right whitespace-nowrap">{fmtNum(r.nb_camera)}</td>
                                <td />
                            </tr>
                        ))}
                        {filtered.length === 0 && (
                            <tr>
                                <td colSpan={8} className="px-3 py-8 text-center text-sm text-gray-500">
                                    Aucun résultat
                                </td>
                            </tr>
                        )}
                    </tbody>
                    {filtered.length > 0 && (
                        <tfoot className="sticky bottom-0 bg-yellow-50">
                            <tr className="border-t-2 border-gray-400 font-semibold" data-testid="secteur-totals">
                                <td colSpan={3} className="px-3 py-2 text-sm text-gray-900 whitespace-nowrap">
                                    TOTAL
                                </td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right whitespace-nowrap">{fmtNum(totals.es)}</td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right whitespace-nowrap">{fmtNum(totals.sa)}</td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right whitespace-nowrap">{fmtNum(totals.rail)}</td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right whitespace-nowrap">{fmtNum(totals.cam)}</td>
                                <td />
                            </tr>
                        </tfoot>
                    )}
                </table>
            </div>
            <div className="h-7 border-t border-gray-200 px-3 flex items-center text-xs text-gray-600 bg-gray-50 flex-shrink-0">
                <span data-testid="secteur-row-count">
                    {filtered.length.toLocaleString("fr-FR")} allées
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
