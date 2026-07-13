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
        // On empile une entrée d'historique au mount. On NE la retire PAS au cleanup :
        // le cleanup s'exécute AVANT le mount du composant suivant (dans le même commit React),
        // donc appeler history.back() ici déclenche un popstate asynchrone qui vient
        // fermer immédiatement le nouvel écran. En laissant l'entrée s'accumuler,
        // le bouton back natif fait ce qu'on attend : popstate → onBack → setState.
        // Coût : quelques entrées bidon dans l'historique pendant la session (nettoyées à la sortie).
        window.history.pushState({ _suiviBack: 1 }, "");
        const handler = () => {
            const fn = cbRef.current;
            if (typeof fn === "function") fn();
        };
        window.addEventListener("popstate", handler);
        return () => {
            window.removeEventListener("popstate", handler);
        };
    }, [active]);
}
