import React, { useState, useMemo, useCallback, useEffect } from "react";
import axios from "axios";
import { Toaster, toast } from "sonner";
import UploadZone from "./components/UploadZone";
import Header from "./components/Header";
import WizardSteps from "./components/WizardSteps";
import BlockingModal from "./components/BlockingModal";
import RawTable from "./components/RawTable";
import RecapTable from "./components/RecapTable";
import ParSecteurTable from "./components/ParSecteurTable";
import CommentTab from "./components/CommentTab";
import PhasageTab from "./components/PhasageTab";
import PhasageCamTab from "./components/PhasageCamTab";
import SuiviPhasageTab from "./components/SuiviPhasageTab";
import AutreTab from "./components/AutreTab";
import TableauDateTab from "./components/TableauDateTab";
import AuthScreen from "./components/AuthScreen";
import LoadingState from "./components/LoadingState";
import ForgotPasswordScreen from "./components/ForgotPasswordScreen";
import ResetPasswordScreen from "./components/ResetPasswordScreen";
import SharedView from "./components/SharedView";
import SuiviApp from "./suivi/SuiviApp";
import { useAuth } from "./contexts/AuthContext";
import { Loader2 } from "lucide-react";
import "./App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const LS_KEY = "eeg.lastUploadId";

// Lit les paramètres d'URL au montage (très simple, pas besoin de router)
function getUrlParam(name) {
    try {
        return new URLSearchParams(window.location.search).get(name);
    } catch {
        return null;
    }
}

// Router racine : aiguillage simple par query string
//  ?share=token     → SharedView (lecture seule, sans auth)
//  ?reset=token     → ResetPasswordScreen
//  sinon            → MainApp (gateé par auth)
export default function App() {
    // App séparée « Suivi de déploiement » sur /suivi
    if (window.location.pathname.startsWith("/suivi")) {
        return (
            <>
                <Toaster position="top-center" richColors closeButton expand visibleToasts={5} theme="dark" />
                <SuiviApp />
            </>
        );
    }
    const shareToken = getUrlParam("share");
    const resetTokenParam = getUrlParam("reset") || getUrlParam("token");

    if (shareToken) {
        return (
            <>
                <Toaster position="top-center" richColors closeButton expand visibleToasts={5} />
                <SharedView token={shareToken} />
            </>
        );
    }
    if (resetTokenParam) {
        return (
            <>
                <Toaster position="top-center" richColors closeButton expand visibleToasts={5} />
                <ResetPasswordScreen
                    token={resetTokenParam}
                    onSuccess={() => { window.location.href = "/"; }}
                />
            </>
        );
    }
    return <MainApp />;
}

// Configuration du parcours guidé (6 étapes)
const WIZARD_STEPS = [
    { n: 1, key: "import", label: "Import" },
    { n: 2, key: "commande", label: "Commande" },
    { n: 3, key: "phasage", label: "Phasage" },
    { n: 4, key: "phasage_cam", label: "Phasage caméras" },
    { n: 5, key: "dates", label: "Dates" },
    { n: 6, key: "export", label: "Export" },
];

// Sous-onglets disponibles pour chaque étape (selon le dataset)
function stepSubTabs(step, dataset) {
    if (!dataset) return [];
    switch (step) {
        case 1:
            return [
                { id: "import_home", label: "Fichier" },
                { id: "raw", label: "Données brutes", count: dataset.row_count || 0 },
            ];
        case 2: {
            const t = [{ id: "recap", label: "Commandes", count: dataset.data.recap.length }];
            if (dataset.has_autre) t.push({ id: "autre", label: "Autre", count: dataset.autre_count || 0 });
            t.push({ id: "parsecteur", label: "Recap par secteur" });
            return t;
        }
        case 3:
            return [
                { id: "pose", label: "Phasage de pose" },
            ];
        case 4:
            return [
                { id: "pose_cam", label: "Phasage caméras" },
            ];
        case 5:
            return [
                { id: "tableau_date", label: "Tableau date" },
                { id: "suivi", label: "Suivi phasage" },
            ];
        case 6:
            return [
                { id: "export_home", label: "Exports" },
                { id: "comment", label: "Commentaire" },
            ];
        default:
            return [];
    }
}

