import React, { useState, useMemo, useEffect } from "react";
import { X, Wand2, Loader2 } from "lucide-react";

// Jours par défaut travaillés : Lundi=0, Mardi=1, Mercredi=2, Jeudi=3
const WEEK_DAYS = [
    { idx: 0, label: "Lundi", short: "Lun" },
    { idx: 1, label: "Mardi", short: "Mar" },
    { idx: 2, label: "Mercredi", short: "Mer" },
    { idx: 3, label: "Jeudi", short: "Jeu" },
];

/**
 * Heuristique par défaut : choisit les jours travaillés (parmi Lun/Mar/Mer/Jeu)
 * en fonction du nombre de nuits, en suivant la règle :
 *   - on ne travaille pas la nuit dont la fin tombe un jour férié
 *   - on ne travaille pas la nuit qui couvre un jour férié
 *
 * On déduit donc le férié par défaut :
 *   - 4 nuits : pas de férié → [Lun, Mar, Mer, Jeu]
 *   - 3 nuits : férié Lundi → [Mar, Mer, Jeu]
 *   - 2 nuits : férié Mardi → [Mer, Jeu]   (cas le plus fréquent)
 *   - 1 nuit  : férié Mercredi → [Jeu]
 *   - 0 nuit  : []
 */
function defaultDaysForWeek(count) {
    if (count >= 4) return [0, 1, 2, 3];
    if (count === 3) return [1, 2, 3];
    if (count === 2) return [2, 3];
    if (count === 1) return [3];
    return [];
}

function isoDate(d) {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
}

/** Recule la date jusqu'au lundi de la semaine (Lundi=1, Dimanche=0 → -6). */
function mondayOf(date) {
    const d = new Date(date);
    const dow = d.getDay(); // 0=dim, 1=lun, ..., 6=sam
    const diff = dow === 0 ? -6 : 1 - dow;
    d.setDate(d.getDate() + diff);
    return d;
}

