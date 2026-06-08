import React, { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { Trash2, Download } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Priorité de tri des secteurs dans la liste de sélection d'allée
// (1 = en haut). Tout secteur inconnu va en bas (99).
const SECTOR_PRIORITY = (() => {
    const map = new Map();
    map.set("pgc", 1);
    map.set("pft", 2);
    map.set("non-al", 3);
    map.set("non al", 3);
    map.set("nonal", 3);
    map.set("caisse", 4);
    map.set("caisses", 4);
    return map;
})();

function sectorPriority(secteur) {
    const s = String(secteur || "").trim().toLowerCase();
    if (!s) return 98;
    if (SECTOR_PRIORITY.has(s)) return SECTOR_PRIORITY.get(s);
    // Préfixes plus larges
    if (s.startsWith("pgc")) return 1;
    if (s.startsWith("pft")) return 2;
    if (s.startsWith("non")) return 3;
    if (s.startsWith("caiss")) return 4;
    return 99;
}

function alleeNumeric(allee) {
    const m = String(allee || "").match(/-?\d+/);
    return m ? parseInt(m[0], 10) : 999999;
}

function fmt(n) {
    if (n == null) return "";
    if (typeof n === "number") return n.toLocaleString("fr-FR");
    return n;
}

function newRowId() {
    return `row_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// Palette FIXE : 1 couleur par "position dans la semaine" (1..4), récurrente d'une
// semaine à l'autre. Couleurs muted/professionnelles, lisibles sur Excel.
// Position 1 = bleu, 2 = jaune, 3 = rouge, 4 = vert.
const WEEK_COLORS = [
    { bg: "#DBEAFE", border: "#60A5FA" }, // 1 bleu doux
    { bg: "#FEF3C7", border: "#F59E0B" }, // 2 jaune doux
    { bg: "#FEE2E2", border: "#EF4444" }, // 3 rouge doux
    { bg: "#DCFCE7", border: "#22C55E" }, // 4 vert doux
];

/**
 * Pour un n° de nuit absolu (1..N) et un découpage par semaine `weeks` (ex: [5,3,6]),
 * retourne sa position dans la semaine courante (1..nb_nuits_semaine).
 * Si pas de découpage (weeks vide), toutes les nuits sont dans une seule "semaine".
 */
function nightPositionInWeek(nuit, weeks) {
    if (!nuit) return 0;
    if (!weeks || weeks.length === 0) return nuit;
    let remaining = nuit;
    for (const w of weeks) {
        const ww = w || 0;
        if (remaining <= ww) return remaining;
        remaining -= ww;
    }
    // Si la nuit dépasse les semaines déclarées, on cycle modulo 4 sur le reste
    return remaining;
}

// Palette legacy (compat caméras) — cyclique par nuit absolue
const NIGHT_COLORS = [
    { bg: "#FEF3C7", border: "#FCD34D" }, // 1 jaune
    { bg: "#DBEAFE", border: "#93C5FD" }, // 2 bleu
    { bg: "#D1FAE5", border: "#6EE7B7" }, // 3 vert
    { bg: "#FCE7F3", border: "#F9A8D4" }, // 4 rose
    { bg: "#E0E7FF", border: "#A5B4FC" }, // 5 indigo
    { bg: "#FED7AA", border: "#FDBA74" }, // 6 orange
    { bg: "#CCFBF1", border: "#5EEAD4" }, // 7 teal
    { bg: "#FAE8FF", border: "#E9D5FF" }, // 8 violet clair
    { bg: "#FFE4E6", border: "#FDA4AF" }, // 9 rouge clair
    { bg: "#ECFCCB", border: "#BEF264" }, // 10 lime
];
function nightColor(n, weeks) {
    if (!n) return null;
    const pos = nightPositionInWeek(n, weeks);
    if (!pos) return null;
    return WEEK_COLORS[(pos - 1) % WEEK_COLORS.length];
}

export default function PhasageTab({ uploadId }) {
    const [summary, setSummary] = useState(null); // { allees, totals, phasage, rails_es_patterns }
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [nbNuits, setNbNuits] = useState(3);
    const [rows, setRows] = useState([]);
    const [weeks, setWeeks] = useState([]); // ex: [5,3,6] ou [] (pas de découpage)
    const [saving, setSaving] = useState(false);
    const [dates, setDates] = useState({}); // {"1": "2026-02-15", ...} (lecture seule ici)
    // Méta-infos magasin / VT
    const [vtStartDate, setVtStartDate] = useState("");
    const [storeName, setStoreName] = useState("");
    const [storeCode, setStoreCode] = useState("");
    const [storeInfoLoaded, setStoreInfoLoaded] = useState(false);

    // Charger summary
    useEffect(() => {
        if (!uploadId) return;
        let mounted = true;
        setLoading(true);
        axios.get(`${API}/dataset/${uploadId}/phasage-summary`)
            .then((res) => {
                if (!mounted) return;
                setSummary(res.data);
                const ph = res.data.phasage || {};
                const p = ph.es || { nb_nuits: 3, rows: [] };
                setNbNuits(p.nb_nuits || 3);
                setWeeks(Array.isArray(p.weeks) ? p.weeks : []);
                setDates(ph.dates || {});
                setRows((p.rows || []).map((r) => ({
                    id: r.id || newRowId(),
                    allee: r.allee || "",
                    nuit: r.nuit ?? null,
                })));
            })
            .catch((e) => mounted && setError(e.message))
            .finally(() => mounted && setLoading(false));
        return () => { mounted = false; };
    }, [uploadId]);

    // Auto-save (debounce) — préserve cam et suivi en relisant le phasage complet
    useEffect(() => {
        if (!summary || !uploadId) return;
        const t = setTimeout(() => {
            setSaving(true);
            const ph = summary.phasage || {};
            axios.patch(`${API}/dataset/${uploadId}/phasage`, {
                es: {
                    nb_nuits: nbNuits,
                    rows: rows.map((r) => ({ id: r.id, allee: r.allee, nuit: r.nuit })),
                    weeks: weeks.length > 0 ? weeks : null,
                },
                cam: ph.cam || { nb_nuits: 3, rows: [], start_at_nuit: 5 },
                suivi: ph.suivi || { rows: [] },
            }).catch((e) => console.error("Save phasage failed:", e))
              .finally(() => setSaving(false));
        }, 600);
        return () => clearTimeout(t);
    }, [nbNuits, rows, weeks, uploadId, summary]);

    const alleeIndex = useMemo(() => {
        if (!summary) return {};
        const map = {};
        // Clé = uid composite (allée + secteur + rayon) pour conserver les doublons.
        // Fallback sur String(allee) si uid absent (ancien backend).
        summary.allees.forEach((a) => { map[String(a.uid || a.allee)] = a; });
        // Ajoute les zones saisonnières (clé = ID, ex: "ZS1")
        (summary.seasonal_zones || []).forEach((z) => {
            map[z.id] = {
                uid: z.id,
                allee: z.id,
                label: z.label,
                es_15: 0,
                es_21: 0,
                sa: z.eeg || 0,
                rails_es: 0,
                cameras: 0,
                is_seasonal: true,
                seasonal_eeg: z.eeg || 0,
            };
        });
        return map;
    }, [summary]);

    // Liste triée des allées dispo + zones saisonnières en fin de liste
    const alleeOptions = useMemo(() => {
        if (!summary) return [];
        // On construit une liste d'options { uid, node } triée par :
        // 1) priorité du secteur (PGC → PFT → Non-al → Caisse → autres)
        // 2) rayon (alphabétique, locale FR)
        // 3) n° d'allée (numérique croissant)
        const items = [];
        summary.allees.forEach((a) => {
            const uid = String(a.uid || a.allee);
            items.push({ uid, node: a });
        });
        (summary.seasonal_zones || []).forEach((z) => {
            items.push({ uid: String(z.id), node: { ...z, is_seasonal: true, allee: z.id, secteur: "", rayon: "" } });
        });
        items.sort((A, B) => {
            // Les zones saisonnières en dernier
            if (A.node.is_seasonal !== B.node.is_seasonal) return A.node.is_seasonal ? 1 : -1;
            const pa = sectorPriority(A.node.secteur);
            const pb = sectorPriority(B.node.secteur);
            if (pa !== pb) return pa - pb;
            const ra = (A.node.rayon || "").toLowerCase();
            const rb = (B.node.rayon || "").toLowerCase();
            if (ra !== rb) return ra.localeCompare(rb, "fr");
            const na = alleeNumeric(A.node.allee);
            const nb = alleeNumeric(B.node.allee);
            if (na !== nb) return na - nb;
            // Tie-breaker (doublons sur même n°) : dup_index croissant
            const da = A.node.dup_index || 0;
            const db = B.node.dup_index || 0;
            if (da !== db) return da - db;
            return String(A.node.allee).localeCompare(String(B.node.allee), "fr", { numeric: true });
        });
        return items;
    }, [summary]);

    // Format d'affichage d'une option : "PGC / Animalerie / Allée 4"
    const formatAlleeLabel = useCallback((node) => {
        if (!node) return "";
        if (node.is_seasonal) {
            return `🌶 ${node.label || node.id} (+${node.seasonal_eeg || 0} EEG)`;
        }
        const parts = [];
        if (node.secteur) parts.push(node.secteur);
        if (node.rayon) parts.push(node.rayon);
        parts.push(`Allée ${node.allee}`);
        let label = parts.join(" / ");
        if (node.is_dup) {
            label = `🟠 [DOUBLON ${node.dup_index}/${node.dup_total}] ` + label;
        }
        return label;
    }, []);

    const seasonalZones = summary?.seasonal_zones || [];

    const updateRow = useCallback((id, patch) => {
        setRows((prev) => prev.map((r) => r.id === id ? { ...r, ...patch } : r));
    }, []);

    const addRow = useCallback((alleeUid = "") => {
        setRows((prev) => [...prev, { id: newRowId(), allee: alleeUid, nuit: null }]);
    }, []);

    const deleteRow = useCallback((id) => {
        setRows((prev) => prev.filter((r) => r.id !== id));
    }, []);

    // Validation : ajuster nuits si nb_nuits diminue
    const onChangeNbNuits = useCallback((n) => {
        const v = Math.max(1, Math.min(30, Number(n) || 1));
        setNbNuits(v);
        setRows((prev) => prev.map((r) => r.nuit && r.nuit > v ? { ...r, nuit: null } : r));
    }, []);

    // Agrégation par nuit
    const nightTotals = useMemo(() => {
        const tot = {};
        for (let n = 1; n <= nbNuits; n++) tot[n] = { es_15: 0, es_21: 0, sa: 0, sa_15: 0, sa_21: 0, rails_es: 0, seasonal: 0, bonus: 0, cameras: 0, allees: [], secteur_rayon: new Set() };
        rows.forEach((r) => {
            if (!r.nuit) return;
            const node = alleeIndex[String(r.allee)];
            if (!node) return;
            tot[r.nuit].es_15 += node.es_15 || 0;
            tot[r.nuit].es_21 += node.es_21 || 0;
            tot[r.nuit].sa += node.sa || 0;
            tot[r.nuit].sa_15 += node.sa_15 || 0;
            tot[r.nuit].sa_21 += node.sa_21 || 0;
            tot[r.nuit].rails_es += node.rails_es || 0;
            tot[r.nuit].bonus += (node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0);
            if (node.is_seasonal) {
                tot[r.nuit].seasonal += node.seasonal_eeg || 0;
            }
            tot[r.nuit].allees.push(String(r.allee));
            // Concatène secteur:rayon (déduplication par Set)
            const sec = node.secteur || "";
            const ray = node.rayon || "";
            if (sec || ray) tot[r.nuit].secteur_rayon.add(`${sec}${ray ? ":" + ray : ""}`);
        });
        // Caméras assignées : depuis phasage.cam (les nuits cam sont décalées par start_at_nuit
        // ex: cam.nuit=1 + start_at=5 → nuit globale 5)
        const camPhasage = summary?.phasage?.cam || { rows: [], start_at_nuit: 5 };
        const startAt = camPhasage.start_at_nuit || 5;
        (camPhasage.rows || []).forEach((cr) => {
            if (!cr.nuit) return;
            const globalNuit = startAt + cr.nuit - 1;
            if (!tot[globalNuit]) return;
            const node = alleeIndex[String(cr.allee)];
            if (!node) return;
            tot[globalNuit].cameras += node.cameras || 0;
        });
        // Tri "intelligent" via l'ordre déjà calculé côté serveur (summary.allees est trié smart).
        const orderIndex = new Map();
        (summary?.allees || []).forEach((a, i) => { orderIndex.set(String(a.allee), i); });
        Object.values(tot).forEach((t) => {
            t.allees.sort((a, b) => {
                const ia = orderIndex.has(a) ? orderIndex.get(a) : 9999;
                const ib = orderIndex.has(b) ? orderIndex.get(b) : 9999;
                if (ia !== ib) return ia - ib;
                return String(a).localeCompare(String(b), "fr", { numeric: true });
            });
        });
        return tot;
    }, [rows, nbNuits, alleeIndex, summary]);

    // Allées déjà utilisées (pour les exclure des selects)
    const usedAllees = useMemo(() => {
        const s = new Set();
        rows.forEach((r) => { if (r.allee) s.add(String(r.allee)); });
        return s;
    }, [rows]);

    // Totaux globaux du récap (ligne TOTAL) — mémoïsé pour éviter 4× reduce à chaque render
    const grandTotals = useMemo(() => {
        const values = Object.values(nightTotals);
        return {
            nbAllees: values.reduce((a, x) => a + (x.allees?.length || 0), 0),
            es: values.reduce((a, x) => a + (x.es_15 || 0) + (x.es_21 || 0), 0),
            rails: values.reduce((a, x) => a + (x.rails_es || 0), 0),
            sa: values.reduce((a, x) => a + (x.sa || 0), 0),
            sa_15: values.reduce((a, x) => a + (x.sa_15 || 0), 0),
            sa_21: values.reduce((a, x) => a + (x.sa_21 || 0), 0),
            seasonal: values.reduce((a, x) => a + (x.seasonal || 0), 0),
            bonus: values.reduce((a, x) => a + (x.bonus || 0), 0),
            cameras: values.reduce((a, x) => a + (x.cameras || 0), 0),
        };
    }, [nightTotals]);

    const handleExport = () => {
        window.location.href = `${API}/export/${uploadId}?sheet=phasage`;
    };

    if (loading) {
        return <div className="p-8 text-sm text-gray-500" data-testid="phasage-loading">Chargement…</div>;
    }
    if (error) {
        return <div className="p-8 text-sm text-red-600">Erreur : {error}</div>;
    }
    if (!summary) return null;

    const { totals, rails_es_patterns } = summary;
    const storeMode = summary?.store_mode || "magasin_1";
    const isMagasin2 = storeMode === "magasin_2";

    // SA 2.1 saisonnier (vient de la catégorie surface du magasin)
    // → désormais sélectionnable explicitement via les "Zones saisonnières"
    //   dans le dropdown des allées (pas de répartition prorata automatique).
    const sa21Saisonnier = summary?.sa_21_saisonnier || 0;
    const totalESBrut = (totals.es_15 || 0) + (totals.es_21 || 0);
    // Bonus rails → ES 1.5
    //  - Magasin 1 : ajouté automatiquement par allée dans l'EEG
    //  - Magasin 2 : NON ajouté dans l'EEG du Phasage (mais bien gardé dans Commandes)
    const totalES15Bonus = isMagasin2 ? 0 : ((totals.es_15_bonus_noir || 0) + (totals.es_15_bonus_blanc || 0));
    // SA 1.5 (noir + blanc) — magasin 2 uniquement : compté dans EEG à installer
    const totalSA15 = isMagasin2 ? ((totals.sa_15 || 0)) : 0;
    // EEG par nuit = ES brut + bonus rails (magasin 1) + SA 1.5 (magasin 2) + saisonnier
    const eegPerNight = (esBrutNuit, seasonalNuit, bonusNuit, sa15Nuit) =>
        Math.round((esBrutNuit || 0) + (bonusNuit || 0) + (sa15Nuit || 0) + (seasonalNuit || 0));
    const totalEEG = totalESBrut + totalES15Bonus + totalSA15 + sa21Saisonnier;
    const avg = nbNuits > 0 ? totalEEG / nbNuits : 0;

    return (
        <div className="h-full flex flex-col bg-white" data-testid="phasage-tab">
            {/* Barre supérieure : nb nuits + moyenne + export */}
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-3 bg-gray-50 flex-shrink-0">
                <label className="text-xs font-medium text-gray-700 whitespace-nowrap">
                    Nombre de nuits :
                </label>
                <input
                    type="number"
                    min={1}
                    max={30}
                    value={nbNuits}
                    onChange={(e) => onChangeNbNuits(e.target.value)}
                    data-testid="phasage-nb-nuits"
                    className="h-7 w-16 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                />
                <div className="flex items-center gap-2 ml-2 px-3 py-1 bg-[#056839] text-white rounded text-xs font-medium" data-testid="phasage-moyenne">
                    Moyenne / nuit :
                    <span className="font-mono-data font-bold">{fmt(Math.round(avg))}</span>
                    <span className="opacity-80">EEG</span>
                </div>
                <button
                    onClick={handleExport}
                    data-testid="phasage-export"
                    className="ml-auto h-7 px-2.5 text-xs font-medium bg-[#056839] text-white rounded hover:bg-[#04502b] flex items-center gap-1.5"
                >
                    <Download className="w-3.5 h-3.5" />
                    Exporter cette vue
                </button>
                {saving && <span className="text-xs text-gray-500">Sauvegarde…</span>}
            </div>

            {/* Découpage par semaine (optionnel) */}
            <div className="border-b border-gray-200 px-3 py-2 flex items-center gap-2 bg-blue-50/40 flex-wrap flex-shrink-0" data-testid="phasage-weeks-bar">
                <label className="text-xs font-medium text-gray-700 whitespace-nowrap">
                    Découpage par semaine :
                </label>
                <label className="text-[11px] text-gray-600">Nb semaines :</label>
                <input
                    type="number"
                    min={0}
                    max={20}
                    value={weeks.length}
                    onChange={(e) => {
                        const raw = e.target.value;
                        if (raw === "") return; // ne pas réinitialiser pendant la saisie
                        const n = Math.max(0, Math.min(20, parseInt(raw, 10) || 0));
                        if (n === 0) {
                            setWeeks([]);
                            return;
                        }
                        const next = [...weeks];
                        while (next.length < n) next.push(Math.max(1, Math.round((nbNuits || 1) / n) || 1));
                        if (next.length > n) next.length = n;
                        setWeeks(next);
                        const newTotal = next.reduce((a, x) => a + (Number(x) || 0), 0);
                        setNbNuits(newTotal);
                        // Désaffecte les rows pointant au-delà du nouveau total
                        setRows((prev) => prev.map((rr) => (rr.nuit && rr.nuit > newTotal ? { ...rr, nuit: null } : rr)));
                    }}
                    data-testid="phasage-nb-semaines"
                    className="h-7 w-14 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                />
                {weeks.length === 0 && (
                    <span className="text-[11px] text-gray-500 italic ml-2">Pas de découpage (le tableau Excel reste en un seul bloc)</span>
                )}
                {weeks.map((w, i) => (
                    <div key={i} className="flex items-center gap-1" data-testid={`phasage-semaine-${i+1}`}>
                        <span className="text-[11px] text-gray-700">S{i + 1} :</span>
                        <input
                            type="number"
                            min={1}
                            max={30}
                            value={w}
                            onChange={(e) => {
                                const raw = e.target.value;
                                if (raw === "") return;
                                const v = Math.max(1, Math.min(30, parseInt(raw, 10) || 1));
                                const next = [...weeks];
                                next[i] = v;
                                setWeeks(next);
                                const newTotal = next.reduce((a, x) => a + (Number(x) || 0), 0);
                                setNbNuits(newTotal);
                                setRows((prev) => prev.map((rr) => (rr.nuit && rr.nuit > newTotal ? { ...rr, nuit: null } : rr)));
                            }}
                            className="h-7 w-14 px-2 text-sm border border-blue-300 bg-white rounded text-right focus:ring-1 focus:ring-blue-500 outline-none"
                        />
                        <span className="text-[10px] text-gray-400">nuits</span>
                    </div>
                ))}
                {weeks.length > 0 && (
                    <span className="text-[11px] text-gray-600 ml-2">
                        Total nuits : <b className="font-mono-data">{weeks.reduce((a, x) => a + (x || 0), 0)}</b>
                    </span>
                )}
            </div>

            {/* Totaux globaux */}
            <div className="border-b border-gray-200 px-3 py-2 flex flex-wrap items-start gap-2 text-xs flex-shrink-0">
                <div className="px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded">
                    <span className="text-gray-600">Total EEG :</span>{" "}
                    <span
                        className="font-mono-data font-bold text-emerald-900"
                        data-testid="total-es"
                        title={`ES (${fmt(totalESBrut)})${totalES15Bonus > 0 ? ` + Bonus rails→ES 1.5 (${fmt(totalES15Bonus)})` : ""}${totalSA15 > 0 ? ` + SA 1.5 (${fmt(totalSA15)})` : ""}${sa21Saisonnier > 0 ? ` + SA 2.1 saisonnier (${fmt(sa21Saisonnier)})` : ""}`}
                    >
                        {fmt(totalEEG)}
                    </span>
                    <span className="text-gray-400 text-[10px] ml-1">
                        {isMagasin2 ? "(ES + SA 1.5 + saison.)" : "(ES + bonus rails + saison.)"}
                    </span>
                </div>
                {totalES15Bonus > 0 && (
                    <div className="px-3 py-1.5 bg-sky-50 border border-sky-200 rounded" title="ES 1.5 ajoutés automatiquement à partir des rails">
                        <span className="text-gray-600">Bonus rails → ES 1.5 :</span>{" "}
                        <span className="font-mono-data font-bold text-sky-900">+{fmt(totalES15Bonus)}</span>
                        <span className="text-gray-400 text-[10px] ml-1">
                            (noir {fmt(totals.es_15_bonus_noir || 0)} / blanc {fmt(totals.es_15_bonus_blanc || 0)})
                        </span>
                    </div>
                )}
                {isMagasin2 && totalSA15 > 0 && (
                    <div className="px-3 py-1.5 bg-purple-50 border border-purple-200 rounded" title="SA 1.5 à poser (inclus dans Total EEG)">
                        <span className="text-gray-600">SA 1.5 (à poser) :</span>{" "}
                        <span className="font-mono-data font-bold text-purple-900">+{fmt(totalSA15)}</span>
                    </div>
                )}
                <div className="px-3 py-1.5 bg-amber-50 border border-amber-200 rounded">
                    <span className="text-gray-600">Total Rails ES :</span>{" "}
                    <span className="font-mono-data font-bold text-amber-900" data-testid="total-railses">{fmt(totals.rails_es)}</span>
                </div>
                <div className="px-3 py-1.5 bg-gray-50 border border-gray-200 rounded italic">
                    <span className="text-gray-500">
                        {isMagasin2 ? "Total SA 2.1 (info) :" : "Total SA (info) :"}
                    </span>{" "}
                    <span className="font-mono-data font-bold text-gray-700" data-testid="total-sa">
                        {fmt(isMagasin2 ? (totals.sa_21 || 0) : (totals.sa || 0))}
                    </span>
                </div>
                {(rails_es_patterns || []).map((p) => (
                    <div key={p} className="px-2 py-1 bg-gray-50 border border-gray-200 rounded text-gray-700">
                        <span className="text-gray-500">{p} :</span>{" "}
                        <span className="font-mono-data">{fmt(totals.rails_es_by_desig?.[p] || 0)}</span>
                    </div>
                ))}
            </div>

            {/* 2 tableaux côte à côte */}
            <div className="flex-1 overflow-auto custom-scroll p-3">
                <div className="grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-4">
                    {/* ----- Tableau gauche ----- */}
                    <div data-testid="phasage-left-table">
                        <div className="flex items-center justify-between mb-2 gap-3">
                            <h3 className="text-sm font-semibold text-gray-800 flex-shrink-0">
                                Plan d&apos;attribution par allée
                            </h3>
                            <div className="flex items-center gap-2 flex-1 max-w-md">
                                <label className="text-xs text-gray-500 whitespace-nowrap">Ajouter :</label>
                                <select
                                    value=""
                                    onChange={(e) => {
                                        const v = e.target.value;
                                        if (!v) return;
                                        addRow(v);
                                    }}
                                    data-testid="phasage-add-allee-picker"
                                    className="flex-1 h-7 px-2 text-xs border border-[#056839] bg-white text-[#056839] rounded font-medium hover:bg-emerald-50 focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                                >
                                    <option value="">+ Choisir une allée à ajouter…</option>
                                    {alleeOptions
                                        .filter((opt) => !usedAllees.has(opt.uid))
                                        .map((opt) => (
                                            <option
                                                key={opt.uid}
                                                value={opt.uid}
                                                style={opt.node.is_dup ? { color: "#C2410C", backgroundColor: "#FFF7ED", fontWeight: 600 } : {}}
                                            >
                                                {formatAlleeLabel(opt.node)}
                                            </option>
                                        ))}
                                </select>
                            </div>
                        </div>
                        <div className="border border-gray-200 rounded overflow-hidden">
                            <table className="w-full text-xs">
                                <thead className="bg-gray-50 text-gray-700">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-semibold">N° Allée</th>
                                        <th className="px-2 py-1.5 text-right font-semibold"
                                            title={isMagasin2
                                                ? "EEG = ES 1.5 + ES 2.1 + SA 1.5 (à poser)"
                                                : "EEG = ES 1.5 + ES 2.1 + bonus rails→ES 1.5"}>
                                            EEG
                                        </th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
                                        {isMagasin2 && (
                                            <th className="px-2 py-1.5 text-right font-semibold text-purple-700" title="SA 1.5 à poser (déjà inclus dans EEG)">SA 1.5</th>
                                        )}
                                        <th className="px-2 py-1.5 text-right font-semibold italic text-gray-500"
                                            title={isMagasin2
                                                ? "Info : SA 2.1 — non incluses dans EEG"
                                                : "Info : toutes étiquettes SA (SA 1.5, SA 2.1, SA 4.2, etc.) — non incluse dans les calculs"}>
                                            {isMagasin2 ? "SA 2.1" : "SA"}
                                        </th>
                                        <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                        <th className="px-2 py-1.5 w-8"></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.length === 0 && (
                                        <tr>
                                            <td colSpan={isMagasin2 ? 7 : 6} className="px-3 py-6 text-center text-gray-500 italic">
                                                Sélectionnez une allée dans la liste ci-dessus pour commencer
                                            </td>
                                        </tr>
                                    )}
                                    {rows.map((r) => {
                                        const node = alleeIndex[String(r.allee)];
                                        const color = nightColor(r.nuit, weeks);
                                        const rowStyle = color ? {
                                            backgroundColor: color.bg,
                                            borderLeft: `4px solid ${color.border}`,
                                        } : {};
                                        // Options de select : allées non utilisées + l'allée courante (pour pouvoir la changer)
                                        const availableAllees = alleeOptions.filter((opt) =>
                                            !usedAllees.has(opt.uid) || opt.uid === String(r.allee)
                                        );
                                        return (
                                            <tr
                                                key={r.id}
                                                className="border-t border-gray-100"
                                                style={rowStyle}
                                                data-testid={`phasage-row-${r.id}`}
                                            >
                                                <td className="px-1 py-1">
                                                    <select
                                                        value={r.allee || ""}
                                                        onChange={(e) => updateRow(r.id, { allee: e.target.value })}
                                                        data-testid={`row-allee-${r.id}`}
                                                        className="w-full h-6 px-1.5 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none font-mono-data bg-white"
                                                    >
                                                        <option value="">Sélectionner…</option>
                                                        {availableAllees.map((opt) => (
                                                            <option
                                                                key={opt.uid}
                                                                value={opt.uid}
                                                                style={opt.node.is_dup ? { color: "#C2410C", backgroundColor: "#FFF7ED", fontWeight: 600 } : {}}
                                                            >
                                                                {formatAlleeLabel(opt.node)}
                                                            </option>
                                                        ))}
                                                    </select>
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800"
                                                    title={node && !node.is_seasonal
                                                        ? (isMagasin2
                                                            ? `ES ${fmt((node.es_15 || 0) + (node.es_21 || 0))}${(node.sa_15 || 0) > 0 ? ` + SA 1.5 ${fmt(node.sa_15)}` : ""}`
                                                            : `ES ${fmt((node.es_15 || 0) + (node.es_21 || 0))}${((node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0)) > 0 ? ` + bonus rails ${fmt((node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0))}` : ""}`)
                                                        : undefined}>
                                                    {node ? fmt(node.is_seasonal
                                                        ? (node.seasonal_eeg || 0)
                                                        : (isMagasin2
                                                            ? ((node.es_15 || 0) + (node.es_21 || 0) + (node.sa_15 || 0))
                                                            : ((node.es_15 || 0) + (node.es_21 || 0) + (node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0)))
                                                    ) : ""}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt(node.rails_es) : ""}</td>
                                                {isMagasin2 && (
                                                    <td className="px-2 py-1 text-right font-mono-data text-purple-700 font-semibold">
                                                        {node ? fmt(node.sa_15 || 0) : ""}
                                                    </td>
                                                )}
                                                <td className="px-2 py-1 text-right font-mono-data italic text-gray-500"
                                                    title={isMagasin2 ? "SA 2.1 (info)" : "Toutes étiquettes SA (info)"}>
                                                    {node ? fmt(isMagasin2 ? (node.sa_21 || 0) : (node.sa || 0)) : ""}
                                                </td>
                                                <td className="px-1 py-1">
                                                    <select
                                                        value={r.nuit ?? ""}
                                                        onChange={(e) => updateRow(r.id, { nuit: e.target.value === "" ? null : Number(e.target.value) })}
                                                        data-testid={`row-nuit-${r.id}`}
                                                        className="w-full h-6 px-1 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none bg-white"
                                                    >
                                                        <option value="">—</option>
                                                        {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => (
                                                            <option key={n} value={n}>Nuit {n}</option>
                                                        ))}
                                                    </select>
                                                </td>
                                                <td className="px-1 py-1 text-center">
                                                    <button
                                                        onClick={() => deleteRow(r.id)}
                                                        data-testid={`row-delete-${r.id}`}
                                                        className="text-gray-400 hover:text-red-600 p-0.5"
                                                        title="Supprimer la ligne"
                                                    >
                                                        <Trash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    {/* ----- Tableau droite : par nuit ----- */}
                    <div data-testid="phasage-right-table">
                        <h3 className="text-sm font-semibold text-gray-800 mb-2">Récap par nuit</h3>
                        <div className="border border-gray-200 rounded overflow-hidden">
                            <table className="w-full text-xs">
                                <thead className="bg-gray-50 text-gray-700">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                        <th className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">Date</th>
                                        <th className="px-2 py-1.5 text-left font-semibold text-[10px] text-gray-600" title="Secteurs / Rayons des allées sélectionnées">Secteur/Rayon</th>
                                        <th className="px-2 py-1.5 text-left font-semibold">Allées</th>
                                        <th className="px-2 py-1.5 text-right font-semibold"
                                            title={isMagasin2
                                                ? "EEG = ES (1.5+2.1) + SA 1.5 + zones saisonnières affectées"
                                                : "EEG = ES (1.5+2.1) affectés + bonus rails→ES 1.5 + zones saisonnières affectées"}>
                                            EEG
                                        </th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
                                        {isMagasin2 && (
                                            <th className="px-2 py-1.5 text-right font-semibold text-purple-700" title="SA 1.5 à poser (inclus dans EEG)">SA 1.5</th>
                                        )}
                                        <th className="px-2 py-1.5 text-right font-semibold italic text-gray-500" title="Info (non inclus dans EEG)">
                                            {isMagasin2 ? "SA 2.1" : "SA"}
                                        </th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-purple-700" title="Caméras (depuis Phasage caméras)">Caméras</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                        const t = nightTotals[n] || { es_15: 0, es_21: 0, sa: 0, sa_15: 0, sa_21: 0, rails_es: 0, seasonal: 0, bonus: 0, allees: [] };
                                        const totalES = (t.es_15 || 0) + (t.es_21 || 0);
                                        const color = nightColor(n, weeks);
                                        // En magasin 2 : bonus rails NON inclus dans EEG nuit
                                        const bonusForNight = isMagasin2 ? 0 : (t.bonus || 0);
                                        const sa15ForNight = isMagasin2 ? (t.sa_15 || 0) : 0;
                                        return (
                                            <tr
                                                key={n}
                                                className="border-t border-gray-100"
                                                style={color ? { backgroundColor: color.bg, borderLeft: `4px solid ${color.border}` } : {}}
                                                data-testid={`recap-nuit-${n}`}
                                            >
                                                <td className="px-2 py-1 font-medium text-gray-900">Nuit {n}</td>
                                                <td className="px-2 py-1 text-[10.5px] text-gray-700 whitespace-nowrap font-mono-data" data-testid={`recap-nuit-date-${n}`}>
                                                    {dates[String(n)] ? new Date(dates[String(n)] + "T00:00:00").toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-[10px] text-gray-600 max-w-[120px] truncate" title={Array.from(t.secteur_rayon).join(" / ")} data-testid={`recap-nuit-sr-${n}`}>
                                                    {t.secteur_rayon.size ? Array.from(t.secteur_rayon).join(" / ") : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 font-mono-data text-gray-700 text-[11px] max-w-[180px] truncate"
                                                    title={t.allees.map((u) => alleeIndex[u]?.allee || u).join(", ")}>
                                                    {t.allees.length ? t.allees.map((u) => alleeIndex[u]?.allee || u).join(", ") : <span className="text-gray-400">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data font-bold text-gray-900"
                                                    title={`ES brut (${fmt(Math.round(totalES))})${bonusForNight > 0 ? ` + Bonus rails (${fmt(bonusForNight)})` : ""}${sa15ForNight > 0 ? ` + SA 1.5 (${fmt(sa15ForNight)})` : ""}${t.seasonal > 0 ? ` + Zone saisonnier (${fmt(t.seasonal)})` : ""}`}>
                                                    {fmt(eegPerNight(totalES, t.seasonal, bonusForNight, sa15ForNight))}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-600">{fmt(t.rails_es)}</td>
                                                {isMagasin2 && (
                                                    <td className="px-2 py-1 text-right font-mono-data text-purple-700 font-semibold">{fmt(t.sa_15 || 0)}</td>
                                                )}
                                                <td className="px-2 py-1 text-right font-mono-data italic text-gray-500">
                                                    {fmt(isMagasin2 ? (t.sa_21 || 0) : (t.sa || 0))}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-purple-700 font-semibold">
                                                    {t.cameras > 0 ? fmt(t.cameras) : <span className="text-gray-300">—</span>}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                    <tr className="border-t-2 border-yellow-300 bg-yellow-50 font-semibold">
                                        <td className="px-2 py-1 text-gray-900">TOTAL</td>
                                        <td className="px-2 py-1 text-gray-300">—</td>
                                        <td className="px-2 py-1 text-gray-300">—</td>
                                        <td className="px-2 py-1 text-gray-500 text-[11px]">
                                            {grandTotals.nbAllees} allées
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(Math.round(grandTotals.es + (isMagasin2 ? grandTotals.sa_15 : grandTotals.bonus) + grandTotals.seasonal))}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(grandTotals.rails)}
                                        </td>
                                        {isMagasin2 && (
                                            <td className="px-2 py-1 text-right font-mono-data text-purple-700">
                                                {fmt(grandTotals.sa_15)}
                                            </td>
                                        )}
                                        <td className="px-2 py-1 text-right font-mono-data italic text-gray-600">
                                            {fmt(isMagasin2 ? grandTotals.sa_21 : grandTotals.sa)}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data text-purple-700">
                                            {fmt(grandTotals.cameras)}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
