import React, { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { KeyRound, X, Loader2, Eye, EyeOff } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function ChangePasswordDialog({ onClose }) {
    const [cur, setCur] = useState("");
    const [next, setNext] = useState("");
    const [confirm, setConfirm] = useState("");
    const [loading, setLoading] = useState(false);
    const [showCur, setShowCur] = useState(false);
    const [showNext, setShowNext] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        if (next.length < 6) {
            toast.error("Le nouveau mot de passe doit faire au moins 6 caractères");
            return;
        }
        if (next !== confirm) {
            toast.error("Les 2 mots de passe ne correspondent pas");
            return;
        }
        setLoading(true);
        try {
            await axios.post(`${API}/auth/change-password`,
                { current_password: cur, new_password: next },
                { withCredentials: true });
            toast.success("Mot de passe changé");
            onClose();
        } catch (err) {
            toast.error(err.response?.data?.detail || "Échec du changement");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
            data-testid="change-password-dialog" onClick={onClose}>
            <div className="w-full max-w-md bg-white rounded-xl shadow-2xl"
                onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200">
                    <div className="flex items-center gap-2">
                        <KeyRound className="w-5 h-5 text-[#005BAB]" />
                        <h3 className="text-base font-bold text-gray-900">Changer mon mot de passe</h3>
                    </div>
                    <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 text-gray-500"
                        data-testid="change-password-close">
                        <X className="w-4 h-4" />
                    </button>
                </div>
                <form onSubmit={submit} className="p-5 space-y-4">
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Mot de passe actuel</label>
                        <div className="relative">
                            <input
                                type={showCur ? "text" : "password"}
                                value={cur}
                                onChange={(e) => setCur(e.target.value)}
                                required
                                autoComplete="current-password"
                                data-testid="change-cur-password"
                                className="w-full h-10 px-3 pr-10 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#005BAB]/30 focus:border-[#005BAB] outline-none"
                            />
                            <button type="button" onClick={() => setShowCur(!showCur)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700">
                                {showCur ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                        </div>
                    </div>
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">
                            Nouveau mot de passe <span className="text-gray-400 font-normal">(min. 6 caractères)</span>
                        </label>
                        <div className="relative">
                            <input
                                type={showNext ? "text" : "password"}
                                value={next}
                                onChange={(e) => setNext(e.target.value)}
                                required
                                minLength={6}
                                autoComplete="new-password"
                                data-testid="change-new-password"
                                className="w-full h-10 px-3 pr-10 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#005BAB]/30 focus:border-[#005BAB] outline-none"
                            />
                            <button type="button" onClick={() => setShowNext(!showNext)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700">
                                {showNext ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                        </div>
                    </div>
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Confirmer le nouveau mot de passe</label>
                        <input
                            type={showNext ? "text" : "password"}
                            value={confirm}
                            onChange={(e) => setConfirm(e.target.value)}
                            required
                            minLength={6}
                            autoComplete="new-password"
                            data-testid="change-confirm-password"
                            className="w-full h-10 px-3 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#005BAB]/30 focus:border-[#005BAB] outline-none"
                        />
                    </div>
                    <div className="flex items-center justify-end gap-2 pt-2">
                        <button type="button" onClick={onClose}
                            className="h-9 px-4 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-100">
                            Annuler
                        </button>
                        <button type="submit" disabled={loading}
                            data-testid="change-submit"
                            className="h-9 px-4 bg-[#005BAB] hover:bg-[#004A8A] text-white text-sm font-semibold rounded flex items-center gap-2 disabled:opacity-60">
                            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                            Valider
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
