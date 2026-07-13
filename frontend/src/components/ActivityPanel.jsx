import React, { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { History, Loader2, RefreshCw, RotateCcw } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Libellés humains des actions
const ACTION_LABELS = {
    session_created: { label: "Fichier importé", color: "text-blue-700", bg: "bg-blue-50" },
    session_deleted: { label: "Session supprimée", color: "text-red-700", bg: "bg-red-50" },
    label_changed: { label: "Renommage", color: "text-blue-700", bg: "bg-blue-50" },
    share_enabled: { label: "Partage activé", color: "text-blue-700", bg: "bg-blue-50" },
    share_disabled: { label: "Partage désactivé", color: "text-gray-700", bg: "bg-gray-50" },
    surface_changed: { label: "Surface modifiée", color: "text-orange-700", bg: "bg-orange-50" },
    dongles_changed: { label: "Dongles modifiés", color: "text-indigo-700", bg: "bg-indigo-50" },
    phasage_updated: { label: "Phasage mis à jour", color: "text-purple-700", bg: "bg-purple-50" },
    phasage_restored: { label: "Phasage restauré", color: "text-blue-700", bg: "bg-blue-50" },
    comment_table_updated: { label: "Commentaire édité", color: "text-amber-700", bg: "bg-amber-50" },
    recap_row_updated: { label: "Ligne récap modifiée", color: "text-cyan-700", bg: "bg-cyan-50" },
    recap_row_added: { label: "Ligne ajoutée", color: "text-cyan-700", bg: "bg-cyan-50" },
    recap_row_deleted: { label: "Ligne supprimée", color: "text-red-700", bg: "bg-red-50" },
};

function formatRelative(iso) {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        const now = new Date();
        const diff = (now - d) / 1000; // seconds
        if (diff < 60) return "à l'instant";
        if (diff < 3600) return `il y a ${Math.floor(diff / 60)} min`;
        if (diff < 86400) return `il y a ${Math.floor(diff / 3600)} h`;
        if (diff < 7 * 86400) return `il y a ${Math.floor(diff / 86400)} j`;
        return d.toLocaleString("fr-FR", {
            day: "2-digit", month: "2-digit", year: "numeric",
            hour: "2-digit", minute: "2-digit",
        });
    } catch {
        return iso;
    }
}

function formatDetails(details) {
    if (!details || Object.keys(details).length === 0) return "";
    const parts = [];
    for (const [k, v] of Object.entries(details)) {
        if (k === "quantity") parts.push(`quantité = ${v}`);
        else if (k === "category") parts.push(`surface = ${v}`);
        else if (k === "row_count") parts.push(`${Number(v).toLocaleString("fr-FR")} lignes`);
        else if (k === "nb_nuits_es") parts.push(`${v} nuits ES`);
        else if (k === "nb_nuits_cam") parts.push(`${v} nuits Cam`);
        else if (k === "cols" || k === "rows") parts.push(`${v} ${k}`);
        else if (k === "snapshot_id" || k === "restored_from") continue;
        else parts.push(`${k} = ${v}`);
    }
    return parts.join(" · ");
}

