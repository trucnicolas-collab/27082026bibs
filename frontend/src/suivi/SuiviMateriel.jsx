import React, { useState, useEffect, useCallback } from "react";
import { ChevronDown, ChevronRight, Loader2, Boxes, Moon, ArrowLeft, TrendingUp, TrendingDown, CheckCircle2, Scale, MapPin } from "lucide-react";

const fmt = (v) => Number(v || 0).toLocaleString("fr-FR");

// Matériel prévu : Nuits → Allées → Éléments (drill-down 3 niveaux)
export default function SuiviMateriel({ actions, phaseKind = "eeg" }) {
    const [overview, setOverview] = useState(null);
    const [selectedNight, setSelectedNight] = useState(null);
    const [nightDetail, setNightDetail] = useState(null);
    const [loading, setLoading] = useState(false);
    const accent = phaseKind === "cam" ? "sky" : "emerald";

    useEffect(() => {
        setOverview(null);
        setSelectedNight(null);
        setNightDetail(null);
        (async () => {
            const data = await actions.getMateriel(phaseKind);
            setOverview(data);
        })();
    }, [actions, phaseKind]);

    const openNight = useCallback(async (n) => {
        setSelectedNight(n);
        setNightDetail(null);
        setLoading(true);
        const data = await actions.getMaterielNuit(n, phaseKind);
        setNightDetail(data);
        setLoading(false);
    }, [actions, phaseKind]);

    if (!overview) {
        return <div className="flex justify-center py-24"><Loader2 className={`w-7 h-7 text-${accent}-400 animate-spin`} /></div>;
    }

    // ---- Niveau 2+3 : détail d'une nuit ----
    if (selectedNight) {
        return (
            <div className="space-y-3" data-testid="materiel-night-detail">
                <button onClick={() => { setSelectedNight(null); setNightDetail(null); }}
                    data-testid="materiel-back"
                    className="flex items-center gap-1.5 text-sm text-blue-400 hover:text-blue-300 transition-colors">
                    <ArrowLeft className="w-4 h-4" /> Toutes les nuits
                </button>
                <h3 className="text-base font-bold flex items-center gap-2">
                    <Moon className="w-4 h-4 text-sky-400" /> Nuit {selectedNight}
                    {nightDetail?.date && <span className="text-xs text-slate-500 font-normal">{new Date(nightDetail.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                </h3>
                {loading || !nightDetail ? (
                    <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 text-blue-400 animate-spin" /></div>
                ) : (
                    <div className="space-y-2">
                        {nightDetail.allees.map((a) => <AlleeMateriel key={a.uid} allee={a} />)}
                        <EcartRecap night={nightDetail} accent={accent} />
                    </div>
                )}
            </div>
        );
    }

    // ---- Niveau 1 : nuits ----
    return (
        <div className="space-y-3" data-testid="suivi-materiel">
            <div className="rounded-xl bg-slate-900 border border-slate-800 p-3 text-xs text-slate-400 flex items-center gap-2">
                <Boxes className="w-4 h-4 text-blue-400 flex-shrink-0" />
                Matériel prévu par nuit. Touchez une nuit pour voir le détail par allée, puis par élément.
            </div>
            {(overview.nights || []).map((n) => (
                <NightMateriel key={n.nuit} night={n} onOpen={() => openNight(n.nuit)} />
            ))}
            {overview.unassigned?.nb_allees > 0 && (
                <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4" data-testid="materiel-unassigned">
                    <div className="text-sm font-semibold text-slate-400 mb-2">Hors phasage ({overview.unassigned.nb_allees} allées non assignées)</div>
                    <ProductTable products={overview.unassigned.products} />
                </div>
            )}
        </div>
    );
}

function NightMateriel({ night, onOpen }) {
    const [expanded, setExpanded] = useState(false);
    const shown = expanded ? night.products : night.products.slice(0, 5);
    return (
        <section className="rounded-2xl border border-slate-800 bg-slate-900 overflow-hidden" data-testid={`materiel-night-${night.nuit}`}>
            <button onClick={onOpen} className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-800/40 transition-colors"
                data-testid={`materiel-night-open-${night.nuit}`}>
                <div className="w-9 h-9 rounded-lg bg-slate-800 text-blue-400 flex items-center justify-center font-bold text-sm flex-shrink-0">
                    {night.nuit}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold">
                        Nuit {night.nuit}
                        {night.date && <span className="text-xs text-slate-500 font-normal ml-2">{new Date(night.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                    </div>
                    <div className="text-xs text-slate-400">{night.nb_allees} allée(s) · {night.products.length} produit(s) différent(s)</div>
                </div>
                <ChevronRight className="w-4 h-4 text-slate-500" />
            </button>
            <div className="px-4 pb-3">
                <ProductTable products={shown} />
                {night.products.length > 5 && (
                    <button onClick={() => setExpanded(!expanded)}
                        className="mt-1.5 text-[11px] text-blue-400 hover:text-blue-300">
                        {expanded ? "Voir moins" : `Voir les ${night.products.length - 5} autres produits`}
                    </button>
                )}
            </div>
        </section>
    );
}

function AlleeMateriel({ allee: a }) {
    const [open, setOpen] = useState(false);
    return (
        <section className="rounded-xl border border-slate-800 bg-slate-900 overflow-hidden" data-testid={`materiel-allee-${a.uid}`}>
            <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 px-3.5 py-2.5 text-left"
                data-testid={`materiel-allee-toggle-${a.uid}`}>
                <span className="px-2 py-0.5 rounded-md bg-slate-700 text-slate-100 text-sm font-bold">Allée {a.allee}</span>
                <span className="text-xs text-slate-400 truncate flex-1 min-w-0">{a.secteur}{a.rayon ? ` · ${a.rayon}` : ""}</span>
                <span className="text-[11px] text-slate-500">{a.elements.length} élément(s)</span>
                <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
            </button>
            <div className="px-3.5 pb-3">
                <ProductTable products={a.products} />
            </div>
            {open && (
                <div className="border-t border-slate-800/80 px-3.5 py-3 space-y-2 bg-slate-950/40" data-testid={`materiel-elements-${a.uid}`}>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Détail par élément</div>
                    {a.elements.map((el) => (
                        <div key={el.element} className="rounded-lg bg-slate-900 border border-slate-800 p-2.5">
                            <div className="text-xs font-bold text-sky-300 font-mono mb-1.5">Élément {el.element}</div>
                            <ProductTable products={el.products} small />
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}

function ProductTable({ products, small = false }) {
    if (!products?.length) return <div className="text-xs text-slate-600">Aucun produit</div>;
    return (
        <div className="divide-y divide-slate-800/60">
            {products.map((p) => (
                <div key={p.designation} className={`flex items-center justify-between gap-3 ${small ? "py-0.5" : "py-1"}`}>
                    <span className={`${small ? "text-[11px]" : "text-xs"} text-slate-300 min-w-0 truncate`} title={p.designation}>{p.designation}</span>
                    <span className={`${small ? "text-[11px]" : "text-xs"} font-bold text-blue-300 tabular-nums flex-shrink-0`}>{fmt(p.qty)}</span>
                </div>
            ))}
        </div>
    );
}


function EcartRecap({ night, accent = "emerald" }) {
    const [showAll, setShowAll] = useState(false);
    const [filter, setFilter] = useState("all"); // all | bonus | manque | conforme
    const [geoOnly, setGeoOnly] = useState(false); // (v28 iter3) toggle « manque de géoloc »
    const ecarts = night.ecarts || [];
    const stats = night.ecart_stats || {};
    // Compte les lignes avec manque de géoloc (is_geo=true et geo < reel)
    const nbGeoMissing = ecarts.filter(e => e.is_geo && (e.geo ?? 0) < (e.reel ?? 0)).length;
    if (!ecarts.length) {
        return (
            <section className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-5 text-center" data-testid="ecart-recap-empty">
                <Scale className="w-6 h-6 text-slate-600 mx-auto mb-2" />
                <p className="text-xs text-slate-500">
                    Aucun réel saisi pour cette nuit. L&apos;écart phasage vs réel s&apos;affichera dès qu&apos;une allée aura une saisie.
                </p>
            </section>
        );
    }
    let filtered = filter === "all" ? ecarts : ecarts.filter((e) => e.status === filter);
    if (geoOnly) {
        filtered = filtered.filter((e) => e.is_geo && (e.geo ?? 0) < (e.reel ?? 0));
    }
    const shown = showAll ? filtered : filtered.slice(0, 8);
    const statusColor = (s) => s === "bonus" ? "text-sky-400" : s === "manque" ? "text-red-400" : "text-blue-400";
    const statusIcon = (s) => s === "bonus" ? TrendingUp : s === "manque" ? TrendingDown : CheckCircle2;

    const filterBtn = (id, label, count, color) => (
        <button onClick={() => { setFilter(id); setShowAll(false); }}
            data-testid={`ecart-filter-${id}`}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold flex items-center gap-1.5 transition-colors border ${filter === id
                ? `bg-slate-800 border-slate-600 ${color}`
                : `bg-slate-900/40 border-slate-800 text-slate-500 hover:text-slate-300`}`}>
            {label} <span className="tabular-nums">{count}</span>
        </button>
    );

    return (
        <section className="mt-4 rounded-2xl border border-slate-800 bg-slate-900 overflow-hidden" data-testid="ecart-recap">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2 flex-wrap">
                <Scale className={`w-4 h-4 text-${accent}-400`} />
                <h4 className="text-sm font-bold flex-1">Écart phasage vs réel — fin de nuit</h4>
                {stats.complete
                    ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 font-bold">NUIT VALIDÉE</span>
                    : <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-semibold">EN COURS</span>}
            </div>
            <div className="px-4 py-3 grid grid-cols-3 gap-2 border-b border-slate-800">
                <MiniStat label="Conforme (±5%)" value={stats.nb_conforme || 0} icon={CheckCircle2} color="text-blue-400" testid="ecart-stat-conforme" />
                <MiniStat label="Bonus posé (>+5%)" value={stats.nb_bonus || 0} icon={TrendingUp} color="text-sky-400" testid="ecart-stat-bonus" />
                <MiniStat label="Sous-livré (<-5%)" value={stats.nb_manque || 0} icon={TrendingDown} color="text-red-400" testid="ecart-stat-manque" />
            </div>
            <div className="px-4 py-2.5 flex items-center gap-2 flex-wrap border-b border-slate-800 bg-slate-950/40">
                {filterBtn("all", "Tous", ecarts.length, "text-slate-200")}
                {filterBtn("conforme", "Conforme", stats.nb_conforme || 0, "text-blue-400")}
                {filterBtn("bonus", "Bonus", stats.nb_bonus || 0, "text-sky-400")}
                {filterBtn("manque", "Manque", stats.nb_manque || 0, "text-red-400")}
                {nbGeoMissing > 0 && (
                    <button onClick={() => { setGeoOnly((v) => !v); setShowAll(false); }}
                        data-testid="ecart-filter-geo-missing"
                        className={`ml-auto px-2.5 py-1 rounded-lg text-[11px] font-semibold flex items-center gap-1.5 transition-colors border ${geoOnly
                            ? "bg-amber-950/60 border-amber-800 text-amber-300"
                            : "bg-slate-900/40 border-slate-800 text-slate-500 hover:text-amber-400"}`}
                        title="Filtre : afficher uniquement les produits posés mais partiellement (ou pas) géolocalisés">
                        <MapPin className="w-3 h-3" /> Manque géoloc <span className="tabular-nums">{nbGeoMissing}</span>
                    </button>
                )}
            </div>
            <div className="divide-y divide-slate-800/60" data-testid="ecart-rows">
                {shown.map((e) => {
                    const Icon = statusIcon(e.status);
                    const color = statusColor(e.status);
                    const pct = e.plan > 0 ? Math.round((e.delta / e.plan) * 100) : 0;
                    // (v28) Colonne Géoloc distincte pour les familles concernées
                    // (rails_es, sa_15, sa_21_std côté EEG ; caméras côté cam).
                    const hasGeo = e.is_geo === true;
                    const geoVal = e.geo === null || e.geo === undefined ? null : e.geo;
                    const geoGap = hasGeo && geoVal !== null && e.reel > 0 ? Math.round(100 * geoVal / e.reel) : null;
                    return (
                        <div key={e.designation} className="flex items-center gap-3 px-4 py-2" data-testid={`ecart-row-${e.designation}`}>
                            <Icon className={`w-4 h-4 flex-shrink-0 ${color}`} />
                            <div className="flex-1 min-w-0">
                                <div className="text-xs text-slate-200 truncate flex items-center gap-1.5" title={e.designation}>
                                    {e.designation}
                                    {hasGeo && (
                                        <span className="text-[9px] px-1 py-0.5 rounded bg-sky-950 text-sky-400 font-bold flex-shrink-0"
                                            title="Géolocalisation requise (Rails ES / SA 1.5 / SA 2.1 / caméras)">
                                            GÉO
                                        </span>
                                    )}
                                </div>
                                <div className="text-[10px] text-slate-500 flex items-center gap-2 flex-wrap">
                                    <span>Prévu <span className="text-slate-300 font-semibold">{fmt(e.plan)}</span></span>
                                    <span>· Posé <span className={color}>{fmt(e.reel)}</span></span>
                                    {hasGeo && (
                                        <span data-testid={`ecart-row-geo-${e.designation}`}>
                                            · Géoloc <span className={geoGap === null ? "text-slate-600" : geoGap >= 100 ? "text-sky-400 font-semibold" : "text-amber-400 font-semibold"}>
                                                {geoVal === null ? "—" : fmt(geoVal)}
                                            </span>
                                            {geoGap !== null && geoGap < 100 && (
                                                <span className="text-[9px] text-amber-500 ml-1">({geoGap}%)</span>
                                            )}
                                        </span>
                                    )}
                                </div>
                            </div>
                            <div className={`text-xs font-bold tabular-nums ${color} flex-shrink-0`}>
                                {e.delta > 0 ? "+" : ""}{fmt(e.delta)}
                                {e.plan > 0 && <span className="text-[10px] text-slate-500 ml-1">({pct > 0 ? "+" : ""}{pct}%)</span>}
                            </div>
                        </div>
                    );
                })}
                {filtered.length === 0 && (
                    <div className="px-4 py-4 text-xs text-slate-500 text-center italic">Aucun produit dans cette catégorie.</div>
                )}
            </div>
            {filtered.length > 8 && (
                <button onClick={() => setShowAll(!showAll)}
                    data-testid="ecart-toggle-all"
                    className={`w-full py-2 text-[11px] text-${accent}-400 hover:text-${accent}-300 border-t border-slate-800 bg-slate-950/30 transition-colors`}>
                    {showAll ? "Voir moins" : `Voir les ${filtered.length - 8} autres produits`}
                </button>
            )}
        </section>
    );
}

function MiniStat({ label, value, icon: Icon, color, testid }) {
    return (
        <div className="text-center" data-testid={testid}>
            <Icon className={`w-4 h-4 ${color} mx-auto mb-1`} />
            <div className={`text-lg font-bold ${color} tabular-nums`}>{value}</div>
            <div className="text-[9px] uppercase tracking-widest text-slate-500 font-semibold leading-tight">{label}</div>
        </div>
    );
}
