import React, { useMemo } from "react";

function fmtNum(v) {
    if (v === "" || v === null || v === undefined) return "";
    if (typeof v === "number") {
        if (Number.isInteger(v)) return v.toLocaleString("fr-FR");
        return v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }
    return v;
}

export default function RecapTable({ rows, search }) {
    const filtered = useMemo(() => {
        if (!search) return rows;
        const q = search.toLowerCase();
        return rows.filter((r) => {
            return (
                (r.designation && r.designation.toLowerCase().includes(q)) ||
                (r.reference && String(r.reference).toLowerCase().includes(q)) ||
                (r.type && r.type.toLowerCase().includes(q))
            );
        });
    }, [rows, search]);

    return (
        <div className="h-full flex flex-col bg-white" data-testid="recap-table">
            <div className="flex-1 overflow-auto custom-scroll">
                <table className="w-full border-collapse text-left">
                    <thead className="sticky top-0 z-10 bg-gray-100 thead-sticky">
                        <tr>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 w-32">
                                Type
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 w-32">
                                Référence
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300">
                                Désignation
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider w-28 text-right">
                                Quantité
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((r, i) => {
                            let rowClass = i % 2 === 0 ? "bg-white" : "bg-gray-50";
                            if (r.kind === "header") rowClass = "row-total";
                            else if (r.kind === "spare") rowClass = "row-spare";
                            else if (r.kind === "inclineur") rowClass = "row-inclineur";
                            else if (r.kind === "empty") rowClass = "row-empty";
                            return (
                                <tr
                                    key={i}
                                    className={`${rowClass} hover:brightness-95 border-b border-gray-200`}
                                    data-testid={`recap-row-${i}`}
                                    data-kind={r.kind}
                                >
                                    <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data">
                                        {r.type}
                                    </td>
                                    <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data">
                                        {r.reference}
                                    </td>
                                    <td className="px-3 py-1.5 text-sm border-r border-gray-200">
                                        {r.designation}
                                    </td>
                                    <td className="px-3 py-1.5 text-sm text-right font-mono-data">
                                        {fmtNum(r.quantite)}
                                    </td>
                                </tr>
                            );
                        })}
                        {filtered.length === 0 && (
                            <tr>
                                <td colSpan={4} className="px-3 py-8 text-center text-sm text-gray-500">
                                    Aucun résultat
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
            <div className="h-7 border-t border-gray-200 px-3 flex items-center text-xs text-gray-600 bg-gray-50 flex-shrink-0">
                <span data-testid="recap-row-count">{filtered.length.toLocaleString("fr-FR")} lignes</span>
                <span className="ml-4 flex items-center gap-3">
                    <span className="flex items-center gap-1">
                        <span className="w-3 h-3 rounded-sm" style={{ background: "#FEF3C7" }} /> Total
                    </span>
                    <span className="flex items-center gap-1">
                        <span className="w-3 h-3 rounded-sm" style={{ background: "#D1FAE5" }} /> Spare (+5%)
                    </span>
                    <span className="flex items-center gap-1">
                        <span className="w-3 h-3 rounded-sm" style={{ background: "#DBEAFE" }} /> Inclineur
                    </span>
                </span>
            </div>
        </div>
    );
}
