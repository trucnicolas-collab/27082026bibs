import React, { useMemo, useState, useCallback, useEffect, useRef } from "react";
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

export default function RecapTable({ rows, search, onUpdateRow, onAddRow, onDeleteRow, surfaceCategory, onSurfaceChange, donglesQuantity, onDonglesChange }) {
    // ---- Dongles : input local + commit debounced (700ms) ou au blur/Enter
    // pour éviter que chaque caractère tapé déclenche une requête backend qui
    // re-render le composant et fait sauter le focus.
    const [donglesDraft, setDonglesDraft] = useState(donglesQuantity ? String(donglesQuantity) : "");
    const donglesDirtyRef = useRef(false);
    const donglesTimer = useRef(null);

    // Quand la prop change depuis l'extérieur (autre source) ET qu'on n'est pas
    // en train de taper, on resynchronise. Si l'utilisateur tape, on garde son draft.
    useEffect(() => {
        if (donglesDirtyRef.current) return;
        setDonglesDraft(donglesQuantity ? String(donglesQuantity) : "");
    }, [donglesQuantity]);

    const commitDongles = useCallback((rawVal) => {
        const v = parseInt(rawVal || "0", 10);
        const safe = isNaN(v) ? 0 : Math.max(0, v);
        donglesDirtyRef.current = false;
        if (safe !== (donglesQuantity || 0)) {
            onDonglesChange && onDonglesChange(safe);
        }
    }, [donglesQuantity, onDonglesChange]);

    const onDonglesInput = (val) => {
        donglesDirtyRef.current = true;
        // Autorise champ vide ou chiffres uniquement
        const cleaned = val.replace(/[^0-9]/g, "");
        setDonglesDraft(cleaned);
        if (donglesTimer.current) clearTimeout(donglesTimer.current);
        donglesTimer.current = setTimeout(() => commitDongles(cleaned), 700);
    };

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
            <div className="min-h-12 border-b border-gray-200 px-3 py-2 flex items-center justify-between bg-gray-50 flex-shrink-0 gap-3 flex-wrap">
                <div className="text-xs text-gray-600">
                    <span className="font-medium text-gray-800">Récapitulatif Produits</span>
                    <span className="ml-2 text-gray-500">
                        Cliquez sur une ligne vide pour saisir vos propres données
                    </span>
                </div>
                {/* Toggle surface + bouton ajouter ligne */}
                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-3 px-4 py-2 bg-amber-100 border-2 border-amber-500 rounded-lg shadow-md" data-testid="surface-toggle">
                        <span className="text-sm font-extrabold text-amber-900 uppercase tracking-wide">Surface magasin :</span>
                        <div className="inline-flex rounded-md border-2 border-amber-500 overflow-hidden shadow-sm">
                            <button
                                type="button"
                                data-testid="surface-moins"
                                onClick={() => onSurfaceChange && onSurfaceChange(surfaceCategory === "moins_10000" ? null : "moins_10000")}
                                className={`px-5 py-2.5 text-base font-bold transition-colors ${
                                    surfaceCategory === "moins_10000"
                                        ? "bg-[#056839] text-white shadow-inner"
                                        : "bg-white text-amber-900 hover:bg-amber-50"
                                }`}
                            >
                                − 10 000 m²
                            </button>
                            <button
                                type="button"
                                data-testid="surface-plus"
                                onClick={() => onSurfaceChange && onSurfaceChange(surfaceCategory === "plus_10000" ? null : "plus_10000")}
                                className={`px-5 py-2.5 text-base font-bold border-l-2 border-amber-500 transition-colors ${
                                    surfaceCategory === "plus_10000"
                                        ? "bg-[#056839] text-white shadow-inner"
                                        : "bg-white text-amber-900 hover:bg-amber-50"
                                }`}
                            >
                                + 10 000 m²
                            </button>
                        </div>
                        {surfaceCategory && (
                            <span className="text-xs text-amber-900 font-semibold italic">
                                → +{surfaceCategory === "plus_10000" ? "6 000" : "4 000"} SA 2.1 (noir) <span className="font-normal">+ Support indiv. alu SA</span> <span className="font-normal">sans spare</span>
                            </span>
                        )}
                    </div>
                    {/* Sélecteur dongles */}
                    <div className="flex items-center gap-2 px-4 py-2 bg-indigo-100 border-2 border-indigo-500 rounded-lg shadow-md" data-testid="dongles-toggle">
                        <span className="text-sm font-extrabold text-indigo-900 uppercase tracking-wide">Dongles :</span>
                        <input
                            type="text"
                            inputMode="numeric"
                            pattern="[0-9]*"
                            value={donglesDraft}
                            onChange={(e) => onDonglesInput(e.target.value)}
                            onBlur={() => {
                                if (donglesTimer.current) clearTimeout(donglesTimer.current);
                                commitDongles(donglesDraft);
                            }}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                    e.preventDefault();
                                    if (donglesTimer.current) clearTimeout(donglesTimer.current);
                                    commitDongles(donglesDraft);
                                    e.target.blur();
                                }
                            }}
                            onFocus={(e) => e.target.select()}
                            placeholder="0"
                            data-testid="dongles-quantity"
                            className="w-28 h-10 px-3 text-base font-bold text-indigo-900 border-2 border-indigo-500 rounded bg-white focus:ring-2 focus:ring-indigo-300 outline-none text-right font-mono-data"
                        />
                        <span className="text-xs text-indigo-900 italic">
                            réf. <span className="font-mono-data font-bold">16639</span> · sans spare
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
                                            onCommit={(v) => {
                                                // Auto-recalcul du Spare quand la Quantité change.
                                                // Règle générique : +5% arrondi sup. (cohérent avec backend).
                                                // Sauf pour Dongle/Inclineur (pas de spare).
                                                const qty = parseFloat(v);
                                                let newSpare = r.spare;
                                                const skipAutoSpare = r.kind === "dongle" || r.kind === "inclineur";
                                                if (!skipAutoSpare && !isNaN(qty) && qty > 0) {
                                                    newSpare = Math.ceil(qty * 0.05);
                                                } else if (!skipAutoSpare && (v === "" || qty === 0)) {
                                                    newSpare = "";
                                                }
                                                onUpdateRow(i, {
                                                    type: r.type,
                                                    reference: r.reference,
                                                    designation: r.designation,
                                                    quantite: v,
                                                    spare: newSpare,
                                                });
                                            }}
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
