import React from "react";
import { Check, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

const BRAND = "#056839";

// Barre de progression (stepper) + sous-onglets de l'étape + navigation Précédent/Suivant.
export default function WizardSteps({
    steps, current, onGoStep, step2Ready = false, step3Ready = false, step4Ready = false,
    subTabs = [], activeSubTab, onSubTab,
    onPrev, onNext, prevDisabled, nextDisabled, nextLabel = "Suivant", nextLoading = false,
}) {
    const readyMap = { 2: step2Ready, 3: step3Ready, 4: step4Ready };
    const readyLabel = { 2: "Complète", 3: "Prêt", 4: "Dates OK" };
    return (
        <div className="bg-white border-b border-gray-200" data-testid="wizard-steps">
            {/* Stepper */}
            <div className="flex items-center px-4 py-2.5 gap-1 overflow-x-auto">
                {steps.map((s, idx) => {
                    const done = s.n < current;
                    const active = s.n === current;
                    const showReadyBadge = !!readyMap[s.n];
                    return (
                        <React.Fragment key={s.n}>
                            <button
                                onClick={() => onGoStep(s.n)}
                                className="flex items-center gap-2 shrink-0 group"
                                data-testid={`wizard-step-${s.n}`}
                                title={s.label}
                            >
                                <span
                                    className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors"
                                    style={
                                        active
                                            ? { backgroundColor: BRAND, borderColor: BRAND, color: "#fff" }
                                            : done
                                                ? { backgroundColor: "#e6f2ec", borderColor: BRAND, color: BRAND }
                                                : { backgroundColor: "#fff", borderColor: "#d1d5db", color: "#9ca3af" }
                                    }
                                >
                                    {done ? <Check className="w-3.5 h-3.5" /> : s.n}
                                </span>
                                <span
                                    className="text-sm font-medium whitespace-nowrap"
                                    style={{ color: active ? BRAND : done ? "#374151" : "#9ca3af" }}
                                >
                                    {s.label}
                                </span>
                                {showReadyBadge && (
                                    <span
                                        className="ml-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap step-ready-badge"
                                        style={{ backgroundColor: "#e6f2ec", color: BRAND }}
                                        data-testid={`step${s.n}-ready-badge`}
                                        title="Étape complète — vous pouvez continuer"
                                    >
                                        <Check className="w-3 h-3" /> {readyLabel[s.n]}
                                    </span>
                                )}
                            </button>
                            {idx < steps.length - 1 && (
                                <div className="flex-1 min-w-[16px] h-px mx-1" style={{ backgroundColor: s.n < current ? BRAND : "#e5e7eb" }} />
                            )}
                        </React.Fragment>
                    );
                })}
            </div>

            {/* Sous-onglets + navigation */}
            <div className="flex items-center justify-between px-4 py-1.5 border-t border-gray-100 gap-2">
                <div className="flex items-center gap-1 overflow-x-auto">
                    {subTabs.map((t) => {
                        const on = t.id === activeSubTab;
                        return (
                            <button
                                key={t.id}
                                onClick={() => onSubTab(t.id)}
                                className="px-3 py-1.5 text-xs font-medium rounded-md whitespace-nowrap transition-colors hover:bg-gray-100"
                                style={on ? { backgroundColor: "#e6f2ec", color: BRAND } : { color: "#6b7280" }}
                                data-testid={`wizard-subtab-${t.id}`}
                            >
                                {t.label}
                                {typeof t.count === "number" && t.count > 0 && (
                                    <span className="ml-1.5 text-[10px] text-gray-400">{t.count}</span>
                                )}
                            </button>
                        );
                    })}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <button
                        onClick={onPrev}
                        disabled={prevDisabled}
                        className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                        data-testid="wizard-prev"
                    >
                        <ChevronLeft className="w-4 h-4" /> Précédent
                    </button>
                    <button
                        onClick={onNext}
                        disabled={nextDisabled}
                        className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-md text-white disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110"
                        style={{ backgroundColor: BRAND }}
                        data-testid="wizard-next"
                    >
                        {nextLoading
                            ? <><Loader2 className="w-4 h-4 animate-spin" /> Validation…</>
                            : <>{nextLabel} <ChevronRight className="w-4 h-4" /></>}
                    </button>
                </div>
            </div>
        </div>
    );
}
