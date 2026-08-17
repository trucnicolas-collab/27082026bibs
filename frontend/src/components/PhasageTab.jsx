import React, { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { Plus, Trash2, Download, PackagePlus } from "lucide-react";
import { toast } from "sonner";
import SaInstallPanel, { computeSaToInstall, computeNodeSaInstall, nodeSaTotal } from "./SaInstallPanel";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function fmt(n) {
    if (n == null) return "";
    if (typeof n === "number") return n.toLocaleString("fr-FR");
    return n;
}

function newRowId() {
    return `row_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// === Suggestion automatique nb_nuits + semaines (16/06/2026, MAJ 05/07/2026) ===
// Règle métier : MAX 4 900 EEG par nuit. Nuits autorisées = 10/12/14/16/18/20.
// On prend la plus petite valeur qui respecte la limite.
const ALLOWED_ES_NIGHTS = [10, 12, 14, 16, 18, 20];
const ES_MAX_PER_NIGHT = 4900;
const MAX_ES_NIGHTS = 20;
function suggestEsConfig(totalEEG) {
    if (!totalEEG || totalEEG <= 0) return { nb_nuits: 12, weeks: [4, 4, 4] };
    // Cherche le plus petit nb dans ALLOWED tel que totalEEG / nb <= MAX
    let best = null;
    for (const v of ALLOWED_ES_NIGHTS) {
        if (totalEEG / v <= ES_MAX_PER_NIGHT) {
            best = v;
            break;
        }
    }
    // Aucune valeur ne respecte la limite (très gros magasin) → on garde 20 (max)
    if (best === null) best = MAX_ES_NIGHTS;
    // Répartition en semaines de 4 nuits + reste (ex : 20 → 5 semaines de 4).
    const full = Math.floor(best / 4);
    const rest = best % 4;
    const weeks = Array(full).fill(4);
    if (rest > 0) weeks.push(rest);
    return { nb_nuits: best, weeks };
}
function isStandardEsNightCount(n) {
    return ALLOWED_ES_NIGHTS.includes(Number(n));
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
    { bg: "#DBEAFE", border: "#6EE7B7" }, // 3 vert
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
    // (iter48k) Couleur = position dans la semaine (règle métier utilisateur).
    // 1ère nuit = bleu, 2e = jaune, 3e = rose, 4e = vert. Semaine suivante
    // recommence à bleu (même si la semaine précédente ne faisait que 2 nuits).
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
    // (iter6) État précis de la sauvegarde pour éviter les pertes silencieuses :
    // "idle" | "saving" | "saved" | "error". L'utilisateur voit toujours le statut.
    const [saveStatus, setSaveStatus] = useState("idle");
    const [lastSavedAt, setLastSavedAt] = useState(null);
    const [saveError, setSaveError] = useState("");
    const [dates, setDates] = useState({}); // {"1": "2026-02-15", ...} (lecture seule ici)
    // Méta-infos magasin / VT
    const [vtStartDate, setVtStartDate] = useState("");
    const [storeName, setStoreName] = useState("");
    const [storeCode, setStoreCode] = useState("");
    const [storeInfoLoaded, setStoreInfoLoaded] = useState(false);
    const [saInstall, setSaInstall] = useState(null);
    // Écran d'intro « EEG SA à poser » avant la grille de phasage (gate).
    const [introDone, setIntroDone] = useState(false);

    // Charger summary
    useEffect(() => {
        if (!uploadId) return;
        let mounted = true;
        setLoading(true);
        axios.get(`${API}/dataset/${uploadId}/phasage-summary`, {
                headers: { "Cache-Control": "no-cache" },
                params: { _t: Date.now() },
            })
            .then((res) => {
                if (!mounted) return;
                setSummary(res.data);
                setSaInstall(res.data.sa_install || null);
                // Si l'utilisateur a déjà répondu Oui/Non (answered), on va
                // directement à la grille ; sinon on affiche l'écran d'intro.
                setIntroDone(!!(res.data.sa_install && res.data.sa_install.answered));
                const ph = res.data.phasage || {};
                const p = ph.es || { nb_nuits: 0, rows: [], weeks: null };
                // Calcule le TOTAL EEG complet (même formule que la moyenne affichée)
                // pour suggérer ou re-suggérer le bon nombre de nuits.
                const t = res.data.totals || {};
                const storeMode = res.data.store_mode || "magasin_1";
                const isMag2 = storeMode === "magasin_2";
                const totalESBrut = (t.es_15 || 0) + (t.es_21 || 0);
                const totalES15Bonus = isMag2 ? 0
                    : ((t.es_15_bonus_noir || 0) + (t.es_15_bonus_blanc || 0));
                const totalFleches = t.fleches || 0;
                const totalSA15 = isMag2 ? (t.sa_15 || 0) : 0;
                const sa21Saisonnier = res.data.sa_21_saisonnier || 0;
                const totalEEG = totalESBrut + totalES15Bonus + totalFleches
                    + totalSA15 + sa21Saisonnier;
                const sugg = suggestEsConfig(totalEEG);

                const hasPersistedConfig = (p.nb_nuits && p.nb_nuits >= 4)
                    || (Array.isArray(p.rows) && p.rows.length > 0);
                if (hasPersistedConfig) {
                    // Si la config persistée ne suffit plus (avg > 4900),
                    // on la remplace automatiquement par la suggestion.
                    const persistedAvg = totalEEG / (p.nb_nuits || 1);
                    if (persistedAvg > ES_MAX_PER_NIGHT && sugg.nb_nuits > (p.nb_nuits || 0)) {
                        setNbNuits(sugg.nb_nuits);
                        setWeeks(sugg.weeks);
                    } else {
                        setNbNuits(p.nb_nuits || 3);
                        setWeeks(Array.isArray(p.weeks) ? p.weeks : []);
                    }
                } else {
                    // Première ouverture : on suggère nb_nuits + semaines basé sur EEG total
                    setNbNuits(sugg.nb_nuits);
                    setWeeks(sugg.weeks);
                }
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
            setSaveStatus("saving");
            const ph = summary.phasage || {};
            axios.patch(`${API}/dataset/${uploadId}/phasage`, {
                es: {
                    nb_nuits: nbNuits,
                    rows: rows.map((r) => ({ id: r.id, allee: r.allee, nuit: r.nuit })),
                    weeks: weeks.length > 0 ? weeks : null,
                },
                cam: ph.cam || { nb_nuits: 3, rows: [], start_at_nuit: 5 },
                suivi: ph.suivi || { rows: [] },
            }).then(() => {
                setSaveStatus("saved");
                setLastSavedAt(new Date());
                setSaveError("");
            }).catch((e) => {
                console.error("Save phasage failed:", e);
                setSaveStatus("error");
                setSaveError(e?.response?.data?.detail || e?.message || "Erreur inconnue");
            }).finally(() => setSaving(false));
        }, 600);
        return () => clearTimeout(t);
    }, [nbNuits, rows, weeks, uploadId, summary]);

    const alleeIndex = useMemo(() => {
        if (!summary) return {};
        const map = {};
        summary.allees.forEach((a) => { map[String(a.uid || a.allee)] = a; });
        // Ajoute les zones saisonnières (clé = ID, ex: "ZS1") — filtrage selon
        // saInstall.seasonal : ZS totalement décochée = skip. Partielle = 0 sur le type décoché.
        const sCfg = saInstall?.seasonal || {};
        const allOn = sCfg.all !== false;
        (summary.seasonal_zones || []).forEach((z) => {
            const zCfg = (sCfg.zones || {})[z.id] || {};
            const take15 = zCfg.sa_15 != null ? Boolean(zCfg.sa_15) : allOn;
            const take21 = zCfg.sa_21 != null ? Boolean(zCfg.sa_21) : allOn;
            if (!take15 && !take21) return; // (iter48l) Zone entièrement décochée
            const sa15 = take15 ? (Number(z.sa_15) || 0) : 0;
            const sa21Raw = Number(z.sa_21) || 0;
            const eegZraw = Number(z.eeg) || (sa15 + sa21Raw);
            // Rétrocompat : ZS sans split explicite → tout dans SA 2.1
            const sa21Effective = take21 ? (sa21Raw || (sa15 === 0 && take15 ? 0 : (Number(z.sa_15) === 0 ? eegZraw : sa21Raw))) : 0;
            map[z.id] = {
                uid: z.id,
                allee: z.id,
                label: z.label,
                es_15: 0,
                es_21: 0,
                sa: sa15 + sa21Effective,
                sa_15: sa15,
                sa_21: sa21Effective,
                sa_21_std: sa21Effective,
                rails_es: 0,
                cameras: 0,
                is_seasonal: true,
                seasonal_eeg: sa15 + sa21Effective,
            };
        });
        return map;
    }, [summary, saInstall]);

    // Liste triée des allées dispo + zones saisonnières en fin de liste
    // (iter48l) Les ZS entièrement décochées sont filtrées
    const alleeOptions = useMemo(() => {
        if (!summary) return [];
        const list = summary.allees.map((a) => String(a.uid || a.allee));
        const sCfg = saInstall?.seasonal || {};
        const allOn = sCfg.all !== false;
        (summary.seasonal_zones || []).forEach((z) => {
            const zCfg = (sCfg.zones || {})[z.id] || {};
            const take15 = zCfg.sa_15 != null ? Boolean(zCfg.sa_15) : allOn;
            const take21 = zCfg.sa_21 != null ? Boolean(zCfg.sa_21) : allOn;
            if (take15 || take21) list.push(z.id);
        });
        return list;
    }, [summary, saInstall]);

    const seasonalZones = summary?.seasonal_zones || [];

    const updateRow = useCallback((id, patch) => {
        setRows((prev) => {
            const next = prev.map((r) => r.id === id ? { ...r, ...patch } : r);
            // Tri auto par nuit (croissant, lignes sans nuit en bas), uniquement
            // pour les sessions où le flag `auto_sort_by_nuit` est activé
            // (nouvelles sessions à partir du 22/06/2026). Stable : on garde
            // l'ordre relatif à l'intérieur d'une même nuit.
            const flag = summary?.phasage?.es?.auto_sort_by_nuit;
            if (flag && Object.prototype.hasOwnProperty.call(patch, "nuit")) {
                // Sort stable basé sur l'index d'origine en cas d'égalité
                const withIdx = next.map((r, i) => ({ r, i }));
                withIdx.sort((a, b) => {
                    const na = a.r.nuit ?? Number.POSITIVE_INFINITY;
                    const nb = b.r.nuit ?? Number.POSITIVE_INFINITY;
                    if (na !== nb) return na - nb;
                    return a.i - b.i;
                });
                return withIdx.map(({ r }) => r);
            }
            return next;
        });
    }, [summary]);

    const addRow = useCallback(() => {
        setRows((prev) => [...prev, { id: newRowId(), allee: "", nuit: null }]);
    }, []);

    const deleteRow = useCallback((id) => {
        setRows((prev) => prev.filter((r) => r.id !== id));
    }, []);

    // Recalcule le nb de nuits suggéré à partir du total EEG COMPLET (incluant
    // les SA à installer choisies dans l'intro). Appelé au « Continuer ».
    const recomputeNightsForSaInstall = useCallback((saCfg) => {
        if (!summary) return;
        const t = summary.totals || {};
        const isMag2 = (summary.store_mode || "magasin_1") === "magasin_2";
        const totalESBrut = (t.es_15 || 0) + (t.es_21 || 0);
        const totalES15Bonus = isMag2 ? 0 : ((t.es_15_bonus_noir || 0) + (t.es_15_bonus_blanc || 0));
        const totalFleches = t.fleches || 0;
        const totalSA15 = isMag2 ? (t.sa_15 || 0) : 0;
        const sa21Sais = summary.sa_21_saisonnier || 0;
        const inst = computeSaToInstall(summary.sa_breakdown, saCfg);
        const instTotal = (inst.sa_15 || 0) + (inst.sa_21 || 0) + (inst.freezer || 0) + (inst.sa_42 || 0);
        const total = totalESBrut + totalES15Bonus + totalFleches + totalSA15 + sa21Sais + instTotal;
        const sugg = suggestEsConfig(total);
        setNbNuits(sugg.nb_nuits);
        setWeeks(sugg.weeks);
        setRows((prev) => prev.map((r) => (r.nuit && r.nuit > sugg.nb_nuits ? { ...r, nuit: null } : r)));
    }, [summary]);

    // Validation : ajuster nuits si nb_nuits diminue
    const onChangeNbNuits = useCallback((n) => {
        const v = Math.max(1, Math.min(MAX_ES_NIGHTS, Number(n) || 1));
        setNbNuits(v);
        setRows((prev) => prev.map((r) => r.nuit && r.nuit > v ? { ...r, nuit: null } : r));
        // Alerte non bloquante si valeur non standard (11/13/15/17/19) ou hors fourchette
        if (v >= 10 && v <= MAX_ES_NIGHTS && !isStandardEsNightCount(v)) {
            toast.warning(`⚠️ ${v} nuits non standard. Les valeurs recommandées sont 10, 12, 14, 16, 18 ou 20 nuits (~4500-5000 EEG/nuit).`, {
                id: "es-night-warning",
                duration: 5000,
            });
        } else if (v < 10 || v > MAX_ES_NIGHTS) {
            toast.warning(`⚠️ ${v} nuits hors fourchette recommandée (10 à ${MAX_ES_NIGHTS} nuits). Vérifiez la charge par nuit.`, {
                id: "es-night-warning",
                duration: 5000,
            });
        }
    }, []);

    // Agrégation par nuit
    const nightTotals = useMemo(() => {
        const tot = {};
        for (let n = 1; n <= nbNuits; n++) tot[n] = { es_15: 0, es_21: 0, sa: 0, sa_15: 0, sa_21: 0, rails_es: 0, seasonal: 0, bonus: 0, fleches: 0, cameras: 0, sa_inst_15: 0, sa_inst_21: 0, sa_inst_freezer: 0, sa_inst_42: 0, sa_mag: 0, allees: [], secteur_rayon: new Set() };
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
            // SA à installer (par NOUS) selon la config du panneau — répartie par allée/nuit
            const inst = computeNodeSaInstall(node, saInstall);
            tot[r.nuit].sa_inst_15 += inst.sa_15 || 0;
            tot[r.nuit].sa_inst_21 += inst.sa_21 || 0;
            tot[r.nuit].sa_inst_freezer += inst.freezer || 0;
            tot[r.nuit].sa_inst_42 += inst.sa_42 || 0;
            // Reste SA installé par le magasin (info) = total SA allée − installées par nous
            tot[r.nuit].sa_mag += Math.max(0, nodeSaTotal(node) - (inst.sa_15 + inst.sa_21 + inst.freezer + inst.sa_42));
            // Bonus rails → ES 1.5 (par couleur, par allée)
            tot[r.nuit].bonus = (tot[r.nuit].bonus || 0) + (node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0);
            // Flèches (= +1 ES 1.5 noir chacune) ajoutées par allée
            tot[r.nuit].fleches = (tot[r.nuit].fleches || 0) + (node.fleches || 0);
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
    }, [rows, nbNuits, alleeIndex, summary, saInstall]);

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
            sa_inst_15: values.reduce((a, x) => a + (x.sa_inst_15 || 0), 0),
            sa_inst_21: values.reduce((a, x) => a + (x.sa_inst_21 || 0), 0),
            sa_inst_freezer: values.reduce((a, x) => a + (x.sa_inst_freezer || 0), 0),
            sa_inst_42: values.reduce((a, x) => a + (x.sa_inst_42 || 0), 0),
            sa_mag: values.reduce((a, x) => a + (x.sa_mag || 0), 0),
            seasonal: values.reduce((a, x) => a + (x.seasonal || 0), 0),
            bonus: values.reduce((a, x) => a + (x.bonus || 0), 0),
            fleches: values.reduce((a, x) => a + (x.fleches || 0), 0),
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
    // Masque la colonne info "SA magasin" quand on installe TOUTES les SA
    // (elle vaudrait toujours 0 → inutile).
    const hideSaMagasin = !!(saInstall?.enabled && saInstall?.toutes);

    // (iter48l) Helper : une ZS est-elle EFFECTIVEMENT à installer, selon
    // la config `saInstall.seasonal` ? Retourne { sa_15, sa_21 } (0 si décoché).
    const effectiveZone = (z) => {
        const sCfg = saInstall?.seasonal || {};
        const allOn = sCfg.all !== false;
        const zCfg = (sCfg.zones || {})[z.id] || {};
        const take15 = zCfg.sa_15 != null ? Boolean(zCfg.sa_15) : allOn;
        const take21 = zCfg.sa_21 != null ? Boolean(zCfg.sa_21) : allOn;
        return {
            sa_15: take15 ? (Number(z.sa_15) || 0) : 0,
            sa_21: take21 ? (Number(z.sa_21) || 0) : 0,
        };
    };
    // (iter48l) Total des SA de ZS DÉSÉLECTIONNÉES → à soustraire du total EEG.
    // Calcul inline (pas useMemo car après le early return de summary).
    let seasonalDeselectedTotal = 0;
    for (const z of (summary?.seasonal_zones || [])) {
        const eff = effectiveZone(z);
        const full = (Number(z.sa_15) || 0) + (Number(z.sa_21) || 0);
        seasonalDeselectedTotal += full - eff.sa_15 - eff.sa_21;
    }

    // SA 2.1 saisonnier (vient de la catégorie surface du magasin)
    // → désormais sélectionnable explicitement via les "Zones saisonnières"
    //   dans le dropdown des allées (pas de répartition prorata automatique).
    const sa21Saisonnier = Math.max(0, (summary?.sa_21_saisonnier || 0) - seasonalDeselectedTotal);
    const totalESBrut = (totals.es_15 || 0) + (totals.es_21 || 0);
    // Bonus rails → ES 1.5
    //  - Magasin 1 : ajouté automatiquement par allée dans l'EEG
    //  - Magasin 2 : NON ajouté dans l'EEG du Phasage (mais bien gardé dans Commandes)
    const totalES15Bonus = isMagasin2 ? 0 : ((totals.es_15_bonus_noir || 0) + (totals.es_15_bonus_blanc || 0));
    // Flèches → +1 ES 1.5 (noir) automatiquement (s'applique aux 2 magasins)
    const totalFleches = totals.fleches || 0;
    // SA 1.5 (noir + blanc) — magasin 2 uniquement : compté dans EEG à installer
    const totalSA15 = isMagasin2 ? ((totals.sa_15 || 0)) : 0;
    // EEG par nuit = ES brut + bonus rails (mag1) + flèches + SA 1.5 (mag2).
    // (v27) Les Zones Saisonnières NE SONT PLUS ajoutées ici : elles sont
    // désormais posées par la VT et comptées en SA 1.5 / SA 2.1 dédiées
    // (via t.sa_inst_15 / t.sa_inst_21 ajoutés séparément dans saInstNuit).
    // `seasonalNuit` reste dans la signature pour rétrocompat des call sites
    // mais est ignoré volontairement.
    // eslint-disable-next-line no-unused-vars
    const eegPerNight = (esBrutNuit, seasonalNuit, bonusNuit, flechesNuit, sa15Nuit, saInstNuit) =>
        Math.round((esBrutNuit || 0) + (bonusNuit || 0) + (flechesNuit || 0) + (sa15Nuit || 0) + (saInstNuit || 0));
    // SA à installer (hors saisonnier) selon la config utilisateur — ajouté aux EEG à poser
    const saToInstall = computeSaToInstall(summary?.sa_breakdown, saInstall);
    const saInstallTotal = (saToInstall.sa_15 || 0) + (saToInstall.sa_21 || 0) + (saToInstall.freezer || 0) + (saToInstall.sa_42 || 0);
    // (v27) sa21Saisonnier (= total SA des Zones Saisonnières, 6000 sur +10000m²)
    // reste dans totalEEG car les ZS sont désormais posées par la VT et
    // computeSaToInstall n'itère pas sur les zones (elles sont séparées du
    // breakdown standard).
    const totalEEG = totalESBrut + totalES15Bonus + totalFleches + totalSA15 + sa21Saisonnier + saInstallTotal;
    const avg = nbNuits > 0 ? totalEEG / nbNuits : 0;

    // Écran d'intro « Étiquettes SA à poser » — bloque la grille tant que
    // l'utilisateur n'a pas répondu Oui/Non (déplacé avant le phasage).
    if (!introDone) {
        return (
            <div className="h-full flex flex-col bg-white" data-testid="phasage-tab">
                <SaInstallPanel
                    mode="intro"
                    uploadId={uploadId}
                    breakdown={summary?.sa_breakdown}
                    seasonalZones={seasonalZones}
                    initialConfig={saInstall}
                    onSaved={(cfg) => setSaInstall(cfg)}
                    onContinue={(cfg) => { setSaInstall(cfg); setIntroDone(true); recomputeNightsForSaInstall(cfg); }}
                />
            </div>
        );
    }

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
                    max={MAX_ES_NIGHTS}
                    value={nbNuits}
                    onChange={(e) => onChangeNbNuits(e.target.value)}
                    data-testid="phasage-nb-nuits"
                    className="h-7 w-16 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-[#005BAB] focus:border-[#005BAB] outline-none"
                />
                <div className="flex items-center gap-2 ml-2 px-3 py-1 bg-[#005BAB] text-white rounded text-xs font-medium" data-testid="phasage-moyenne">
                    Moyenne / nuit :
                    <span className="font-mono-data font-bold">{fmt(Math.round(avg))}</span>
                    <span className="opacity-80">EEG</span>
                </div>
                <button
                    onClick={() => setIntroDone(false)}
                    data-testid="phasage-edit-sa"
                    className="ml-auto h-7 px-2.5 text-xs font-medium bg-white border border-gray-300 text-gray-700 rounded hover:bg-gray-100 flex items-center gap-1.5"
                    title="Modifier les EEG SA à poser"
                >
                    <PackagePlus className="w-3.5 h-3.5" />
                    EEG SA à poser
                </button>
                {saving && <span className="text-xs text-gray-500" data-testid="phasage-save-saving">Sauvegarde…</span>}
                {!saving && saveStatus === "saved" && lastSavedAt && (
                    <span className="text-xs text-green-700 flex items-center gap-1" data-testid="phasage-save-ok"
                        title={`Dernière sauvegarde à ${lastSavedAt.toLocaleTimeString("fr-FR")}`}>
                        ✓ Sauvegardé à {lastSavedAt.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                    </span>
                )}
                {!saving && saveStatus === "error" && (
                    <span className="text-xs text-red-700 font-bold flex items-center gap-1 bg-red-50 px-2 py-0.5 rounded"
                        data-testid="phasage-save-error"
                        title={`ERREUR SAUVEGARDE : ${saveError}. Vos modifications ne sont PAS enregistrées. Reconnectez-vous et réessayez.`}>
                        ⚠️ NON SAUVEGARDÉ — {saveError.length > 40 ? saveError.slice(0, 40) + "…" : saveError}
                    </span>
                )}
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
                    className="h-7 w-14 px-2 text-sm border border-gray-300 rounded text-right focus:ring-1 focus:ring-[#005BAB] focus:border-[#005BAB] outline-none"
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

            {/* Config : installer des EEG SA (hors saisonnier) — déplacée dans
                l'écran d'intro. Bouton pour revenir modifier la réponse. */}

            {/* Totaux globaux */}
            <div className="border-b border-gray-200 px-3 py-2 flex flex-wrap items-start gap-2 text-xs flex-shrink-0">
                <div className="px-3 py-1.5 bg-blue-50 border border-blue-200 rounded">
                    <span className="text-gray-600">Total EEG :</span>{" "}
                    <span
                        className="font-mono-data font-bold text-blue-900"
                        data-testid="total-es"
                        title={`ES (${fmt(totalESBrut)})${totalES15Bonus > 0 ? ` + Bonus rails→ES 1.5 (${fmt(totalES15Bonus)})` : ""}${totalFleches > 0 ? ` + Flèches → ES 1.5 noir (${fmt(totalFleches)})` : ""}${totalSA15 > 0 ? ` + SA 1.5 (${fmt(totalSA15)})` : ""}${sa21Saisonnier > 0 ? ` + SA 2.1 saisonnier (${fmt(sa21Saisonnier)})` : ""}`}
                    >
                        {fmt(totalEEG)}
                    </span>
                    <span className="text-gray-400 text-[10px] ml-1">
                        {isMagasin2 ? "(ES + flèches + SA 1.5 + saison.)" : "(ES + bonus rails + flèches + saison.)"}
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
                {totalFleches > 0 && (
                    <div className="px-3 py-1.5 bg-amber-50 border border-amber-200 rounded" title="1 flèche dans l'export brut = +1 ES 1.5 (noir) ajouté automatiquement">
                        <span className="text-gray-600">dont flèches :</span>{" "}
                        <span className="font-mono-data font-bold text-amber-900" data-testid="total-fleches">+{fmt(totalFleches)}</span>
                        <span className="text-gray-400 text-[10px] ml-1">
                            ES 1.5 (noir)
                        </span>
                    </div>
                )}
                {isMagasin2 && totalSA15 > 0 && (
                    <div className="px-3 py-1.5 bg-purple-50 border border-purple-200 rounded" title="SA 1.5 à poser (inclus dans Total EEG)">
                        <span className="text-gray-600">SA 1.5 (à poser) :</span>{" "}
                        <span className="font-mono-data font-bold text-purple-900">+{fmt(totalSA15)}</span>
                    </div>
                )}
                {saInstallTotal > 0 && (
                    <div className="px-3 py-1.5 bg-blue-50 border border-blue-300 rounded" data-testid="sa-install-chip"
                        title={`SA à installer — SA 1.5 ${fmt(saToInstall.sa_15)} / SA 2.1 ${fmt(saToInstall.sa_21)} / Freezer ${fmt(saToInstall.freezer)} / 4.2/4.2 WP ${fmt(saToInstall.sa_42)}`}>
                        <span className="text-gray-600">EEG SA à installer :</span>{" "}
                        <span className="font-mono-data font-bold" style={{ color: "#005BAB" }}>+{fmt(saInstallTotal)}</span>
                        <span className="text-gray-400 text-[10px] ml-1">
                            (1.5 {fmt(saToInstall.sa_15)} / 2.1 {fmt(saToInstall.sa_21)} / frz {fmt(saToInstall.freezer)} / 4.2 {fmt(saToInstall.sa_42)})
                        </span>
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
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-semibold text-gray-800">Plan d&apos;attribution par allée</h3>
                            <button
                                onClick={addRow}
                                data-testid="phasage-add-row"
                                className="h-7 px-2 text-xs font-medium bg-white border border-[#005BAB] text-[#005BAB] rounded hover:bg-blue-50 flex items-center gap-1"
                            >
                                <Plus className="w-3.5 h-3.5" />
                                Ajouter une allée
                            </button>
                        </div>
                        <div className="border border-gray-200 rounded overflow-hidden">
                            <table className="w-full text-xs">
                                <thead className="bg-gray-50 text-gray-700">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-semibold">N° Allée</th>
                                        <th className="px-2 py-1.5 text-right font-semibold"
                                            title={isMagasin2
                                                ? "EEG ES = ES 1.5 + ES 2.1 + SA 1.5 + flèches (hors SA à installer VT, qui sont dans les colonnes dédiées)"
                                                : "EEG ES = ES 1.5 + ES 2.1 + bonus rails→ES 1.5 + flèches (hors SA à installer VT, qui sont dans les colonnes dédiées)"}>
                                            EEG ES
                                        </th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="SA 1.5 à installer (VT) — selon la config du panneau">SA 1.5</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="SA 2.1 à installer (VT) — selon la config du panneau">SA 2.1</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="SA 2.1 Freezer à installer (VT) — selon la config du panneau">SA 2.1 frz</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="4.2 / 4.2 WP à installer (VT) — selon la config du panneau">4.2/4.2 WP</th>
                                        {!hideSaMagasin && (
                                            <th className="px-2 py-1.5 text-right font-semibold italic text-gray-500" title="SA restantes installées par le magasin (info, non incluses dans EEG)">SA magasin</th>
                                        )}
                                        <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                        <th className="px-2 py-1.5 w-8"></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.length === 0 && (
                                        <tr>
                                            <td colSpan={hideSaMagasin ? 9 : 10} className="px-3 py-6 text-center text-gray-500 italic">
                                                Cliquez sur « Ajouter une allée » pour commencer
                                            </td>
                                        </tr>
                                    )}
                                    {rows.map((r) => {
                                        const node = alleeIndex[String(r.allee)];
                                        const inst = computeNodeSaInstall(node, saInstall);
                                        const instTotal = (inst.sa_15 || 0) + (inst.sa_21 || 0) + (inst.freezer || 0) + (inst.sa_42 || 0);
                                        const saMag = node ? Math.max(0, nodeSaTotal(node) - instTotal) : 0;
                                        const color = nightColor(r.nuit, weeks);
                                        const rowStyle = color ? {
                                            backgroundColor: color.bg,
                                            borderLeft: `4px solid ${color.border}`,
                                        } : {};
                                        // Options de select : allées non utilisées + l'allée courante (pour pouvoir la changer)
                                        const availableAllees = alleeOptions.filter((a) =>
                                            !usedAllees.has(a) || a === String(r.allee)
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
                                                        className="w-full h-6 px-1.5 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-[#005BAB] focus:border-[#005BAB] outline-none font-mono-data bg-white"
                                                    >
                                                        <option value="">Sélectionner…</option>
                                                        {availableAllees.map((a) => {
                                                            const node = alleeIndex[a];
                                                            const isSeasonal = node?.is_seasonal;
                                                            const isDup = node?.is_dup;
                                                            const dupTag = isDup ? `🟠 [DOUBLON ${node.dup_index}/${node.dup_total}] ` : "";
                                                            return (
                                                                <option key={a} value={a} style={isDup ? { color: "#C2410C", backgroundColor: "#FFF7ED", fontWeight: 600 } : {}}>
                                                                    {isSeasonal
                                                                        ? `🌶 ${node.label} (${fmt(node.sa_15 || 0)} SA 1.5 + ${fmt(node.sa_21 || node.sa_21_std || 0)} SA 2.1)`
                                                                        : `${dupTag}${node?.allee}${node?.secteur ? ` (${node.secteur}${node.rayon ? " · " + node.rayon : ""})` : ""}`
                                                                    }
                                                                </option>
                                                            );
                                                        })}
                                                    </select>
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800"
                                                    title={node && !node.is_seasonal
                                                        ? (isMagasin2
                                                            ? `ES ${fmt((node.es_15 || 0) + (node.es_21 || 0))}${(node.sa_15 || 0) > 0 ? ` + SA 1.5 ${fmt(node.sa_15)}` : ""}${(node.fleches || 0) > 0 ? ` + ${fmt(node.fleches)} flèche(s)` : ""}`
                                                            : `ES ${fmt((node.es_15 || 0) + (node.es_21 || 0))}${((node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0)) > 0 ? ` + bonus rails ${fmt((node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0))}` : ""}${(node.fleches || 0) > 0 ? ` + ${fmt(node.fleches)} flèche(s)` : ""}`)
                                                        : undefined}>
                                                    {node ? fmt(node.is_seasonal
                                                        ? 0
                                                        : (isMagasin2
                                                            ? ((node.es_15 || 0) + (node.es_21 || 0) + (node.sa_15 || 0) + (node.fleches || 0))
                                                            : ((node.es_15 || 0) + (node.es_21 || 0) + (node.es_15_bonus_noir || 0) + (node.es_15_bonus_blanc || 0) + (node.fleches || 0)))
                                                    ) : ""}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-800">{node ? fmt(node.rails_es) : ""}</td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {node && inst.sa_15 > 0 ? fmt(inst.sa_15) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {node && inst.sa_21 > 0 ? fmt(inst.sa_21) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {node && inst.freezer > 0 ? fmt(inst.freezer) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {node && inst.sa_42 > 0 ? fmt(inst.sa_42) : <span className="text-gray-300">—</span>}
                                                </td>
                                                {!hideSaMagasin && (
                                                    <td className="px-2 py-1 text-right font-mono-data italic text-gray-500"
                                                        title="SA restantes installées par le magasin (info)">
                                                        {node && saMag > 0 ? fmt(saMag) : <span className="text-gray-300">—</span>}
                                                    </td>
                                                )}
                                                <td className="px-1 py-1">
                                                    <select
                                                        value={r.nuit ?? ""}
                                                        onChange={(e) => updateRow(r.id, { nuit: e.target.value === "" ? null : Number(e.target.value) })}
                                                        data-testid={`row-nuit-${r.id}`}
                                                        className="w-full h-6 px-1 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-[#005BAB] focus:border-[#005BAB] outline-none bg-white"
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
                                                ? "EEG ES = ES (1.5+2.1) + SA 1.5 + flèches + zones saisonnières affectées"
                                                : "EEG ES = ES (1.5+2.1) affectés + bonus rails→ES 1.5 + flèches + zones saisonnières affectées"}>
                                            EEG ES
                                        </th>
                                        <th className="px-2 py-1.5 text-right font-semibold">Rails ES</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="SA 1.5 à installer (VT)">SA 1.5</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="SA 2.1 à installer (VT)">SA 2.1</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="SA 2.1 Freezer à installer (VT)">SA 2.1 frz</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-blue-700" title="4.2 / 4.2 WP à installer (VT)">4.2/4.2 WP</th>
                                        <th className="px-2 py-1.5 text-right font-semibold text-gray-900" title="Total = EEG ES + SA 1.5 + SA 2.1 + SA 2.1 Freezer + 4.2/4.2 WP (hors Rails ES)">Total</th>
                                        {!hideSaMagasin && (
                                            <th className="px-2 py-1.5 text-right font-semibold italic text-gray-500" title="SA restantes installées par le magasin (info)">SA magasin</th>
                                        )}
                                    </tr>
                                </thead>
                                <tbody>
                                    {Array.from({ length: nbNuits }, (_, i) => i + 1).map((n) => {
                                        const t = nightTotals[n] || { es_15: 0, es_21: 0, sa: 0, sa_15: 0, sa_21: 0, rails_es: 0, seasonal: 0, bonus: 0, fleches: 0, sa_inst_15: 0, sa_inst_21: 0, sa_inst_freezer: 0, sa_inst_42: 0, sa_mag: 0, allees: [] };
                                        const totalES = (t.es_15 || 0) + (t.es_21 || 0);
                                        const color = nightColor(n, weeks);
                                        // En magasin 2 : bonus rails NON inclus dans EEG nuit
                                        const bonusForNight = isMagasin2 ? 0 : (t.bonus || 0);
                                        // Flèches comptées en ES 1.5 noir, magasin 1 et 2
                                        const flechesForNight = t.fleches || 0;
                                        const sa15ForNight = isMagasin2 ? (t.sa_15 || 0) : 0;
                                        const saInstNuit = (t.sa_inst_15 || 0) + (t.sa_inst_21 || 0) + (t.sa_inst_freezer || 0) + (t.sa_inst_42 || 0);
                                        // EEG ES = part ES uniquement (sans les SA à installer)
                                        const eegES = eegPerNight(totalES, t.seasonal, bonusForNight, flechesForNight, sa15ForNight, 0);
                                        // Total = EEG ES + SA 1.5 + SA 2.1 + SA 2.1 freezer (hors Rails ES)
                                        const totalNuit = eegES + saInstNuit;
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
                                                    title={`ES brut (${fmt(Math.round(totalES))})${bonusForNight > 0 ? ` + Bonus rails (${fmt(bonusForNight)})` : ""}${flechesForNight > 0 ? ` + Flèches (${fmt(flechesForNight)})` : ""}${sa15ForNight > 0 ? ` + SA 1.5 (${fmt(sa15ForNight)})` : ""}${t.seasonal > 0 ? ` + Zone saisonnier (${fmt(t.seasonal)})` : ""}`}>
                                                    {fmt(eegES)}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-gray-600">{fmt(t.rails_es)}</td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {t.sa_inst_15 > 0 ? fmt(t.sa_inst_15) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {t.sa_inst_21 > 0 ? fmt(t.sa_inst_21) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {t.sa_inst_freezer > 0 ? fmt(t.sa_inst_freezer) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data text-blue-700 font-semibold">
                                                    {t.sa_inst_42 > 0 ? fmt(t.sa_inst_42) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-2 py-1 text-right font-mono-data font-bold text-gray-900" data-testid={`recap-nuit-total-${n}`}>
                                                    {fmt(totalNuit)}
                                                </td>
                                                {!hideSaMagasin && (
                                                    <td className="px-2 py-1 text-right font-mono-data italic text-gray-500">
                                                        {t.sa_mag > 0 ? fmt(t.sa_mag) : <span className="text-gray-300">—</span>}
                                                    </td>
                                                )}
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
                                        <td className="px-2 py-1 text-right font-mono-data"
                                            title="Somme des lignes ci-dessus (les Zones Saisonnières sont comptées dans les colonnes SA 1.5 et SA 2.1)">
                                            {fmt(Math.round(grandTotals.es + (isMagasin2 ? grandTotals.sa_15 : grandTotals.bonus) + grandTotals.fleches))}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data">
                                            {fmt(grandTotals.rails)}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data text-blue-700">
                                            {fmt(grandTotals.sa_inst_15)}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data text-blue-700">
                                            {fmt(grandTotals.sa_inst_21)}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data text-blue-700">
                                            {fmt(grandTotals.sa_inst_freezer)}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data text-blue-700">
                                            {fmt(grandTotals.sa_inst_42)}
                                        </td>
                                        <td className="px-2 py-1 text-right font-mono-data font-bold text-gray-900" data-testid="recap-nuit-total-grand"
                                            title="Total = somme des colonnes EEG ES + SA 1.5 + SA 2.1 + SA 2.1 frz + 4.2/4.2 WP. Doit correspondre au « Total EEG » affiché en haut.">
                                            {fmt(Math.round(grandTotals.es + (isMagasin2 ? grandTotals.sa_15 : grandTotals.bonus) + grandTotals.fleches) + grandTotals.sa_inst_15 + grandTotals.sa_inst_21 + grandTotals.sa_inst_freezer + grandTotals.sa_inst_42)}
                                        </td>
                                        {!hideSaMagasin && (
                                            <td className="px-2 py-1 text-right font-mono-data italic text-gray-600">
                                                {fmt(grandTotals.sa_mag)}
                                            </td>
                                        )}
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
                {/* ----- Tableau caméras par nuit (séparé des EEG) ----- */}
                <div className="mt-4" data-testid="phasage-cameras-table">
                    <h3 className="text-sm font-semibold text-gray-800 mb-2">Récap caméras par nuit</h3>
                    <div className="border border-gray-200 rounded overflow-hidden max-w-md">
                        <table className="w-full text-xs">
                            <thead className="bg-gray-50 text-gray-700">
                                <tr>
                                    <th className="px-2 py-1.5 text-left font-semibold">Nuit</th>
                                    <th className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">Date</th>
                                    <th className="px-2 py-1.5 text-right font-semibold text-purple-700">Caméras</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(() => {
                                    const camNights = Array.from({ length: nbNuits }, (_, i) => i + 1).filter((n) => (nightTotals[n]?.cameras || 0) > 0);
                                    if (camNights.length === 0) {
                                        return (
                                            <tr><td colSpan={3} className="px-3 py-6 text-center text-gray-500 italic">Aucune caméra affectée (voir l&apos;onglet Phasage caméras).</td></tr>
                                        );
                                    }
                                    return camNights.map((n) => (
                                        <tr key={n} className="border-t border-gray-100" data-testid={`recap-cam-nuit-${n}`}>
                                            <td className="px-2 py-1 font-medium text-gray-900">Nuit {n}</td>
                                            <td className="px-2 py-1 text-[10.5px] text-gray-700 whitespace-nowrap font-mono-data">
                                                {dates[String(n)] ? new Date(dates[String(n)] + "T00:00:00").toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : <span className="text-gray-300">—</span>}
                                            </td>
                                            <td className="px-2 py-1 text-right font-mono-data text-purple-700 font-semibold">{fmt(nightTotals[n].cameras)}</td>
                                        </tr>
                                    ));
                                })()}
                                {grandTotals.cameras > 0 && (
                                    <tr className="border-t-2 border-yellow-300 bg-yellow-50 font-semibold">
                                        <td className="px-2 py-1 text-gray-900" colSpan={2}>TOTAL</td>
                                        <td className="px-2 py-1 text-right font-mono-data text-purple-700">{fmt(grandTotals.cameras)}</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>

            </div>
        </div>
    );
}
