import React, { useState, useMemo, useCallback } from "react";
import axios from "axios";
import { Toaster, toast } from "sonner";
import UploadZone from "./components/UploadZone";
import Header from "./components/Header";
import BottomTabs from "./components/BottomTabs";
import RawTable from "./components/RawTable";
import RecapTable from "./components/RecapTable";
import SecteurTable from "./components/SecteurTable";
import "./App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function App() {
    const [dataset, setDataset] = useState(null);
    const [activeTab, setActiveTab] = useState("raw");
    const [search, setSearch] = useState("");
    const [loading, setLoading] = useState(false);

    const handleUpload = useCallback(async (file) => {
        setLoading(true);
        const formData = new FormData();
        formData.append("file", file);
        try {
            const res = await axios.post(`${API}/upload-excel`, formData, {
                headers: { "Content-Type": "multipart/form-data" },
                timeout: 120000,
            });
            setDataset(res.data);
            setActiveTab("raw");
            toast.success(`Fichier traité : ${res.data.row_count.toLocaleString("fr-FR")} lignes`);
        } catch (err) {
            const msg = err.response?.data?.detail || err.message;
            toast.error(`Erreur : ${msg}`);
        } finally {
            setLoading(false);
        }
    }, []);

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
        setActiveTab("raw");
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

    const tabs = useMemo(() => {
        if (!dataset) return [];
        return [
            { id: "raw", label: "Données Brutes", count: dataset.data.raw.length },
            { id: "recap", label: "Récapitulatif Produits", count: dataset.data.recap.length },
            { id: "secteur", label: "Par Secteur / Allée", count: dataset.data.secteur.length },
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
                                <RawTable
                                    rows={dataset.data.raw}
                                    columns={dataset.columns}
                                    search={search}
                                />
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
                            {activeTab === "secteur" && (
                                <SecteurTable rows={dataset.data.secteur} search={search} />
                            )}
                        </div>
                        <BottomTabs tabs={tabs} active={activeTab} onChange={setActiveTab} />
                    </>
                )}
            </main>
        </div>
    );
}
