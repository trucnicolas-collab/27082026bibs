import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, PackageCheck, Undo2, Search } from "lucide-react";

const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));

// Stock PAR PRODUIT : chaque désignation du fichier
// phaseKind = "eeg" | "cam" | null → filtre les produits par domaine
const CAPTANA_DESIGNATIONS = new Set([
    "caméra (blanche)", "caméra (noire)",
    "batterie caméra", "software caméra",
    "support mobilier captana (blanc)", "support mobilier captana (noir)",
    "support ajustable adhésif captana",
    "pied réglable 0,5-1 m adhésif captana",
]);
function isCamStockRow(s) {
    if (s.family === "cameras") return true;
    const t = (s.type || "").trim().toLowerCase();
    if (t === "caméra" || t === "camera") return true;
    const d = (s.designation || "").trim().toLowerCase();
    if (CAPTANA_DESIGNATIONS.has(d)) return true;
    if (d.includes("captana")) return true;
    return false;
}
export default function SuiviStock({ state, actions, phaseKind = null }) {
    const [query, setQuery] = useState("");
    const [onlyAlerts, setOnlyAlerts] = useState(false);
    const scoped = (state.stock || []).filter((s) => {
        if (phaseKind === "cam") return isCamStockRow(s);
        if (phaseKind === "eeg") return !isCamStockRow(s);
        return true;
    });
    const all = scoped.filter((s) => s.prevu > 0 || s.recu !== null || s.pose > 0);
    const nbAlerts = all.filter((s) => s.alert).length;
    const rows = all.filter((s) =>
        (!onlyAlerts || s.alert) &&
        (query.trim() === "" || s.designation.toLowerCase().includes(query.trim().toLowerCase())));

    return (
        <div className="space-y-3" data-testid="suivi-stock">
            <div className="rounded-xl bg-slate-900 border border-slate-800 p-3 text-xs text-slate-400 leading-relaxed">
                Le <b className="text-slate-200">prévu</b> vient du fichier. Saisissez le <b className="text-slate-200">reçu réel</b> par produit à la
                livraison. Le <b className="text-slate-200">posé</b> se décompte automatiquement des saisies par allée.
                🚨 Alerte si le stock restant ne couvre pas ce qu'il reste à poser.
            </div>
            <div className="flex items-center gap-2">
                <div className="relative flex-1">
                    <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                    <input value={query} onChange={(e) => setQuery(e.target.value)}
                        placeholder="Rechercher un produit..."
                        data-testid="stock-search"
                        className="w-full h-9 pl-8 pr-3 rounded-lg bg-slate-900 border border-slate-800 text-xs placeholder:text-slate-600 focus:border-emerald-600 outline-none" />
                </div>
                <button onClick={() => setOnlyAlerts(!onlyAlerts)} data-testid="stock-filter-alerts"
                    className={`h-9 px-3 rounded-lg text-xs font-semibold flex items-center gap-1.5 border transition-colors
                        ${onlyAlerts ? "bg-red-600 border-red-600 text-white" : "border-slate-700 text-slate-400 hover:bg-slate-800"}`}>
                    <AlertTriangle className="w-3.5 h-3.5" /> Alertes{nbAlerts > 0 ? ` (${nbAlerts})` : ""}
                </button>
            </div>
            <div className="text-[11px] text-slate-500">{rows.length} / {all.length} produits</div>
            <div className="space-y-2">
                {rows.map((s) => <StockRow key={s.designation} s={s} actions={actions} />)}
                {rows.length === 0 && <div className="text-center py-10 text-slate-600 text-sm">Aucun produit trouvé</div>}
            </div>
        </div>
    );
}

function StockRow({ s, actions }) {
    const [recu, setRecu] = useState(s.recu === null ? "" : String(s.recu));
    const save = async () => {
        const num = recu === "" ? null : Number(recu);
        if (recu !== "" && (isNaN(num) || num < 0)) return;
        if (num === s.recu) return;
        await actions.patchStock(s.designation, num);
    };
    return (
        <div className={`rounded-xl border p-3 ${s.alert ? "bg-red-950/40 border-red-900/70" : "bg-slate-900 border-slate-800"}`}
            data-testid={`stock-row-${s.designation}`}>
            <div className="flex items-center justify-between gap-2 mb-2">
                <div className="font-semibold text-xs sm:text-sm flex items-center gap-2 min-w-0">
                    {s.alert ? <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" /> : <PackageCheck className="w-4 h-4 text-emerald-500 flex-shrink-0" />}
                    <span className="truncate" title={s.designation}>{s.designation}</span>
                    {s.type && <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500 font-normal flex-shrink-0">{s.type}</span>}
                </div>
                {s.alert ? (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-600 text-white font-bold flex-shrink-0" data-testid={`stock-alert-${s.designation}`}>
                        MANQUE {fmt(s.manque)}
                    </span>
                ) : (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-900/60 text-emerald-300 font-semibold flex items-center gap-1 flex-shrink-0">
                        <CheckCircle2 className="w-3 h-3" /> OK
                    </span>
                )}
            </div>
            <div className="grid grid-cols-5 gap-1.5 text-center">
                <Cell label="Prévu" value={fmt(s.prevu)} />
                <div className="rounded-lg bg-slate-800/60 p-1.5">
                    <div className="text-[9px] uppercase tracking-wide text-slate-500 font-semibold flex items-center justify-center gap-1">
                        Reçu {s.recu_theorique && <span className="text-amber-500" title="Théorique (= prévu), saisissez le réel">*</span>}
                        {!s.recu_theorique && (
                            <button onClick={() => { setRecu(""); actions.patchStock(s.designation, null); }}
                                title="Revenir au théorique" className="text-slate-600 hover:text-slate-300">
                                <Undo2 className="w-3 h-3" />
                            </button>
                        )}
                    </div>
                    <input type="number" min="0" inputMode="numeric" value={recu}
                        onChange={(e) => setRecu(e.target.value)} onBlur={save}
                        placeholder={String(s.prevu)}
                        data-testid={`stock-recu-${s.designation}`}
                        className="w-full mt-0.5 h-7 px-1 rounded bg-slate-900 border border-slate-700 text-xs sm:text-sm font-bold text-center focus:border-emerald-500 outline-none placeholder:text-slate-600" />
                </div>
                <Cell label="Posé" value={fmt(s.pose)} accent="text-emerald-400" />
                <Cell label="Reste stock" value={fmt(s.restant_stock)} accent={s.restant_stock < 0 ? "text-red-400" : ""} />
                <Cell label="Reste à poser" value={fmt(s.restant_a_poser)} accent={s.alert ? "text-red-400" : ""} />
            </div>
        </div>
    );
}

function Cell({ label, value, accent = "" }) {
    return (
        <div className="rounded-lg bg-slate-800/60 p-1.5">
            <div className="text-[9px] uppercase tracking-wide text-slate-500 font-semibold">{label}</div>
            <div className={`text-xs sm:text-sm font-bold mt-1 ${accent}`}>{value}</div>
        </div>
    );
}
