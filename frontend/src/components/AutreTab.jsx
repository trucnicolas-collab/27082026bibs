import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Loader2, AlertCircle } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function fmtNum(v) {
    if (v === "" || v === null || v === undefined) return "";
    if (typeof v === "number" && Number.isFinite(v)) {
        return Number.isInteger(v) ? v.toLocaleString("fr-FR") : v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }
    return String(v);
}

/**
 * Onglet "Autre" : affiche les lignes du fichier original dont
 *   Type == "Fixation" ET Référence commence par "AUTRE".
 * Lecture seule, toutes les colonnes du fichier d'origine sont affichées.
 *
 * Si `endpoint` est fourni (vue partagée), il est utilisé à la place de l'endpoint authentifié.
 */
export default function AutreTab({ uploadId, search = "", endpoint }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!uploadId && !endpoint) return;
        let mounted = true;
        setLoading(true);
        const url = endpoint || `${API}/dataset/${uploadId}/autre`;
        axios.get(url)
            .then((res) => mounted && setData(res.data))
            .catch((e) => mounted && setError(e.response?.data?.detail || e.message))
            .finally(() => mounted && setLoading(false));
        return () => { mounted = false; };
    }, [uploadId, endpoint]);

    const columns = data?.columns || [];
    const rows = data?.rows || [];

    const filtered = useMemo(() => {
        if (!search) return rows;
        const q = search.toLowerCase();
        return rows.filter((r) => Object.values(r).some((v) => String(v ?? "").toLowerCase().includes(q)));
    }, [rows, search]);

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
                    {rows.length} ligne{rows.length > 1 ? "s" : ""} · lecture seule (issues du fichier d'origine)
                </span>
            </div>
            <div className="flex-1 overflow-auto custom-scroll">
                <table className="border-collapse text-sm">
                    <thead className="sticky top-0 z-10 bg-gray-100 thead-sticky">
                        <tr>
                            <th className="px-2 py-1.5 text-left text-xs font-semibold text-gray-700 border-b border-gray-300 w-12">#</th>
                            {columns.map((c) => (
                                <th
                                    key={c}
                                    className="px-3 py-1.5 text-left text-xs font-semibold text-gray-700 border-b border-gray-300 whitespace-nowrap"
                                >
                                    {c}
                                </th>
                            ))}
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
