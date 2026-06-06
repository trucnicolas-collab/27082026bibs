import React, { useEffect, useMemo, useState, useRef } from "react";
import axios from "axios";
import { Loader2, AlertCircle, X, Filter } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function fmtNum(v) {
    if (v === "" || v === null || v === undefined) return "";
    if (typeof v === "number" && Number.isFinite(v)) {
        return Number.isInteger(v) ? v.toLocaleString("fr-FR") : v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }
    return String(v);
}

// Colonnes masquées par défaut (ne servent pas à l'utilisateur final)
const HIDDEN_COLS = new Set(["ID", "Photo allée", "📷Allée"]);

function isHiddenCol(name) {
    if (!name) return false;
    if (HIDDEN_COLS.has(name)) return true;
    // tolérance casse / espaces / accents
    const n = String(name).trim().toLowerCase();
    if (n === "id" || n === "photo allée" || n === "photo allee") return true;
    // "📷Allée" / "📷 Allée" / variantes avec/sans accent
    const stripped = n.replace(/📷|📸/g, "").trim();
    if (stripped === "allée" || stripped === "allee") return true;
    return false;
}

/**
 * Onglet "Autre" : affiche les lignes du fichier original dont
 *   Type == "Fixation" ET Référence commence par "AUTRE".
 * Lecture seule. Filtres par colonne + recherche globale.
 */
