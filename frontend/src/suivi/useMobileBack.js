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
        window.history.pushState({ _suiviBack: Math.random() }, "");
        let poppedByUser = false;
        const handler = () => {
            poppedByUser = true;
            const fn = cbRef.current;
            if (typeof fn === "function") fn();
        };
        window.addEventListener("popstate", handler);
        return () => {
            window.removeEventListener("popstate", handler);
            // Démontage programmatique (navigation interne, ex: passage d'un écran à un autre plus profond)
            // → on retire l'entrée pushée pour ne pas polluer la stack.
            // Le listener est déjà retiré → history.back() ne déclenchera pas onBack.
            if (!poppedByUser) {
                window.history.back();
            }
        };
    }, [active]);
}
