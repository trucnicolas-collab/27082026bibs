import React, { useMemo, useRef } from "react";
import { FixedSizeList as List } from "react-window";

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

export default function RawTable({ rows, columns, search }) {
    const containerRef = useRef(null);

    const filtered = useMemo(() => {
        if (!search) return rows;
        const q = search.toLowerCase();
        return rows.filter((r) =>
            columns.some((c) => {
                const v = r[c];
                return v != null && String(v).toLowerCase().includes(q);
            })
        );
    }, [rows, columns, search]);

    const totalWidth = columns.length * COL_WIDTH;

    const Row = ({ index, style }) => {
        const r = filtered[index];
        return (
            <div
                style={style}
                className={`flex border-b border-gray-200 ${index % 2 === 0 ? "bg-white" : "bg-gray-50"} hover:bg-blue-50`}
                data-testid={`raw-row-${index}`}
            >
                {columns.map((c) => (
                    <div
                        key={c}
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
        <div className="h-full flex flex-col bg-white" data-testid="raw-table">
            <div className="flex-1 overflow-auto custom-scroll" ref={containerRef}>
                <div style={{ minWidth: totalWidth }}>
                    {/* Header */}
                    <div className="flex sticky top-0 z-10 bg-gray-100 thead-sticky">
                        {columns.map((c) => (
                            <div
                                key={c}
                                className="px-3 py-2 text-xs font-semibold text-gray-700 uppercase tracking-wider border-r border-gray-300 last:border-r-0 truncate"
                                style={{ width: COL_WIDTH, minWidth: COL_WIDTH }}
                                title={c}
                            >
                                {c}
                            </div>
                        ))}
                    </div>
                    {/* Virtualized rows */}
                    <List
                        height={Math.max(window.innerHeight - 14 * 4 - 40 - 32, 300)}
                        itemCount={filtered.length}
                        itemSize={ROW_HEIGHT}
                        width={totalWidth}
                    >
                        {Row}
                    </List>
                </div>
            </div>
            <div className="h-7 border-t border-gray-200 px-3 flex items-center text-xs text-gray-600 bg-gray-50 flex-shrink-0">
                <span data-testid="raw-row-count">
                    {filtered.length.toLocaleString("fr-FR")} ligne{filtered.length > 1 ? "s" : ""}
                    {search && rows.length !== filtered.length && ` (filtré sur ${rows.length.toLocaleString("fr-FR")})`}
                </span>
            </div>
        </div>
    );
}
