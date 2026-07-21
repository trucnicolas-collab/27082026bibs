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
import SuiviFloorplan from "./SuiviFloorplan";
import TerrainApp from "./TerrainApp";
import PhaseCategoryPicker from "./PhaseCategoryPicker";
import { makeActions } from "./api";
import {
    LayoutDashboard, Moon, Package, ChevronLeft, LogOut,
    Loader2, ClipboardList, Store, ChevronRight, Cctv, Boxes,
    Eye, Copy, X, MapPin,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const LS_KEY = "suivi.lastUploadId";
const LS_PHASE = "suivi.lastPhase";

const TABS_EEG = [
    { id: "dashboard", label: "Tableau de bord", shortLabel: "Board", icon: LayoutDashboard },
    { id: "nuits", label: "Nuits", shortLabel: "Nuits", icon: Moon },
    { id: "plan", label: "Plan", shortLabel: "Plan", icon: MapPin },
    { id: "materiel", label: "Matériel", shortLabel: "Matériel", icon: Boxes },
    { id: "stock", label: "Stock", shortLabel: "Stock", icon: Package },
];
const TABS_CAM = [
    { id: "dashboard", label: "Tableau de bord", shortLabel: "Board", icon: LayoutDashboard },
    { id: "cam", label: "Caméras", shortLabel: "Cam", icon: Cctv },
    { id: "plan", label: "Plan", shortLabel: "Plan", icon: MapPin },
    { id: "materiel", label: "Matériel", shortLabel: "Matériel", icon: Boxes },
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

    const fetchState = useCallback(async (id, { silent = false } = {}) => {
        if (!id) return;
        if (!silent) setLoading(true);
        try {
            const res = await axios.get(`${API}/suivi/${id}`);
            setState(res.data);
        } catch (e) {
            toast.error("Impossible de charger le suivi de ce magasin");
            setUploadId(null);
            try { localStorage.removeItem(LS_KEY); } catch { /* ignore */ }
        } finally { if (!silent) setLoading(false); }
    }, []);

    useEffect(() => { if (user && user !== false) fetchSessions(); }, [user, fetchSessions]);
    useEffect(() => { if (user && user !== false && uploadId) fetchState(uploadId); }, [user, uploadId, fetchState]);

    const openSession = (id) => {
        setUploadId(id);
        setState(null);
        setPhaseKind(null);
        try { localStorage.setItem(LS_KEY, id); localStorage.removeItem(LS_PHASE); } catch { /* ignore */ }
    };
    const closeSession = () => {
        setUploadId(null); setState(null); setTab("dashboard"); setPhaseKind(null);
        try { localStorage.removeItem(LS_KEY); localStorage.removeItem(LS_PHASE); } catch { /* ignore */ }
    };
    const pickPhase = (kind) => {
        setPhaseKind(kind);
        setTab("dashboard");
        try { localStorage.setItem(LS_PHASE, kind); } catch { /* ignore */ }
    };
    const backToPhasePicker = () => {
        setPhaseKind(null);
        try { localStorage.removeItem(LS_PHASE); } catch { /* ignore */ }
    };

    // (iter32) Refresh silencieux après chaque patch — évite le remount complet
    // de <SuiviNuits>/<SuiviStock>/<AlleeScreen> qui perdait la sélection de
    // nuit + le scroll à chaque saisie de champ.
    const actions = useMemo(
        () => makeActions(`${API}/suivi/${uploadId}`, () => fetchState(uploadId, { silent: true })),
        [uploadId, fetchState]
    );

    if (user === null) {
        return (
            <div className="min-h-screen bg-slate-950 flex items-center justify-center">
                <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
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
                    <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0">
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
                                    <span className={`ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold ${phaseKind === "cam" ? "bg-sky-900/60 text-sky-300" : "bg-blue-900/60 text-blue-300"}`}>
                                        {phaseKind === "cam" ? "PHASAGE CAMÉRA" : "PHASAGE EEG"}
                                    </span>
                                )}
                            </p>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <ViewerLinkButton />
                    <a href="/" className="text-[11px] text-slate-400 hover:text-blue-400 transition-colors hidden sm:block">
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
                    <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
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
                                            ${active ? "text-blue-400" : "text-slate-500 hover:text-slate-300"}`}>
                                        <Icon className="w-5 h-5 sm:w-4 sm:h-4" />
                                        <span className="sm:hidden">{t.shortLabel}</span>
                                        <span className="hidden sm:inline">{t.label}</span>
                                        {alertCount > 0 && (
                                            <span className="absolute top-1 right-[calc(50%-22px)] sm:static sm:ml-1 w-4 h-4 rounded-full bg-red-500 text-white text-[9px] flex items-center justify-center font-bold">
                                                {alertCount}
                                            </span>
                                        )}
                                        {active && <span className="absolute bottom-0 inset-x-4 h-0.5 bg-blue-400 rounded-full hidden sm:block" />}
                                    </button>
                                );
                            })}
                        </div>
                    </nav>
                    <main className={`${tab === "plan" ? "max-w-[1600px]" : "max-w-5xl"} mx-auto px-3 sm:px-6 pt-4 pb-24 sm:pb-10`}>
                        {tab === "dashboard" && <SuiviDashboard state={state} actions={actions} goTab={setTab} phaseKind={phaseKind} />}
                        {tab === "nuits" && phaseKind === "eeg" && <SuiviNuits state={state} actions={actions} mode="chef" />}
                        {tab === "cam" && phaseKind === "cam" && <SuiviCam state={state} actions={actions} />}
                        {tab === "materiel" && <SuiviMateriel actions={actions} phaseKind={phaseKind} />}
                        {tab === "stock" && <SuiviStock state={state} actions={actions} phaseKind={phaseKind} />}
                        {tab === "plan" && <SuiviFloorplan state={state} actions={actions} phaseKind={phaseKind} />}
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
                <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 text-blue-400 animate-spin" /></div>
            ) : sessions.length === 0 ? (
                <div className="text-center py-16 text-slate-500 text-sm">
                    Aucune session. Créez d'abord un phasage dans l'<a href="/" className="text-blue-400 underline">app Phasage</a>.
                </div>
            ) : (
                <div className="space-y-2">
                    {sessions.map((s) => (
                        <button key={s.upload_id} onClick={() => onOpen(s.upload_id)}
                            data-testid={`suivi-session-${s.upload_id}`}
                            className="w-full flex items-center gap-3 p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-blue-600/60 hover:bg-slate-900/60 transition-all text-left group">
                            <div className="w-10 h-10 rounded-lg bg-slate-800 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-900/40 transition-colors">
                                <Store className="w-5 h-5 text-blue-400" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-sm font-semibold truncate">{s.label || s.filename}</div>
                                <div className="text-[11px] text-slate-500">
                                    {s.row_count?.toLocaleString("fr-FR")} lignes · {s.uploaded_at ? new Date(s.uploaded_at).toLocaleDateString("fr-FR") : ""}
                                </div>
                            </div>
                            <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-blue-400 transition-colors" />
                        </button>
                    ))}
                </div>
            )}
        </main>
    );
}

// Bouton discret dans le header : affiche le lien de partage client (Lecture Seule)
// dans une modale. PAS de bouton Régénérer côté UI pour éviter toute casse
// accidentelle du lien envoyé aux clients (le seul moyen de le régénérer est
// désormais un appel API direct côté admin).
function ViewerLinkButton() {
    const [open, setOpen] = React.useState(false);
    const [token, setToken] = React.useState(null);
    const link = token ? `${window.location.origin}/suivi/view?token=${token}` : "";

    const openModal = async () => {
        setOpen(true);
        if (token !== null) return;
        try {
            const res = await axios.get(`${API}/suivi/viewer-link`);
            setToken(res.data?.token || "");
        } catch { setToken(""); }
    };
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(link);
            toast.success("Lien copié — envoyez-le à vos clients");
        } catch { toast.error("Copie impossible"); }
    };

    return (
        <>
            <button onClick={openModal} data-testid="viewer-link-open"
                title="Voir le lien de partage client (lecture seule)"
                className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-purple-300 transition-colors">
                <Eye className="w-4 h-4" />
            </button>
            {open && (
                <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
                    data-testid="viewer-link-modal" onClick={() => setOpen(false)}>
                    <div className="w-full max-w-lg rounded-2xl bg-slate-900 border border-purple-800/50 p-5 shadow-2xl space-y-3"
                        onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-2">
                            <div className="w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
                                <Eye className="w-4 h-4 text-purple-400" />
                            </div>
                            <h3 className="text-sm font-bold flex-1">Lien de partage client — Lecture seule</h3>
                            <button onClick={() => setOpen(false)} data-testid="viewer-link-close"
                                className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400">
                                <X className="w-4 h-4" />
                            </button>
                        </div>
                        <p className="text-xs text-slate-400 leading-relaxed">
                            Un lien <b className="text-slate-200">unique et permanent</b> à partager à vos clients.
                            Ils voient tous les magasins <b className="text-slate-200">publiés</b> en Lecture Seule, sans pouvoir modifier quoi que ce soit.
                            Publier ou dépublier un magasin met à jour la liste automatiquement — le lien lui-même ne change jamais.
                        </p>
                        <div className="rounded-lg bg-slate-950 border border-purple-800/40 px-3 py-2.5"
                            data-testid="viewer-link-box">
                            {token === null ? (
                                <div className="text-[11px] text-slate-500 italic">Chargement du lien...</div>
                            ) : !token ? (
                                <div className="text-[11px] text-red-400">
                                    Lien indisponible — connectez-vous en admin puis rouvrez cette fenêtre.
                                </div>
                            ) : (
                                <code className="text-[11px] text-purple-300 break-all select-all leading-relaxed block"
                                    data-testid="viewer-link-url">
                                    {link}
                                </code>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            <button onClick={copy} disabled={!token} data-testid="viewer-link-copy"
                                className="flex-1 h-9 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-40">
                                <Copy className="w-3.5 h-3.5" /> Copier le lien
                            </button>
                            {token && (
                                <a href={link} target="_blank" rel="noreferrer" data-testid="viewer-link-open-tab"
                                    className="h-9 px-3 rounded-lg border border-purple-800 text-purple-300 hover:bg-purple-950/40 text-xs font-semibold flex items-center gap-1.5 transition-colors">
                                    Tester
                                </a>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}

