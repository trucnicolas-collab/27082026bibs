import React, { useState, useMemo, useCallback } from "react";
import axios from "axios";
import { Toaster, toast } from "sonner";
import UploadZone from "./components/UploadZone";
import Header from "./components/Header";
import BottomTabs from "./components/BottomTabs";
import RawTable from "./components/RawTable";
import RecapTable from "./components/RecapTable";
import SecteurTable from "./components/SecteurTable";
import ParSecteurTable from "./components/ParSecteurTable";
import CommentTab from "./components/CommentTab";
import "./App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function App() {
    const [dataset, setDataset] = useState(null);
    const [activeTab, setActiveTab] = useState("recap");
    const [search, setSearch] = useState("");
    const [loading, setLoading] = useState(false);
    const [rawLoading, setRawLoading] = useState(false);

    const handleUpload = useCallback(async (file) => {
        setLoading(true);
        const formData = new FormData();
        formData.append("file", file);
        try {
            const res = await axios.post(`${API}/upload-excel`, formData, {
                headers: { "Content-Type": "multipart/form-data" },
                timeout: 300000,  // 5 min pour gros fichiers
            });
            // Initialiser avec raw=null ; sera chargé à la demande au clic sur l'onglet
            const ds = {
                ...res.data,
                data: { ...res.data.data, raw: null },
            };
            setDataset(ds);
            setActiveTab("recap");  // Récap par défaut (instantané, raw chargé après)
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
            if (tabId === "raw") ensureRawLoaded();
        },
        [ensureRawLoaded]
    );

    const handleExport = useCallback(async () => {
        if (!dataset?.upload_id) return;
        try {
            const res = await axios.get(`${API}/export/${dataset.upload_id}?sheet=all`, {
                responseType: "blob",
            });
            const url = window.URL.createObjectURL(new Blob([res.data]));
            const link = document.createElement("a");
            link.href = url;
            const base = dataset.filename.replace(/\.xlsx?$/i, "");
            link.setAttribute("download", `${base}_traité.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            toast.success("Export téléchargé");
        } catch (err) {
            toast.error(`Erreur d'export : ${err.message}`);
        }
    }, [dataset]);

    const handleReset = useCallback(() => {
        setDataset(null);
        setSearch("");
        setActiveTab("recap");
    }, []);

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

    const tabs = useMemo(() => {
        if (!dataset) return [];
        return [
            { id: "raw", label: "Données Brutes", count: dataset.row_count || 0 },
            { id: "parsecteur", label: "Par Secteur", count: dataset.row_count || 0 },
            { id: "recap", label: "Commandes", count: dataset.data.recap.length },
            { id: "phasage", label: "Phasage", count: dataset.data.secteur.length },
            { id: "comment", label: "Commentaire", count: (dataset.data.comment_table?.rows?.length) || 0 },
        ];
    }, [dataset]);

    return (
        <div className="app-root" data-testid="app-root">
            <Toaster position="top-right" richColors />
            <Header
                dataset={dataset}
                search={search}
                onSearchChange={setSearch}
                onExport={handleExport}
                onReset={handleReset}
            />

            <main className="flex-1 overflow-hidden flex flex-col">
                {!dataset ? (
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
                                />
                            )}
                            {activeTab === "phasage" && (
                                <SecteurTable rows={dataset.data.secteur} search={search} />
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
                                    />
                                )
                            )}
                            {activeTab === "comment" && (
                                <CommentTab
                                    value={dataset.data.comment_table}
                                    onCommit={updateComment}
                                />
                            )}
                        </div>
                        <BottomTabs tabs={tabs} active={activeTab} onChange={handleTabChange} />
                    </>
                )}
            </main>
        </div>
    );
}
