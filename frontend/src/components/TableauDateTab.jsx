import React, { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { CalendarDays, Loader2, Wand2 } from "lucide-react";
import PrefillDatesDialog from "./PrefillDatesDialog";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Mêmes couleurs que PhasageTab : 1 couleur par position dans la semaine
const WEEK_COLORS = [
    { bg: "#DBEAFE", border: "#60A5FA" }, // 1 bleu
    { bg: "#FEF3C7", border: "#F59E0B" }, // 2 jaune
    { bg: "#FEE2E2", border: "#EF4444" }, // 3 rouge
    { bg: "#DCFCE7", border: "#22C55E" }, // 4 vert
];

function nightPositionInWeek(nuit, weeks) {
    if (!nuit) return 0;
    if (!weeks || weeks.length === 0) return nuit;
    let remaining = nuit;
    for (const w of weeks) {
        const ww = w || 0;
        if (remaining <= ww) return remaining;
        remaining -= ww;
    }
    return remaining;
}

function nightColor(n, weeks) {
    if (!n) return null;
    // (iter48k) Couleur = position dans la semaine (règle métier utilisateur)
    const pos = nightPositionInWeek(n, weeks);
    if (!pos) return null;
    return WEEK_COLORS[(pos - 1) % WEEK_COLORS.length];
}

function fmt(n) {
    if (n == null || n === 0) return "—";
    if (typeof n === "number") return n.toLocaleString("fr-FR");
    return n;
}

function formatDateLong(iso) {
    if (!iso) return "";
    try {
        const d = new Date(iso + "T00:00:00");
        return d.toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "short" });
    } catch {
        return iso;
    }
}

/**
 * Tableau Date : pour chaque nuit du plan ES (Phasage de pose), affiche :
 *   - Date (input HTML5 type=date, calendrier natif)
 *   - EEG à poser (auto, somme par nuit du plan ES)
 *   - Caméras à poser (auto, somme par nuit du plan Caméras, en alignant via start_at_nuit)
 *   - SA (info, italique, somme SA 1.5+2.1 par nuit)
 *
 * Lecture seule sauf la ligne Date.
 */
