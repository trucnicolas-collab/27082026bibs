import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, PackageCheck, Undo2 } from "lucide-react";

const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR"));

export default function SuiviStock({ state, actions }) {
    const rows = (state.stock || []).filter((s) => s.prevu > 0 || s.recu !== null || s.pose > 0);

    return (
        <div className="space-y-4" data-testid="suivi-stock">
            <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 text-xs text-slate-400 leading-relaxed">
                <b className="text-slate-200">Comment ça marche :</b> le <b>prévu</b> vient du phasage. Saisissez le <b>reçu réel</b> à la
                livraison (sinon on prend le prévu comme théorique). Le <b>posé</b> se décompte automatiquement des saisies par allée.
                🚨 Alerte si le stock restant ne couvre pas ce qu'il reste à poser.
            </div>
            <div className="space-y-2">
                {rows.map((s) => <StockRow key={s.family} s={s} actions={actions} />)}
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
        await actions.patchStock(s.family, num);
    };
    return (
        <div className={`rounded-xl border p-3.5 ${s.alert ? "bg-red-950/40 border-red-900/70" : "bg-slate-900 border-slate-800"}`}
            data-testid={`stock-row-${s.family}`}>
            <div className="flex items-center justify-between gap-2 mb-2.5">
                <div className="font-semibold text-sm flex items-center gap-2">
                    {s.alert ? <AlertTriangle className="w-4 h-4 text-red-400" /> : <PackageCheck className="w-4 h-4 text-emerald-500" />}
                    {s.label}
                </div>
                {s.alert ? (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-600 text-white font-bold" data-testid={`stock-alert-${s.family}`}>
                        MANQUE {fmt(s.manque)}
                    </span>
                ) : (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-900/60 text-emerald-300 font-semibold flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" /> OK
                    </span>
                )}
            </div>
            <div className="grid grid-cols-5 gap-2 text-center">
                <Cell label="Prévu" value={fmt(s.prevu)} />
                <div className="rounded-lg bg-slate-800/60 p-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold flex items-center justify-center gap-1">
                        Reçu {s.recu_theorique && <span className="text-amber-500" title="Théorique (= prévu), saisissez le réel">*</span>}
                        {!s.recu_theorique && (
                            <button onClick={() => { setRecu(""); actions.patchStock(s.family, null); }}
                                title="Revenir au théorique" className="text-slate-600 hover:text-slate-300">
                                <Undo2 className="w-3 h-3" />
                            </button>
                        )}
                    </div>
                    <input type="number" min="0" inputMode="numeric" value={recu}
                        onChange={(e) => setRecu(e.target.value)} onBlur={save}
                        placeholder={String(s.prevu)}
                        data-testid={`stock-recu-${s.family}`}
                        className="w-full mt-0.5 h-7 px-1 rounded bg-slate-900 border border-slate-700 text-sm font-bold text-center focus:border-emerald-500 outline-none placeholder:text-slate-600" />
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
        <div className="rounded-lg bg-slate-800/60 p-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">{label}</div>
            <div className={`text-sm font-bold mt-1 ${accent}`}>{value}</div>
        </div>
    );
}
