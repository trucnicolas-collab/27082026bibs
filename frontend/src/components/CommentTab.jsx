import React, { useState, useEffect, useRef, useCallback } from "react";
import { Plus, Trash2 } from "lucide-react";

function EditableCell({ value, onCommit, placeholder = "", isHeader = false }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(value || "");

    const startEdit = useCallback(() => {
        setDraft(value || "");
        setEditing(true);
    }, [value]);

    const commit = useCallback(() => {
        setEditing(false);
        if (draft !== (value || "")) onCommit(draft);
    }, [draft, value, onCommit]);

    const cancel = useCallback(() => {
        setEditing(false);
        setDraft(value || "");
    }, [value]);

    if (editing) {
        return (
            <input
                autoFocus
                onFocus={(e) => e.target.select()}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); commit(); }
                    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
                }}
                placeholder={placeholder}
                className={`w-full h-full px-2 py-1 text-sm border border-[#056839] outline-none bg-white ${isHeader ? "font-semibold" : ""}`}
            />
        );
    }
    return (
        <div
            onClick={startEdit}
            className={`w-full h-full px-3 py-1.5 text-sm cursor-text hover:bg-emerald-50/60 ${isHeader ? "font-semibold text-gray-700 uppercase tracking-wider text-xs" : ""} ${!value ? "text-gray-400 italic" : ""}`}
            data-testid="comment-cell"
        >
            {value || placeholder || "—"}
        </div>
    );
}

export default function CommentTab({ value, onCommit }) {
    // value = { columns: [...], rows: [[...]] }
    const [table, setTable] = useState(value || { columns: [], rows: [] });
    const timerRef = useRef(null);

    useEffect(() => {
        setTable(value || { columns: [], rows: [] });
    }, [value]);

    const scheduleSave = useCallback((next) => {
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => onCommit(next), 600);
    }, [onCommit]);

    const updateHeader = (colIdx, newVal) => {
        const next = { ...table, columns: [...table.columns] };
        next.columns[colIdx] = newVal;
        setTable(next);
        scheduleSave(next);
    };

    const updateCell = (rowIdx, colIdx, newVal) => {
        const next = { ...table, rows: table.rows.map((r) => [...r]) };
        next.rows[rowIdx][colIdx] = newVal;
        setTable(next);
        scheduleSave(next);
    };

    const addRow = () => {
        const next = { ...table, rows: [...table.rows, table.columns.map(() => "")] };
        setTable(next);
        scheduleSave(next);
    };

    const addColumn = () => {
        const colName = `Colonne ${table.columns.length + 1}`;
        const next = {
            columns: [...table.columns, colName],
            rows: table.rows.map((r) => [...r, ""]),
        };
        setTable(next);
        scheduleSave(next);
    };

    const deleteRow = (rowIdx) => {
        const next = { ...table, rows: table.rows.filter((_, i) => i !== rowIdx) };
        setTable(next);
        scheduleSave(next);
    };

    const deleteColumn = (colIdx) => {
        if (table.columns.length <= 1) return;
        const next = {
            columns: table.columns.filter((_, i) => i !== colIdx),
            rows: table.rows.map((r) => r.filter((_, i) => i !== colIdx)),
        };
        setTable(next);
        scheduleSave(next);
    };

    return (
        <div className="h-full flex flex-col bg-white" data-testid="comment-tab">
            <div className="h-9 border-b border-gray-200 px-3 flex items-center bg-gray-50 flex-shrink-0 gap-2">
                <span className="text-xs font-medium text-gray-800">Commentaires</span>
                <span className="ml-2 text-xs text-gray-500">
                    Tableau libre. Cliquez sur une cellule pour saisir. Sauvegarde auto.
                </span>
                <div className="ml-auto flex items-center gap-2">
                    <button
                        onClick={addColumn}
                        data-testid="comment-add-col"
                        className="h-7 px-2.5 text-xs font-medium bg-white border border-gray-300 rounded hover:bg-gray-100 flex items-center gap-1.5 text-gray-700"
                    >
                        <Plus className="w-3.5 h-3.5" />
                        Colonne
                    </button>
                    <button
                        onClick={addRow}
                        data-testid="comment-add-row"
                        className="h-7 px-2.5 text-xs font-medium bg-white border border-gray-300 rounded hover:bg-gray-100 flex items-center gap-1.5 text-gray-700"
                    >
                        <Plus className="w-3.5 h-3.5" />
                        Ligne
                    </button>
                </div>
            </div>
            <div className="flex-1 overflow-auto custom-scroll p-4">
                <table className="border-collapse" data-testid="comment-table">
                    <thead>
                        <tr>
                            {table.columns.map((c, ci) => (
                                <th
                                    key={ci}
                                    className="border border-gray-300 bg-gray-100 p-0 align-middle min-w-[160px] group relative"
                                >
                                    <EditableCell
                                        value={c}
                                        onCommit={(v) => updateHeader(ci, v)}
                                        placeholder={`Colonne ${ci + 1}`}
                                        isHeader
                                    />
                                    {table.columns.length > 1 && (
                                        <button
                                            onClick={() => deleteColumn(ci)}
                                            className="absolute -top-2 -right-1 opacity-0 group-hover:opacity-100 p-1 bg-white border border-gray-300 rounded-full text-gray-400 hover:text-red-600 transition-opacity"
                                            title="Supprimer cette colonne"
                                            data-testid={`comment-delete-col-${ci}`}
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </button>
                                    )}
                                </th>
                            ))}
                            <th className="border border-transparent" style={{ width: 32 }} />
                        </tr>
                    </thead>
                    <tbody>
                        {table.rows.map((row, ri) => (
                            <tr key={ri} className="group">
                                {row.map((cell, ci) => (
                                    <td
                                        key={ci}
                                        className="border border-gray-300 p-0 align-middle min-w-[160px]"
                                    >
                                        <EditableCell
                                            value={cell}
                                            onCommit={(v) => updateCell(ri, ci, v)}
                                            placeholder=""
                                        />
                                    </td>
                                ))}
                                <td className="border border-transparent p-0 text-center align-middle">
                                    <button
                                        onClick={() => deleteRow(ri)}
                                        className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 transition-opacity"
                                        title="Supprimer cette ligne"
                                        data-testid={`comment-delete-row-${ri}`}
                                    >
                                        <Trash2 className="w-3.5 h-3.5" />
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="h-7 border-t border-gray-200 px-3 flex items-center text-xs text-gray-600 bg-gray-50 flex-shrink-0">
                <span>
                    {table.rows.length} ligne{table.rows.length > 1 ? "s" : ""} × {table.columns.length} colonne{table.columns.length > 1 ? "s" : ""}
                </span>
            </div>
        </div>
    );
}
