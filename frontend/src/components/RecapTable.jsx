import React, { useMemo, useState, useCallback } from "react";
import { Plus, Trash2 } from "lucide-react";

function fmtNum(v) {
    if (v === "" || v === null || v === undefined) return "";
    if (typeof v === "number") {
        if (Number.isInteger(v)) return v.toLocaleString("fr-FR");
        return v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }
    return v;
}

function EditableCell({ value, onCommit, type = "text", align = "left", placeholder = "" }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(value);

    const startEdit = useCallback(() => {
        setDraft(value === "" || value === null || value === undefined ? "" : String(value));
        setEditing(true);
    }, [value]);

    const commit = useCallback(() => {
        setEditing(false);
        const original = value === "" || value === null || value === undefined ? "" : String(value);
        if (draft !== original) {
            onCommit(draft);
        }
    }, [draft, onCommit, value]);

    const cancel = useCallback(() => {
        setEditing(false);
        setDraft(value === "" || value === null || value === undefined ? "" : String(value));
    }, [value]);

    if (editing) {
        return (
            <input
                autoFocus
                onFocus={(e) => e.target.select()}
                type={type}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => {
                    if (e.key === "Enter") {
                        e.preventDefault();
                        commit();
                    } else if (e.key === "Escape") {
                        e.preventDefault();
                        cancel();
                    }
                }}
                placeholder={placeholder}
                className={`w-full h-full px-2 py-1 text-sm border border-[#056839] outline-none font-mono-data bg-white ${
                    align === "right" ? "text-right" : ""
                }`}
            />
        );
    }
    return (
        <div
            onClick={startEdit}
            className={`w-full h-full px-3 py-1.5 text-sm cursor-text font-mono-data hover:bg-emerald-50/60 ${
                align === "right" ? "text-right" : ""
            } ${value === "" || value === null ? "text-gray-400 italic" : ""}`}
            data-testid="editable-cell"
        >
            {value === "" || value === null || value === undefined
                ? placeholder || "—"
                : type === "number"
                  ? fmtNum(value)
                  : value}
        </div>
    );
}

