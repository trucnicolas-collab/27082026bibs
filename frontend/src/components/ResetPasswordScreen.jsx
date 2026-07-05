import React, { useState } from "react";
import axios from "axios";
import { FileSpreadsheet, Lock, Loader2 } from "lucide-react";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function ResetPasswordScreen({ token, onSuccess }) {
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [done, setDone] = useState(false);

    const onSubmit = async (e) => {
        e.preventDefault();
        setError("");
        if (password !== confirm) {
            setError("Les mots de passe ne correspondent pas");
            return;
        }
        if (password.length < 6) {
            setError("Au moins 6 caractères");
            return;
        }
        setLoading(true);
        try {
            await axios.post(`${API}/auth/reset-password`, { token, password });
            setDone(true);
            toast.success("Mot de passe réinitialisé");
            // Nettoie l'URL puis redirige vers login après un délai
            setTimeout(() => {
                window.history.replaceState({}, "", window.location.pathname);
                onSuccess && onSuccess();
            }, 1500);
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-50 via-white to-gray-100 px-4" data-testid="reset-screen">
            <div className="w-full max-w-md">
                <div className="flex items-center gap-3 mb-8 justify-center">
                    <div className="w-12 h-12 rounded-lg bg-[#056839] flex items-center justify-center shadow-md">
                        <FileSpreadsheet className="w-7 h-7 text-white" strokeWidth={2} />
                    </div>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900">phasage_crf</h1>
                        <p className="text-sm text-gray-500">Nouveau mot de passe</p>
                    </div>
                </div>

                <div className="bg-white rounded-xl shadow-lg border border-gray-100 p-6">
                    {done ? (
                        <div className="text-center py-3" data-testid="reset-done">
                            <div className="text-3xl mb-2">✅</div>
                            <h2 className="text-base font-semibold text-gray-900">Mot de passe réinitialisé</h2>
                            <p className="text-sm text-gray-500 mt-2">Redirection vers la page de connexion…</p>
                        </div>
                    ) : (
                        <form onSubmit={onSubmit} className="space-y-4">
                            <h2 className="text-base font-semibold text-gray-900">Choisissez votre nouveau mot de passe</h2>
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Nouveau mot de passe</label>
                                <div className="relative">
                                    <Lock className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                                    <input
                                        type="password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        required
                                        minLength={6}
                                        autoComplete="new-password"
                                        placeholder="••••••••"
                                        data-testid="reset-password"
                                        className="w-full h-10 pl-9 pr-3 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#056839]/30 focus:border-[#056839] outline-none"
                                    />
                                </div>
                                <p className="mt-1 text-xs text-gray-500">Au moins 6 caractères</p>
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Confirmer</label>
                                <div className="relative">
                                    <Lock className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                                    <input
                                        type="password"
                                        value={confirm}
                                        onChange={(e) => setConfirm(e.target.value)}
                                        required
                                        minLength={6}
                                        placeholder="••••••••"
                                        data-testid="reset-confirm"
                                        className="w-full h-10 pl-9 pr-3 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#056839]/30 focus:border-[#056839] outline-none"
                                    />
                                </div>
                            </div>
                            {error && (
                                <div className="px-3 py-2 bg-red-50 border border-red-200 rounded text-sm text-red-700" data-testid="reset-error">
                                    {error}
                                </div>
                            )}
                            <button
                                type="submit"
                                disabled={loading}
                                data-testid="reset-submit"
                                className="w-full h-10 bg-[#056839] hover:bg-[#04502b] text-white text-sm font-semibold rounded transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                            >
                                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                                Réinitialiser
                            </button>
                        </form>
                    )}
                </div>
            </div>
        </div>
    );
}
