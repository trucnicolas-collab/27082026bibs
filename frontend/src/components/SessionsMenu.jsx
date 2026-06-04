import React, { useState, useRef, useEffect, useCallback } from "react";
import axios from "axios";
import { History, FolderOpen, Trash2, Loader2 } from "lucide-react";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function formatSize(bytes) {
    if (!bytes) return "—";
    if (bytes < 1024) return `${bytes} o`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
    return `${(bytes / 1024 / 1024).toFixed(1)} Mo`;
}

function formatDate(iso) {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        return d.toLocaleString("fr-FR", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return iso;
    }
}

export default function SessionsMenu({ currentUploadId, onOpen, onDeleted }) {
    const [open, setOpen] = useState(false);
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [deletingId, setDeletingId] = useState(null);
    const ref = useRef(null);

    const fetchSessions = useCallback(async () => {
        setLoading(true);
        try {
            const res = await axios.get(`${API}/datasets`);
            setSessions(res.data.datasets || []);
        } catch (err) {
            toast.error(`Impossible de charger les sessions : ${err.message}`);
        } finally {
            setLoading(false);
        }
    }, []);

    // Fetch quand le menu s'ouvre
    useEffect(() => {
        if (open) fetchSessions();
    }, [open, fetchSessions]);

    // Fermer au clic extérieur
    useEffect(() => {
        if (!open) return;
        const onClick = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener("mousedown", onClick);
        return () => document.removeEventListener("mousedown", onClick);
    }, [open]);

    const handleDelete = async (uploadId, filename, e) => {
        e.stopPropagation();
        if (!window.confirm(`Supprimer définitivement « ${filename} » ?\nCette action libère l'espace serveur et est irréversible.`)) {
            return;
        }
        setDeletingId(uploadId);
        try {
            await axios.delete(`${API}/dataset/${uploadId}`);
            setSessions((s) => s.filter((x) => x.upload_id !== uploadId));
            toast.success("Session supprimée");
            if (uploadId === currentUploadId && onDeleted) onDeleted(uploadId);
        } catch (err) {
            toast.error(`Suppression échouée : ${err.response?.data?.detail || err.message}`);
        } finally {
            setDeletingId(null);
        }
    };

    const handleOpen = (uploadId) => {
        if (uploadId === currentUploadId) {
            setOpen(false);
            return;
        }
        setOpen(false);
        onOpen(uploadId);
    };

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen((o) => !o)}
                data-testid="sessions-menu-button"
                className="h-8 px-3 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-100 flex items-center gap-1.5 transition-colors"
                title="Mes sessions"
            >
                <History className="w-4 h-4" />
                <span className="hidden sm:inline">Sessions</span>
            </button>

            {open && (
                <div
                    data-testid="sessions-menu-panel"
                    className="absolute right-0 top-10 z-50 w-[440px] max-w-[90vw] bg-white border border-gray-200 rounded-lg shadow-xl"
                >
                    <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between bg-gray-50 rounded-t-lg">
                        <h3 className="text-sm font-semibold text-gray-900">Mes sessions sauvegardées</h3>
                        <span className="text-xs text-gray-500">
                            {sessions.length} {sessions.length > 1 ? "fichiers" : "fichier"}
                        </span>
                    </div>

                    <div className="max-h-[60vh] overflow-y-auto">
                        {loading ? (
                            <div className="flex items-center justify-center py-8 text-gray-500">
                                <Loader2 className="w-5 h-5 animate-spin mr-2" /> Chargement…
                            </div>
                        ) : sessions.length === 0 ? (
                            <div className="px-4 py-6 text-sm text-gray-500 text-center">
                                Aucune session enregistrée.<br />
                                <span className="text-xs text-gray-400">Les fichiers uploadés apparaissent ici automatiquement.</span>
                            </div>
                        ) : (
                            <ul className="divide-y divide-gray-100">
                                {sessions.map((s) => {
                                    const isCurrent = s.upload_id === currentUploadId;
                                    return (
                                        <li
                                            key={s.upload_id}
                                            data-testid={`session-item-${s.upload_id}`}
                                            className={`px-4 py-2.5 flex items-center gap-3 hover:bg-gray-50 transition-colors ${
                                                isCurrent ? "bg-emerald-50/50" : ""
                                            }`}
                                        >
                                            <button
                                                onClick={() => handleOpen(s.upload_id)}
                                                className="flex-1 min-w-0 text-left flex items-center gap-2 disabled:opacity-50"
                                                disabled={isCurrent}
                                                title={isCurrent ? "Session actuelle" : "Ouvrir cette session"}
                                                data-testid={`session-open-${s.upload_id}`}
                                            >
                                                <FolderOpen className={`w-4 h-4 flex-shrink-0 ${isCurrent ? "text-emerald-600" : "text-gray-400"}`} />
                                                <div className="min-w-0">
                                                    <div className={`text-sm truncate font-medium ${isCurrent ? "text-emerald-700" : "text-gray-900"}`}>
                                                        {s.filename}
                                                        {isCurrent && <span className="ml-2 text-xs font-normal">· en cours</span>}
                                                    </div>
                                                    <div className="text-xs text-gray-500 truncate">
                                                        {formatDate(s.uploaded_at)} · {s.row_count?.toLocaleString("fr-FR") || 0} lignes · {formatSize(s.compressed_bytes || s.size_bytes)}
                                                    </div>
                                                </div>
                                            </button>
                                            <button
                                                onClick={(e) => handleDelete(s.upload_id, s.filename, e)}
                                                disabled={deletingId === s.upload_id}
                                                data-testid={`session-delete-${s.upload_id}`}
                                                className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                                                title="Supprimer cette session"
                                            >
                                                {deletingId === s.upload_id ? (
                                                    <Loader2 className="w-4 h-4 animate-spin" />
                                                ) : (
                                                    <Trash2 className="w-4 h-4" />
                                                )}
                                            </button>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </div>

                    <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 rounded-b-lg text-xs text-gray-500">
                        Vos modifications sont sauvegardées automatiquement. La session reprend là où vous l'aviez laissée.
                    </div>
                </div>
            )}
        </div>
    );
}
