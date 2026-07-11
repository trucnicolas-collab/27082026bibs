import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { Loader2, HardHat, AlertCircle, Moon, Cctv, Boxes, Store, ChevronRight, ChevronLeft, LayoutDashboard, Package } from "lucide-react";
import SuiviNuits from "./SuiviNuits";
import SuiviCam from "./SuiviCam";
import SuiviMateriel from "./SuiviMateriel";
import SuiviDashboard from "./SuiviDashboard";
import SuiviStock from "./SuiviStock";
import { makeActions } from "./api";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const LS_KEY = "suivi.terrain.lastStore";

const TABS = [
    { id: "dashboard", label: "Board", icon: LayoutDashboard },
    { id: "pose", label: "Nuits", icon: Moon },
    { id: "cam", label: "Caméras", icon: Cctv },
    { id: "materiel", label: "Matériel", icon: Boxes },
    { id: "stock", label: "Stock", icon: Package },
];

// Espace équipe terrain COMMUN (/suivi/terrain) : sans compte,
// liste des magasins publiés par les créateurs de phasage.
export default function TerrainApp() {
    const [stores, setStores] = useState(null);
    const [uploadId, setUploadId] = useState(() => {
        try { return localStorage.getItem(LS_KEY) || null; } catch { return null; }
    });
    const [state, setState] = useState(null);
    const [error, setError] = useState(null);
    const [tab, setTab] = useState("dashboard");
    const base = `${API}/suivi-terrain/${uploadId}`;

    const fetchStores = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/suivi-terrain/stores`);
            setStores(res.data.stores || []);
        } catch { setStores([]); }
    }, []);

    const fetchState = useCallback(async () => {
        if (!uploadId) return;
        try {
            const res = await axios.get(base);
            setState(res.data);
            setError(null);
        } catch (e) {
            if (e?.response?.status === 404) {
                // Magasin dépublié → retour à la liste
                setUploadId(null); setState(null);
                try { localStorage.removeItem(LS_KEY); } catch { }
            } else {
                setError("Erreur de chargement, réessayez.");
            }
        }
    }, [base, uploadId]);

    useEffect(() => { fetchStores(); }, [fetchStores]);
    useEffect(() => { if (uploadId) fetchState(); }, [uploadId, fetchState]);

    const actions = useMemo(() => makeActions(base, fetchState), [base, fetchState]);

    const openStore = (id) => {
        setUploadId(id); setState(null); setTab("dashboard");
        try { localStorage.setItem(LS_KEY, id); } catch { }
    };
    const closeStore = () => {
        setUploadId(null); setState(null);
        try { localStorage.removeItem(LS_KEY); } catch { }
        fetchStores();
    };

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 antialiased" data-testid="terrain-app">
            <header className="sticky top-0 z-40 h-14 bg-slate-900/90 backdrop-blur border-b border-slate-800 flex items-center gap-3 px-4">
                {uploadId && (
                    <button onClick={closeStore} data-testid="terrain-back-btn"
                        className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 transition-colors">
                        <ChevronLeft className="w-5 h-5" />
                    </button>
                )}
                <div className="w-8 h-8 rounded-lg bg-amber-500 flex items-center justify-center flex-shrink-0">
                    <HardHat className="w-5 h-5 text-slate-950" />
                </div>
                <div className="min-w-0 flex-1">
                    <h1 className="text-sm font-bold leading-tight truncate" data-testid="terrain-title">
                        {uploadId && state
                            ? (state.store_name
                                ? `${state.store_name}${state.store_code ? ` (${state.store_code})` : ""}`
                                : state.filename)
                            : "Suivi de pose"}
                    </h1>
                    <p className="text-[11px] text-amber-400/90 font-semibold">Espace équipe terrain</p>
                </div>
            </header>

            {!uploadId ? (
                <TerrainStorePicker stores={stores} onOpen={openStore} />
            ) : error ? (
                <div className="flex flex-col items-center gap-3 py-24 text-center px-4" data-testid="terrain-error">
                    <AlertCircle className="w-10 h-10 text-red-400" />
                    <p className="text-sm text-slate-300 max-w-xs">{error}</p>
                    <button onClick={closeStore} className="text-sm text-amber-400 underline">Retour à la liste</button>
                </div>
            ) : !state ? (
                <div className="flex items-center justify-center py-32">
                    <Loader2 className="w-8 h-8 text-amber-400 animate-spin" />
                </div>
            ) : (
                <>
                    <nav className="fixed bottom-0 inset-x-0 z-40 bg-slate-900/95 backdrop-blur border-t border-slate-800 sm:sticky sm:top-14 sm:bottom-auto sm:border-t-0 sm:border-b sm:bg-slate-900/80">
                        <div className="max-w-3xl mx-auto flex">
                            {TABS.map((t) => {
                                const Icon = t.icon;
                                const active = tab === t.id;
                                return (
                                    <button key={t.id} onClick={() => setTab(t.id)}
                                        data-testid={`terrain-tab-${t.id}`}
                                        className={`flex-1 sm:flex-none sm:px-6 py-2.5 flex flex-col sm:flex-row items-center gap-1 sm:gap-2 text-[11px] sm:text-sm font-medium transition-colors relative
                                            ${active ? "text-amber-400" : "text-slate-500 hover:text-slate-300"}`}>
                                        <Icon className="w-5 h-5 sm:w-4 sm:h-4" />
                                        {t.label}
                                        {active && <span className="absolute bottom-0 inset-x-4 h-0.5 bg-amber-400 rounded-full hidden sm:block" />}
                                    </button>
                                );
                            })}
                        </div>
                    </nav>
                    <main className="max-w-3xl mx-auto px-3 sm:px-6 py-4 pb-24 sm:pb-16">
                        {tab === "dashboard" && <SuiviDashboard state={state} actions={actions} mode="terrain"
                            goTab={(t) => setTab(t === "nuits" ? "pose" : t)} />}
                        {tab === "pose" && <SuiviNuits state={state} actions={actions} mode="terrain" />}
                        {tab === "cam" && <SuiviCam state={state} actions={actions} />}
                        {tab === "materiel" && <SuiviMateriel actions={actions} />}
                        {tab === "stock" && <SuiviStock state={state} actions={actions} />}
                    </main>
                </>
            )}
        </div>
    );
}

function TerrainStorePicker({ stores, onOpen }) {
    return (
        <main className="max-w-2xl mx-auto px-4 py-8" data-testid="terrain-store-picker">
            <h2 className="text-lg font-bold mb-1">Choisir un magasin</h2>
            <p className="text-sm text-slate-400 mb-5">Seuls les magasins publiés par le chef de projet apparaissent ici.</p>
            {stores === null ? (
                <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 text-amber-400 animate-spin" /></div>
            ) : stores.length === 0 ? (
                <div className="text-center py-16 text-slate-500 text-sm" data-testid="terrain-no-stores">
                    Aucun magasin publié pour le moment.<br />Demandez au chef de projet de publier le suivi.
                </div>
            ) : (
                <div className="space-y-2">
                    {stores.map((s) => (
                        <button key={s.upload_id} onClick={() => onOpen(s.upload_id)}
                            data-testid={`terrain-store-${s.upload_id}`}
                            className="w-full flex items-center gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-amber-500/60 transition-all text-left group">
                            <div className="w-10 h-10 rounded-lg bg-slate-800 flex items-center justify-center flex-shrink-0 group-hover:bg-amber-900/30 transition-colors">
                                <Store className="w-5 h-5 text-amber-400" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-sm font-semibold truncate">
                                    {s.store_name
                                        ? `${s.store_name}${s.store_code ? ` (${s.store_code})` : ""}`
                                        : (s.label || s.filename)}
                                </div>
                                {s.published_by && <div className="text-[11px] text-slate-500">publié par {s.published_by}</div>}
                            </div>
                            <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-amber-400 transition-colors" />
                        </button>
                    ))}
                </div>
            )}
        </main>
    );
}
