import React, { useState } from "react";
import { FileSpreadsheet, Mail, Lock, User, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../contexts/AuthContext";

function formatApiErrorDetail(detail) {
    if (detail == null) return "Une erreur est survenue.";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        return detail
            .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
            .filter(Boolean)
            .join(" ");
    }
    if (detail && typeof detail.msg === "string") return detail.msg;
    return String(detail);
}

export default function AuthScreen({ onForgotPassword }) {
    const [mode, setMode] = useState("login"); // 'login' | 'register'
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [name, setName] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const { login, register } = useAuth();

    const onSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError("");
        try {
            if (mode === "login") {
                await login(email.trim(), password);
                toast.success("Connexion réussie");
            } else {
                await register(email.trim(), password, name.trim());
                toast.success("Compte créé !");
            }
        } catch (err) {
            const msg = formatApiErrorDetail(err.response?.data?.detail) || err.message;
            setError(msg);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-50 via-white to-gray-100 px-4" data-testid="auth-screen">
            <div className="w-full max-w-md">
                <div className="flex items-center gap-3 mb-8 justify-center">
                    <div className="w-12 h-12 rounded-lg bg-[#056839] flex items-center justify-center shadow-md">
                        <FileSpreadsheet className="w-7 h-7 text-white" strokeWidth={2} />
                    </div>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900">Inventaire EEG</h1>
                        <p className="text-sm text-gray-500">Gestion des étiquettes électroniques</p>
                    </div>
                </div>

                <div className="bg-white rounded-xl shadow-lg border border-gray-100 overflow-hidden">
                    <div className="flex border-b border-gray-100">
                        <button
                            onClick={() => { setMode("login"); setError(""); }}
                            data-testid="auth-tab-login"
                            className={`flex-1 py-3 text-sm font-semibold transition-colors ${
                                mode === "login"
                                    ? "text-[#056839] border-b-2 border-[#056839] bg-emerald-50/40"
                                    : "text-gray-500 hover:text-gray-700"
                            }`}
                        >
                            Connexion
                        </button>
                        <button
                            onClick={() => { setMode("register"); setError(""); }}
                            data-testid="auth-tab-register"
                            className={`flex-1 py-3 text-sm font-semibold transition-colors ${
                                mode === "register"
                                    ? "text-[#056839] border-b-2 border-[#056839] bg-emerald-50/40"
                                    : "text-gray-500 hover:text-gray-700"
                            }`}
                        >
                            Créer un compte
                        </button>
                    </div>

                    <form onSubmit={onSubmit} className="p-6 space-y-4">
                        {mode === "register" && (
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Nom</label>
                                <div className="relative">
                                    <User className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                                    <input
                                        type="text"
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        placeholder="Votre nom (optionnel)"
                                        data-testid="auth-name"
                                        className="w-full h-10 pl-9 pr-3 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#056839]/30 focus:border-[#056839] outline-none"
                                    />
                                </div>
                            </div>
                        )}
                        <div>
                            <label className="block text-xs font-semibold text-gray-700 mb-1">Email</label>
                            <div className="relative">
                                <Mail className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                                <input
                                    type="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                    autoComplete={mode === "login" ? "username" : "email"}
                                    placeholder="vous@exemple.com"
                                    data-testid="auth-email"
                                    className="w-full h-10 pl-9 pr-3 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#056839]/30 focus:border-[#056839] outline-none"
                                />
                            </div>
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-gray-700 mb-1">Mot de passe</label>
                            <div className="relative">
                                <Lock className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                                <input
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    minLength={6}
                                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                                    placeholder="••••••••"
                                    data-testid="auth-password"
                                    className="w-full h-10 pl-9 pr-3 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#056839]/30 focus:border-[#056839] outline-none"
                                />
                            </div>
                            {mode === "register" && (
                                <p className="mt-1 text-xs text-gray-500">Au moins 6 caractères</p>
                            )}
                        </div>

                        {error && (
                            <div className="px-3 py-2 bg-red-50 border border-red-200 rounded text-sm text-red-700" data-testid="auth-error">
                                {error}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            data-testid="auth-submit"
                            className="w-full h-10 bg-[#056839] hover:bg-[#04502b] text-white text-sm font-semibold rounded transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                        >
                            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                            {mode === "login" ? "Se connecter" : "Créer mon compte"}
                        </button>

                        {mode === "login" && onForgotPassword && (
                            <div className="text-center">
                                <button
                                    type="button"
                                    onClick={onForgotPassword}
                                    data-testid="auth-forgot-link"
                                    className="text-xs text-emerald-700 hover:text-emerald-900 hover:underline"
                                >
                                    Mot de passe oublié ?
                                </button>
                            </div>
                        )}
                    </form>

                    <div className="px-6 pb-4 text-xs text-gray-500 text-center">
                        Vos sessions sont privées et liées à votre compte.
                    </div>
                </div>
            </div>
        </div>
    );
}