function MainApp() {
    const { user, logout } = useAuth();
    const [dataset, setDataset] = useState(null);
    const [phasageVersion, setPhasageVersion] = useState(0);
    const [activeTab, setActiveTab] = useState("import_home");
    const [currentStep, setCurrentStep] = useState(1);
    const [showBlocking, setShowBlocking] = useState(false);
    const [blockingIssues, setBlockingIssues] = useState([]);
    const [validatingStep2, setValidatingStep2] = useState(false);
    const [wizardStatus, setWizardStatus] = useState({ step3_ready: false, step4_ready: false });
    const [search, setSearch] = useState("");
    const [loading, setLoading] = useState(false);
    const [rawLoading, setRawLoading] = useState(false);
    const [restoring, setRestoring] = useState(true);
    const [authView, setAuthView] = useState("login"); // 'login' | 'forgot'

    // Charge un dataset par son upload_id (utilisé par auto-restore et menu Sessions)
    const loadDataset = useCallback(async (uploadId, { silent = false } = {}) => {
        try {
            const res = await axios.get(`${API}/dataset/${uploadId}`);
            const d = res.data;
            const ds = {
                upload_id: d.upload_id,
                filename: d.filename,
                row_count: d.row_count,
                columns: d.columns,
                surface_category: d.surface_category || null,
                dongles_quantity: d.dongles_quantity || 0,
                has_autre: !!d.has_autre,
                autre_count: d.autre_count || 0,
                data: { ...d.data, raw: null },
            };
            setDataset(ds);
            setActiveTab("import_home");
            setCurrentStep(1);
            setSearch("");
            try { localStorage.setItem(LS_KEY, uploadId); } catch (_) {}
            if (!silent) {
                toast.success(`Session restaurée : ${d.filename}`);
            }
            return true;
        } catch (err) {
            if (err.response?.status === 404) {
                try { localStorage.removeItem(LS_KEY); } catch (_) {}
                if (!silent) toast.error("Cette session n'existe plus sur le serveur.");
            } else if (!silent) {
                toast.error(`Erreur de chargement : ${err.message}`);
            }
            return false;
        }
    }, []);

    // Auto-restauration au montage de l'app (après login)
    useEffect(() => {
        // Attend que l'auth soit résolue (user === null = checking)
        if (user === null) return;
        if (!user) {
            // Pas connecté : on ne tente pas de restaurer
            setRestoring(false);
            setDataset(null);
            return;
        }
        const lastId = (() => { try { return localStorage.getItem(LS_KEY); } catch { return null; } })();
        if (!lastId) {
            setRestoring(false);
            return;
        }
        (async () => {
            setRestoring(true);
            await loadDataset(lastId, { silent: false });
            setRestoring(false);
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [user]);

    const handleUpload = useCallback(async (file) => {
        setLoading(true);
        const formData = new FormData();
        formData.append("file", file);
        try {
            const res = await axios.post(`${API}/upload-excel`, formData, {
                headers: { "Content-Type": "multipart/form-data" },
                timeout: 300000,  // 5 min pour gros fichiers
            });
            const ds = {
                ...res.data,
                data: { ...res.data.data, raw: null },
            };
            setDataset(ds);
            setActiveTab("import_home");
            setCurrentStep(1);
            try { localStorage.setItem(LS_KEY, res.data.upload_id); } catch (_) {}
            toast.success(`Fichier traité : ${res.data.row_count.toLocaleString("fr-FR")} lignes`);
            // Contrôle de cohérence : toasts empilés pour chaque anomalie
            const warns = res.data.coherence_warnings || [];
            for (const w of warns) {
                const opts = { description: w.message, duration: 8000 };
                if (w.level === "error") toast.error("⚠ Anomalie détectée", opts);
                else if (w.level === "warning") toast.warning("Cohérence — attention", opts);
                else toast.info("Cohérence", opts);
            }
        } catch (err) {
            const msg = err.response?.data?.detail || err.message;
            toast.error(`Erreur : ${msg}`);
        } finally {
            setLoading(false);
        }
    }, []);

    const ensureRawLoaded = useCallback(async () => {
        if (!dataset?.upload_id) return;
        if (dataset.data.raw !== null) return;  // déjà chargé
        if (rawLoading) return;
        setRawLoading(true);
        try {
            const res = await axios.get(`${API}/dataset/${dataset.upload_id}/raw`, {
                timeout: 300000,
            });
            setDataset((d) => ({
                ...d,
                data: { ...d.data, raw: res.data.raw },
            }));
        } catch (err) {
            toast.error(`Impossible de charger les données brutes : ${err.message}`);
        } finally {
            setRawLoading(false);
        }
    }, [dataset, rawLoading]);

    const [exportingRTR, setExportingRTR] = useState(false);
    const [exportingCarrefour, setExportingCarrefour] = useState(false);
    const [exportingPPTX, setExportingPPTX] = useState(false);

    // Base du nom de fichier des exports : "Export {store} ({code}) DD-MM-YYYY HH-MM"
    // Aligné strictement sur le backend (server.py::_export_basename).
    const exportBase = useCallback(() => {
        const name = (dataset?.store_name || "").trim();
        const code = (dataset?.store_code || "").trim();
        let store;
        if (name && code) store = `${name} (${code})`;
        else if (name) store = name;
        else {
            const stem = (dataset?.filename || "export").replace(/\.xlsx?$/i, "");
            store = stem.replace(/\s+\d{2}-\d{2}-\d{4}\s+\d{2}[-h:]\d{2}(?:\s+\S+@\S+)?\s*$/, "").trim() || "export";
        }
        const d = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        const stamp = `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()} ${pad(d.getHours())}-${pad(d.getMinutes())}`;
        return `Export ${store} ${stamp}`;
    }, [dataset]);

    const handleExport = useCallback(async () => {
        if (!dataset?.upload_id || exportingRTR) return;
        setExportingRTR(true);
        try {
            toast.loading("Génération de l'export RTR…", { id: "rtr-export" });
            const res = await axios.get(`${API}/export/${dataset.upload_id}?sheet=all`, {
                responseType: "blob",
                timeout: 180000,
            });
            const url = window.URL.createObjectURL(new Blob([res.data]));
            const link = document.createElement("a");
            link.href = url;
            link.setAttribute("download", `${exportBase()}_RTR.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            toast.success("Export RTR téléchargé", { id: "rtr-export" });
        } catch (err) {
            const msg = err.response?.data?.detail || err.message;
            toast.error(`Erreur d'export : ${msg}`, { id: "rtr-export" });
        } finally {
            setExportingRTR(false);
        }
    }, [dataset, exportingRTR, exportBase]);

    const handleExportCarrefour = useCallback(async () => {
        if (!dataset?.upload_id || exportingCarrefour) return;
        setExportingCarrefour(true);
        try {
            toast.loading("Génération de l'export Carrefour…", { id: "carrefour-export" });
            const res = await axios.get(`${API}/export-carrefour/${dataset.upload_id}`, {
                responseType: "blob",
                timeout: 120000,
            });
            const url = window.URL.createObjectURL(new Blob([res.data]));
            const link = document.createElement("a");
            link.href = url;
            link.setAttribute("download", `${exportBase()}_Carrefour.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            toast.success("Export Carrefour téléchargé", { id: "carrefour-export" });
        } catch (err) {
            const msg = err.response?.data?.detail || err.message;
            toast.error(`Erreur d'export Carrefour : ${msg}`, { id: "carrefour-export" });
        } finally {
            setExportingCarrefour(false);
        }
    }, [dataset, exportingCarrefour, exportBase]);

    const handleExportPPTX = useCallback(async () => {
        if (!dataset?.upload_id || exportingPPTX) return;
        setExportingPPTX(true);
        try {
            toast.loading("Génération du PowerPoint…", { id: "pptx-export" });
            const res = await axios.get(`${API}/export-pptx/${dataset.upload_id}`, {
                responseType: "blob",
                timeout: 240000,
            });
            const url = window.URL.createObjectURL(new Blob([res.data]));
            const link = document.createElement("a");
            link.href = url;
            link.setAttribute("download", `${exportBase()}_CR_VT.pptx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            // Affiche la version PPTX dans le toast pour vérifier que le backend
            // exécute bien le dernier code après un (re)déploiement.
            const pptxVersion = res.headers?.["x-pptx-version"] || "?";
            toast.success(`PowerPoint téléchargé (backend ${pptxVersion})`, { id: "pptx-export" });
        } catch (err) {
            const msg = err.response?.data?.detail || err.message;
            toast.error(`Erreur export PowerPoint : ${msg}`, { id: "pptx-export" });
        } finally {
            setExportingPPTX(false);
        }
    }, [dataset, exportingPPTX, exportBase]);

    const handleReset = useCallback(() => {
        setDataset(null);
        setSearch("");
        setActiveTab("import_home");
        setCurrentStep(1);
        try { localStorage.removeItem(LS_KEY); } catch (_) {}
    }, []);

    const handleOpenSession = useCallback(async (uploadId) => {
        await loadDataset(uploadId, { silent: false });
    }, [loadDataset]);

    const handlePhasageRestored = useCallback(async () => {
        if (dataset?.upload_id) {
            // Force le remount des onglets Phasage pour qu'ils re-fetch le summary
            setPhasageVersion((v) => v + 1);
        }
    }, [dataset]);

    const handleDeletedSession = useCallback((uploadId) => {
        // Si on a supprimé la session active, on revient à l'écran d'upload
        if (dataset?.upload_id === uploadId) {
            setDataset(null);
            setSearch("");
            setActiveTab("import_home");
            setCurrentStep(1);
            try { localStorage.removeItem(LS_KEY); } catch (_) {}
        }
    }, [dataset]);

    const updateRecapRow = useCallback(async (index, patch) => {
        if (!dataset?.upload_id) return;
        // Optimistic update
        const prev = dataset.data.recap[index];
        const optimistic = { ...prev, ...patch };
        // Détermine kind localement
        const isEmpty =
            !optimistic.type &&
            !optimistic.reference &&
            !optimistic.designation &&
            (optimistic.quantite === "" || optimistic.quantite === 0 || optimistic.quantite === null);
        optimistic.kind = isEmpty ? "empty" : "manual";

        setDataset((d) => {
            const next = { ...d, data: { ...d.data, recap: [...d.data.recap] } };
            next.data.recap[index] = optimistic;
            return next;
        });

        try {
            const res = await axios.patch(`${API}/dataset/${dataset.upload_id}/recap-row/${index}`, patch);
            setDataset((d) => {
                const next = { ...d, data: { ...d.data, recap: [...d.data.recap] } };
                next.data.recap[index] = res.data.row;
                // Si le backend renvoie un récap complet (suite au recalcul VCare),
                // on le réutilise pour refléter le nouveau bloc VCare en temps réel.
                if (Array.isArray(res.data.rows)) {
                    next.data.recap = res.data.rows;
                }
                return next;
            });
        } catch (err) {
            // Rollback
            setDataset((d) => {
                const next = { ...d, data: { ...d.data, recap: [...d.data.recap] } };
                next.data.recap[index] = prev;
                return next;
            });
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        }
    }, [dataset]);

    const addRecapRow = useCallback(async () => {
        if (!dataset?.upload_id) return;
        try {
            const res = await axios.post(`${API}/dataset/${dataset.upload_id}/recap-row`);
            setDataset((d) => ({
                ...d,
                data: { ...d.data, recap: [...d.data.recap, res.data.row] },
            }));
            toast.success("Ligne ajoutée");
        } catch (err) {
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        }
    }, [dataset]);

    const deleteRecapRow = useCallback(async (index) => {
        if (!dataset?.upload_id) return;
        const prev = dataset.data.recap[index];
        // Optimistic remove
        setDataset((d) => {
            const next = { ...d, data: { ...d.data, recap: [...d.data.recap] } };
            next.data.recap.splice(index, 1);
            return next;
        });
        try {
            await axios.delete(`${API}/dataset/${dataset.upload_id}/recap-row/${index}`);
        } catch (err) {
            // Rollback
            setDataset((d) => {
                const next = { ...d, data: { ...d.data, recap: [...d.data.recap] } };
                next.data.recap.splice(index, 0, prev);
                return next;
            });
            toast.error(`Erreur : ${err.response?.data?.detail || err.message}`);
        }
    }, [dataset]);

    const updateComment = useCallback(async (table) => {
        if (!dataset?.upload_id) return;
        setDataset((d) => ({ ...d, data: { ...d.data, comment_table: table } }));
        try {
            await axios.patch(`${API}/dataset/${dataset.upload_id}/comment-table`, table);
        } catch (err) {
            toast.error(`Sauvegarde commentaire échouée : ${err.message}`);
        }
    }, [dataset]);

    const updateSurfaceCategory = useCallback(async (cat) => {
        if (!dataset?.upload_id) return;
        try {
            const res = await axios.patch(`${API}/dataset/${dataset.upload_id}/surface`, { category: cat });
            setDataset((d) => ({
                ...d,
                surface_category: res.data.category,
                data: { ...d.data, recap: res.data.rows },
            }));
        } catch (err) {
            toast.error(`Surface : ${err.response?.data?.detail || err.message}`);
        }
    }, [dataset]);

    const updateDonglesQuantity = useCallback(async (qty) => {
        if (!dataset?.upload_id) return;
        try {
            const res = await axios.patch(`${API}/dataset/${dataset.upload_id}/dongles`, { quantity: qty });
            setDataset((d) => ({
                ...d,
                dongles_quantity: res.data.quantity,
                data: { ...d.data, recap: res.data.rows },
            }));
        } catch (err) {
            toast.error(`Dongles : ${err.response?.data?.detail || err.message}`);
        }
    }, [dataset]);

    const subTabs = useMemo(() => stepSubTabs(currentStep, dataset), [currentStep, dataset]);

    // État "Étape 2 complète" calculé en direct (surface + dongles + refs valides),
    // pour informer l'utilisateur avant de cliquer « Suivant ». Miroir de la logique
    // backend /step2-validation (kinds système exclus, désignation vide ignorée).
    const step2Ready = useMemo(() => {
        const recap = dataset?.data?.recap || [];
        const surfaceOk = ["plus_10000", "moins_10000"].includes(dataset?.surface_category);
        const donglesOk = (dataset?.dongles_quantity || 0) > 0;
        const hasBadRef = recap.some((r) => {
            if (["section", "header", "empty", "surface_added", "dongle", "bonus"].includes(r.kind)) return false;
            const desig = String(r.designation || "").trim();
            if (!desig) return false;
            const ref = String(r.reference || "").trim();
            return !ref || !/^\d+$/.test(ref);
        });
        return surfaceOk && donglesOk && !hasBadRef;
    }, [dataset]);

    // Statut des étapes 3 (Phasage) et 4 (Dates) — récupéré côté backend
    // (les données phasage/dates ne sont pas chargées dans le state front).
    const refreshWizardStatus = useCallback(async () => {
        if (!dataset?.upload_id) return;
        try {
            const res = await axios.get(`${API}/dataset/${dataset.upload_id}/wizard-status`, {
                params: { _t: Date.now() },
            });
            setWizardStatus(res.data || { step3_ready: false, step4_ready: false });
        } catch (_) { /* silencieux : badge non affiché en cas d'échec */ }
    }, [dataset]);

    // Rafraîchit le statut à chaque changement d'onglet/étape (les éditions de
    // phasage/dates sont auto-sauvegardées côté backend → statut à jour à la nav).
    useEffect(() => {
        refreshWizardStatus();
    }, [refreshWizardStatus, activeTab, currentStep, phasageVersion]);

    const applyStep = useCallback((target) => {
        const subs = stepSubTabs(target, dataset);
        const first = subs[0]?.id;
        setCurrentStep(target);
        if (first) setActiveTab(first);
        if (first === "raw" || first === "parsecteur") ensureRawLoaded();
    }, [dataset, ensureRawLoaded]);

    const validateStep2 = useCallback(async () => {
        if (!dataset?.upload_id) return false;
        setValidatingStep2(true);
        try {
            const res = await axios.get(`${API}/dataset/${dataset.upload_id}/step2-validation`, {
                headers: { "Cache-Control": "no-cache" },
                params: { _t: Date.now() },
            });
            if (res.data.ok) return true;
            setBlockingIssues(res.data.issues || []);
            setShowBlocking(true);
            return false;
        } catch (err) {
            toast.error(`Validation impossible : ${err.response?.data?.detail || err.message}`);
            return false;
        } finally {
            setValidatingStep2(false);
        }
    }, [dataset]);

    // Navigation vers une étape : bloque le passage vers l'étape 3+ tant que
    // l'étape 2 (Commande) n'est pas valide (lignes Autre traitées, surface, dongles).
    const goToStep = useCallback(async (target) => {
        if (!dataset || target === currentStep) return;
        if (target >= 3 && currentStep <= 2) {
            const ok = await validateStep2();
            if (!ok) return;
        }
        applyStep(target);
    }, [dataset, currentStep, validateStep2, applyStep]);

    const handleNext = useCallback(() => {
        if (currentStep < WIZARD_STEPS.length) goToStep(currentStep + 1);
    }, [currentStep, goToStep]);

    const handlePrev = useCallback(() => {
        if (currentStep > 1) applyStep(currentStep - 1);
    }, [currentStep, applyStep]);

    const onSubTab = useCallback((id) => {
        setActiveTab(id);
        if (id === "raw" || id === "parsecteur") ensureRawLoaded();
    }, [ensureRawLoaded]);

    return (
        <div className="app-root" data-testid="app-root">
            <Toaster position="top-center" richColors closeButton expand visibleToasts={5} />
            {user === null ? (
                <div className="min-h-screen flex items-center justify-center text-gray-500" data-testid="auth-loading">
                    <Loader2 className="w-5 h-5 animate-spin mr-2" /> Chargement…
                </div>
            ) : !user ? (
                authView === "forgot" ? (
                    <ForgotPasswordScreen onBack={() => setAuthView("login")} />
                ) : (
                    <AuthScreen onForgotPassword={() => setAuthView("forgot")} />
                )
            ) : (
                <>
                    <Header
                        dataset={dataset}
                        search={search}
                        onSearchChange={setSearch}
                        onExport={handleExport}
                        onExportCarrefour={handleExportCarrefour}
                        onExportPPTX={handleExportPPTX}
                        exportingRTR={exportingRTR}
                        exportingCarrefour={exportingCarrefour}
                        exportingPPTX={exportingPPTX}
                        onReset={handleReset}
                        onOpenSession={handleOpenSession}
                        onDeletedSession={handleDeletedSession}
                        onPhasageRestored={handlePhasageRestored}
                        user={user}
                        onLogout={logout}
                    />

                    <main className="flex-1 overflow-hidden flex flex-col">
                        {restoring ? (
                            <LoadingState message="Restauration de la session précédente…" testId="session-restoring" />
                        ) : !dataset ? (
                            <UploadZone onUpload={handleUpload} loading={loading} />
                        ) : (
                    <>
                        <WizardSteps
                            steps={WIZARD_STEPS}
                            current={currentStep}
                            onGoStep={goToStep}
                            step2Ready={step2Ready}
                            step3Ready={wizardStatus.step3_ready}
                            step4Ready={wizardStatus.step4_ready}
                            subTabs={subTabs}
                            activeSubTab={activeTab}
                            onSubTab={onSubTab}
                            onPrev={handlePrev}
                            onNext={handleNext}
                            prevDisabled={currentStep <= 1}
                            nextDisabled={currentStep >= WIZARD_STEPS.length || validatingStep2}
                            nextLabel={currentStep === 2 ? "Valider et continuer" : "Suivant"}
                            nextLoading={validatingStep2}
                        />
                        <div key={activeTab} className="flex-1 overflow-hidden eeg-fade-in">
                            {activeTab === "import_home" && (
                                <div className="p-6 overflow-auto h-full">
                                    <div className="max-w-3xl mx-auto space-y-4">
                                        <div className="border border-gray-200 rounded-lg bg-white p-4">
                                            <h3 className="text-sm font-semibold text-gray-800 mb-2">Fichier importé</h3>
                                            <div className="text-sm text-gray-600 space-y-0.5">
                                                <div><span className="text-gray-400">Nom : </span>{dataset.filename}</div>
                                                <div><span className="text-gray-400">Lignes : </span>{(dataset.row_count || 0).toLocaleString("fr-FR")}</div>
                                            </div>
                                            <button onClick={handleReset} className="mt-3 text-xs text-gray-500 underline hover:text-gray-700" data-testid="import-reset">
                                                Importer un autre fichier
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )}
                            {activeTab === "raw" && (
                                dataset.data.raw === null || rawLoading ? (
                                    <LoadingState message={`Chargement des ${(dataset.row_count || 0).toLocaleString("fr-FR")} lignes brutes…`} testId="raw-loading" />
                                ) : (
                                    <RawTable
                                        rows={dataset.data.raw}
                                        columns={dataset.columns}
                                        search={search}
                                    />
                                )
                            )}
                            {activeTab === "recap" && (
                                <RecapTable
                                    rows={dataset.data.recap}
                                    search={search}
                                    onUpdateRow={updateRecapRow}
                                    onAddRow={addRecapRow}
                                    onDeleteRow={deleteRecapRow}
                                    surfaceCategory={dataset.surface_category || null}
                                    onSurfaceChange={updateSurfaceCategory}
                                    donglesQuantity={dataset.dongles_quantity || 0}
                                    onDonglesChange={updateDonglesQuantity}
                                />
                            )}
                            {activeTab === "parsecteur" && (
                                dataset.data.raw === null || rawLoading ? (
                                    <LoadingState message={`Chargement des ${(dataset.row_count || 0).toLocaleString("fr-FR")} lignes…`} testId="parsecteur-loading" />
                                ) : (
                                    <ParSecteurTable
                                        rows={dataset.data.raw}
                                        columns={dataset.columns}
                                        search={search}
                                        uploadId={dataset.upload_id}
                                    />
                                )
                            )}
                            {activeTab === "comment" && (
                                <CommentTab
                                    value={dataset.data.comment_table}
                                    onCommit={updateComment}
                                />
                            )}
                            {activeTab === "pose" && (
                                <PhasageTab key={`pose-${phasageVersion}`} uploadId={dataset.upload_id} />
                            )}
                            {activeTab === "pose_cam" && (
                                <PhasageCamTab key={`cam-${phasageVersion}`} uploadId={dataset.upload_id} />
                            )}
                            {activeTab === "suivi" && (
                                <SuiviPhasageTab uploadId={dataset.upload_id} />
                            )}
                            {activeTab === "autre" && (
                                <AutreTab uploadId={dataset.upload_id} search={search} />
                            )}
                            {activeTab === "tableau_date" && (
                                <TableauDateTab uploadId={dataset.upload_id} />
                            )}
                            {activeTab === "export_home" && (
                                <div className="p-6 overflow-auto h-full">
                                    <div className="max-w-3xl mx-auto space-y-4">
                                        <div>
                                            <h3 className="text-sm font-semibold text-gray-800">Exports</h3>
                                            <p className="text-xs text-gray-500 mt-1">Générez les livrables finaux.</p>
                                        </div>
                                        <div className="grid sm:grid-cols-3 gap-3">
                                            <button onClick={handleExport} disabled={exportingRTR} className="flex flex-col items-start gap-1 p-4 rounded-lg border border-gray-200 bg-white hover:shadow-md hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 text-left" data-testid="export-rtr">
                                                <span className="text-sm font-semibold flex items-center gap-1.5" style={{ color: "#005BAB" }}>
                                                    {exportingRTR && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Excel RTR
                                                </span>
                                                <span className="text-xs text-gray-500">Fichier de commande RTR (toutes feuilles)</span>
                                            </button>
                                            <button onClick={handleExportCarrefour} disabled={exportingCarrefour} className="flex flex-col items-start gap-1 p-4 rounded-lg border border-gray-200 bg-white hover:shadow-md hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 text-left" data-testid="export-carrefour">
                                                <span className="text-sm font-semibold text-red-600 flex items-center gap-1.5">
                                                    {exportingCarrefour && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Excel Carrefour
                                                </span>
                                                <span className="text-xs text-gray-500">Format Carrefour</span>
                                            </button>
                                            <button onClick={handleExportPPTX} disabled={exportingPPTX} className="flex flex-col items-start gap-1 p-4 rounded-lg border border-gray-200 bg-white hover:shadow-md hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 text-left" data-testid="export-pptx">
                                                <span className="text-sm font-semibold text-purple-700 flex items-center gap-1.5">
                                                    {exportingPPTX && <Loader2 className="w-3.5 h-3.5 animate-spin" />}PowerPoint
                                                </span>
                                                <span className="text-xs text-gray-500">CR VT</span>
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </>
                )}
            </main>
            <BlockingModal
                open={showBlocking}
                issues={blockingIssues}
                onClose={() => setShowBlocking(false)}
            />
                </>
            )}
        </div>
    );
}