export default function ActivityPanel({ uploadId, onRestored }) {
    const [open, setOpen] = useState(false);
    const [activity, setActivity] = useState([]);
    const [loading, setLoading] = useState(false);
    const [restoringId, setRestoringId] = useState(null);
    const ref = useRef(null);

    const fetchActivity = useCallback(async () => {
        if (!uploadId) return;
        setLoading(true);
        try {
            const res = await axios.get(`${API}/dataset/${uploadId}/activity`);
            setActivity(res.data.activity || []);
        } catch (err) {
            toast.error(`Erreur historique : ${err.response?.data?.detail || err.message}`);
        } finally {
            setLoading(false);
        }
    }, [uploadId]);

    const restoreSnapshot = useCallback(async (snapshotId, when) => {
        if (!uploadId || !snapshotId) return;
        const ok = window.confirm(
            `Restaurer le phasage à la version du ${when} ?\n\n` +
            `La version actuelle sera sauvegardée comme un nouveau snapshot ` +
            `(vous pourrez l'annuler).`
        );
        if (!ok) return;
        setRestoringId(snapshotId);
        try {
            await axios.post(`${API}/dataset/${uploadId}/phasage-restore/${snapshotId}`);
            toast.success("Phasage restauré.");
            await fetchActivity();
            if (typeof onRestored === "function") onRestored();
        } catch (err) {
            toast.error(`Restauration échouée : ${err.response?.data?.detail || err.message}`);
        } finally {
            setRestoringId(null);
        }
    }, [uploadId, fetchActivity, onRestored]);

    useEffect(() => {
        if (open) fetchActivity();
    }, [open, fetchActivity]);

    useEffect(() => {
        if (!open) return;
        const onClick = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener("mousedown", onClick);
        return () => document.removeEventListener("mousedown", onClick);
    }, [open]);

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen((o) => !o)}
                data-testid="activity-button"
                title="Historique des modifications de cette session"
                className="h-8 px-2.5 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-100 flex items-center gap-1.5 transition-colors"
            >
                <History className="w-4 h-4" />
                <span className="hidden lg:inline">Historique</span>
            </button>

            {open && (
                <div
                    data-testid="activity-panel"
                    className="absolute right-0 top-10 z-50 w-[460px] max-w-[95vw] bg-white border border-gray-200 rounded-lg shadow-xl"
                >
                    <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between bg-gray-50 rounded-t-lg">
                        <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                            <History className="w-4 h-4 text-gray-700" />
                            Historique de la session
                        </h3>
                        <button
                            onClick={fetchActivity}
                            disabled={loading}
                            data-testid="activity-refresh"
                            className="p-1 text-gray-400 hover:text-gray-700 rounded disabled:opacity-50"
                            title="Actualiser"
                        >
                            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
                        </button>
                    </div>

                    <div className="max-h-[60vh] overflow-y-auto">
                        {loading && activity.length === 0 ? (
                            <div className="flex items-center justify-center py-8 text-gray-500">
                                <Loader2 className="w-5 h-5 animate-spin mr-2" /> Chargement…
                            </div>
                        ) : activity.length === 0 ? (
                            <div className="px-4 py-6 text-sm text-gray-500 text-center">
                                Aucune action enregistrée pour cette session.
                            </div>
                        ) : (
                            <ul className="divide-y divide-gray-100">
                                {activity.map((it, idx) => {
                                    const meta = ACTION_LABELS[it.action] || {
                                        label: it.action,
                                        color: "text-gray-700",
                                        bg: "bg-gray-50",
                                    };
                                    const details = formatDetails(it.details);
                                    const snapshotId = it.details?.snapshot_id;
                                    const isRestoring = restoringId === snapshotId;
                                    return (
                                        <li key={idx} className="px-4 py-2.5" data-testid={`activity-item-${idx}`}>
                                            <div className="flex items-start gap-2">
                                                <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold ${meta.bg} ${meta.color} whitespace-nowrap`}>
                                                    {meta.label}
                                                </span>
                                                <div className="flex-1 min-w-0">
                                                    {it.target && (
                                                        <div className="text-xs text-gray-900 font-medium truncate" title={it.target}>
                                                            {it.target}
                                                        </div>
                                                    )}
                                                    {details && (
                                                        <div className="text-[11px] text-gray-500">{details}</div>
                                                    )}
                                                </div>
                                                <span className="text-[10.5px] text-gray-400 whitespace-nowrap" title={it.timestamp}>
                                                    {formatRelative(it.timestamp)}
                                                </span>
                                            </div>
                                            <div className="flex items-center justify-between mt-0.5 ml-1">
                                                <div className="text-[10px] text-gray-400">
                                                    par <span className="text-gray-600 font-medium">{it.user_name || it.user_email}</span>
                                                </div>
                                                {snapshotId && (
                                                    <button
                                                        type="button"
                                                        className="inline-flex items-center gap-1 text-[10.5px] text-purple-700 hover:text-purple-900 hover:bg-purple-50 px-1.5 py-0.5 rounded transition-colors disabled:opacity-50 disabled:cursor-wait"
                                                        onClick={() => restoreSnapshot(snapshotId, formatRelative(it.timestamp))}
                                                        disabled={isRestoring}
                                                        data-testid={`activity-restore-${idx}`}
                                                        title="Restaurer cette version du phasage"
                                                    >
                                                        {isRestoring ? (
                                                            <Loader2 className="w-3 h-3 animate-spin" />
                                                        ) : (
                                                            <RotateCcw className="w-3 h-3" />
                                                        )}
                                                        Restaurer
                                                    </button>
                                                )}
                                            </div>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </div>

                    <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 rounded-b-lg text-[10.5px] text-gray-500">
                        {activity.length} entrée{activity.length > 1 ? "s" : ""} · 200 max · conservées 1 an
                    </div>
                </div>
            )}
        </div>
    );
}
