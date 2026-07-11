import React, { useState, useRef, useEffect, useCallback } from "react";
import axios from "axios";
import { History, FolderOpen, Trash2, Loader2, Pencil, Check, X, Share2, Copy, Link as LinkIcon } from "lucide-react";
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
            day: "2-digit", month: "2-digit", year: "numeric",
            hour: "2-digit", minute: "2-digit",
        });
    } catch {
        return iso;
    }
}

function buildShareUrl(token) {
    const origin = window.location.origin;
    return `${origin}/?share=${token}`;
}

function ShareDialog({ session, onClose, onUpdate }) {
    const [loading, setLoading] = useState(false);
    const enabled = !!session.share_enabled;
    const url = session.share_token ? buildShareUrl(session.share_token) : "";

    const enable = async () => {
        setLoading(true);
        try {
            const res = await axios.post(`${API}/dataset/${session.upload_id}/share`);
            onUpdate({ ...session, share_enabled: true, share_token: res.data.share_token });
            toast.success("Lien de partage généré");
        } catch (err) {
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        } finally {
            setLoading(false);
        }
    };

    const disable = async () => {
        if (!window.confirm("Désactiver le partage ? Le lien actuel ne fonctionnera plus.")) return;
        setLoading(true);
        try {
            await axios.delete(`${API}/dataset/${session.upload_id}/share`);
            onUpdate({ ...session, share_enabled: false, share_token: null });
            toast.success("Partage désactivé");
        } catch (err) {
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        } finally {
            setLoading(false);
        }
    };

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(url);
            toast.success("Lien copié dans le presse-papier");
        } catch (_) {
            toast.error("Impossible de copier — sélectionnez et copiez manuellement");
        }
    };

    return (
        <div className="fixed inset-0 z-[100] bg-black/40 flex items-center justify-center p-4" onClick={onClose} data-testid="share-dialog">
            <div className="bg-white rounded-lg shadow-2xl w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2">
                        <Share2 className="w-5 h-5 text-emerald-600" />
                        <h3 className="text-base font-bold text-gray-900">Partager en lecture seule</h3>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600" data-testid="share-dialog-close">
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <p className="text-sm text-gray-600 mb-4">
                    <span className="font-semibold">{session.label || session.filename}</span><br />
                    Toute personne disposant du lien pourra consulter ce fichier et télécharger l'export Excel, sans pouvoir modifier les données.
                </p>

                {enabled && url ? (
                    <>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Lien de partage actif</label>
                        <div className="flex gap-2 mb-3">
                            <input
                                type="text"
                                readOnly
                                value={url}
                                onClick={(e) => e.target.select()}
                                data-testid="share-url-input"
                                className="flex-1 h-9 px-3 text-xs border border-gray-300 rounded bg-gray-50 font-mono"
                            />
                            <button
                                onClick={copy}
                                data-testid="share-copy-button"
                                className="h-9 px-3 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded flex items-center gap-1.5 transition-colors"
                            >
                                <Copy className="w-4 h-4" /> Copier
                            </button>
                        </div>
                        <div className="flex justify-between items-center pt-3 border-t border-gray-100">
                            <span className="text-xs text-emerald-700 flex items-center gap-1">
                                <LinkIcon className="w-3 h-3" /> Partage actif
                            </span>
                            <button
                                onClick={disable}
                                disabled={loading}
                                data-testid="share-disable-button"
                                className="h-8 px-3 text-sm text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                            >
                                Désactiver le lien
                            </button>
                        </div>
                    </>
                ) : (
                    <button
                        onClick={enable}
                        disabled={loading}
                        data-testid="share-enable-button"
                        className="w-full h-10 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
                    >
                        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Share2 className="w-4 h-4" />}
                        Générer un lien de partage
                    </button>
                )}
            </div>
        </div>
    );
}

