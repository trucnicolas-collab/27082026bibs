import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import {
    Loader2, Eye, AlertCircle, Moon, Cctv, Boxes, Store,
    ChevronRight, ChevronLeft, LayoutDashboard, Package, MapPin,
} from "lucide-react";
import SuiviNuits from "./SuiviNuits";
import SuiviCam from "./SuiviCam";
import SuiviMateriel from "./SuiviMateriel";
import SuiviDashboard from "./SuiviDashboard";
import SuiviStock from "./SuiviStock";
import SuiviFloorplan from "./SuiviFloorplan";
import PhaseCategoryPicker from "./PhaseCategoryPicker";
import { makeActions } from "./api";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const LS_KEY = "suivi.viewer.lastStore";
const LS_PHASE = "suivi.viewer.lastPhase";

const TABS_EEG = [
    { id: "dashboard", label: "Board", icon: LayoutDashboard },
    { id: "pose", label: "Nuits", icon: Moon },
    { id: "plan", label: "Plan", icon: MapPin },
    { id: "materiel", label: "Matériel", icon: Boxes },
    { id: "stock", label: "Stock", icon: Package },
];
const TABS_CAM = [
    { id: "dashboard", label: "Board", icon: LayoutDashboard },
    { id: "cam", label: "Caméras", icon: Cctv },
    { id: "plan", label: "Plan", icon: MapPin },
    { id: "materiel", label: "Matériel", icon: Boxes },
    { id: "stock", label: "Stock", icon: Package },
];

/**
 * Espace CLIENT — Lecture seule (/suivi/view?token=…).
 * Un token global stocké côté backend. Toutes les routes appelées ici sont
 * en GET et n'exposent aucune écriture. Le flag `readOnly` neutralise en
 * plus toute action côté UI (défense en profondeur).
 */
