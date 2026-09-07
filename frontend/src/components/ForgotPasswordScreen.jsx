import React from "react";
import { FileSpreadsheet, ArrowLeft, ShieldAlert } from "lucide-react";

export default function ForgotPasswordScreen({ onBack }) {
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

                    <div className="text-center py-4" data-testid="forgot-contact-admin">
                        <div className="w-14 h-14 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-4">
                            <ShieldAlert className="w-7 h-7 text-[#005BAB]" />
                        </div>
                        <h2 className="text-base font-semibold text-gray-900 mb-2">
                            Contactez votre administrateur
                        </h2>
                        <p className="text-sm text-gray-600 leading-relaxed">
                            Pour réinitialiser votre mot de passe, merci de contacter directement l&apos;administrateur de l&apos;outil.
                            Il pourra vous générer un nouveau mot de passe temporaire.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
}
