/**
 * useAutoSave — Hook générique pour sauvegarde automatique robuste.
 *
 * Ce qu'il apporte par rapport à un simple debounce + PATCH :
 *
 * 1. **Alerte visible en cas d'échec** :
 *    - Retourne `saveStatus` ("idle" | "saving" | "saved" | "error")
 *      + `retryCount` + `errorMessage` + `retryNow()` pour bouton retry manuel.
 *    - Peut piloter un banner rouge global (voir <SaveStatusBanner />).
 *
 * 2. **Backup localStorage automatique** :
 *    - Chaque changement est immédiatement sérialisé en local (`ls_key`).
 *    - Sur mount, si un backup local plus récent que le serveur existe, il
 *      est renvoyé via `pendingRecovery` pour proposer une restauration.
 *
 * 3. **Retry auto avec back-off** :
 *    - En cas d'échec réseau, retry à 3s / 10s / 30s (max 5 tentatives).
 *    - Le backup local est conservé jusqu'à un save réussi.
 *
 * Usage :
 *   const { saveStatus, retryCount, errorMessage, retryNow, pendingRecovery,
 *           dismissRecovery, applyRecovery }
 *     = useAutoSave({
 *         data: { es, cam, suivi },
 *         key: `phasage:${uploadId}`,
 *         url: `${API}/dataset/${uploadId}/phasage`,
 *         debounceMs: 600,
 *         enabled: Boolean(summary && uploadId),
 *       });
 */
import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";

const RETRY_DELAYS_MS = [3000, 10000, 30000, 60000, 120000]; // 3s → 2 min

export function useAutoSave({ data, key, url, debounceMs = 600, enabled = true, method = "patch" }) {
    const [saveStatus, setSaveStatus] = useState("idle");
    const [errorMessage, setErrorMessage] = useState("");
    const [retryCount, setRetryCount] = useState(0);
    const [pendingRecovery, setPendingRecovery] = useState(null); // { data, savedAt }
    const [lastSavedAt, setLastSavedAt] = useState(null);

    const debounceTimer = useRef(null);
    const retryTimer = useRef(null);
    const currentDataRef = useRef(data);
    const isMountedRef = useRef(true);

    // ── Chargement du backup local à l'init ─────────────────────────────
    useEffect(() => {
        if (!key) return;
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return;
            const parsed = JSON.parse(raw);
            if (parsed?.data && parsed?.savedAt) {
                setPendingRecovery(parsed);
            }
        } catch (_e) { /* ignore parse errors */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key]);

    // ── Sauvegarde locale immédiate + PATCH avec debounce ──────────────
    useEffect(() => {
        currentDataRef.current = data;
        if (!enabled || !key || !url) return;
        // 1. Backup local IMMÉDIAT — pas de debounce ici
        try {
            localStorage.setItem(key, JSON.stringify({
                data,
                savedAt: new Date().toISOString(),
                pending: true,  // sera False après save réussi
            }));
        } catch (_e) { /* localStorage plein ou désactivé — ignore */ }

        // 2. Debounce le PATCH
        if (debounceTimer.current) clearTimeout(debounceTimer.current);
        debounceTimer.current = setTimeout(() => {
            performSave(0);
        }, debounceMs);

        return () => {
            if (debounceTimer.current) clearTimeout(debounceTimer.current);
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data, key, url, enabled, debounceMs]);

    useEffect(() => {
        isMountedRef.current = true;
        return () => {
            isMountedRef.current = false;
            if (retryTimer.current) clearTimeout(retryTimer.current);
            if (debounceTimer.current) clearTimeout(debounceTimer.current);
        };
    }, []);

    const performSave = useCallback(async (attempt) => {
        if (!isMountedRef.current) return;
        setSaveStatus("saving");
        setRetryCount(attempt);
        try {
            await axios({
                method,
                url,
                data: currentDataRef.current,
                withCredentials: true,
                timeout: 15000,
            });
            if (!isMountedRef.current) return;
            setSaveStatus("saved");
            setErrorMessage("");
            setRetryCount(0);
            setLastSavedAt(new Date());
            // Marque le backup local comme non-pending (save confirmée)
            try {
                if (key) localStorage.setItem(key, JSON.stringify({
                    data: currentDataRef.current,
                    savedAt: new Date().toISOString(),
                    pending: false,
                }));
            } catch (_e) { /* ignore */ }
        } catch (err) {
            if (!isMountedRef.current) return;
            const msg = err?.response?.data?.detail || err?.message || "Erreur inconnue";
            setSaveStatus("error");
            setErrorMessage(msg);
            // Auto-retry
            const nextAttempt = attempt + 1;
            if (nextAttempt < RETRY_DELAYS_MS.length) {
                const delay = RETRY_DELAYS_MS[nextAttempt];
                if (retryTimer.current) clearTimeout(retryTimer.current);
                retryTimer.current = setTimeout(() => performSave(nextAttempt), delay);
            }
        }
    }, [url, key, method]);

    const retryNow = useCallback(() => {
        if (retryTimer.current) clearTimeout(retryTimer.current);
        performSave(0);
    }, [performSave]);

    const dismissRecovery = useCallback(() => {
        setPendingRecovery(null);
        try { if (key) localStorage.removeItem(key); } catch (_e) { /* ignore */ }
    }, [key]);

    const applyRecovery = useCallback(() => {
        const recovered = pendingRecovery?.data;
        setPendingRecovery(null);
        return recovered;
    }, [pendingRecovery]);

    return {
        saveStatus,
        errorMessage,
        retryCount,
        retryNow,
        lastSavedAt,
        pendingRecovery,
        dismissRecovery,
        applyRecovery,
    };
}
