import React from "react";
import { Boxes, Cctv, ChevronRight } from "lucide-react";

/**
 * Écran de sélection Phasage EEG vs Phasage Caméra.
 * Affiché après le choix d'un magasin, avant l'accès au tableau de bord/nuits/etc.
 * Les deux catégories partagent le même dataset backend (rapport commun) mais
 * proposent une vue simplifiée pour l'utilisateur terrain / chef de projet.
 */
export default function PhaseCategoryPicker({ state, onPick, accent = "emerald" }) {
    const eegNuits = (state?.nights || []).filter((n) => n.nb_allees > 0).length;
    const camNuits = ((state?.cam || {}).nights || []).filter((n) => n.nb_allees > 0).length;
    const camAllees = ((state?.cam || {}).allees || []).length;
    const eegAllees = (state?.allees || []).length;
    const camStart = state?.cam?.start_at_nuit || null;
    const accentBorder = accent === "amber" ? "hover:border-amber-500/60" : "hover:border-emerald-600/60";
    const accentText = accent === "amber" ? "text-amber-400" : "text-emerald-400";
    const accentBg = accent === "amber" ? "bg-amber-900/30" : "bg-emerald-900/40";
    const accentIcon = accent === "amber" ? "text-amber-400" : "text-emerald-400";

    return (
        <main className="max-w-2xl mx-auto px-4 py-8" data-testid="phase-category-picker">
            <h2 className="text-lg font-bold mb-1">Choisir un phasage</h2>
            <p className="text-sm text-slate-400 mb-5">
                Deux vues distinctes pour ce magasin — les données restent connectées et
                le rapport reste commun.
            </p>
            <div className="space-y-3">
                <button onClick={() => onPick("eeg")} data-testid="pick-phase-eeg"
                    className={`w-full flex items-center gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 ${accentBorder} hover:bg-slate-900/60 transition-all text-left group`}>
                    <div className={`w-11 h-11 rounded-lg bg-slate-800 flex items-center justify-center flex-shrink-0 group-hover:${accentBg} transition-colors`}>
                        <Boxes className={`w-5 h-5 ${accentIcon}`} />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold">Phasage EEG</div>
                        <div className="text-[11px] text-slate-500">
                            {eegNuits} nuit(s) planifiée(s) · {eegAllees} allée(s) EEG
                        </div>
                    </div>
                    <ChevronRight className={`w-4 h-4 text-slate-600 group-hover:${accentText} transition-colors`} />
                </button>
                <button onClick={() => onPick("cam")} data-testid="pick-phase-cam"
                    className="w-full flex items-center gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-sky-500/60 hover:bg-slate-900/60 transition-all text-left group">
                    <div className="w-11 h-11 rounded-lg bg-slate-800 flex items-center justify-center flex-shrink-0 group-hover:bg-sky-900/40 transition-colors">
                        <Cctv className="w-5 h-5 text-sky-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold">Phasage Caméra</div>
                        <div className="text-[11px] text-slate-500">
                            {camNuits} nuit(s) caméras · {camAllees} allée(s)
                            {camStart ? ` · démarrage nuit ${camStart}` : ""}
                        </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-sky-400 transition-colors" />
                </button>
            </div>
        </main>
    );
}
