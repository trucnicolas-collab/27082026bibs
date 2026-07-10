import axios from "axios";
import { toast } from "sonner";

// Fabrique les actions API du suivi. `base` = .../api/suivi/{uploadId}
// ou .../api/suivi-terrain/{token} (mêmes routes ensuite).
export function makeActions(base, refresh) {
    return {
        patchAllee: async (uid, fields) => {
            try {
                await axios.patch(`${base}/allee`, { uid, ...fields });
                await refresh();
                return true;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Erreur d'enregistrement");
                return false;
            }
        },
        patchStock: async (family, recu) => {
            try {
                await axios.patch(`${base}/stock`, { family, recu });
                await refresh();
            } catch { toast.error("Erreur d'enregistrement du stock"); }
        },
        addIncident: async (nuit, text) => {
            try {
                await axios.post(`${base}/incident`, { nuit, text });
                await refresh();
                toast.success("Incident enregistré");
            } catch { toast.error("Erreur"); }
        },
        delIncident: async (id) => {
            try {
                await axios.delete(`${base}/incident/${id}`);
                await refresh();
            } catch { toast.error("Erreur"); }
        },
        downloadReport: async (nuit) => {
            try {
                const res = await fetch(`${base}/rapport-nuit/${nuit}`, { credentials: "include" });
                if (!res.ok) throw new Error();
                const blob = await res.blob();
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `Rapport_nuit_${nuit}.xlsx`;
                a.click();
                URL.revokeObjectURL(a.href);
            } catch { toast.error("Impossible de générer le rapport"); }
        },
        uploadPhoto: async (uid, blob) => {
            try {
                const fd = new FormData();
                fd.append("uid", uid);
                fd.append("file", blob, "photo.jpg");
                await axios.post(`${base}/allee-photo`, fd);
                await refresh();
                toast.success("Photo ajoutée");
                return true;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Envoi de la photo impossible");
                return false;
            }
        },
        photoUrl: (pid) => `${base}/photo/${pid}`,
        delPhoto: async (pid) => {
            try {
                await axios.delete(`${base}/photo/${pid}`);
                await refresh();
            } catch { toast.error("Suppression impossible"); }
        },
        replan: async (apply) => {
            try {
                const res = await axios.post(`${base}/replan`, { apply });
                if (apply) {
                    toast.success(`Phasage replanifié — ${res.data.allees_deplacees} allée(s) déplacée(s)`);
                    await refresh();
                }
                return res.data;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Replanification impossible");
                return null;
            }
        },
        terrainShare: async (enabled) => {
            try {
                const res = await axios.post(`${base}/terrain-share`, { enabled });
                await refresh();
                return res.data;
            } catch { toast.error("Erreur"); return null; }
        },
        refresh,
    };
}

// Compression côté client des photos (téléphone → ~200-400 Ko JPEG)
export function compressImage(file, maxDim = 1400, quality = 0.72) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
            const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
            const canvas = document.createElement("canvas");
            canvas.width = Math.max(1, Math.round(img.width * scale));
            canvas.height = Math.max(1, Math.round(img.height * scale));
            canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
            canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("compress failed"))), "image/jpeg", quality);
            URL.revokeObjectURL(img.src);
        };
        img.onerror = () => reject(new Error("image load failed"));
        img.src = URL.createObjectURL(file);
    });
}