export default function ViewerApp() {
    const [token] = useState(() => {
        try { return new URLSearchParams(window.location.search).get("token") || ""; } catch { return ""; }
    });
    const [stores, setStores] = useState(null);
    const [uploadId, setUploadId] = useState(() => {
        try { return localStorage.getItem(LS_KEY) || null; } catch { return null; }
    });
    const [state, setState] = useState(null);
    const [error, setError] = useState(null);
    const [tab, setTab] = useState("dashboard");
    const [phaseKind, setPhaseKind] = useState(() => {
        try { return localStorage.getItem(LS_PHASE) || null; } catch { return null; }
    });
    const base = `${API}/suivi-view/${uploadId}`;
    const tokenParam = `token=${encodeURIComponent(token)}`;
    const TABS = phaseKind === "cam" ? TABS_CAM : TABS_EEG;

    const fetchStores = useCallback(async () => {
        if (!token) { setStores([]); return; }
        try {
            const res = await axios.get(`${API}/suivi-view/stores`, { params: { token } });
            setStores(res.data.stores || []);
        } catch (e) {
            if (e?.response?.status === 401) setError("Lien de partage invalide ou expiré.");
            setStores([]);
        }
    }, [token]);

    const fetchState = useCallback(async () => {
        if (!uploadId) return;
        try {
            const res = await axios.get(base, { params: { token } });
            setState(res.data);
            setError(null);
        } catch (e) {
            if (e?.response?.status === 404) {
                setUploadId(null); setState(null);
                try { localStorage.removeItem(LS_KEY); } catch (_) { /* noop */ }
            } else if (e?.response?.status === 401) {
                setError("Lien de partage invalide ou expiré.");
            } else {
                setError("Erreur de chargement, réessayez.");
            }
        }
    }, [base, uploadId, token]);

    useEffect(() => { fetchStores(); }, [fetchStores]);
    useEffect(() => { if (uploadId) fetchState(); }, [uploadId, fetchState]);

    const actions = useMemo(
        () => makeActions(base, fetchState, { readOnly: true, tokenParam }),
        [base, fetchState, tokenParam]
    );

    const openStore = (id) => {
        setUploadId(id); setState(null); setTab("dashboard"); setPhaseKind(null);
        try { localStorage.setItem(LS_KEY, id); localStorage.removeItem(LS_PHASE); } catch (_) { /* noop */ }
    };
    const closeStore = () => {
        setUploadId(null); setState(null); setPhaseKind(null);
        try { localStorage.removeItem(LS_KEY); localStorage.removeItem(LS_PHASE); } catch (_) { /* noop */ }
        fetchStores();
    };
    const pickPhase = (kind) => {
        setPhaseKind(kind);
        setTab("dashboard");
        try { localStorage.setItem(LS_PHASE, kind); } catch (_) { /* noop */ }
    };
    const backToPhasePicker = () => {
        setPhaseKind(null);
        try { localStorage.removeItem(LS_PHASE); } catch (_) { /* noop */ }
    };

    if (!token) {
        return (
            <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-4"
                data-testid="viewer-no-token">
                <div className="max-w-md text-center space-y-3">
                    <AlertCircle className="w-10 h-10 text-red-400 mx-auto" />
                    <h1 className="text-lg font-bold">Lien invalide</h1>
                    <p className="text-sm text-slate-400">
                        Ce lien ne contient pas de jeton d'accès. Demandez à votre contact chez Vusion un lien valide.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 antialiased" data-testid="viewer-app">
            <header className="sticky top-0 z-40 h-14 bg-slate-900/90 backdrop-blur border-b border-purple-800/60 flex items-center gap-3 px-4">
                {uploadId && (
                    <button onClick={phaseKind ? backToPhasePicker : closeStore} data-testid="viewer-back-btn"
                        className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 transition-colors">
                        <ChevronLeft className="w-5 h-5" />
                    </button>
                )}
                <div className="w-8 h-8 rounded-lg bg-purple-500 flex items-center justify-center flex-shrink-0">
                    <Eye className="w-5 h-5 text-slate-950" />
                </div>
                <div className="min-w-0 flex-1">
                    <h1 className="text-sm font-bold leading-tight truncate" data-testid="viewer-title">
                        {uploadId && state
                            ? (state.store_name
                                ? `${state.store_name}${state.store_code ? ` (${state.store_code})` : ""}`
                                : state.filename)
                            : "Suivi de déploiement"}
                    </h1>
                    <p className="text-[11px] text-purple-300 font-semibold flex items-center gap-1.5">
                        <Eye className="w-3 h-3" /> Mode lecture seule — Client
                        {phaseKind && (
                            <span className={`ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold ${phaseKind === "cam" ? "bg-sky-900/60 text-sky-300" : "bg-blue-900/60 text-blue-300"}`}>
                                {phaseKind === "cam" ? "PHASAGE CAMÉRA" : "PHASAGE EEG"}
                            </span>
                        )}
                    </p>
                </div>
            </header>

            {error ? (
                <div className="flex flex-col items-center gap-3 py-24 text-center px-4" data-testid="viewer-error">
                    <AlertCircle className="w-10 h-10 text-red-400" />
                    <p className="text-sm text-slate-300 max-w-xs">{error}</p>
                </div>
            ) : !uploadId ? (
                <ViewerStorePicker stores={stores} onOpen={openStore} />
            ) : !state ? (
                <div className="flex items-center justify-center py-32">
                    <Loader2 className="w-8 h-8 text-purple-400 animate-spin" />
                </div>
            ) : !phaseKind ? (
                <PhaseCategoryPicker state={state} onPick={pickPhase} accent="amber" />
            ) : (
                <>
                    <nav className="fixed bottom-0 inset-x-0 z-40 bg-slate-900/95 backdrop-blur border-t border-slate-800 sm:sticky sm:top-14 sm:bottom-auto sm:border-t-0 sm:border-b sm:bg-slate-900/80">
                        <div className="max-w-3xl mx-auto flex">
                            {TABS.map((t) => {
                                const Icon = t.icon;
                                const active = tab === t.id;
                                return (
                                    <button key={t.id} onClick={() => setTab(t.id)}
                                        data-testid={`viewer-tab-${t.id}`}
                                        className={`flex-1 sm:flex-none sm:px-6 py-2.5 flex flex-col sm:flex-row items-center gap-1 sm:gap-2 text-[11px] sm:text-sm font-medium transition-colors relative
                                            ${active ? "text-purple-300" : "text-slate-500 hover:text-slate-300"}`}>
                                        <Icon className="w-5 h-5 sm:w-4 sm:h-4" />
                                        {t.label}
                                        {active && <span className="absolute bottom-0 inset-x-4 h-0.5 bg-purple-400 rounded-full hidden sm:block" />}
                                    </button>
                                );
                            })}
                        </div>
                    </nav>
                    <main className="max-w-3xl mx-auto px-3 sm:px-6 py-4 pb-24 sm:pb-16">
                        {tab === "dashboard" && <SuiviDashboard state={state} actions={actions} mode="viewer" phaseKind={phaseKind}
                            goTab={(t) => setTab(t === "nuits" ? "pose" : t)} />}
                        {tab === "pose" && phaseKind === "eeg" && <SuiviNuits state={state} actions={actions} mode="viewer" />}
                        {tab === "cam" && phaseKind === "cam" && <SuiviCam state={state} actions={actions} />}
                        {tab === "materiel" && <SuiviMateriel actions={actions} phaseKind={phaseKind} />}
                        {tab === "stock" && <SuiviStock state={state} actions={actions} phaseKind={phaseKind} />}
                        {tab === "plan" && <SuiviFloorplan state={state} actions={actions} phaseKind={phaseKind} readOnly />}
                    </main>
                </>
            )}
        </div>
    );
}

function ViewerStorePicker({ stores, onOpen }) {
    return (
        <main className="max-w-2xl mx-auto px-4 py-8" data-testid="viewer-store-picker">
            <h2 className="text-lg font-bold mb-1">Choisir un magasin</h2>
            <p className="text-sm text-slate-400 mb-5">Sélectionnez un magasin pour consulter le suivi de déploiement en lecture seule.</p>
            {stores === null ? (
                <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 text-purple-400 animate-spin" /></div>
            ) : stores.length === 0 ? (
                <div className="text-center py-16 text-slate-500 text-sm" data-testid="viewer-no-stores">
                    Aucun magasin publié pour le moment.
                </div>
            ) : (
                <div className="space-y-2">
                    {stores.map((s) => (
                        <button key={s.upload_id} onClick={() => onOpen(s.upload_id)}
                            data-testid={`viewer-store-${s.upload_id}`}
                            className="w-full flex items-center gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-purple-500/60 transition-all text-left group">
                            <div className="w-10 h-10 rounded-lg bg-slate-800 flex items-center justify-center flex-shrink-0 group-hover:bg-purple-900/30 transition-colors">
                                <Store className="w-5 h-5 text-purple-400" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-sm font-semibold truncate">
                                    {s.store_name
                                        ? `${s.store_name}${s.store_code ? ` (${s.store_code})` : ""}`
                                        : (s.label || s.filename)}
                                </div>
                                {s.published_by && <div className="text-[11px] text-slate-500">publié par {s.published_by}</div>}
                            </div>
                            <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-purple-400 transition-colors" />
                        </button>
                    ))}
                </div>
            )}
        </main>
    );
}
