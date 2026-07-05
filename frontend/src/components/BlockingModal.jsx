import React from "react";
import { AlertTriangle, X } from "lucide-react";

// Message simple, centré à l'écran, expliquant pourquoi on ne peut pas continuer.
export default function BlockingModal({ open, title, issues, onClose }) {
    if (!open) return null;
    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
            onClick={onClose}
            data-testid="blocking-modal"
        >
            <div
                className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
                    <div className="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
                        <AlertTriangle className="w-5 h-5 text-amber-600" />
                    </div>
                    <h3 className="text-base font-semibold text-gray-900 flex-1">
                        {title || "Impossible de continuer"}
                    </h3>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600" data-testid="blocking-modal-close">
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <div className="px-5 py-4">
                    <p className="text-sm text-gray-600 mb-3">
                        Corrigez les points suivants avant de passer à l’étape suivante :
                    </p>
                    <ul className="space-y-2">
                        {(issues || []).map((it, i) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-gray-800" data-testid={`blocking-issue-${i}`}>
                                <span className="mt-1 w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0" />
                                <span>{typeof it === "string" ? it : it.message}</span>
                            </li>
                        ))}
                    </ul>
                </div>
                <div className="px-5 py-3 bg-gray-50 flex justify-end">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm font-medium text-white rounded-lg"
                        style={{ backgroundColor: "#056839" }}
                        data-testid="blocking-modal-ok"
                    >
                        J’ai compris
                    </button>
                </div>
            </div>
        </div>
    );
}
