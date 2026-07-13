import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useAuth } from "../contexts/AuthContext";
import AuthScreen from "../components/AuthScreen";
import SuiviDashboard from "./SuiviDashboard";
import SuiviNuits from "./SuiviNuits";
import SuiviCam from "./SuiviCam";
import SuiviMateriel from "./SuiviMateriel";
import SuiviStock from "./SuiviStock";
import TerrainApp from "./TerrainApp";
import PhaseCategoryPicker from "./PhaseCategoryPicker";
import { makeActions } from "./api";
import {
    LayoutDashboard, Moon, Package, ChevronLeft, LogOut,
    Loader2, ClipboardList, Store, ChevronRight, Cctv, Boxes,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const LS_KEY = "suivi.lastUploadId";
const LS_PHASE = "suivi.lastPhase";

const TABS_EEG = [
    { id: "dashboard", label: "Tableau de bord", shortLabel: "Board", icon: LayoutDashboard },
    { id: "nuits", label: "Nuits", shortLabel: "Nuits", icon: Moon },
    { id: "materiel", label: "Matériel", shortLabel: "Matériel", icon: Boxes },
    { id: "stock", label: "Stock", shortLabel: "Stock", icon: Package },
];
const TABS_CAM = [
    { id: "dashboard", label: "Tableau de bord", shortLabel: "Board", icon: LayoutDashboard },
    { id: "cam", label: "Caméras", shortLabel: "Cam", icon: Cctv },
    { id: "stock", label: "Stock", shortLabel: "Stock", icon: Package },
];

export default function SuiviApp() {
    // Espace équipe terrain commun : /suivi/terrain — sans compte
    if (window.location.pathname.startsWith("/suivi/terrain")) return <TerrainApp />;
    return <ChefApp />;
}

function ChefApp() {
    const { user, logout } = useAuth();
    const [uploadId, setUploadId] = useState(() => {
        try { return localStorage.getItem(LS_KEY) || null; } catch { return null; }
    });
    const [phaseKind, setPhaseKind] = useState(() => {
        try { return localStorage.getItem(LS_PHASE) || null; } catch { return null; }
    });
    const [sessions, setSessions] = useState(null);
    const [state, setState] = useState(null);
    const [loading, setLoading] = useState(false);
    const [tab, setTab] = useState("dashboard");
    const TABS = phaseKind === "cam" ? TABS_CAM : TABS_EEG;

    const fetchSessions = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/datasets`);
            setSessions(res.data.datasets || []);
        } catch { setSessions([]); }
    }, []);

    const fetchState = useCallback(async (id) => {
        if (!id) return;
        setLoading(true);
        try {
            const res = await axios.get(`${API}/suivi/${id}`);
            setState(res.data);
        } catch (e) {
            toast.error("Impossible de charger le suivi de ce magasin");
            setUploadId(null);
            try { localStorage.removeItem(LS_KEY); } catch { }
        } finally { setLoading(false); }
    }, []);

    useEffect(() => { if (user && user !== false) fetchSessions(); }, [user, fetchSessions]);
    useEffect(() => { if (user && user !== false && uploadId) fetchState(uploadId); }, [user, uploadId, fetchState]);

    const openSession = (id) => {
        setUploadId(id);
        setState(null);
        setPhaseKind(null);
        try { localStorage.setItem(LS_KEY, id); localStorage.removeItem(LS_PHASE); } catch { }
    };
    const closeSession = () => {
        setUploadId(null); setState(null); setTab("dashboard"); setPhaseKind(null);
        try { localStorage.removeItem(LS_KEY); localStorage.removeItem(LS_PHASE); } catch { }
    };
    const pickPhase = (kind) => {
        setPhaseKind(kind);
        setTab("dashboard");
        try { localStorage.setItem(LS_PHASE, kind); } catch { }
    };
    const backToPhasePicker = () => {
        setPhaseKind(null);
        try { localStorage.removeItem(LS_PHASE); } catch { }
    };

    const actions = useMemo(
        () => makeActions(`${API}/suivi/${uploadId}`, () => fetchState(uploadId)),
        [uploadId, fetchState]
    );

    if (user === null) {
        return (
            <div className="min-h-screen bg-slate-950 flex items-center justify-center">
                <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
            </div>
        );
    }
    if (user === false) {
        return (
            <div data-testid="suivi-auth">
                <AuthScreen />
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 antialiased" data-testid="suivi-app">
            <header className="sticky top-0 z-40 h-14 bg-slate-900/90 backdrop-blur border-b border-slate-800 flex items-center justify-between px-4">
                <div className="flex items-center gap-3 min-w-0">
                    {uploadId && (
                        <button onClick={phaseKind ? backToPhasePicker : closeSession} data-testid="suivi-back-btn"
                            className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 transition-colors">
                            <ChevronLeft className="w-5 h-5" />
                        </button>
                    )}
                    <div className="w-8 h-8 rounded-lg bg-emerald-600 flex items-center justify-center flex-shrink-0">
                        <ClipboardList className="w-5 h-5 text-white" />
                    </div>
                    <div className="min-w-0">
                        <h1 className="text-sm font-bold leading-tight truncate" data-testid="suivi-title">Suivi de déploiement</h1>
                        {state && (
                            <p className="text-[11px] text-slate-400 truncate">
                                {state.store_name
                                    ? `${state.store_name}${state.store_code ? ` (${state.store_code})` : ""}`
                                    : state.filename}
                                {phaseKind && (
                                    <span className={`ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold ${phaseKind === "cam" ? "bg-sky-900/60 text-sky-300" : "bg-emerald-900/60 text-emerald-300"}`}>
                                        {phaseKind === "cam" ? "PHASAGE CAMÉRA" : "PHASAGE EEG"}
                                    </span>
                                )}
                            </p>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <a href="/" className="text-[11px] text-slate-400 hover:text-emerald-400 transition-colors hidden sm:block">
                        ← App Phasage
                    </a>
                    <button onClick={logout} data-testid="suivi-logout"
                        className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-red-400 transition-colors">
                        <LogOut className="w-4 h-4" />
                    </button>
                </div>
            </header>

            {!uploadId ? (
                <SessionPicker sessions={sessions} onOpen={openSession} />
            ) : loading || !state ? (
                <div className="flex items-center justify-center py-32">
                    <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
                </div>
            ) : !phaseKind ? (
                <PhaseCategoryPicker state={state} onPick={pickPhase} accent="emerald" />
            ) : (
                <>
                    <nav className="fixed bottom-0 inset-x-0 z-40 bg-slate-900/95 backdrop-blur border-t border-slate-800 sm:sticky sm:top-14 sm:bottom-auto sm:border-t-0 sm:border-b sm:bg-slate-900/80">
                        <div className="max-w-5xl mx-auto flex">
                            {TABS.map((t) => {
                                const Icon = t.icon;
                                const active = tab === t.id;
                                const alertCount = t.id === "stock" ? (state.alerts || []).filter(a => a.type === "rupture").length : 0;
                                return (
                                    <button key={t.id} onClick={() => setTab(t.id)}
                                        data-testid={`suivi-tab-${t.id}`}
                                        className={`flex-1 sm:flex-none sm:px-6 py-2.5 flex flex-col sm:flex-row items-center gap-1 sm:gap-2 text-[11px] sm:text-sm font-medium transition-colors relative
                                            ${active ? "text-emerald-400" : "text-slate-500 hover:text-slate-300"}`}>
                                        <Icon className="w-5 h-5 sm:w-4 sm:h-4" />
                                        <span className="sm:hidden">{t.shortLabel}</span>
                                        <span className="hidden sm:inline">{t.label}</span>
                                        {alertCount > 0 && (
                                            <span className="absolute top-1 right-[calc(50%-22px)] sm:static sm:ml-1 w-4 h-4 rounded-full bg-red-500 text-white text-[9px] flex items-center justify-center font-bold">
                                                {alertCount}
                                            </span>
                                        )}
                                        {active && <span className="absolute bottom-0 inset-x-4 h-0.5 bg-emerald-400 rounded-full hidden sm:block" />}
                                    </button>
                                );
                            })}
                        </div>
                    </nav>
                    <main className="max-w-5xl mx-auto px-3 sm:px-6 pt-4 pb-24 sm:pb-10">
                        {tab === "dashboard" && <SuiviDashboard state={state} actions={actions} goTab={setTab} phaseKind={phaseKind} />}
                        {tab === "nuits" && phaseKind === "eeg" && <SuiviNuits state={state} actions={actions} mode="chef" />}
                        {tab === "cam" && phaseKind === "cam" && <SuiviCam state={state} actions={actions} />}
                        {tab === "materiel" && phaseKind === "eeg" && <SuiviMateriel actions={actions} />}
                        {tab === "stock" && <SuiviStock state={state} actions={actions} phaseKind={phaseKind} />}
                    </main>
                </>
            )}
        </div>
    );
}

function SessionPicker({ sessions, onOpen }) {
    return (
        <main className="max-w-2xl mx-auto px-4 py-8" data-testid="suivi-session-picker">
            <h2 className="text-lg font-bold mb-1">Choisir un magasin</h2>
            <p className="text-sm text-slate-400 mb-5">Le suivi reprend automatiquement le phasage validé de la session.</p>
            {sessions === null ? (
                <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 text-emerald-400 animate-spin" /></div>
            ) : sessions.length === 0 ? (
                <div className="text-center py-16 text-slate-500 text-sm">
                    Aucune session. Créez d'abord un phasage dans l'<a href="/" className="text-emerald-400 underline">app Phasage</a>.
                </div>
            ) : (
                <div className="space-y-2">
                    {sessions.map((s) => (
                        <button key={s.upload_id} onClick={() => onOpen(s.upload_id)}
                            data-testid={`suivi-session-${s.upload_id}`}
                            className="w-full flex items-center gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-emerald-600/60 hover:bg-slate-900/60 transition-all text-left group">
                            <div className="w-10 h-10 rounded-lg bg-slate-800 flex items-center justify-center flex-shrink-0 group-hover:bg-emerald-900/40 transition-colors">
                                <Store className="w-5 h-5 text-emerald-400" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-sm font-semibold truncate">{s.label || s.filename}</div>
                                <div className="text-[11px] text-slate-500">
                                    {s.row_count?.toLocaleString("fr-FR")} lignes · {s.uploaded_at ? new Date(s.uploaded_at).toLocaleDateString("fr-FR") : ""}
                                </div>
                            </div>
                            <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-emerald-400 transition-colors" />
                        </button>
                    ))}
                </div>
            )}
        </main>
    );
}
