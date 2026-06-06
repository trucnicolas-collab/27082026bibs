import React from "react";
import { Download, RotateCcw, Search, FileSpreadsheet, LogOut, Store, Presentation as PresentationIcon } from "lucide-react";
import SessionsMenu from "./SessionsMenu";
import ActivityPanel from "./ActivityPanel";

export default function Header({
    dataset,
    search,
    onSearchChange,
    onExport,
    onExportPptx,
    onReset,
    onOpenStoreInfo,
    onOpenSession,
    onDeletedSession,
    user,
    onLogout,
}) {
    const storeLabel = dataset
        ? ([dataset.store_city || dataset.store_name, dataset.store_code]
              .filter(Boolean).join(" ") || "Compléter")
        : "";

    return (
        <header className="h-14 border-b border-gray-200 flex items-center justify-between px-4 bg-gray-50 flex-shrink-0">
            <div className="flex items-center gap-3 min-w-0">
                <div className="w-8 h-8 rounded bg-[#056839] flex items-center justify-center flex-shrink-0">
                    <FileSpreadsheet className="w-5 h-5 text-white" strokeWidth={2} />
                </div>
                <div className="min-w-0">
                    <h1 className="text-base font-semibold text-gray-900 leading-tight truncate" data-testid="app-title">
                        VT/Phasage Carrefour
                    </h1>
                    {dataset && (
                        <p className="text-xs text-gray-500 truncate" data-testid="file-info">
                            {dataset.filename} · {dataset.row_count.toLocaleString("fr-FR")} lignes
                        </p>
                    )}
                </div>
            </div>

            <div className="flex items-center gap-2">
                {dataset && (
                    <div className="relative">
                        <Search className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                        <input
                            type="text"
                            placeholder="Rechercher..."
                            value={search}
                            onChange={(e) => onSearchChange(e.target.value)}
                            data-testid="search-input"
                            className="h-8 w-48 sm:w-64 pl-8 pr-3 text-sm border border-gray-300 rounded focus:ring-1 focus:ring-[#056839] focus:border-[#056839] outline-none"
                        />
                    </div>
                )}
                <SessionsMenu
                    currentUploadId={dataset?.upload_id}
                    onOpen={onOpenSession}
                    onDeleted={onDeletedSession}
                />
                {dataset && (
                    <ActivityPanel uploadId={dataset.upload_id} />
                )}
                {dataset && (
                    <button
                        onClick={onOpenStoreInfo}
                        data-testid="store-info-button"
                        title={`Infos magasin · ${storeLabel}`}
                        className="h-8 px-2.5 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-100 flex items-center gap-1.5 transition-colors"
                    >
                        <Store className="w-4 h-4" />
                        <span className="hidden xl:inline max-w-[140px] truncate">
                            {storeLabel}
                        </span>
                    </button>
                )}
                {dataset && (
                    <>
                        <button
                            onClick={onExport}
                            data-testid="export-button"
                            title="Exporter Excel"
                            className="h-8 px-3 bg-[#056839] text-white text-sm rounded hover:bg-[#04502b] flex items-center gap-1.5 transition-colors font-medium shadow-sm"
                        >
                            <Download className="w-4 h-4" />
                            <span className="hidden sm:inline">Excel</span>
                        </button>
                        <button
                            onClick={onExportPptx}
                            data-testid="export-pptx-button"
                            title="Exporter PowerPoint (CR VT + Plan de phasage)"
                            className="h-8 px-3 bg-[#B45309] text-white text-sm rounded hover:bg-[#92400E] flex items-center gap-1.5 transition-colors font-medium shadow-sm"
                        >
                            <PresentationIcon className="w-4 h-4" />
                            <span className="hidden sm:inline">PPT</span>
                        </button>
                        <button
                            onClick={onReset}
                            data-testid="reset-button"
                            className="h-8 px-3 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-100 flex items-center gap-1.5 transition-colors"
                            title="Nouveau fichier"
                        >
                            <RotateCcw className="w-4 h-4" />
                            <span className="hidden sm:inline">Nouveau</span>
                        </button>
                    </>
                )}
                {user && (
                    <div className="flex items-center gap-2 pl-2 ml-1 border-l border-gray-200" data-testid="user-area">
                        <div className="hidden md:flex flex-col items-end leading-tight">
                            <span className="text-xs font-semibold text-gray-700 truncate max-w-[160px]" title={user.email}>
                                {user.name || user.email}
                            </span>
                            <span className="text-[10px] text-gray-400 truncate max-w-[160px]">{user.email}</span>
                        </div>
                        <button
                            onClick={onLogout}
                            data-testid="logout-button"
                            title="Se déconnecter"
                            className="h-8 px-2.5 bg-white border border-gray-300 text-gray-600 text-sm rounded hover:bg-red-50 hover:text-red-600 hover:border-red-200 flex items-center gap-1.5 transition-colors"
                        >
                            <LogOut className="w-4 h-4" />
                        </button>
                    </div>
                )}
            </div>
        </header>
    );
}