export default function AutreTab({ uploadId, search = "", endpoint }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [colFilters, setColFilters] = useState({});  // { col: "texte filtre" }
    const [openFilter, setOpenFilter] = useState(null); // col actuellement ouvert (dropdown)
    const filterDropdownRef = useRef(null);

    const fetchData = React.useCallback(async () => {
        if (!uploadId && !endpoint) return;
        setLoading(true);
        const url = endpoint || `${API}/dataset/${uploadId}/autre`;
        try {
            const res = await axios.get(url);
            setData(res.data);
            setError(null);
        } catch (e) {
            setError(e.response?.data?.detail || e.message);
        } finally {
            setLoading(false);
        }
    }, [uploadId, endpoint]);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    // Fermer le dropdown au clic en dehors
    useEffect(() => {
        if (!openFilter) return;
        const onClick = (e) => {
            if (filterDropdownRef.current && !filterDropdownRef.current.contains(e.target)) {
                setOpenFilter(null);
            }
        };
        document.addEventListener("mousedown", onClick);
        return () => document.removeEventListener("mousedown", onClick);
    }, [openFilter]);

    const allColumns = data?.columns || [];
    const rows = data?.rows || [];
    // Colonnes affichées : on retire ID et Photo allée
    const columns = useMemo(() => allColumns.filter((c) => !isHiddenCol(c)), [allColumns]);

    // Valeurs uniques par colonne (utilisées dans le dropdown de filtre)
    const uniqueValuesByCol = useMemo(() => {
        const map = {};
        for (const c of columns) {
            const set = new Set();
            for (const r of rows) {
                const v = r[c];
                if (v !== null && v !== undefined && v !== "") {
                    set.add(String(v));
                }
            }
            map[c] = Array.from(set).sort((a, b) => a.localeCompare(b, "fr", { numeric: true }));
        }
        return map;
    }, [columns, rows]);

    const filtered = useMemo(() => {
        const q = search.toLowerCase();
        const activeFilters = Object.entries(colFilters).filter(([, v]) => v && String(v).trim());
        return rows.filter((r) => {
            // Recherche globale (utilise toutes les cols, même cachées)
            if (q && !Object.values(r).some((v) => String(v ?? "").toLowerCase().includes(q))) {
                return false;
            }
            // Filtres par colonne (texte "contient")
            for (const [col, fval] of activeFilters) {
                const cell = String(r[col] ?? "").toLowerCase();
                if (!cell.includes(String(fval).toLowerCase())) return false;
            }
            return true;
        });
    }, [rows, search, colFilters]);

    const setColFilter = (col, value) => {
        setColFilters((prev) => {
            const next = { ...prev };
            if (!value) delete next[col];
            else next[col] = value;
            return next;
        });
    };

    const clearAllFilters = () => setColFilters({});
    const activeCount = Object.values(colFilters).filter((v) => v && String(v).trim()).length;

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full text-sm text-gray-500" data-testid="autre-loading">
                <Loader2 className="w-4 h-4 animate-spin mr-2" /> Chargement…
            </div>
        );
    }
    if (error) {
        return (
            <div className="p-8 text-sm text-red-600" data-testid="autre-error">
                <AlertCircle className="w-4 h-4 inline-block mr-1" /> {error}
            </div>
        );
    }
    if (!rows.length) {
        return (
            <div className="flex items-center justify-center h-full text-sm text-gray-500 italic" data-testid="autre-empty">
                Aucune fixation « AUTRE » dans le fichier original.
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-white" data-testid="autre-tab">
            <div className="border-b border-gray-200 px-3 py-2 bg-amber-50/60 flex items-center gap-3 flex-shrink-0">
                <span className="text-sm font-semibold text-amber-900">Fixations « AUTRE »</span>
                <span className="text-xs text-amber-800 italic">
                    {filtered.length} / {rows.length} ligne{rows.length > 1 ? "s" : ""} · lecture seule
                </span>
                {activeCount > 0 && (
                    <button
                        onClick={clearAllFilters}
                        data-testid="autre-clear-filters"
                        className="ml-auto h-6 px-2 text-xs bg-amber-100 hover:bg-amber-200 border border-amber-300 rounded flex items-center gap-1 text-amber-900 transition-colors"
                        title="Effacer tous les filtres"
                    >
                        <X className="w-3 h-3" /> Effacer {activeCount} filtre{activeCount > 1 ? "s" : ""}
                    </button>
                )}
            </div>
            <div className="flex-1 overflow-auto custom-scroll">
                <table className="border-collapse text-sm">
                    <thead className="sticky top-0 z-10 bg-gray-100 thead-sticky">
                        <tr>
                            <th className="px-2 py-1.5 text-left text-xs font-semibold text-gray-700 border-b border-gray-300 w-12">#</th>
                            {columns.map((c) => {
                                const isFilterActive = !!(colFilters[c] && String(colFilters[c]).trim());
                                return (
                                    <th
                                        key={c}
                                        className="px-3 py-1.5 text-left text-xs font-semibold text-gray-700 border-b border-gray-300 whitespace-nowrap relative"
                                    >
                                        <div className="flex items-center gap-1.5">
                                            <span>{c}</span>
                                            <button
                                                onClick={() => setOpenFilter(openFilter === c ? null : c)}
                                                data-testid={`autre-filter-toggle-${c}`}
                                                className={`p-0.5 rounded transition-colors ${
                                                    isFilterActive
                                                        ? "bg-amber-500 text-white"
                                                        : "text-gray-400 hover:text-gray-700 hover:bg-gray-200"
                                                }`}
                                                title={isFilterActive ? `Filtré: "${colFilters[c]}"` : "Filtrer"}
                                            >
                                                <Filter className="w-3 h-3" />
                                            </button>
                                        </div>
                                        {openFilter === c && (
                                            <FilterDropdown
                                                ref={filterDropdownRef}
                                                col={c}
                                                value={colFilters[c] || ""}
                                                uniqueValues={uniqueValuesByCol[c] || []}
                                                onChange={(v) => setColFilter(c, v)}
                                                onClose={() => setOpenFilter(null)}
                                            />
                                        )}
                                    </th>
                                );
                            })}
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((r, idx) => (
                            <tr key={idx} className="border-b border-gray-100 hover:bg-amber-50/40" data-testid={`autre-row-${idx}`}>
                                <td className="px-2 py-1 text-xs text-gray-400 font-mono-data">{idx + 1}</td>
                                {columns.map((c) => (
                                    <td key={c} className="px-3 py-1 text-sm text-gray-800 font-mono-data whitespace-nowrap">
                                        {fmtNum(r[c])}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

const FilterDropdown = React.forwardRef(function FilterDropdown({ col, value, uniqueValues, onChange, onClose }, ref) {
    const [localText, setLocalText] = useState(value || "");
    useEffect(() => {
        setLocalText(value || "");
    }, [value]);

    // Top 20 valeurs uniques (suggestions cliquables) filtrées par la saisie
    const suggestions = useMemo(() => {
        const q = (localText || "").toLowerCase().trim();
        if (!q) return uniqueValues.slice(0, 20);
        return uniqueValues.filter((v) => v.toLowerCase().includes(q)).slice(0, 20);
    }, [localText, uniqueValues]);

    return (
        <div
            ref={ref}
            className="absolute top-full left-0 mt-1 z-30 w-64 bg-white border border-gray-300 rounded shadow-lg p-2"
            data-testid={`autre-filter-dropdown-${col}`}
        >
            <div className="flex items-center gap-1 mb-2">
                <input
                    type="text"
                    autoFocus
                    placeholder="Filtrer…"
                    value={localText}
                    onChange={(e) => {
                        setLocalText(e.target.value);
                        onChange(e.target.value);
                    }}
                    onKeyDown={(e) => {
                        if (e.key === "Escape") {
                            onClose();
                        } else if (e.key === "Enter") {
                            onClose();
                        }
                    }}
                    data-testid={`autre-filter-input-${col}`}
                    className="flex-1 h-7 px-2 text-xs border border-gray-300 rounded focus:ring-1 focus:ring-amber-500 focus:border-amber-500 outline-none"
                />
                {localText && (
                    <button
                        onClick={() => { setLocalText(""); onChange(""); }}
                        title="Effacer"
                        data-testid={`autre-filter-clear-${col}`}
                        className="p-1 hover:bg-gray-100 rounded"
                    >
                        <X className="w-3 h-3 text-gray-500" />
                    </button>
                )}
            </div>
            {suggestions.length > 0 ? (
                <ul className="max-h-48 overflow-auto text-xs custom-scroll">
                    {suggestions.map((s) => (
                        <li key={s}>
                            <button
                                onClick={() => {
                                    setLocalText(s);
                                    onChange(s);
                                    onClose();
                                }}
                                data-testid={`autre-filter-option-${col}-${s}`}
                                className="w-full text-left px-2 py-1 hover:bg-amber-50 rounded truncate"
                                title={s}
                            >
                                {s}
                            </button>
                        </li>
                    ))}
                </ul>
            ) : (
                <div className="text-xs text-gray-400 italic p-2">Aucune valeur</div>
            )}
            {uniqueValues.length > 20 && (
                <div className="text-[10px] text-gray-400 italic mt-1 px-1">
                    {uniqueValues.length - 20} autres valeurs · affinez la recherche
                </div>
            )}
        </div>
    );
});