export default function PrefillDatesDialog({ open, weeks, nbNuits, initialNuit1, onClose, onApply }) {
    const computedWeeks = useMemo(() => {
        if (Array.isArray(weeks) && weeks.length > 0 && weeks.some((w) => w > 0)) return weeks.filter((w) => w > 0);
        // Pas de découpage semaine défini : on traite tout comme une seule "période"
        return nbNuits > 0 ? [nbNuits] : [];
    }, [weeks, nbNuits]);

    // État : date de Nuit 1 + pour chaque semaine, set des jours cochés
    const [nuit1Date, setNuit1Date] = useState(initialNuit1 || "");
    const [weekDays, setWeekDays] = useState([]); // [ [0,1,2,3], [2,3], ... ]

    // (Re)initialisation à l'ouverture
    useEffect(() => {
        if (!open) return;
        setNuit1Date(initialNuit1 || "");
        setWeekDays(computedWeeks.map((c) => defaultDaysForWeek(c)));
    }, [open, initialNuit1, computedWeeks]);

    const toggleDay = (weekIdx, dayIdx) => {
        setWeekDays((prev) => {
            const next = prev.map((arr) => [...arr]);
            const set = new Set(next[weekIdx]);
            if (set.has(dayIdx)) set.delete(dayIdx);
            else set.add(dayIdx);
            next[weekIdx] = Array.from(set).sort((a, b) => a - b);
            return next;
        });
    };

    const totalSelected = weekDays.reduce((s, w) => s + w.length, 0);
    const overShoot = totalSelected !== nbNuits;

    const handleApply = () => {
        if (!nuit1Date) return;
        // Lundi de la semaine de la première nuit
        let monday = mondayOf(new Date(nuit1Date + "T12:00:00"));
        const result = {};
        let nuit = 1;
        for (let wi = 0; wi < weekDays.length; wi++) {
            const days = weekDays[wi];
            for (const dayIdx of days) {
                const d = new Date(monday);
                d.setDate(d.getDate() + dayIdx);
                result[String(nuit)] = isoDate(d);
                nuit++;
                if (nuit > nbNuits) break;
            }
            if (nuit > nbNuits) break;
            // Passe à la semaine suivante (Lundi + 7)
            monday.setDate(monday.getDate() + 7);
        }
        onApply(result);
    };

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-[100] bg-black/40 flex items-center justify-center p-4" onClick={onClose} data-testid="prefill-dialog">
            <div className="bg-white rounded-lg shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                <div className="px-5 py-3 border-b border-gray-200 flex items-center justify-between bg-gradient-to-r from-emerald-50 to-white">
                    <div className="flex items-center gap-2">
                        <Wand2 className="w-5 h-5 text-emerald-700" />
                        <h3 className="text-base font-bold text-gray-900">Pré-remplir les dates</h3>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600" data-testid="prefill-close">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-5 space-y-4">
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Date de la Nuit 1</label>
                        <input
                            type="date"
                            value={nuit1Date}
                            onChange={(e) => setNuit1Date(e.target.value)}
                            data-testid="prefill-nuit1-date"
                            className="w-full sm:w-56 h-9 px-3 text-sm border border-gray-300 rounded focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 outline-none font-mono-data"
                        />
                        <p className="mt-1 text-xs text-gray-500">
                            Choisissez le jour de pose de la <strong>première nuit</strong>. L'app calcule le reste à partir de cette date.
                        </p>
                    </div>

                    <div className="border-t border-gray-100 pt-3">
                        <p className="text-xs text-gray-700 mb-2">
                            <strong>Jours travaillés par semaine.</strong>{" "}
                            Par défaut, on travaille <strong>Lun-Mar-Mer-Jeu</strong>. Si une semaine a moins de nuits (jour férié), décochez les jours non travaillés (la nuit dont la fin tombe un férié <em>et</em> celle qui couvre le férié sont à exclure).
                        </p>

                        <div className="space-y-2" data-testid="prefill-weeks">
                            {computedWeeks.map((cnt, wi) => {
                                const selected = weekDays[wi] || [];
                                const ok = selected.length === cnt;
                                return (
                                    <div
                                        key={wi}
                                        className={`flex items-center gap-3 p-2 rounded border ${ok ? "border-emerald-200 bg-emerald-50/40" : "border-amber-300 bg-amber-50/40"}`}
                                    >
                                        <span className="text-xs font-semibold text-gray-700 w-24 flex-shrink-0">
                                            Semaine {wi + 1}
                                            <span className="block text-[10px] font-normal text-gray-500">
                                                {cnt} nuit{cnt > 1 ? "s" : ""}
                                            </span>
                                        </span>
                                        <div className="flex gap-1.5 flex-wrap">
                                            {WEEK_DAYS.map((d) => {
                                                const on = selected.includes(d.idx);
                                                return (
                                                    <button
                                                        key={d.idx}
                                                        type="button"
                                                        onClick={() => toggleDay(wi, d.idx)}
                                                        data-testid={`prefill-w${wi}-day-${d.idx}`}
                                                        className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                                                            on
                                                                ? "bg-emerald-600 text-white border-emerald-600"
                                                                : "bg-white text-gray-600 border-gray-300 hover:bg-gray-50"
                                                        }`}
                                                        title={d.label}
                                                    >
                                                        {d.short}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                        <span className={`text-xs ${ok ? "text-emerald-700" : "text-amber-700 font-semibold"}`}>
                                            {selected.length} / {cnt}
                                        </span>
                                    </div>
                                );
                            })}
                        </div>

                        {overShoot && (
                            <p className="mt-2 text-xs text-amber-700">
                                ⚠ Total sélectionné : <strong>{totalSelected}</strong> · attendu : <strong>{nbNuits}</strong>. Ajustez les cases.
                            </p>
                        )}
                    </div>
                </div>

                <div className="px-5 py-3 border-t border-gray-100 bg-gray-50 flex items-center justify-between rounded-b-lg">
                    <p className="text-xs text-gray-500">Vous pourrez modifier chaque date manuellement après application.</p>
                    <div className="flex gap-2">
                        <button
                            onClick={onClose}
                            className="h-9 px-3 text-sm text-gray-600 hover:bg-gray-100 rounded"
                            data-testid="prefill-cancel"
                        >
                            Annuler
                        </button>
                        <button
                            onClick={handleApply}
                            disabled={!nuit1Date}
                            data-testid="prefill-apply"
                            className="h-9 px-4 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded disabled:opacity-50 flex items-center gap-1.5"
                        >
                            <Wand2 className="w-4 h-4" /> Appliquer
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
