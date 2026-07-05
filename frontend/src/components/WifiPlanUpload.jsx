import React, { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Wifi, Upload, Trash2, Loader2, ImageIcon } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Upload / gestion des plans wifi (max 2) — insérés automatiquement dans le PPTX.
export default function WifiPlanUpload({ uploadId }) {
    const [plans, setPlans] = useState([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [maxPlans, setMaxPlans] = useState(2);
    const inputRef = useRef(null);

    const refresh = useCallback(async () => {
        if (!uploadId) return;
        try {
            const res = await axios.get(`${API}/dataset/${uploadId}/wifi-plans`, {
                headers: { "Cache-Control": "no-cache" },
                params: { _t: Date.now() },
            });
            setPlans(res.data.plans || []);
            setMaxPlans(res.data.max || 2);
        } catch (err) {
            // silencieux : pas bloquant
        } finally {
            setLoading(false);
        }
    }, [uploadId]);

    useEffect(() => { refresh(); }, [refresh]);

    const handleFile = useCallback(async (file) => {
        if (!file) return;
        const ok = /\.(png|jpe?g)$/i.test(file.name) || ["image/png", "image/jpeg", "image/jpg"].includes(file.type);
        if (!ok) { toast.error("Format non supporté : importez une image JPG ou PNG."); return; }
        setUploading(true);
        const fd = new FormData();
        fd.append("file", file);
        try {
            const res = await axios.post(`${API}/dataset/${uploadId}/wifi-plan`, fd, {
                headers: { "Content-Type": "multipart/form-data" },
            });
            setPlans(res.data.plans || []);
            toast.success("Plan wifi ajouté");
        } catch (err) {
            toast.error(err.response?.data?.detail || "Échec de l'upload du plan wifi");
        } finally {
            setUploading(false);
            if (inputRef.current) inputRef.current.value = "";
        }
    }, [uploadId]);

    const handleDelete = useCallback(async (planId) => {
        try {
            const res = await axios.delete(`${API}/dataset/${uploadId}/wifi-plan/${planId}`);
            setPlans(res.data.plans || []);
            toast.success("Plan wifi supprimé");
        } catch (err) {
            toast.error(err.response?.data?.detail || "Échec de la suppression");
        }
    }, [uploadId]);

    const canAdd = plans.length < maxPlans;

    return (
        <div className="border border-gray-200 rounded-lg bg-white p-4" data-testid="wifi-plan-upload">
            <div className="flex items-center gap-2 mb-1">
                <Wifi className="w-4 h-4" style={{ color: "#056839" }} />
                <h3 className="text-sm font-semibold text-gray-800">Plan(s) wifi du magasin</h3>
                <span className="text-xs text-gray-400">({plans.length}/{maxPlans})</span>
            </div>
            <p className="text-xs text-gray-500 mb-3">
                Importez jusqu’à {maxPlans} images (JPG/PNG). Elles seront insérées automatiquement
                — une par diapositive « Plan wifi magasin » — dans l’export PowerPoint.
            </p>

            {loading ? (
                <div className="text-sm text-gray-400 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Chargement…</div>
            ) : (
                <div className="flex flex-wrap gap-3">
                    {plans.map((p, i) => (
                        <div key={p.plan_id} className="relative group border border-gray-200 rounded-md overflow-hidden" style={{ width: 200 }} data-testid={`wifi-plan-${i}`}>
                            <img
                                src={`${API}/dataset/${uploadId}/wifi-plan/${p.plan_id}?_t=${Date.now()}`}
                                alt={p.filename}
                                className="w-full h-28 object-cover bg-gray-50"
                            />
                            <div className="px-2 py-1 text-[11px] text-gray-600 truncate" title={p.filename}>{p.filename}</div>
                            <button
                                onClick={() => handleDelete(p.plan_id)}
                                className="absolute top-1 right-1 bg-white/90 hover:bg-red-50 text-red-600 rounded p-1 shadow-sm"
                                title="Supprimer ce plan"
                                data-testid={`wifi-plan-delete-${i}`}
                            >
                                <Trash2 className="w-3.5 h-3.5" />
                            </button>
                        </div>
                    ))}

                    {canAdd && (
                        <button
                            onClick={() => inputRef.current?.click()}
                            disabled={uploading}
                            className="flex flex-col items-center justify-center gap-1 border-2 border-dashed border-gray-300 rounded-md text-gray-500 hover:border-gray-400 hover:text-gray-700 transition-colors"
                            style={{ width: 200, height: 116 }}
                            data-testid="wifi-plan-add"
                        >
                            {uploading ? (
                                <><Loader2 className="w-5 h-5 animate-spin" /><span className="text-xs">Envoi…</span></>
                            ) : (
                                <><Upload className="w-5 h-5" /><span className="text-xs">Ajouter un plan</span></>
                            )}
                        </button>
                    )}

                    {!canAdd && plans.length === 0 && (
                        <div className="flex items-center gap-2 text-sm text-gray-400"><ImageIcon className="w-4 h-4" /> Aucun plan</div>
                    )}
                </div>
            )}

            <input
                ref={inputRef}
                type="file"
                accept="image/png,image/jpeg"
                className="hidden"
                onChange={(e) => handleFile(e.target.files?.[0])}
                data-testid="wifi-plan-input"
            />
        </div>
    );
}
