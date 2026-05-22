import React, { useState, useEffect, useRef } from "react";

export default function CommentTab({ value, onCommit }) {
    const [draft, setDraft] = useState(value || "");
    const timerRef = useRef(null);

    useEffect(() => {
        setDraft(value || "");
    }, [value]);

    const handleChange = (e) => {
        const v = e.target.value;
        setDraft(v);
        // Debounce : sauvegarde 800ms après dernier coup de clavier
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => onCommit(v), 800);
    };

    const handleBlur = () => {
        if (timerRef.current) clearTimeout(timerRef.current);
        if (draft !== (value || "")) onCommit(draft);
    };

    return (
        <div className="h-full flex flex-col bg-white" data-testid="comment-tab">
            <div className="h-9 border-b border-gray-200 px-3 flex items-center bg-gray-50 flex-shrink-0">
                <span className="text-xs font-medium text-gray-800">Commentaires</span>
                <span className="ml-2 text-xs text-gray-500">
                    Notes libres, sauvegardées automatiquement. Exportées dans le fichier Excel.
                </span>
                <span className="ml-auto text-xs text-gray-400">
                    {draft.length.toLocaleString("fr-FR")} caractère{draft.length > 1 ? "s" : ""}
                </span>
            </div>
            <textarea
                value={draft}
                onChange={handleChange}
                onBlur={handleBlur}
                placeholder="Saisissez vos notes, remarques, points d'attention, etc."
                data-testid="comment-textarea"
                className="flex-1 w-full p-4 text-sm font-mono-data resize-none outline-none focus:bg-emerald-50/30"
                style={{ lineHeight: "1.6" }}
            />
        </div>
    );
}