export default function TableauDateTab({ uploadId, readOnly = false }) {
    const [summary, setSummary] = useState(null);
    const [dates, setDates] = useState({}); // {"1":"2026-02-15",...}
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [saving, setSaving] = useState(false);
    const [prefillOpen, setPrefillOpen] = useState(false);

    const load = useCallback(() => {
        if (!uploadId) return;
        setLoading(true);
        axios.get(`${API}/dataset/${uploadId}/phasage-summary`)
            .then((res) => {
                setSummary(res.data);
                const ph = res.data.phasage || {};
                setDates(ph.dates || {});
            })
            .catch((e) => setError(e.response?.data?.detail || e.message))
            .finally(() => setLoading(false));
    }, [uploadId]);

    useEffect(() => { load(); }, [load]);

    // Auto-save dates avec debounce
    useEffect(() => {
        if (!summary || readOnly) return;
        const t = setTimeout(() => {
            setSaving(true);
            const ph = summary.phasage || {};
            axios.patch(`${API}/dataset/${uploadId}/phasage`, {
                es: ph.es || { nb_nuits: 3, rows: [] },
                cam: ph.cam || { nb_nuits: 3, rows: [], start_at_nuit: 5 },
                suivi: ph.suivi || { rows: [] },
                dates,
            }).catch((e) => console.error("Save dates failed:", e))
              .finally(() => setSaving(false));
        }, 500);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [dates]);

    // Calcule l'ensemble unifié des nuits à afficher : union nuits ES + nuits Cam (avec offset start_at)
    const { nbNuits, weeks, esRows, camRows, camStartAt, alleeIndex } = useMemo(() => {
        if (!summary) return { nbNuits: 0, weeks: [], esRows: [], camRows: [], camStartAt: 5, alleeIndex: {} };
        const ph = summary.phasage || {};
        const es = ph.es || { nb_nuits: 3, rows: [], weeks: null };
        const cam = ph.cam || { nb_nuits: 3, rows: [], start_at_nuit: 5 };
        const map = {};
        (summary.allees || []).forEach((a) => { map[String(a.uid || a.allee)] = a; });
        (summary.seasonal_zones || []).forEach((z) => {
            const sa15 = Number(z.sa_15) || 0;
            const sa21 = Number(z.sa_21) || 0;
            const eegZ = Number(z.eeg) || (sa15 + sa21);
            map[z.id] = {
                uid: z.id, allee: z.id, label: z.label,
                es_15: 0, es_21: 0,
                sa: sa15 + sa21, sa_15: sa15, sa_21: sa21 || (sa15 === 0 ? eegZ : 0),
                sa_21_std: sa21 || (sa15 === 0 ? eegZ : 0),
                rails_es: 0, cameras: 0,
                is_seasonal: true, seasonal_eeg: eegZ,
            };
        });
        // nbNuits = max entre es.nb_nuits ET (cam.start_at + cam.nb_nuits - 1)
        const startAt = cam.start_at_nuit || 5;
        const maxNuit = Math.max(es.nb_nuits || 0, startAt + (cam.nb_nuits || 0) - 1);
        return {
            nbNuits: maxNuit,
            weeks: Array.isArray(es.weeks) ? es.weeks : [],
            esRows: es.rows || [],
            camRows: cam.rows || [],
            camStartAt: startAt,
            alleeIndex: map,
        };
    }, [summary]);

    // Calcule par nuit les totaux EEG / Cam / SA
    const totalsByNight = useMemo(() => {
        const tot = {};
        const isMag2 = summary?.store_mode === "magasin_2";
        for (let n = 1; n <= nbNuits; n++) {
            tot[n] = { eeg: 0, cameras: 0, sa: 0 };
        }
        // EEG (depuis plan ES)
        esRows.forEach((r) => {
            if (!r.nuit) return;
            const node = alleeIndex[String(r.allee)];
            if (!node) return;
            if (node.is_seasonal) {
                // (v27) ZS = SA posées par VT : 400 SA 1.5 + 1600 SA 2.1.
                // Ces valeurs vont dans EEG ES+SA, PAS dans SA magasin.
                const sa15z = node.sa_15 || 0;
                const sa21z = node.sa_21 || node.sa_21_std || 0;
                tot[r.nuit].eeg += sa15z + sa21z;
            } else {
                const base = (node.es_15 || 0) + (node.es_21 || 0);
                const bonus = isMag2 ? 0 : ((node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0));
                const sa15 = isMag2 ? (node.sa_15 || 0) : 0;
                tot[r.nuit].eeg += base + bonus + sa15;
                tot[r.nuit].sa += isMag2 ? (node.sa_21 || 0) : (node.sa || 0);
            }
        });
        // Caméras (depuis plan Cam, en décalant)
        camRows.forEach((r) => {
            if (!r.nuit) return;
            const globalN = camStartAt + r.nuit - 1;
            if (!tot[globalN]) return;
            const node = alleeIndex[String(r.allee)];
            if (!node) return;
            tot[globalN].cameras += node.cameras || 0;
        });
        return tot;
    }, [esRows, camRows, camStartAt, alleeIndex, nbNuits, summary]);

    const onChangeDate = (nuit, val) => {
        setDates((d) => {
            const next = { ...d };
            const k = String(nuit);
            if (val) next[k] = val;
            else delete next[k];
            return next;
        });
    };

    if (loading) return <div className="flex items-center justify-center h-full text-sm text-gray-500"><Loader2 className="w-4 h-4 animate-spin mr-2" />Chargement…</div>;
    if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;
    if (nbNuits === 0) {
        return <div className="p-8 text-sm text-gray-500 italic">Aucune nuit configurée. Allez d'abord dans « Phasage de pose » pour définir le nombre de nuits.</div>;
    }

    return (
        <div className="h-full flex flex-col bg-white" data-testid="tableau-date-tab">
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-3 bg-blue-50/50 flex-shrink-0">
                <CalendarDays className="w-4 h-4 text-blue-700" />
                <span className="text-sm font-semibold text-blue-900">Tableau date</span>
                <span className="text-xs text-blue-800 italic">
                    {nbNuits} nuit{nbNuits > 1 ? "s" : ""} · structure depuis « Phasage de pose »
                </span>
                {saving && <span className="text-xs text-gray-500 ml-2">Sauvegarde…</span>}
                <div className="ml-auto">
                    {!readOnly && (
                        <button
                            onClick={() => setPrefillOpen(true)}
                            disabled={nbNuits === 0}
                            data-testid="prefill-open-button"
                            className="h-8 px-3 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded flex items-center gap-1.5 disabled:opacity-50 transition-colors"
                            title="Pré-remplir automatiquement les dates de toutes les nuits"
                        >
                            <Wand2 className="w-3.5 h-3.5" />
                            Pré-remplir les dates
                        </button>
                    )}
                </div>
            </div>

            <div className="flex-1 overflow-auto custom-scroll p-3">
                <table className="border-collapse text-xs" data-testid="tableau-date-grid">
                    <thead>
                        <tr>
                            <th className="px-2 py-1.5 text-left font-semibold text-gray-700 bg-gray-50 border border-gray-200 sticky left-0 z-10 min-w-[80px]">
                                Libellé
                            </th>
                            {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                const c = nightColor(n, weeks);
                                return (
                                    <th
                                        key={n}
                                        className="px-2 py-1.5 text-center font-semibold text-gray-800 border border-gray-200 min-w-[110px]"
                                        style={c ? { backgroundColor: c.bg, borderTopColor: c.border, borderTopWidth: "3px" } : {}}
                                        data-testid={`td-header-${n}`}
                                    >
                                        Nuit {n}
                                    </th>
                                );
                            })}
                        </tr>
                    </thead>
                    <tbody>
                        {/* Ligne DATE */}
                        <tr>
                            <th className="px-2 py-1.5 text-left font-semibold text-gray-700 bg-gray-50 border border-gray-200 sticky left-0">Date</th>
                            {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                const c = nightColor(n, weeks);
                                const k = String(n);
                                return (
                                    <td
                                        key={n}
                                        className="px-2 py-1.5 text-center border border-gray-200"
                                        style={c ? { backgroundColor: c.bg } : {}}
                                    >
                                        <input
                                            type="date"
                                            value={dates[k] || ""}
                                            onChange={(e) => onChangeDate(n, e.target.value)}
                                            disabled={readOnly}
                                            data-testid={`td-date-${n}`}
                                            className="w-full h-7 px-1.5 text-xs border border-gray-300 bg-white rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none font-mono-data"
                                        />
                                        {dates[k] && (
                                            <div className="text-[10px] text-gray-500 mt-0.5 capitalize">{formatDateLong(dates[k])}</div>
                                        )}
                                    </td>
                                );
                            })}
                        </tr>
                        {/* Ligne EEG ES+SA */}
                        <tr>
                            <th className="px-2 py-1.5 text-left font-semibold text-gray-700 bg-gray-50 border border-gray-200 sticky left-0">EEG ES+SA</th>
                            {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                const c = nightColor(n, weeks);
                                const t = totalsByNight[n] || { eeg: 0 };
                                return (
                                    <td
                                        key={n}
                                        className="px-2 py-1.5 text-center font-mono-data font-bold text-gray-900 border border-gray-200"
                                        style={c ? { backgroundColor: c.bg } : {}}
                                        data-testid={`td-eeg-${n}`}
                                    >
                                        {fmt(Math.round(t.eeg))}
                                    </td>
                                );
                            })}
                        </tr>
                        {/* Ligne SA magasin — italique car pour info */}
                        <tr>
                            <th className="px-2 py-1.5 text-left font-semibold text-gray-500 bg-gray-50 border border-gray-200 sticky left-0 italic">SA magasin</th>
                            {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                const c = nightColor(n, weeks);
                                const t = totalsByNight[n] || { sa: 0 };
                                return (
                                    <td
                                        key={n}
                                        className="px-2 py-1.5 text-center font-mono-data text-gray-500 italic border border-gray-200"
                                        style={c ? { backgroundColor: c.bg } : {}}
                                        data-testid={`td-sa-${n}`}
                                    >
                                        {fmt(t.sa)}
                                    </td>
                                );
                            })}
                        </tr>
                    </tbody>
                </table>
            </div>

            <PrefillDatesDialog
                open={prefillOpen}
                weeks={weeks}
                nbNuits={nbNuits}
                initialNuit1={dates["1"] || ""}
                onClose={() => setPrefillOpen(false)}
                onApply={(newDates) => {
                    setDates(newDates);
                    setPrefillOpen(false);
                }}
            />
        </div>
    );
}