function SessionRow({ s, isCurrent, onOpen, onDelete, onRename, onShare, deletingId }) {
    const [editing, setEditing] = useState(false);
    const [labelDraft, setLabelDraft] = useState(s.label || "");
    const [saving, setSaving] = useState(false);
    const displayName = s.label || s.filename;

    const save = async () => {
        const v = (labelDraft || "").trim();
        if (v === (s.label || "")) {
            setEditing(false);
            return;
        }
        setSaving(true);
        try {
            await axios.patch(`${API}/dataset/${s.upload_id}/label`, { label: v });
            onRename(s.upload_id, v);
            toast.success(v ? "Renommé" : "Libellé réinitialisé");
            setEditing(false);
        } catch (err) {
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        } finally {
            setSaving(false);
        }
    };

    const cancel = () => {
        setLabelDraft(s.label || "");
        setEditing(false);
    };

    return (
        <li
            data-testid={`session-item-${s.upload_id}`}
            className={`px-4 py-2.5 flex items-center gap-2 hover:bg-gray-50 transition-colors ${
                isCurrent ? "bg-emerald-50/50" : ""
            }`}
        >
            {editing ? (
                <>
                    <input
                        autoFocus
                        type="text"
                        value={labelDraft}
                        onChange={(e) => setLabelDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") save();
                            if (e.key === "Escape") cancel();
                        }}
                        placeholder={s.filename}
                        data-testid={`session-label-input-${s.upload_id}`}
                        className="flex-1 h-8 px-2 text-sm border border-emerald-300 rounded focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
                    />
                    <button onClick={save} disabled={saving} className="p-1.5 text-emerald-600 hover:bg-emerald-50 rounded" data-testid={`session-label-save-${s.upload_id}`}>
                        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                    </button>
                    <button onClick={cancel} className="p-1.5 text-gray-400 hover:bg-gray-100 rounded" data-testid={`session-label-cancel-${s.upload_id}`}>
                        <X className="w-4 h-4" />
                    </button>
                </>
            ) : (
                <>
                    <button
                        onClick={() => onOpen(s.upload_id)}
                        className="flex-1 min-w-0 text-left flex items-center gap-2 disabled:opacity-50"
                        disabled={isCurrent}
                        title={isCurrent ? "Session actuelle" : "Ouvrir cette session"}
                        data-testid={`session-open-${s.upload_id}`}
                    >
                        <FolderOpen className={`w-4 h-4 flex-shrink-0 ${isCurrent ? "text-emerald-600" : "text-gray-400"}`} />
                        <div className="min-w-0">
                            <div className={`text-sm truncate font-medium flex items-center gap-1.5 ${isCurrent ? "text-emerald-700" : "text-gray-900"}`}>
                                {displayName}
                                {s.share_enabled && (
                                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-700" title="Partage actif">
                                        <Share2 className="w-2.5 h-2.5 mr-0.5" /> partagé
                                    </span>
                                )}
                                {isCurrent && <span className="text-xs font-normal">· en cours</span>}
                            </div>
                            <div className="text-xs text-gray-500 truncate">
                                {s.label ? <span className="text-gray-400 italic">{s.filename} · </span> : null}
                                {formatDate(s.uploaded_at)} · {s.row_count?.toLocaleString("fr-FR") || 0} lignes · {formatSize(s.compressed_bytes || s.size_bytes)}
                                {s.owner_email && (
                                    <span className="ml-1.5 text-emerald-700 font-medium" data-testid={`session-owner-${s.upload_id}`}>
                                        · par {s.owner_email}
                                    </span>
                                )}
                            </div>
                        </div>
                    </button>
                    <button
                        onClick={() => { setLabelDraft(s.label || ""); setEditing(true); }}
                        data-testid={`session-rename-${s.upload_id}`}
                        className="p-1.5 text-gray-400 hover:text-emerald-600 hover:bg-emerald-50 rounded transition-colors"
                        title="Renommer"
                    >
                        <Pencil className="w-4 h-4" />
                    </button>
                    <button
                        onClick={() => onShare(s)}
                        data-testid={`session-share-${s.upload_id}`}
                        className={`p-1.5 rounded transition-colors ${
                            s.share_enabled
                                ? "text-emerald-600 hover:bg-emerald-50"
                                : "text-gray-400 hover:text-emerald-600 hover:bg-emerald-50"
                        }`}
                        title={s.share_enabled ? "Gérer le partage (actif)" : "Partager en lecture seule"}
                    >
                        <Share2 className="w-4 h-4" />
                    </button>
                    <button
                        onClick={() => onDelete(s.upload_id, displayName)}
                        disabled={deletingId === s.upload_id}
                        data-testid={`session-delete-${s.upload_id}`}
                        className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                        title="Supprimer cette session"
                    >
                        {deletingId === s.upload_id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    </button>
                </>
            )}
        </li>
    );
}

export default function SessionsMenu({ currentUploadId, onOpen, onDeleted }) {
    const [open, setOpen] = useState(false);
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [deletingId, setDeletingId] = useState(null);
    const [shareTarget, setShareTarget] = useState(null);
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

    useEffect(() => {
        if (open) fetchSessions();
    }, [open, fetchSessions]);

    useEffect(() => {
        if (!open || shareTarget) return;
        const onClick = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener("mousedown", onClick);
        return () => document.removeEventListener("mousedown", onClick);
    }, [open, shareTarget]);

    const handleDelete = async (uploadId, displayName) => {
        if (!window.confirm(`Supprimer définitivement « ${displayName} » ?\nCette action libère l'espace serveur et est irréversible.`)) return;
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

    const handleRename = (uploadId, newLabel) => {
        setSessions((arr) => arr.map((x) => x.upload_id === uploadId ? { ...x, label: newLabel } : x));
    };

    const handleShareUpdate = (updated) => {
        setSessions((arr) => arr.map((x) => x.upload_id === updated.upload_id ? updated : x));
        setShareTarget(updated);
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
                    className="absolute right-0 top-10 z-50 w-[520px] max-w-[95vw] bg-white border border-gray-200 rounded-lg shadow-xl"
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
                                {sessions.map((s) => (
                                    <SessionRow
                                        key={s.upload_id}
                                        s={s}
                                        isCurrent={s.upload_id === currentUploadId}
                                        onOpen={handleOpen}
                                        onDelete={handleDelete}
                                        onRename={handleRename}
                                        onShare={setShareTarget}
                                        deletingId={deletingId}
                                    />
                                ))}
                            </ul>
                        )}
                    </div>

                    <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 rounded-b-lg text-xs text-gray-500">
                        Renommer · Partager (lien lecture seule) · Supprimer. Modifications sauvegardées automatiquement.
                    </div>
                </div>
            )}

            {shareTarget && (
                <ShareDialog
                    session={shareTarget}
                    onClose={() => setShareTarget(null)}
                    onUpdate={handleShareUpdate}
                />
            )}
        </div>
    );
}
