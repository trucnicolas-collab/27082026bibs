import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Loader2, HardHat, AlertCircle } from "lucide-react";
import SuiviNuits from "./SuiviNuits";
import { makeActions } from "./api";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// App équipe terrain : accès par token, SANS compte, mobile-first.
export default function TerrainApp({ token }) {
    const [state, setState] = useState(null);
    const [error, setError] = useState(null);
    const base = `${API}/suivi-terrain/${token}`;

    const fetchState = useCallback(async () => {
        try {
            const res = await axios.get(base);
            setState(res.data);
            setError(null);
        } catch (e) {
            setError(e?.response?.status === 404
                ? "Lien invalide ou désactivé. Demandez un nouveau lien au chef de projet."
                : "Erreur de chargement, réessayez.");
        }
    }, [base]);

    useEffect(() => { fetchState(); }, [fetchState]);

    const actions = makeActions(base, fetchState);

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 antialiased" data-testid="terrain-app">
            <header className="sticky top-0 z-40 h-14 bg-slate-900/90 backdrop-blur border-b border-slate-800 flex items-center gap-3 px-4">
                <div className="w-8 h-8 rounded-lg bg-amber-500 flex items-center justify-center flex-shrink-0">
                    <HardHat className="w-5 h-5 text-slate-950" />
                </div>
                <div className="min-w-0 flex-1">
                    <h1 className="text-sm font-bold leading-tight truncate" data-testid="terrain-title">
                        {state ? (state.store_name || state.filename) : "Suivi de pose"}
                    </h1>
                    <p className="text-[11px] text-amber-400/90 font-semibold">Mode équipe terrain</p>
                </div>
            </header>
            <main className="max-w-3xl mx-auto px-3 sm:px-6 py-4 pb-16">
                {error ? (
                    <div className="flex flex-col items-center gap-3 py-24 text-center" data-testid="terrain-error">
                        <AlertCircle className="w-10 h-10 text-red-400" />
                        <p className="text-sm text-slate-300 max-w-xs">{error}</p>
                    </div>
                ) : !state ? (
                    <div className="flex items-center justify-center py-32">
                        <Loader2 className="w-8 h-8 text-amber-400 animate-spin" />
                    </div>
                ) : (
                    <>
                        <p className="text-xs text-slate-500 mb-3">
                            Saisissez le <b className="text-slate-300">réel posé</b> et le <b className="text-slate-300">géolocalisé</b> par allée,
                            ajoutez photos et commentaires, puis <b className="text-slate-300">validez</b> chaque allée terminée.
                        </p>
                        <SuiviNuits state={state} actions={actions} mode="terrain" />
                    </>
                )}
            </main>
        </div>
    );
}
