import React, { useState, useMemo, useCallback, useEffect } from "react";
import axios from "axios";
import { Toaster, toast } from "sonner";
import UploadZone from "./components/UploadZone";
import Header from "./components/Header";
import BottomTabs from "./components/BottomTabs";
import RawTable from "./components/RawTable";
import RecapTable from "./components/RecapTable";
import ParSecteurTable from "./components/ParSecteurTable";
import CommentTab from "./components/CommentTab";
import PhasageTab from "./components/PhasageTab";
import PhasageCamTab from "./components/PhasageCamTab";
import PhasageFullTab from "./components/PhasageFullTab";
import SuiviPhasageTab from "./components/SuiviPhasageTab";
import AutreTab from "./components/AutreTab";
import TableauDateTab from "./components/TableauDateTab";
import AuthScreen from "./components/AuthScreen";
import ForgotPasswordScreen from "./components/ForgotPasswordScreen";
import ResetPasswordScreen from "./components/ResetPasswordScreen";
import SharedView from "./components/SharedView";
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

function MainApp() {
    const { user, logout } = useAuth();
    const [dataset, setDataset] = useState(null);
    const [phasageVersion, setPhasageVersion] = useState(0);
    const [activeTab, setActiveTab] = useState("recap");
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
            setActiveTab("recap");
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
            setActiveTab("recap");
            try { localStorage.setItem(LS_KEY, res.data.upload_id); } catch (_) {}
            toast.success(`Fichier traité : ${res.data.row_count.toLocaleString("fr-FR")} lignes`);
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

    const handleTabChange = useCallback(
        (tabId) => {
            setActiveTab(tabId);
            if (tabId === "raw" || tabId === "parsecteur") ensureRawLoaded();
        },
        [ensureRawLoaded]
    );

    const [exportingRTR, setExportingRTR] = useState(false);
    const [exportingCarrefour, setExportingCarrefour] = useState(false);
    const [exportingPPTX, setExportingPPTX] = useState(false);

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
            const base = dataset.filename.replace(/\.xlsx?$/i, "");
            link.setAttribute("download", `${base}_RTR.xlsx`);
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
    }, [dataset, exportingRTR]);

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
            const base = dataset.filename.replace(/\.xlsx?$/i, "");
            link.setAttribute("download", `${base}_Carrefour.xlsx`);
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
    }, [dataset, exportingCarrefour]);

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
            const base = dataset.filename.replace(/\.xlsx?$/i, "");
            link.setAttribute("download", `${base}_CR_VT.pptx`);
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
    }, [dataset, exportingPPTX]);

    const handleReset = useCallback(() => {
        setDataset(null);
        setSearch("");
        setActiveTab("recap");
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
            setActiveTab("recap");
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

    const tabs = useMemo(() => {
        if (!dataset) return [];
        const t = [
            { id: "raw", label: "Données Brutes", count: dataset.row_count || 0 },
            { id: "recap", label: "Commandes", count: dataset.data.recap.length },
        ];
        // Onglet "Autre" : seulement si le fichier contient des fixations AUTRE*
        if (dataset.has_autre) {
            t.push({ id: "autre", label: "Autre", count: dataset.autre_count || 0 });
        }
        t.push({ id: "parsecteur", label: "Recap par secteur", count: dataset.row_count || 0 });
        t.push({ id: "pose", label: "Phasage de pose", count: 0 });
        t.push({ id: "tableau_date", label: "Tableau date", count: 0 });
        t.push({ id: "pose_cam", label: "Phasage caméras", count: 0 });
        t.push({ id: "pose_full", label: "Phasage full", count: 0 });
        t.push({ id: "suivi", label: "Suivi phasage", count: 0 });
        t.push({ id: "comment", label: "Commentaire", count: (dataset.data.comment_table?.rows?.length) || 0 });
        return t;
    }, [dataset]);

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
                            <div className="flex-1 flex items-center justify-center text-sm text-gray-500" data-testid="session-restoring">
                                Restauration de la session précédente…
                            </div>
                        ) : !dataset ? (
                            <UploadZone onUpload={handleUpload} loading={loading} />
                        ) : (
                    <>
                        <div className="flex-1 overflow-hidden">
                            {activeTab === "raw" && (
                                dataset.data.raw === null || rawLoading ? (
                                    <div className="flex-1 flex items-center justify-center h-full text-sm text-gray-500" data-testid="raw-loading">
                                        Chargement des {(dataset.row_count || 0).toLocaleString("fr-FR")} lignes brutes...
                                    </div>
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
                                    <div className="flex-1 flex items-center justify-center h-full text-sm text-gray-500" data-testid="parsecteur-loading">
                                        Chargement des {(dataset.row_count || 0).toLocaleString("fr-FR")} lignes...
                                    </div>
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
                            {activeTab === "pose_full" && (
                                <PhasageFullTab uploadId={dataset.upload_id} />
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
                        </div>
                        <BottomTabs tabs={tabs} active={activeTab} onChange={handleTabChange} />
                    </>
                )}
            </main>
                </>
            )}
        </div>
    );
}
