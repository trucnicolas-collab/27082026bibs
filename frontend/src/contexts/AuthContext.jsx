import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Axios global : envoie systématiquement les cookies (httpOnly access/refresh tokens)
axios.defaults.withCredentials = true;

// Intercepteur global : sur 401 → tente un refresh silencieux via
// /api/auth/refresh puis rejoue la requête d'origine. Si le refresh échoue
// aussi (refresh_token expiré), on émet un événement 'auth-session-lost'
// que le composant AuthProvider transforme en modal bloquant côté UI.
// Empêche la perte silencieuse de saisies (Phasage, Suivi, etc.).
let _refreshPromise = null;
axios.interceptors.response.use(
    (r) => r,
    async (error) => {
        const original = error?.config || {};
        const status = error?.response?.status;
        const url = String(original?.url || "");
        // Ne pas boucler : le refresh lui-même ou les endpoints d'auth
        // (login, register, logout) doivent remonter leur 401 tels quels.
        const isAuthPath = /\/api\/auth\/(login|register|logout|refresh|forgot|reset)/i.test(url);
        if (status !== 401 || original._retry || isAuthPath) {
            return Promise.reject(error);
        }
        original._retry = true;
        try {
            if (!_refreshPromise) {
                _refreshPromise = axios.post(`${API}/auth/refresh`).finally(() => {
                    _refreshPromise = null;
                });
            }
            await _refreshPromise;
            return axios(original);   // rejoue la requête après refresh
        } catch (_e) {
            // Refresh échoué → session totalement perdue. On lève un
            // événement bloquant pour l'utilisateur (voir AuthProvider).
            try {
                window.dispatchEvent(new CustomEvent("auth-session-lost", {
                    detail: { url },
                }));
            } catch (_) { /* dispatch failed, ignore */ }
            return Promise.reject(error);
        }
    }
);

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    // user state: null = checking, false = not authenticated, object = authenticated
    const [user, setUser] = useState(null);
    // Modal bloquant affiché quand la session est perdue en pleine saisie.
    // Garde les données non sauvegardées en RAM (React state du composant appelant).
    const [sessionLost, setSessionLost] = useState(false);
    const relogEmail = useRef("");
    const [relogPwd, setRelogPwd] = useState("");
    const [reloging, setReloging] = useState(false);
    const [relogError, setRelogError] = useState("");

    const fetchMe = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/auth/me`);
            setUser(res.data);
            relogEmail.current = res.data?.email || relogEmail.current;
            return res.data;
        } catch (_err) {
            setUser(false);
            return null;
        }
    }, []);

    useEffect(() => {
        fetchMe();
    }, [fetchMe]);

    // Écoute l'événement émis par l'intercepteur axios si le refresh échoue
    useEffect(() => {
        const onLost = () => {
            if (relogEmail.current) setSessionLost(true);
            else setUser(false);   // Pas de contexte user → redirige vers login
        };
        window.addEventListener("auth-session-lost", onLost);
        return () => window.removeEventListener("auth-session-lost", onLost);
    }, []);

    const login = useCallback(async (email, password) => {
        const res = await axios.post(`${API}/auth/login`, { email, password });
        setUser(res.data);
        relogEmail.current = res.data?.email || email;
        return res.data;
    }, []);

    const register = useCallback(async (email, password, name) => {
        const res = await axios.post(`${API}/auth/register`, { email, password, name });
        setUser(res.data);
        relogEmail.current = email;
        return res.data;
    }, []);

    const logout = useCallback(async () => {
        try {
            await axios.post(`${API}/auth/logout`);
        } catch (_) { /* logout errors are non-blocking */ }
        setUser(false);
        try { localStorage.removeItem("eeg.lastUploadId"); } catch (_) { /* localStorage unavailable */ }
    }, []);

    const submitRelog = async (e) => {
        e?.preventDefault?.();
        if (!relogEmail.current || !relogPwd) return;
        setReloging(true); setRelogError("");
        try {
            const res = await axios.post(`${API}/auth/login`, {
                email: relogEmail.current, password: relogPwd,
            });
            setUser(res.data);
            setSessionLost(false);
            setRelogPwd("");
            // (iter6) Prévient tous les composants en cours d'affichage
            // qu'ils doivent refetch leurs données (les précédents fetch
            // avaient renvoyé 401 et laissé un état d'erreur affiché).
            try {
                window.dispatchEvent(new CustomEvent("auth-session-recovered"));
            } catch (_) { /* dispatch failed, ignore */ }
        } catch (err) {
            setRelogError(err?.response?.data?.detail || "Reconnexion impossible");
        } finally {
            setReloging(false);
        }
    };

    return (
        <AuthContext.Provider value={{ user, login, register, logout, refresh: fetchMe }}>
            {children}
            {sessionLost && (
                <div className="fixed inset-0 z-[9999] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
                    data-testid="session-lost-modal">
                    <div className="w-full max-w-md bg-slate-900 border-2 border-red-600 rounded-2xl p-6 shadow-2xl">
                        <div className="flex items-center gap-2 mb-3">
                            <span className="text-2xl">⚠️</span>
                            <h2 className="text-lg font-bold text-red-400">Session expirée</h2>
                        </div>
                        <div className="text-sm text-slate-200 mb-4 space-y-1.5">
                            <p><strong className="text-red-300">Vos modifications non sauvegardées sont EN DANGER.</strong></p>
                            <p>Reconnectez-vous <strong>ici même</strong> (sans quitter la page) pour reprendre votre travail sans rien perdre.</p>
                        </div>
                        <form onSubmit={submitRelog} className="space-y-2">
                            <input type="email" value={relogEmail.current} disabled readOnly
                                className="w-full h-10 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 px-3 text-sm"
                                data-testid="session-lost-email" />
                            <input type="password" value={relogPwd} autoFocus
                                onChange={(e) => setRelogPwd(e.target.value)}
                                placeholder="Mot de passe"
                                className="w-full h-10 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 px-3 text-sm focus:border-blue-500 outline-none"
                                data-testid="session-lost-password" />
                            {relogError && <div className="text-xs text-red-400" data-testid="session-lost-error">{relogError}</div>}
                            <button type="submit" disabled={reloging || !relogPwd}
                                className="w-full h-10 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm disabled:opacity-50"
                                data-testid="session-lost-submit">
                                {reloging ? "Reconnexion..." : "Se reconnecter et garder mon travail"}
                            </button>
                        </form>
                        <div className="mt-3 text-[10px] text-slate-500 text-center">
                            Ne quittez pas cette page — vos données sont encore en mémoire.
                        </div>
                    </div>
                </div>
            )}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error("useAuth must be used within AuthProvider");
    return ctx;
}
