import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Toaster, toast } from "sonner";
import { FileSpreadsheet, Download, Eye, AlertCircle, Loader2 } from "lucide-react";
import BottomTabs from "./BottomTabs";
import RawTable from "./RawTable";
import RecapTable from "./RecapTable";
import SecteurTable from "./SecteurTable";
import ParSecteurTable from "./ParSecteurTable";
import CommentTab from "./CommentTab";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const noop = () => toast.info("Mode lecture seule : modification désactivée");

export default function SharedView({ token }) {
    const [dataset, setDataset] = useState(null);
    const [error, setError] = useState("");
    const [search, setSearch] = useState("");
    const [activeTab, setActiveTab] = useState("recap");
    const [rawLoading, setRawLoading] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await axios.get(`${API}/share/${token}`);
            setDataset({ ...res.data, data: { ...res.data.data, raw: null } });
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    const loadRaw = useCallback(async () => {
        if (!dataset || dataset.data.raw !== null) return;
        setRawLoading(true);
        try {
            const res = await axios.get(`${API}/share/${token}/raw`);
            setDataset((d) => ({ ...d, data: { ...d.data, raw: res.data.raw } }));
        } catch (err) {
            toast.error(`Erreur : ${err.message}`);
        } finally {
            setRawLoading(false);
        }
    }, [dataset, token]);

    const handleTabChange = (tabId) => {
        setActiveTab(tabId);
        if (tabId === "raw" || tabId === "parsecteur") loadRaw();
    };

    const handleExport = async () => {
        try {
            const res = await axios.get(`${API}/share/${token}/export?sheet=all`, { responseType: "blob" });
            const url = window.URL.createObjectURL(new Blob([res.data]));
            const link = document.createElement("a");
            link.href = url;
            const base = (dataset.label || dataset.filename || "export").replace(/\.xlsx?$/i, "");
            link.setAttribute("download", `${base}_traité.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            toast.success("Export téléchargé");
        } catch (err) {
            toast.error(`Erreur d'export : ${err.message}`);
        }
    };

    if (error) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4" data-testid="share-error">
                <div className="max-w-md text-center">
                    <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-3" />
                    <h2 className="text-lg font-semibold text-gray-900 mb-2">Lien indisponible</h2>
                    <p className="text-sm text-gray-600">{error}</p>
                    <p className="text-xs text-gray-400 mt-3">Le partage a peut-être été désactivé par son propriétaire.</p>
                </div>
            </div>
        );
    }

    if (!dataset) {
        return (
            <div className="min-h-screen flex items-center justify-center text-gray-500" data-testid="share-loading">
                <Loader2 className="w-5 h-5 animate-spin mr-2" /> Chargement du document partagé…
            </div>
        );
    }

    const tabs = [
        { id: "raw", label: "Données Brutes", count: dataset.row_count || 0 },
        { id: "recap", label: "Commandes", count: dataset.data.recap.length },
        { id: "parsecteur", label: "Recap par secteur", count: dataset.row_count || 0 },
        { id: "phasage", label: "Tableau phasage", count: dataset.data.secteur.length },
        { id: "comment", label: "Commentaire", count: (dataset.data.comment_table?.rows?.length) || 0 },
    ];

    return (
        <div className="app-root" data-testid="shared-view">
            <Toaster position="top-right" richColors />
            <header className="h-14 border-b border-gray-200 flex items-center justify-between px-4 bg-gray-50 flex-shrink-0">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded bg-[#005BAB] flex items-center justify-center flex-shrink-0">
                        <FileSpreadsheet className="w-5 h-5 text-white" strokeWidth={2} />
                    </div>
                    <div className="min-w-0">
                        <h1 className="text-base font-semibold text-gray-900 leading-tight truncate flex items-center gap-2" data-testid="shared-title">
                            {dataset.label || dataset.filename}
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 text-blue-700">
                                <Eye className="w-3 h-3 mr-1" /> LECTURE SEULE
                            </span>
                        </h1>
                        <p className="text-xs text-gray-500 truncate">
                            {dataset.row_count.toLocaleString("fr-FR")} lignes · partagé en lecture seule
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <input
                        type="text"
                        placeholder="Rechercher..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        data-testid="shared-search"
                        className="h-8 w-48 sm:w-64 px-3 text-sm border border-gray-300 rounded focus:ring-1 focus:ring-[#005BAB] focus:border-[#005BAB] outline-none"
                    />
                    <button
                        onClick={handleExport}
                        data-testid="shared-export"
                        className="h-8 px-3 bg-[#005BAB] text-white text-sm rounded hover:bg-[#04502b] flex items-center gap-1.5 transition-colors font-medium shadow-sm"
                    >
                        <Download className="w-4 h-4" />
                        <span className="hidden sm:inline">Télécharger</span>
                    </button>
                </div>
            </header>

            <main className="flex-1 overflow-hidden flex flex-col">
                <div className="flex-1 overflow-hidden">
                    {activeTab === "raw" && (
                        dataset.data.raw === null || rawLoading ? (
                            <div className="flex-1 flex items-center justify-center h-full text-sm text-gray-500">
                                Chargement des {(dataset.row_count || 0).toLocaleString("fr-FR")} lignes brutes...
                            </div>
                        ) : (
                            <RawTable rows={dataset.data.raw} columns={dataset.columns} search={search} />
                        )
                    )}
                    {activeTab === "recap" && (
                        <RecapTable
                            rows={dataset.data.recap}
                            search={search}
                            onUpdateRow={noop}
                            onAddRow={noop}
                            onDeleteRow={noop}
                            surfaceCategory={dataset.surface_category || null}
                            onSurfaceChange={noop}
                            donglesQuantity={dataset.dongles_quantity || 0}
                            onDonglesChange={noop}
                        />
                    )}
                    {activeTab === "phasage" && (
                        <SecteurTable rows={dataset.data.secteur} search={search} />
                    )}
                    {activeTab === "parsecteur" && (
                        dataset.data.raw === null || rawLoading ? (
                            <div className="flex-1 flex items-center justify-center h-full text-sm text-gray-500">
                                Chargement des {(dataset.row_count || 0).toLocaleString("fr-FR")} lignes...
                            </div>
                        ) : (
                            <ParSecteurTable
                                rows={dataset.data.raw}
                                columns={dataset.columns}
                                search={search}
                                uploadId={null}
                            />
                        )
                    )}
                    {activeTab === "comment" && (
                        <CommentTab value={dataset.data.comment_table} onCommit={noop} />
                    )}
                </div>
                <BottomTabs tabs={tabs} active={activeTab} onChange={handleTabChange} />
            </main>
        </div>
    );
}