export default function RecapTable({ rows, search, onUpdateRow, onAddRow, onDeleteRow }) {
    const filtered = useMemo(() => {
        if (!search) return rows.map((r, i) => ({ ...r, _origIndex: i }));
        const q = search.toLowerCase();
        return rows
            .map((r, i) => ({ ...r, _origIndex: i }))
            .filter((r) => {
                return (
                    (r.designation && r.designation.toLowerCase().includes(q)) ||
                    (r.reference && String(r.reference).toLowerCase().includes(q)) ||
                    (r.type && r.type.toLowerCase().includes(q))
                );
            });
    }, [rows, search]);

    return (
        <div className="h-full flex flex-col bg-white" data-testid="recap-table">
            <div className="h-9 border-b border-gray-200 px-3 flex items-center justify-between bg-gray-50 flex-shrink-0">
                <div className="text-xs text-gray-600">
                    <span className="font-medium text-gray-800">Récapitulatif Produits</span>
                    <span className="ml-2 text-gray-500">
                        Cliquez sur une ligne vide pour saisir vos propres données
                    </span>
                </div>
                <button
                    onClick={onAddRow}
                    data-testid="add-row-button"
                    className="h-7 px-2.5 text-xs font-medium bg-white border border-gray-300 rounded hover:bg-gray-100 flex items-center gap-1.5 text-gray-700"
                >
                    <Plus className="w-3.5 h-3.5" />
                    Ajouter une ligne
                </button>
            </div>
            <div className="flex-1 overflow-auto custom-scroll">
                <table className="border-collapse text-left">
                    <thead className="sticky top-0 z-10 bg-gray-100 thead-sticky">
                        <tr>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 whitespace-nowrap">
                                Type
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 whitespace-nowrap">
                                Référence
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 whitespace-nowrap">
                                Désignation
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider text-right border-r border-gray-300 whitespace-nowrap">
                                Quantité
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider text-right border-r border-gray-300 whitespace-nowrap bg-emerald-50">
                                Spare
                            </th>
                            <th className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider text-right border-r border-gray-300 whitespace-nowrap bg-blue-50">
                                Total + Spare
                            </th>
                            <th className="w-10" />
                            <th className="w-full" />
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((r, displayIdx) => {
                            const i = r._origIndex;
                            // Toutes les lignes sont éditables SAUF les en-têtes de section (TOTAL EEG, TOTAL Fixation, etc.)
                            const editable = r.kind !== "header";
                            let rowClass = displayIdx % 2 === 0 ? "bg-white" : "bg-gray-50";
                            if (r.kind === "header") rowClass = "row-total";
                            else if (r.kind === "inclineur") rowClass = "row-inclineur";
                            else if (r.kind === "empty") rowClass = "row-empty";
                            else if (r.kind === "manual") rowClass = "bg-emerald-50/30";

                            if (!editable) {
                                return (
                                    <tr
                                        key={i}
                                        className={`${rowClass} hover:brightness-95 border-b border-gray-200`}
                                        data-testid={`recap-row-${i}`}
                                        data-kind={r.kind}
                                    >
                                        <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data whitespace-nowrap">{r.type}</td>
                                        <td className="px-3 py-1.5 text-sm border-r border-gray-200 font-mono-data whitespace-nowrap">{r.reference}</td>
                                        <td className="px-3 py-1.5 text-sm border-r border-gray-200 whitespace-nowrap">{r.designation}</td>
                                        <td className="px-3 py-1.5 text-sm text-right font-mono-data border-r border-gray-200 whitespace-nowrap">{fmtNum(r.quantite)}</td>
                                        <td className="px-3 py-1.5 text-sm text-right font-mono-data border-r border-gray-200 whitespace-nowrap bg-emerald-50/40">{fmtNum(r.spare)}</td>
                                        <td className="px-3 py-1.5 text-sm text-right font-mono-data border-r border-gray-200 whitespace-nowrap bg-blue-50/40 font-semibold">{fmtNum(r.total_plus_spare)}</td>
                                        <td />
                                        <td />
                                    </tr>
                                );
                            }
                            // Editable row
                            return (
                                <tr
                                    key={i}
                                    className={`${rowClass} border-b border-gray-200 group`}
                                    data-testid={`recap-row-${i}`}
                                    data-kind={r.kind}
                                >
                                    <td className="p-0 border-r border-gray-200 align-middle">
                                        <EditableCell
                                            value={r.type}
                                            placeholder="Type"
                                            onCommit={(v) => onUpdateRow(i, { type: v, reference: r.reference, designation: r.designation, quantite: r.quantite, spare: r.spare })}
                                        />
                                    </td>
                                    <td className="p-0 border-r border-gray-200 align-middle">
                                        <EditableCell
                                            value={r.reference}
                                            placeholder="Référence"
                                            onCommit={(v) => onUpdateRow(i, { type: r.type, reference: v, designation: r.designation, quantite: r.quantite, spare: r.spare })}
                                        />
                                    </td>
                                    <td className="p-0 border-r border-gray-200 align-middle">
                                        <EditableCell
                                            value={r.designation}
                                            placeholder="Désignation"
                                            onCommit={(v) => onUpdateRow(i, { type: r.type, reference: r.reference, designation: v, quantite: r.quantite, spare: r.spare })}
                                        />
                                    </td>
                                    <td className="p-0 border-r border-gray-200 align-middle">
                                        <EditableCell
                                            value={r.quantite}
                                            placeholder="Qté"
                                            type="number"
                                            align="right"
                                            onCommit={(v) => onUpdateRow(i, { type: r.type, reference: r.reference, designation: r.designation, quantite: v, spare: r.spare })}
                                        />
                                    </td>
                                    <td className="p-0 border-r border-gray-200 align-middle bg-emerald-50/40">
                                        <EditableCell
                                            value={r.spare}
                                            placeholder="Spare"
                                            type="number"
                                            align="right"
                                            onCommit={(v) => onUpdateRow(i, { type: r.type, reference: r.reference, designation: r.designation, quantite: r.quantite, spare: v })}
                                        />
                                    </td>
                                    <td className="px-3 py-1.5 text-sm text-right font-mono-data border-r border-gray-200 whitespace-nowrap bg-blue-50/40 font-semibold">{fmtNum(r.total_plus_spare)}</td>
                                    <td className="p-0 text-center align-middle">
                                        <button
                                            onClick={() => onDeleteRow(i)}
                                            data-testid={`delete-row-${i}`}
                                            className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 transition-opacity"
                                            title="Supprimer cette ligne"
                                        >
                                            <Trash2 className="w-3.5 h-3.5" />
                                        </button>
                                    </td>
                                    <td />
                                </tr>
                            );
                        })}
                        {filtered.length === 0 && (
                            <tr>
                                <td colSpan={8} className="px-3 py-8 text-center text-sm text-gray-500">
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
                        <span className="w-3 h-3 rounded-sm" style={{ background: "#DBEAFE" }} /> Inclineur
                    </span>
                    <span className="flex items-center gap-1">
                        <span className="w-3 h-3 rounded-sm bg-emerald-50 border border-emerald-200" /> Spare
                    </span>
                    <span className="flex items-center gap-1">
                        <span className="w-3 h-3 rounded-sm bg-blue-50 border border-blue-200" /> Total + Spare
                    </span>
                </span>
            </div>
        </div>
    );
}
