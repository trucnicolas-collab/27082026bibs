import React, { useState, useEffect, useCallback } from "react";
import { ChevronDown, ChevronRight, Loader2, Boxes, Moon, ArrowLeft } from "lucide-react";

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
                    className="flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300 transition-colors">
                    <ArrowLeft className="w-4 h-4" /> Toutes les nuits
                </button>
                <h3 className="text-base font-bold flex items-center gap-2">
                    <Moon className="w-4 h-4 text-sky-400" /> Nuit {selectedNight}
                    {nightDetail?.date && <span className="text-xs text-slate-500 font-normal">{new Date(nightDetail.date + "T00:00:00").toLocaleDateString("fr-FR")}</span>}
                </h3>
                {loading || !nightDetail ? (
                    <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 text-emerald-400 animate-spin" /></div>
                ) : (
                    <div className="space-y-2">
                        {nightDetail.allees.map((a) => <AlleeMateriel key={a.uid} allee={a} />)}
                    </div>
                )}
            </div>
        );
    }

    // ---- Niveau 1 : nuits ----
    return (
        <div className="space-y-3" data-testid="suivi-materiel">
            <div className="rounded-xl bg-slate-900 border border-slate-800 p-3 text-xs text-slate-400 flex items-center gap-2">
                <Boxes className="w-4 h-4 text-emerald-400 flex-shrink-0" />
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
                <div className="w-9 h-9 rounded-lg bg-slate-800 text-emerald-400 flex items-center justify-center font-bold text-sm flex-shrink-0">
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
                        className="mt-1.5 text-[11px] text-emerald-400 hover:text-emerald-300">
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
                    <span className={`${small ? "text-[11px]" : "text-xs"} font-bold text-emerald-300 tabular-nums flex-shrink-0`}>{fmt(p.qty)}</span>
                </div>
            ))}
        </div>
    );
}
