import React, { useState } from "react";
import axios from "axios";
import { FileSpreadsheet, Mail, Loader2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function ForgotPasswordScreen({ onBack }) {
    const [email, setEmail] = useState("");
    const [loading, setLoading] = useState(false);
    const [submitted, setSubmitted] = useState(false);

    const onSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            await axios.post(`${API}/auth/forgot-password`, { email: email.trim() });
            setSubmitted(true);
            toast.success("Demande envoyée");
        } catch (err) {
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 via-white to-gray-100 px-4" data-testid="forgot-screen">
            <div className="w-full max-w-md">
                <div className="flex items-center gap-3 mb-8 justify-center">
                    <div className="w-12 h-12 rounded-lg bg-[#005BAB] flex items-center justify-center shadow-md">
                        <FileSpreadsheet className="w-7 h-7 text-white" strokeWidth={2} />
                    </div>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900">phasage_crf</h1>
                        <p className="text-sm text-gray-500">Mot de passe oublié</p>
                    </div>
                </div>

                <div className="bg-white rounded-xl shadow-lg border border-gray-100 p-6">
                    <button
                        onClick={onBack}
                        data-testid="forgot-back"
                        className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 mb-4"
                    >
                        <ArrowLeft className="w-3 h-3" /> Retour à la connexion
                    </button>

                    {submitted ? (
                        <div data-testid="forgot-confirm" className="text-center py-3">
                            <div className="text-3xl mb-3">📩</div>
                            <h2 className="text-base font-semibold text-gray-900 mb-2">Demande enregistrée</h2>
                            <p className="text-sm text-gray-600">
                                Si un compte existe pour <span className="font-semibold">{email}</span>, un lien de réinitialisation a été généré.
                            </p>
                            <p className="text-xs text-gray-500 mt-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded">
                                ⚠️ Service email non configuré : demandez à votre administrateur de récupérer le lien dans les logs serveur, ou consultez-les directement.
                            </p>
                        </div>
                    ) : (
                        <form onSubmit={onSubmit} className="space-y-4">
                            <h2 className="text-base font-semibold text-gray-900">Réinitialiser le mot de passe</h2>
                            <p className="text-xs text-gray-500">
                                Entrez votre email. Un lien de réinitialisation sera généré (valable 1h).
                            </p>
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Email</label>
                                <div className="relative">
                                    <Mail className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                                    <input
                                        type="email"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        required
                                        autoComplete="email"
                                        placeholder="vous@exemple.com"
                                        data-testid="forgot-email"
                                        className="w-full h-10 pl-9 pr-3 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-[#005BAB]/30 focus:border-[#005BAB] outline-none"
                                    />
                                </div>
                            </div>
                            <button
                                type="submit"
                                disabled={loading}
                                data-testid="forgot-submit"
                                className="w-full h-10 bg-[#005BAB] hover:bg-[#04502b] text-white text-sm font-semibold rounded transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                            >
                                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                                Envoyer la demande
                            </button>
                        </form>
                    )}
                </div>
            </div>
        </div>
    );
}
