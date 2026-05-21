import React, { useMemo } from "react";

function fmtNum(v) {
    if (v === "" || v === null || v === undefined) return "";
    if (typeof v === "number") {
        if (Number.isInteger(v)) return v.toLocaleString("fr-FR");
        return v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }
    return v;
}

export default function SecteurTable({ rows, search }) {
    const filtered = useMemo(() => {
        if (!search) return rows;
        const q = search.toLowerCase();
        return rows.filter(
            (r) =>
                (r.secteur && r.secteur.toLowerCase().includes(q)) ||
                (r.rayon && r.rayon.toLowerCase().includes(q)) ||
                (r.allee && String(r.allee).toLowerCase().includes(q))
        );
    }, [rows, search]);

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

    return (
        <div className="h-full flex flex-col bg-white" data-testid="secteur-table">
            <div className="flex-1 overflow-auto custom-scroll">
                <table className="w-full border-collapse text-left">
                    <thead className="sticky top-0 z-10 bg-gray-100 thead-sticky">
                        <tr>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300">
                                Secteur
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300">
                                Rayon
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 w-24">
                                N° Allée
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 w-24 text-right">
                                EEG ES
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 w-24 text-right">
                                EEG SA
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 w-24 text-right">
                                Rails
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider w-24 text-right">
                                Caméras
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((r, i) => (
                            <tr
                                key={i}
                                className={`${i % 2 === 0 ? "bg-white" : "bg-gray-50"} hover:bg-blue-50 border-b border-gray-200`}
                                data-testid={`secteur-row-${i}`}
                            >
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200">{r.secteur}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200">{r.rayon}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data">{r.allee}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data text-right">{fmtNum(r.nb_eeg_es)}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data text-right">{fmtNum(r.nb_eeg_sa)}</td>
                                <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data text-right">{fmtNum(r.nb_rail)}</td>
                                <td className="px-3 py-1.5 text-sm font-mono-data text-right">{fmtNum(r.nb_camera)}</td>
                            </tr>
                        ))}
                        {filtered.length === 0 && (
                            <tr>
                                <td colSpan={7} className="px-3 py-8 text-center text-sm text-gray-500">
                                    Aucun résultat
                                </td>
                            </tr>
                        )}
                    </tbody>
                    {filtered.length > 0 && (
                        <tfoot className="sticky bottom-0 bg-yellow-50">
                            <tr className="border-t-2 border-gray-400 font-semibold" data-testid="secteur-totals">
                                <td colSpan={3} className="px-3 py-2 text-sm text-gray-900">
                                    TOTAL
                                </td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right">{fmtNum(totals.es)}</td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right">{fmtNum(totals.sa)}</td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right">{fmtNum(totals.rail)}</td>
                                <td className="px-3 py-2 text-sm font-mono-data text-right">{fmtNum(totals.cam)}</td>
                            </tr>
                        </tfoot>
                    )}
                </table>
            </div>
            <div className="h-7 border-t border-gray-200 px-3 flex items-center text-xs text-gray-600 bg-gray-50 flex-shrink-0">
                <span data-testid="secteur-row-count">{filtered.length.toLocaleString("fr-FR")} allées</span>
            </div>
        </div>
    );
}
