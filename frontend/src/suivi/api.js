import axios from "axios";
import { toast } from "sonner";

// Fabrique les actions API du suivi. `base` = .../api/suivi/{uploadId}
// ou .../api/suivi-terrain/{token} (mêmes routes ensuite).
//
// Mode `viewer` (lecture seule client) : toutes les fonctions d'écriture
// sont neutralisées côté frontend (défense en profondeur — le backend
// n'expose de toute façon aucune route d'écriture sur /api/suivi-view).
// `tokenParam` : "?token=xxx" ajouté aux URLs GET quand on est en mode viewer.
export function makeActions(base, refresh, { readOnly = false, tokenParam = "" } = {}) {
    const withTk = (u) => tokenParam ? `${u}${u.includes("?") ? "&" : "?"}${tokenParam}` : u;
    const denyRO = () => { toast.info("Mode lecture seule — aucune modification possible"); return false; };
    return {
        readOnly,
        patchAllee: async (uid, fields) => {
            if (readOnly) return denyRO();
            try {
                await axios.patch(`${base}/allee`, { uid, ...fields });
                await refresh();
                return true;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Erreur d'enregistrement");
                return false;
            }
        },
        patchCamAllee: async (uid, fields) => {
            if (readOnly) return denyRO();
            try {
                await axios.patch(`${base}/allee-cam`, { uid, ...fields });
                await refresh();
                return true;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Erreur d'enregistrement");
                return false;
            }
        },
        getMateriel: async (mode) => {
            try { return (await axios.get(withTk(`${base}/materiel`), { params: mode ? { mode } : undefined })).data; }
            catch { toast.error("Chargement du matériel impossible"); return { nights: [], unassigned: { nb_allees: 0, products: [] } }; }
        },
        getMaterielNuit: async (n, mode) => {
            try { return (await axios.get(withTk(`${base}/materiel/${n}`), { params: mode ? { mode } : undefined })).data; }
            catch { toast.error("Chargement impossible"); return { nuit: n, allees: [] }; }
        },
        patchStock: async (designation, recu) => {
            if (readOnly) return denyRO();
            try {
                await axios.patch(`${base}/stock`, { designation, recu });
                await refresh();
            } catch { toast.error("Erreur d'enregistrement du stock"); }
        },
        addIncident: async (nuit, text) => {
            if (readOnly) return denyRO();
            try {
                await axios.post(`${base}/incident`, { nuit, text });
                await refresh();
                toast.success("Incident enregistré");
            } catch { toast.error("Erreur"); }
        },
        delIncident: async (id) => {
            if (readOnly) return denyRO();
            try {
                await axios.delete(`${base}/incident/${id}`);
                await refresh();
            } catch { toast.error("Erreur"); }
        },
        downloadReport: async (nuit) => {
            try {
                const res = await fetch(withTk(`${base}/rapport-nuit/${nuit}`), { credentials: "include" });
                if (!res.ok) throw new Error();
                // (iter37) On lit le nom du fichier envoyé par le serveur pour respecter
                // le format demandé « <Magasin> - Nuit N.xlsx » plutôt qu'un nom générique.
                let filename = `Nuit ${nuit}.xlsx`;
                const cd = res.headers.get("content-disposition") || "";
                const m = cd.match(/filename\*?=(?:UTF-8''|")?([^";]+)"?/i);
                if (m) filename = decodeURIComponent(m[1]);
                const blob = await res.blob();
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = filename;
                a.click();
                URL.revokeObjectURL(a.href);
            } catch { toast.error("Impossible de générer le rapport"); }
        },
        uploadPhoto: async (uid, blob) => {
            if (readOnly) return denyRO();
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
        photoUrl: (pid) => withTk(`${base}/photo/${pid}`),
        delPhoto: async (pid) => {
            if (readOnly) return denyRO();
            try {
                await axios.delete(`${base}/photo/${pid}`);
                await refresh();
            } catch { toast.error("Suppression impossible"); }
        },
        replan: async (apply) => {
            if (readOnly) return denyRO();
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
        publish: async (published) => {
            if (readOnly) return denyRO();
            try {
                const res = await axios.post(`${base}/publish`, { published });
                await refresh();
                return res.data;
            } catch { toast.error("Erreur"); return null; }
        },
        resetSuivi: async () => {
            if (readOnly) return denyRO();
            try {
                await axios.delete(`${base}/reset`);
                await refresh();
                toast.success("Suivi effacé — vous pouvez repartir de zéro");
                return true;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Effacement impossible");
                return false;
            }
        },
        // ---- Floorplans (iter45) ----
        listFloorplans: async () => {
            try {
                const url = readOnly ? withTk(`${base}/floorplans`) : `${base}/floorplans`;
                const res = await axios.get(url);
                return res.data.floorplans || [];
            } catch { return []; }
        },
        createFloorplan: async (label, imageDataUrl, zones = [], phaseKind = "eeg") => {
            if (readOnly) return denyRO();
            try {
                const res = await axios.post(`${base}/floorplans`, { label, image_data_url: imageDataUrl, zones, phase_kind: phaseKind });
                toast.success("Plan ajouté");
                return res.data.floorplan;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Ajout du plan impossible");
                return null;
            }
        },
        updateFloorplan: async (floorId, patch) => {
            if (readOnly) return denyRO();
            try {
                const res = await axios.put(`${base}/floorplans/${floorId}`, patch);
                return res.data.floorplan;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Mise à jour du plan impossible");
                return null;
            }
        },
        deleteFloorplan: async (floorId) => {
            if (readOnly) return denyRO();
            try {
                await axios.delete(`${base}/floorplans/${floorId}`);
                toast.success("Plan supprimé");
                return true;
            } catch (e) {
                toast.error(e?.response?.data?.detail || "Suppression impossible");
                return false;
            }
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
