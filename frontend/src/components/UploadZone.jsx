import React from "react";
import { useDropzone } from "react-dropzone";
import { UploadCloud, FileSpreadsheet, Loader2 } from "lucide-react";

export default function UploadZone({ onUpload, loading }) {
    const onDrop = (files) => {
        if (files && files[0]) onUpload(files[0]);
    };

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
            "application/vnd.ms-excel": [".xls"],
        },
        multiple: false,
        disabled: loading,
    });

    return (
        <div className="flex-1 flex items-center justify-center px-4 py-8 bg-white">
            <div
                {...getRootProps()}
                data-testid="upload-dropzone"
                className={`w-full max-w-2xl border-2 border-dashed rounded-lg p-16 flex flex-col items-center justify-center transition-all cursor-pointer ${
                    isDragActive
                        ? "border-[#056839] bg-emerald-50"
                        : "border-gray-300 bg-gray-50 hover:bg-gray-100 hover:border-gray-400"
                } ${loading ? "opacity-60 cursor-wait" : ""}`}
            >
                <input {...getInputProps()} data-testid="upload-input" />
                {loading ? (
                    <>
                        <Loader2 className="w-12 h-12 text-[#056839] animate-spin mb-4" />
                        <p className="text-lg font-medium text-gray-700">Traitement en cours...</p>
                        <p className="text-sm text-gray-500 mt-1">
                            Analyse de votre fichier Excel
                        </p>
                    </>
                ) : isDragActive ? (
                    <>
                        <UploadCloud className="w-12 h-12 text-[#056839] mb-4" />
                        <p className="text-lg font-medium text-[#056839]">
                            Déposez le fichier ici
                        </p>
                    </>
                ) : (
                    <>
                        <FileSpreadsheet className="w-14 h-14 text-gray-400 mb-4" strokeWidth={1.5} />
                        <p className="text-lg font-medium text-gray-700 mb-2">
                            Déposez votre fichier Excel ici
                        </p>
                        <p className="text-sm text-gray-500 mb-6">
                            ou cliquez pour parcourir (format .xlsx ou .xls)
                        </p>
                        <div className="text-xs text-gray-400 space-y-1 max-w-md text-center">
                            <p>
                                L'application générera automatiquement le récapitulatif produits
                                (avec Spare +5% et Inclineur) et le tri par Secteur/Allée.
                            </p>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
