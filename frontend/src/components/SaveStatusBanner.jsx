import React from "react";
import { AlertTriangle, RotateCw, X, Loader2, Save, CheckCircle2 } from "lucide-react";

/**
 * Banner de statut de sauvegarde — s'affiche en HAUT de l'écran quand :
 *   - saveStatus === "error"  → banner rouge PERSISTANT avec bouton "Réessayer"
 *   - saveStatus === "saving" → banner bleu discret pendant retry (attempt > 0)
 *   - saveStatus === "saved"  → petit toast vert "Sauvegardé" qui s'estompe
 */
export function SaveStatusBanner({ saveStatus, errorMessage, retryCount, retryNow, lastSavedAt }) {
    if (saveStatus === "error") {
        return (
            <div className="w-full bg-red-600 text-white px-4 py-2.5 flex items-center gap-3 shadow-md"
                data-testid="save-error-banner">
                <AlertTriangle className="w-5 h-5 shrink-0" />
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold">
                        Sauvegarde impossible — vos dernières modifications ne sont pas enregistrées
                    </div>
                    <div className="text-xs text-red-100 mt-0.5 truncate">
                        {retryCount > 0 && `Tentative ${retryCount} · `}
                        {errorMessage || "Vérifiez votre connexion internet"}
                        {" · Votre travail est sauvegardé localement dans votre navigateur"}
                    </div>
                </div>
                <button
                    onClick={retryNow}
                    data-testid="save-retry-now"
                    className="px-3 py-1.5 bg-white text-red-700 text-xs font-bold rounded hover:bg-red-50 flex items-center gap-1.5 whitespace-nowrap"
                >
                    <RotateCw className="w-3.5 h-3.5" /> Réessayer maintenant
                </button>
            </div>
        );
    }
    if (saveStatus === "saving" && retryCount > 0) {
        return (
            <div className="w-full bg-amber-500 text-white px-4 py-2 flex items-center gap-3"
                data-testid="save-retrying-banner">
                <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                <div className="text-sm">
                    Nouvelle tentative de sauvegarde en cours (essai #{retryCount + 1})…
                </div>
            </div>
        );
    }
    if (saveStatus === "saved" && lastSavedAt) {
        // Affiché sous forme d'indicateur discret dans le header, pas ici
        return null;
    }
    return null;
}

/**
 * Prompt de récupération — s'affiche si un backup localStorage plus récent
 * que le serveur est détecté au chargement.
 */
export function RecoveryPrompt({ pendingRecovery, onApply, onDismiss }) {
    if (!pendingRecovery) return null;
    const savedAt = pendingRecovery.savedAt
        ? new Date(pendingRecovery.savedAt).toLocaleString("fr-FR")
        : "";
    const wasPending = pendingRecovery.pending === true;
    return (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
            data-testid="recovery-prompt">
            <div className="w-full max-w-md bg-white rounded-xl shadow-2xl overflow-hidden">
                <div className="px-5 py-3 bg-amber-50 border-b border-amber-200 flex items-center gap-2">
                    <Save className="w-5 h-5 text-amber-700" />
                    <h3 className="text-base font-bold text-amber-900">Sauvegarde locale détectée</h3>
                </div>
                <div className="p-5 text-sm text-gray-700 space-y-3">
                    <p>
                        Une sauvegarde locale de vos modifications a été trouvée sur ce navigateur
                        {wasPending && " (elle n'a pas pu être enregistrée sur le serveur au moment du plantage)"}
                        .
                    </p>
                    <p className="text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded px-2 py-1.5 font-mono">
                        Dernière modification locale : {savedAt}
                    </p>
                    <p>Que souhaitez-vous faire ?</p>
                </div>
                <div className="px-5 pb-5 flex items-center justify-end gap-2">
                    <button
                        onClick={onDismiss}
                        data-testid="recovery-dismiss"
                        className="h-9 px-3 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-100"
                    >
                        Ignorer (garder la version serveur)
                    </button>
                    <button
                        onClick={onApply}
                        data-testid="recovery-apply"
                        className="h-9 px-4 bg-[#005BAB] text-white text-sm font-semibold rounded hover:bg-[#004A8A] flex items-center gap-1.5"
                    >
                        <CheckCircle2 className="w-4 h-4" /> Restaurer la sauvegarde locale
                    </button>
                </div>
            </div>
        </div>
    );
}

/**
 * Indicateur discret dans l'en-tête (petit texte + icône).
 */
export function SaveIndicator({ saveStatus, lastSavedAt }) {
    if (saveStatus === "saving") {
        return (
            <span className="text-xs text-gray-500 flex items-center gap-1" data-testid="save-indicator-saving">
                <Loader2 className="w-3 h-3 animate-spin" /> Sauvegarde…
            </span>
        );
    }
    if (saveStatus === "saved" && lastSavedAt) {
        return (
            <span className="text-xs text-green-700 flex items-center gap-1" data-testid="save-indicator-saved">
                <CheckCircle2 className="w-3 h-3" /> Sauvegardé
            </span>
        );
    }
    return null;
}
