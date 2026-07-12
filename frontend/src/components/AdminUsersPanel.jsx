import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Users, X, Loader2, RefreshCw, KeyRound, Unlock, Trash2, Shield, User as UserIcon, Crown, Copy, Check } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const ROLE_STYLE = {
    superadmin: { color: "text-amber-700 bg-amber-50 border-amber-200", label: "Créateur", Icon: Crown },
    admin: { color: "text-blue-700 bg-blue-50 border-blue-200", label: "Admin", Icon: Shield },
    user: { color: "text-gray-700 bg-gray-50 border-gray-200", label: "User", Icon: UserIcon },
};

function fmt(dt) {
    if (!dt) return "—";
    try {
        const d = new Date(dt);
        return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch {
        return String(dt);
    }
}

export default function AdminUsersPanel({ currentUser, onClose }) {
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [tempPassword, setTempPassword] = useState(null); // { email, temp_password }
    const [copied, setCopied] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await axios.get(`${API}/admin/users`, { withCredentials: true });
            setUsers(res.data.users || []);
        } catch (err) {
            toast.error("Erreur chargement utilisateurs : " + (err.response?.data?.detail || err.message));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const resetPassword = async (u) => {
        if (!window.confirm(`Générer un nouveau mot de passe temporaire pour ${u.email} ?\n\nL'ancien mot de passe sera immédiatement invalidé.`)) return;
        try {
            const res = await axios.post(`${API}/admin/users/${u.id}/reset-password`,
                { length: 14 }, { withCredentials: true });
            setTempPassword({ email: res.data.email, temp_password: res.data.temp_password });
            toast.success("Nouveau mot de passe généré");
            load();
        } catch (err) {
            toast.error("Erreur : " + (err.response?.data?.detail || err.message));
        }
    };

    const unlockUser = async (u) => {
        try {
            const res = await axios.post(`${API}/admin/users/${u.id}/unlock`, {}, { withCredentials: true });
            toast.success(`Compte débloqué (${res.data.cleared_attempts} tentative(s) effacée(s))`);
            load();
        } catch (err) {
            toast.error("Erreur : " + (err.response?.data?.detail || err.message));
        }
    };

    const changeRole = async (u, newRole) => {
        if (u.role === newRole) return;
        if (!window.confirm(`Passer ${u.email} de "${u.role}" à "${newRole}" ?`)) return;
        try {
            await axios.patch(`${API}/admin/users/${u.id}/role`, { role: newRole }, { withCredentials: true });
            toast.success(`Rôle mis à jour : ${newRole}`);
            load();
        } catch (err) {
            toast.error("Erreur : " + (err.response?.data?.detail || err.message));
        }
    };

    const deleteUser = async (u) => {
        if (!window.confirm(`Supprimer définitivement le compte ${u.email} ?\n\nSes ${u.dataset_count} phasage(s) resteront en base mais ne lui seront plus accessibles.`)) return;
        if (!window.confirm(`Vraiment sûr ? Cette action est irréversible.`)) return;
        try {
            const res = await axios.delete(`${API}/admin/users/${u.id}`, { withCredentials: true });
            toast.success(`Compte supprimé (${res.data.orphaned_datasets} phasage(s) orphelin(s))`);
            load();
        } catch (err) {
            toast.error("Erreur : " + (err.response?.data?.detail || err.message));
        }
    };

    const copyPwd = () => {
        if (!tempPassword) return;
        navigator.clipboard.writeText(tempPassword.temp_password);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-start sm:items-center justify-center p-4 overflow-y-auto"
            data-testid="admin-users-panel" onClick={onClose}>
            <div className="w-full max-w-4xl bg-white rounded-xl shadow-2xl my-8 flex flex-col max-h-[92vh]"
                onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200">
                    <div className="flex items-center gap-2">
                        <Users className="w-5 h-5 text-[#056839]" />
                        <h3 className="text-base font-bold text-gray-900">Gestion des utilisateurs</h3>
                        <span className="text-xs text-gray-500 ml-2">({users.length} compte{users.length > 1 ? "s" : ""})</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <button onClick={load} disabled={loading} data-testid="admin-refresh"
                            className="p-1.5 rounded hover:bg-gray-100 text-gray-500 disabled:opacity-50">
                            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                        </button>
                        <button onClick={onClose} data-testid="admin-close"
                            className="p-1.5 rounded hover:bg-gray-100 text-gray-500">
                            <X className="w-4 h-4" />
                        </button>
                    </div>
                </div>

                {tempPassword && (
                    <div className="mx-5 mt-3 p-3 rounded-lg bg-amber-50 border border-amber-300" data-testid="temp-password-banner">
                        <div className="text-xs font-semibold text-amber-900 mb-1">
                            🔑 Nouveau mot de passe pour <span className="font-bold">{tempPassword.email}</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <code className="flex-1 px-3 py-2 bg-white border border-amber-300 rounded text-sm font-mono text-gray-900 select-all"
                                data-testid="temp-password-value">{tempPassword.temp_password}</code>
                            <button onClick={copyPwd} data-testid="temp-password-copy"
                                className="px-3 py-2 bg-amber-600 text-white text-sm font-semibold rounded hover:bg-amber-700 flex items-center gap-1.5">
                                {copied ? <><Check className="w-4 h-4" /> Copié</> : <><Copy className="w-4 h-4" /> Copier</>}
                            </button>
                            <button onClick={() => setTempPassword(null)}
                                className="px-2 py-2 text-amber-700 hover:bg-amber-100 rounded"><X className="w-4 h-4" /></button>
                        </div>
                        <p className="text-[11px] text-amber-800 mt-1.5">
                            Transmettez ce mot de passe à l&apos;utilisateur par un canal sûr. Il ne sera plus affiché après fermeture.
                        </p>
                    </div>
                )}

                <div className="flex-1 overflow-y-auto p-4">
                    {loading && users.length === 0 && (
                        <div className="text-center py-12 text-gray-400"><Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" />Chargement…</div>
                    )}
                    <div className="space-y-2">
                        {users.map((u) => {
                            const rs = ROLE_STYLE[u.role] || ROLE_STYLE.user;
                            const isSelf = u.id === currentUser?.id;
                            return (
                                <div key={u.id} data-testid={`user-row-${u.id}`}
                                    className={`rounded-lg border p-3 hover:bg-gray-50 transition-colors
                                        ${u.locked ? "border-red-300 bg-red-50/50" : "border-gray-200 bg-white"}`}>
                                    <div className="flex items-start gap-3">
                                        <div className={`w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 ${rs.color} border`}>
                                            <rs.Icon className="w-4 h-4" />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className="font-semibold text-sm text-gray-900">{u.name || "—"}</span>
                                                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${rs.color}`}>{rs.label.toUpperCase()}</span>
                                                {isSelf && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-300">VOUS</span>}
                                                {u.locked && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-800 border border-red-300">BLOQUÉ</span>}
                                            </div>
                                            <div className="text-xs text-gray-600 truncate" title={u.email}>{u.email}</div>
                                            <div className="text-[11px] text-gray-500 mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                                                <span>Créé : {fmt(u.created_at)}</span>
                                                <span>Dernière connexion : {fmt(u.last_login_at)}</span>
                                                <span className="font-semibold">{u.dataset_count} phasage{u.dataset_count > 1 ? "s" : ""}</span>
                                                {u.failed_attempts > 0 && <span className="text-red-600">{u.failed_attempts} tentative(s) échouée(s)</span>}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                                        <button onClick={() => resetPassword(u)} data-testid={`reset-password-${u.id}`}
                                            title="Générer un nouveau mot de passe"
                                            className="h-7 px-2 text-xs font-medium bg-white border border-gray-300 text-gray-700 rounded hover:bg-gray-100 flex items-center gap-1">
                                            <KeyRound className="w-3.5 h-3.5" /> Reset MDP
                                        </button>
                                        <button onClick={() => unlockUser(u)} data-testid={`unlock-${u.id}`}
                                            disabled={!u.locked && u.failed_attempts === 0}
                                            title="Effacer les tentatives échouées"
                                            className="h-7 px-2 text-xs font-medium bg-white border border-gray-300 text-gray-700 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1">
                                            <Unlock className="w-3.5 h-3.5" /> Débloquer
                                        </button>
                                        <select value={u.role}
                                            onChange={(e) => changeRole(u, e.target.value)}
                                            disabled={isSelf}
                                            data-testid={`role-select-${u.id}`}
                                            title={isSelf ? "Vous ne pouvez pas modifier votre propre rôle" : "Changer le rôle"}
                                            className="h-7 px-2 text-xs font-medium bg-white border border-gray-300 text-gray-700 rounded disabled:opacity-40 disabled:cursor-not-allowed">
                                            <option value="user">User</option>
                                            <option value="admin">Admin</option>
                                            <option value="superadmin">Créateur</option>
                                        </select>
                                        {!isSelf && (
                                            <button onClick={() => deleteUser(u)} data-testid={`delete-${u.id}`}
                                                title="Supprimer ce compte"
                                                className="h-7 px-2 text-xs font-medium bg-white border border-red-300 text-red-600 rounded hover:bg-red-50 flex items-center gap-1 ml-auto">
                                                <Trash2 className="w-3.5 h-3.5" /> Supprimer
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}
