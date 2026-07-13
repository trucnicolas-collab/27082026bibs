import { useEffect, useRef } from "react";

/**
 * Empile une entrée dans l'historique du navigateur quand le composant devient actif,
 * et intercepte le bouton back natif (Android) pour appeler onBack() au lieu de sortir de l'app.
 *
 * Utilisation :
 *   useMobileBack(onBack, active)
 *   - onBack : callback appelé quand l'utilisateur fait back (natif ou history.back())
 *   - active : true tant que l'écran est visible
 *
 * Les boutons UI de retour doivent appeler window.history.back() (qui déclenchera
 * popstate → onBack) plutôt que onBack() directement, afin de garder la stack propre.
 */
export function useMobileBack(onBack, active = true) {
    const cbRef = useRef(onBack);
    cbRef.current = onBack;

    useEffect(() => {
        if (!active) return undefined;
        // Marqueur unique pour vérifier que notre entrée est bien au sommet de la stack au cleanup
        const marker = "_sb_" + Date.now() + "_" + Math.random().toString(36).slice(2);
        window.history.pushState({ _suiviBack: marker }, "");
        let poppedByUser = false;
        const handler = () => {
            poppedByUser = true;
            const fn = cbRef.current;
            if (typeof fn === "function") fn();
        };
        window.addEventListener("popstate", handler);
        return () => {
            window.removeEventListener("popstate", handler);
            // Ne PAS appeler history.back() si un écran plus profond a déjà pushé par-dessus
            // (sinon history.back() est asynchrone et vient refermer le nouvel écran).
            // On ne dépile que si notre marqueur est encore au sommet de la stack.
            if (!poppedByUser) {
                try {
                    const topMarker = window.history.state && window.history.state._suiviBack;
                    if (topMarker === marker) {
                        window.history.back();
                    }
                    // Sinon : un autre écran a pushé par-dessus, ne rien faire ; il gèrera son propre cleanup.
                } catch (_) {
                    /* ignore */
                }
            }
        };
    }, [active]);
}
