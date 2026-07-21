# PRD - Application Inventaire EEG (Étiquettes Électroniques)

## Changelog 19/02/2026 (v29 iter33 — Mode Lecture Seule client)

### Demande utilisateur
« J'aimerais donner un lien aux clients (le même pour tous) où ils peuvent naviguer sans faire de changement — pas juste ajouter un mot à l'URL, il faut que ce soit sécurisé. »
Décision : option A — un seul lien global permettant de choisir n'importe quel magasin publié.

### Fix appliqué
**Backend (`suivi_deploy.py`)**
- Nouveau router `viewer = APIRouter(prefix="/suivi-view")` **strictement GET-only** (aucune route d'écriture n'existe = sécurité par construction).
- Endpoints GET : `/stores`, `/{upload_id}`, `/{upload_id}/materiel[/{nuit}]`, `/{upload_id}/photo/{photo_id}`, `/{upload_id}/rapport-nuit/{nuit}` — tous requièrent `?token=…` validé via `secrets.compare_digest`.
- Token global stocké dans `db.settings` (`key: "suivi_viewer_token"`), généré à la volée à la première demande.
- Endpoints admin : `GET /api/suivi/viewer-link` (récupère/crée) + `POST /api/suivi/viewer-link/rotate` (régénère, invalide les anciens liens — admin/superadmin uniquement).
- Placés AVANT `/{upload_id}` pour éviter collision de routage FastAPI.

**Frontend**
- Nouveau composant `frontend/src/suivi/ViewerApp.jsx` (mode Lecture Seule, header violet, bandeau « Mode lecture seule — Client », picker de magasins publiés).
- Route `/suivi/view?token=…` gérée dans `App.js` — indépendante de `/suivi` (chef) et `/suivi/terrain` (équipe).
- `api.js` : `makeActions` accepte `{ readOnly, tokenParam }` — en mode viewer, toutes les fonctions d'écriture sont neutralisées (toast « Mode lecture seule — aucune modification possible ») et les GET reçoivent `?token=…`.
- `SuiviStock`, `SuiviCam`, `SuiviNuits` (NightScreen + AlleeScreen) modifiés pour respecter `actions.readOnly` : inputs verrouillés (fond sombre + cursor-not-allowed), boutons Valider/Bloquer/Reset/Photo/Incident/Rapatriement/`Ajouter allée` masqués, sélecteur de nuit remplacé par un badge.
- `SuiviDashboard.PublishCard` : ajout d'une carte violette **« Partage client — Lecture seule »** avec URL + bouton Copier + bouton Régénérer.

### Sécurité
- Défense en profondeur : (1) le backend n'expose PAS de route d'écriture sur `/suivi-view` (PATCH/POST/DELETE → 404), (2) le token est vérifié à chaque appel, (3) le frontend neutralise toute action d'écriture, (4) la régénération invalide immédiatement tous les liens partagés.
- URL exemple : `https://<host>/suivi/view?token=hjNwqsC4X2BwHZBVeQfm_L45M-T2r_rf`

### Validation
- **18/18 tests pytest OK** dans `backend/tests/test_iter33_viewer_readonly.py` :
  - Token requires auth, idempotent, rotation invalidates old
  - All GET endpoints work with valid token, 401 with bad/missing token
  - **7 write routes tested** (PATCH allee, allee-cam, stock ; POST incident, publish, replan ; DELETE reset) → tous en 404/405 (pas d'écriture possible)
- Validation visuelle Playwright : header violet OK, dashboard sans Publier/Effacer/Replan, écran nuit sans Ajouter/Incident, écran allée sans boutons Valider/Bloquer/Photo, inputs en readonly.
- Régressions : 0 (les 6 échecs pré-existants sur `test_suivi_deploy.py` sont indépendants — dataset schema drift).


## Changelog 13/02/2026 (v28 iter6 — Refonte Suivi Caméras + masquage batterie/software + labels dashboard)

### Demandes utilisateur
1. Retirer partout « batterie caméra » et « software caméra » du Suivi.
2. Rendre la saisie caméra **symétrique EEG** : grille par produit (Caméras blanches/noires + fixations Captana) avec Posé/Géoloc individuel — permet alertes stock par produit.
3. Clarifier les KPIs dashboard « POSE PRODUITS » / « GÉOLOCALISATION » (labels flous).

### Fix appliqué
- **`suivi_deploy.py`** : constante `SUIVI_HIDDEN_DESIGNATIONS = {"batterie caméra", "software caméra"}` + helper `is_hidden_in_suivi()`. Filtre appliqué dans `_materiel_par_allee` → propage à tous les écrans (stock, matériel par nuit, écrans allée, exports).
- **`CamAlleeUpdate`** enrichi avec `products: List[ProductEntry]` (mêmes champs que EEG). Champs scalaires `cameras_reel/cameras_geo/fixations_reel` conservés en RÉTROCOMPAT lecture mais désormais **dérivés** de `products` (via `_apply_cam_update`).
- **`_build_cam_state`** : chaque produit cam remonte maintenant `plan`, `reel`, `geo`, `geo_gap`, `is_camera`, `is_fixation`, `is_geo` — mêmes flags que côté EEG.
- **Frontend `SuiviCam.jsx CamAlleeCard`** : grille compacte par produit (5 colonnes : Produit / Prévu / Posé / Géoloc / Δ), 📷 pour caméras, 🔧 pour fixations, colonne Géoloc = « — » pour fixations. Bouton `patchCamAllee` envoie désormais `{products: [{designation, reel/geo}]}`.
- **Dashboard**: KPIs renommés `Saisies posées` / `Saisies géoloc` + tooltip explicatif + petite légende « Rails ES / SA 1.5 / SA 2.1 géolocalisés ».

### Migration
Comme convenu (iter1 option b) : les anciennes saisies scalaires sont **ignorées**. Les poseurs re-saisissent par produit dès la mise en prod.

### Validation
- 14/14 tests pytest OK (dont 6 nouveaux `test_iter32_suivi_cam_products.py`).
- Testing agent iter32 : 100% backend + frontend (grille validée par code review, dataset test sans caméras).



## Changelog 13/02/2026 (v28 iter5 — Storyboard photos inline dans le rapport)

### Demande utilisateur
Ajouter les photos directement dans la feuille Résumé (inline) pour éviter d'ouvrir une feuille séparée — vrai storyboard visuel de la nuit.

### Fix appliqué (`backend/suivi_deploy.py::_rapport_response`)
- Nouvelle section **« 📸 STORYBOARD PHOTOS »** en bas de la feuille Résumé (bandeau bleu Carrefour) : compte total + nombre d'allées concernées.
- Photos groupées par allée avec titre `Allée X · Secteur · Rayon (N photos)`.
- Grille 4 photos par ligne, max 16 photos par allée, image scale 200 px de large.
- Try/except autour de chaque photo pour éviter qu'une image corrompue casse l'export.
- Suppression de la section « Photos » redondante dans la feuille « Détail allées » (renvoie au Résumé).

### Validation
- Export généré OK (200/OK, 5 feuilles).
- Tests régression 18/18 OK.



## Changelog 13/02/2026 (v28 iter4 — Export Excel rapport de nuit refondu)

### Demande utilisateur
« Export Excel précis et ludique qui montre tout ce qui a été fait dans la nuit. »

### Fix appliqué (`backend/suivi_deploy.py::_rapport_response`)
Refonte complète de la 1ʳᵉ feuille (« Résumé N{n} ») :
- **Bandeau titre coloré** : « ⚡ RAPPORT DE NUIT N°X » (fond bleu Carrefour, taille 22, cellules fusionnées).
- **8 cartes KPI colorées** (2 lignes × 4 cards) : EEG posées, prévues, taux de pose, écart, allées validées, à finaliser, non faites, posés sans géoloc. Couleur dynamique selon perf (vert ≥95%, bleu ≥75%, orange ≥50%, rouge sinon).
- **Verdict ludique** en gros (16pt) avec emoji contextuel : ⚡🎉 bravo / ✅ conforme / ⚠️ léger retard / 🚨 retard important.
- **Sections thématiques** avec bandeaux colorés :
  - 📊 Contexte campagne (rythme réel/prévu, cumul, avance/retard)
  - ⚠️ Alertes stock (fond rouge)
  - 🚨 Incidents (avec auteur + horodatage)
  - 💬 Commentaires d'allée (fond orange)
  - 📌 Écarts >5% justifiés
  - 📋 Détail visuel des allées de la nuit (statut avec emoji ⏳✅🚫⚠️, lignes zébrées)

Les 4 autres feuilles ("Détail allées", "Détail produits", "Écart phasage vs réel", "Synthèse déploiement") conservent leurs données brutes complètes pour analyse.

### Validation
- Export généré : 5 feuilles, 11.6 KB, aucune erreur.
- Contenu vérifié via openpyxl : titres, KPIs, verdict, incidents, commentaires, écarts, détails allées tous présents.
- 18/18 tests régression OK.



## Changelog 13/02/2026 (v28 iter3 — Filtre géoloc + badges/modal résumé nuit)

### Demandes utilisateur
1. Filtre rapide « Voir uniquement les manques de géoloc » dans le Dashboard matériel.
2. Dans le Dashboard principal, savoir si une nuit a des commentaires/photos/incidents.
3. Cliquer sur une nuit doit ouvrir les commentaires et photos.

### Fix appliqué (`frontend/src/suivi/` uniquement)
- **SuiviMateriel.jsx EcartRecap** : nouveau toggle « Manque géoloc » (data-testid `ecart-filter-geo-missing`) affiché seulement si `nbGeoMissing > 0`. Il filtre les lignes `is_geo=true` avec `geo < reel`. Fond ambré quand actif.
- **SuiviDashboard.jsx cartes de nuit** : 3 badges optionnels (flag rouge = incidents, message ambré = commentaires, camera bleu = photos) avec compteur. Data-testids : `dash-night-{n}-comment-badge`, `-photo-badge`, `-incident-badge`.
- **NightSummaryModal** : 3 nouvelles sections avant la liste d'allées — Incidents (rouge), Commentaires par allée (ambré), Photos (grille miniatures cliquables → overlay zoom plein écran). Petites icônes 💬/📷 aussi sur chaque ligne d'allée dans la modal si concernée.
- Import de `MessageSquare`, `Camera`, `Flag` (lucide-react) dans SuiviDashboard, `MapPin` dans SuiviMateriel.

### Validation
- Frontend testing_agent iter31 : 100 % OK runtime (filtre géoloc, badges, modal sections). Zoom photo validé par code review.
- Aucun changement backend, aucune régression.



## Changelog 13/02/2026 (v28 iter2 — Fusion agrégée dans le stock du Suivi)

### Demande utilisateur
Simplifier l'affichage stock du Suivi (les poseurs reçoivent UNE seule livraison par ES/SA, sans distinguer ZS/Flèche/Signalétique). **Aucun changement dans l'outil Phasage.**

### Fix appliqué (`backend/suivi_deploy.py` uniquement)
Après la construction de `prod_agg`, fusion agrégée dans le stock :
1. **Zones Saisonnières** : `SA 1.5 (Zone saisonnier)` (1200) → fusionné dans `SA 1.5 (noir)`. `SA 2.1 (Zone saisonnier)` (4800) → fusionné dans `SA 2.1 (noir)`.
2. **Flèches** : toute désignation ou type contenant « flèche » → fusionné dans `ES 1.5 (noir)`.
3. **Signalétique** : rails 1187/1240/1320/990/650/535 mm → fusionnés dans `ES 1.5 (noir)` ou `ES 1.5 (blanc)` selon la couleur.

Les autres écrans (matériel par nuit, écran détail allée, exports Excel de nuit) **conservent** les désignations propres pour la traçabilité terrain.

### Rollback
Modifications de mes précédents patches sur `server.py` (Excel Récap Carrefour, PPTX) annulées via `git checkout backend/server.py`.

### Validation
- `test_iter31_stock_fusion.py` : 5/5 tests unitaires OK (ZS, flèches, signalétique couleurs, fallback, préservation autres produits).
- Régression : 18/18 tests iter28/29/30/31 OK.
- Test bout-en-bout curl : aucune Zone Saisonnière visible dans le stock, quantités fusionnées correctement.



## Changelog 13/02/2026 (v28 iter1 — Distinction POSE vs GÉOLOCALISATION dans Suivi)

### Contexte
L'utilisateur veut que la POSE (Rails ES, EEG SA 1.5, EEG SA 2.1, Caméras) soit clairement distinguée de la GÉOLOCALISATION dans tous les dashboards et exports. Règle métier : on peut poser sans géolocaliser mais pas l'inverse. Les autres familles (ES 1.5, ES 2.1, SA freezer, SA 4.2, flèches) ne sont PAS géolocalisées. Option retenue : **B** — conserver les 2 champs numériques Posé/Géoloc existants, focus sur les dashboards + exports.

### Fix appliqué
- **`backend/suivi_deploy.py` L40** : `GEO_KEYS = ["rails_es", "sa_15", "sa_21_std"]` (retiré `sa_21_freezer`).
- **`_materiel_nuit`** : calcule maintenant `totals_geo` par désignation en parallèle des `totals_reel`. Chaque item d'écart (nuit et allée) remonte `geo`, `family`, `is_geo`.
- **`SuiviMateriel.jsx` EcartRecap** : ligne d'écart avec badge orange **`GÉO`** pour les produits `is_geo=true`, affichage `Prévu / Posé / Géoloc (%)` en ligne, alerte ambre si géoloc < posé.
- **Export Excel rapport-nuit** : bloc Caméras a maintenant 9 colonnes (Allée / Secteur / Prévu / Posées / Géoloc / **Fixations prévues** / Fixations posées / Statut / Commentaire).
- **`SuiviCam.jsx`** : les fixations caméra prévues (`fix_plan`) sont déjà affichées à côté des posées (`fix_reel`). Aucun changement UI nécessaire.

### Validation
- Backend : 20/20 tests pytest OK, régression iter28/29/30 → 13/13 tests OK.
- Frontend : badge GÉO + colonne Géoloc affichés correctement, zéro erreur JS.
- Test bout-en-bout curl : SA 1.5 noir (plan=15, reel=12, geo=7) → `family=sa_15`, `is_geo=true`, `geo=7` remontés correctement.

### Reset des saisies
Pas nécessaire pour l'option B : la structure de données `{reel, geo}` existait déjà et n'a pas changé. Les saisies historiques restent valides. Le champ `geo` sur d'anciens produits `sa_21_freezer` est simplement ignoré à l'affichage (plus flaggé `is_geo`).



## Changelog 13/02/2026 (v27 iter7 — Cohérence visuelle Phasage)

### Bugs remontés (PDF « Erreur tableau.pdf »)
1. **Flèche 1 vs 2** — Récap par nuit : la colonne « EEG ES » par nuit N'INCLUAIT PAS le saisonnier, mais la ligne TOTAL l'INCLUAIT via `grandTotals.seasonal`. Or les Zones Saisonnières sont DÉJÀ comptées dans `sa_inst_15` (1200) + `sa_inst_21` (4800) = 6000 → **doublon numérique** de 6000 EEG dans le total du récap.
2. **Flèche 3** — Tableau Plan d'attribution par allée : la colonne « EEG » incluait `instTotal` (SA à installer VT) → mélange EEG ES + SA VT, incohérent avec la colonne « EEG ES » du récap à droite.

### Fix appliqué (`frontend/src/components/PhasageTab.jsx`)
- **Ligne 918** : total colonne EEG ES du récap → retrait de `+ grandTotals.seasonal`.
- **Ligne 936** : total colonne Total du récap → retrait de `+ grandTotals.seasonal`.
- **Ligne 691** : colonne renommée « EEG » → « EEG ES » (tableau Plan d'allée).
- **Ligne 764-768** : formule EEG ES par allée → retrait de `+ instTotal` ; ZS → 0 (les SA sont déjà dans les colonnes dédiées).
- Tooltips clarifiés partout.

### Cohérence garantie (post-fix)
- Somme des lignes « EEG ES » = ligne TOTAL colonne « EEG ES » ✓
- Ligne TOTAL colonne « Total » du récap = KPI « Total EEG » en haut ✓
- Colonne « EEG ES » du tableau Plan d'allée = même sémantique qu'à droite ✓

### Tests
- `/app/backend/tests/test_iter30_phasage_recap_totals.py` : 2/2 tests OK (reproduction fidèle du calcul JS).



## Changelog 13/02/2026 (v27 iter6 — Prévention perte de saisie sur 401)

### Contexte
L'utilisateur a perdu 2 h de saisie dans le Phasage à cause d'une erreur 401 silencieuse. Le token access de 24 h expirait après une nuit, chaque PATCH remontait en 401 sans alerter → au refresh, l'ancien état revenait.

### Fix appliqué (4 mesures)
1. **TTL access token : 24 h → 8 jours** (`backend/auth.py` L26). Refresh token : 7 j → 30 j.
2. **Intercepteur axios global** (`frontend/src/contexts/AuthContext.jsx`) : sur toute réponse 401 (hors endpoints d'auth), appelle silencieusement `/api/auth/refresh` puis rejoue la requête. Une seule promesse de refresh partagée pour éviter les avalanches.
3. **Modal bloquant SessionLost** (data-testid=`session-lost-modal`) : affiché uniquement si le refresh échoue (refresh_token expiré / cookies effacés). Email pré-rempli, champ password. Reconnexion sans quitter la page → l'état React (données saisies) est préservé.
4. **Indicateur autosave visible** dans PhasageTab : `Sauvegarde…` → `✓ Sauvegardé à HH:MM` → `⚠️ NON SAUVEGARDÉ — {erreur}` (rouge, très visible). L'utilisateur voit toujours si ses modifs sont bien enregistrées.

Bonus : `App.js` utilise `previousUserIdRef` pour ne PAS ré-initialiser l'onglet actif après un relog silencieux (même utilisateur). Événement `auth-session-recovered` dispatché après relog → force `phasageVersion++` et refetch des composants Phasage/Cam qui affichaient l'erreur 401.

### Validation
- **Backend** : login/refresh/me OK via curl. Aucune régression sur les 28 tests pré-existants.
- **Frontend** : iter28 = 100 % OK, zéro erreur JS. Flow relog → onglet préservé → composants refetch.



## Changelog 13/02/2026 (v27 iter5 — Indicateur visuel ZS dans le Suivi mobile)

### Demande utilisateur
« Ajouter un indicateur visuel dédié pour distinguer les Zones Saisonnières des allées standard, afin d'éviter les confusions de comptage par les poseurs sur le terrain. »

### Fix appliqué (`frontend/src/suivi/SuiviNuits.jsx`)
- Import de `Sun` (lucide-react).
- Détection `isSeasonal = a.secteur === "Zone saisonnier"` (aligné backend v27).
- **Liste allées d'une nuit** : fond `bg-amber-950/20 border-amber-800/60`, badge `bg-amber-600` avec icône Sun, pastille orange `SAISON` en tooltip explicatif « Zone saisonnière — posée par la VT (400 SA 1.5 + 1600 SA 2.1) ».
- **Écran détail allée** (`AlleeScreen`) : bloc en-tête ambré, badge principal `ZS1` (au lieu de `Allée ZS1`) avec icône Sun, pastille orange `SAISON · VT`.
- **Panneau de rapatriement** (« Ajouter allée ») : badge ambré + icône Sun sur les ZS proposées.
- Data-testids ajoutés : `allee-seasonal-badge-ZS{n}`, `allee-screen-seasonal-badge-ZS{n}`.

### Validation
- 100% frontend testé bout-en-bout via testing_agent_v3_fork (iter24).
- Régression OK : allées standard gardent leur style gris sans marqueur SAISON.



## Changelog 13/02/2026 (v27 iter4 — SUIVI de déploiement synchronisé avec Phasage pour les Zones Saisonnières)

### Problème remonté
Après le fix v27 côté Phasage (ZS = 400 SA 1.5 + 1600 SA 2.1 posées par la VT), le module « Suivi de déploiement » ignorait totalement les Zones Saisonnières : elles n'apparaissaient ni dans l'état, ni dans le matériel par nuit. Les poseurs n'avaient donc aucune façon de valider les SA VT-posées des ZS.

### Root cause
`suivi_deploy.py::_build_state` construisait `by_uid` uniquement à partir de `summary["allees"]`, en ignorant `summary["seasonal_zones"]`. Les ZS étaient présentes dans `es.rows` (via `nuit_by_uid`), mais leur nœud allée retournait `{}` → plan = 0 partout. Aucun produit synthétique n'était non plus injecté dans `matidx`.

### Fix appliqué — RÉUTILISE la logique Phasage existante (pas de duplication)
- `build_suivi_router` accepte désormais `full_allee_index` (fonction `_full_allee_index` de server.py) comme dépendance injectée. **Source unique de vérité** pour les ZS, partagée avec les exports Excel/PPTX du Phasage.
- Nouvelle fonction `_apply_seasonal_zones(matidx, by_uid, summary)` dans `suivi_deploy.py` :
  1. Appelle `full_allee_index(summary)` → récupère les nœuds ZS canoniques (mêmes champs que ceux utilisés dans le Tableau date, Récap Carrefour et PPTX slide 11).
  2. Injecte ces nœuds dans `by_uid` (secteur='Zone saisonnier', rayon, sa_15=400, sa_21_std=1600, is_seasonal=True).
  3. Fabrique 2 produits synthétiques par ZS pour la saisie terrain : `SA 1.5 (Zone saisonnier)` et `SA 2.1 (Zone saisonnier)`.
- `_sa_families_off` et `_sa_families_off_for` bypassent les ZS (`if a.get("is_seasonal"): return set()`) — cohérent avec `compute_node_sa_install` qui renvoie déjà sa_15+sa_21 quel que soit le cfg pour les ZS.
- Nouveau helper `_materiel_par_allee_with_zs(d)` utilisé dans `_materiel_overview`, `_materiel_nuit` et `_guarded_allee_update`.
- `_materiel_context` inclut les ZS canoniques dans son `by_uid` (pour que `_filter_materiel_node` en mode EEG applique correctement le bypass).

### Impact validé E2E
- `GET /api/suivi/{upload_id}` (magasin +10000m² = 3 ZS) : les 3 ZS apparaissent avec `plan.sa_15=400` + `plan.sa_21_std=1600`, secteur='Zone saisonnier', rayon='Zone saisonnier 1/2/3'. ✅
- `state.stats.eeg_prevues` = 6335 (inclut les 6000 EEG des 3 ZS). ✅
- `GET /api/suivi/{upload_id}/materiel/{nuit}?mode=eeg` : 3 allées ZS avec produits `SA 1.5 (Zone saisonnier)` × 400 et `SA 2.1 (Zone saisonnier)` × 1600 chacune. ✅
- Bypass sa_install : même avec `answered=true, enabled=false`, les ZS restent disponibles. ✅

### Tests
- `tests/test_iter29_suivi_seasonal_zones.py` (3 tests unitaires — classify_family, compute_node_sa_install, structure summary).
- `tests/test_iter29_e2e_suivi_seasonal_zones.py` (4 tests E2E HTTP — state, materiel, sa_install off, stats).
- `tests/test_iter28_zone_saisonniere_sa_mag.py` (8 tests régression Phasage — inchangés).
- **15/15 tests iter28+iter29 passent. 0 régression** sur le reste (28 failed pré-existants avant/après).



## Changelog 13/02/2026 (v27 iter3 — Fix double comptage Zone Saisonnière dans Récap par nuit)

### Problème remonté
L'utilisateur a montré le Récap par nuit affichant Nuit 1 = EEG ES 2000 + SA 1.5 400 + SA 2.1 1600 = **Total 4000** (au lieu de 2000). Les étiquettes ZS étaient comptées deux fois : une fois en « EEG ES » (héritage ancien) + une fois via SA 1.5 / SA 2.1.

### Root cause (`PhasageTab.jsx::eegPerNight`)
```js
const eegPerNight = (esBrut, seasonal, bonus, fleches, sa15, saInst) =>
    esBrut + bonus + fleches + sa15 + seasonal + saInst;
```
Le paramètre `seasonal` correspondait à l'ancienne sémantique où les ZS étaient de l'ES saisonnier. Sous la v27 (ZS = SA VT-posé), les valeurs sont désormais dans `sa_inst_15` et `sa_inst_21` (via `computeNodeSaInstall`), et il ne faut plus les rajouter en `seasonal`.

### Fix appliqué
- `eegPerNight` : suppression de `seasonalNuit` du calcul (le paramètre est conservé dans la signature pour rétrocompat des call sites, ignoré via eslint-disable).
- `totalEEG` (header) : rétablit `sa21Saisonnier` (les ZS ne sont pas dans `saInstallTotal` retourné par `computeSaToInstall(breakdown)` car les zones sont séparées du breakdown standard).

### Impact UI post-redeploy
- Récap par nuit avec 1 ZS : EEG ES = 0, SA 1.5 = 400, SA 2.1 = 1600, **Total = 2000** ✅
- Récap par nuit avec 2 ZS : EEG ES = 0, SA 1.5 = 800, SA 2.1 = 3200, **Total = 4000** ✅
- Header « EEG à poser » continue d'inclure les ZS (via sa21Saisonnier=6000) ✅
- Tableau date UI : idem, plus de double comptage ✅

### Validé
- 61/61 tests backend passent (aucune régression).


## Changelog 13/02/2026 (v27 iter2 — Frontend aligné sur ZS VT-posées)

### Problème remonté
Après le fix backend v27, l'UI phasage affichait toujours :
- Dropdown ZS : "Zone saisonnier 1 (+2000 EEG)" (ancienne étiquette)
- Récap par nuit : SA 1.5 = 0, SA 2.1 = « — » (dash), Total = 0 (le split 400/1600 n'était pas remonté)

### Cause
Le frontend a sa propre logique JS pour construire l'`alleeIndex` et calculer les totaux du Récap par nuit (indépendante du backend). Elle n'était pas mise à jour.

### Fix appliqué (frontend)
1. **`PhasageTab.jsx`** `alleeIndex` : les nœuds ZS ont désormais `sa_15 = z.sa_15`, `sa_21 = z.sa_21`, `sa_21_std = z.sa_21`. Rétrocompat gérée : si le backend renvoie une ZS sans split explicite, tout va en SA 2.1.
2. **`PhasageTab.jsx`** dropdown label : `"🌶 {label} ({sa_15} SA 1.5 + {sa_21} SA 2.1)"` — remplace l'ancien "+X EEG".
3. **`SaInstallPanel.jsx`** `computeNodeSaInstall` : les ZS retournent `{sa_15: node.sa_15, sa_21: node.sa_21_std}` (avant : `{0, 0, ...}`).
4. **`SaInstallPanel.jsx`** `nodeSaTotal` : renvoie `sa_15 + sa_21` pour les ZS (avant : 0).
5. **`TableauDateTab.jsx`** : nœud ZS construit avec split. Calcul totalsByNight utilise `sa_15z + sa_21z` en EEG (au lieu de `seasonal_eeg`).

### Validé
- 61/61 tests backend continuent de passer.
- Le Récap par nuit UI, le Tableau date UI et le Panneau SA à installer sont maintenant tous alignés sur la nouvelle sémantique.


## Changelog 13/02/2026 (v27 — Zones Saisonnières = SA VT-posées avec split 400/1600)

### Changement métier
Les Zones Saisonnières changent de sémantique :
- **Avant** : 3 zones de 2000 SA 2.1 chacune, posées par le magasin (SA magasin).
- **Après** : 3 zones de **400 SA 1.5 + 1600 SA 2.1** chacune (2000 par zone), **posées par la VT**.
- Totaux : +10 000 m² = 4800 SA 2.1 + 1200 SA 1.5 (au lieu de 6000 SA 2.1). -10 000 m² = 3200 SA 2.1 + 800 SA 1.5.

### Fichiers modifiés (backend/server.py)
1. **`compute_phasage_summary`** : `seasonal_zones` désormais avec `{id, label, sa_15: 400, sa_21: 1600, eeg: 2000, is_seasonal: True}` (au lieu de `eeg: 2000` seul).
2. **`_full_allee_index`** : les nœuds ZS ont `sa_15=z.sa_15`, `sa_21=z.sa_21`, `sa_21_std=z.sa_21`, `es_15=es_21=0` (ne sont plus de l'ES). Rétrocompat : ZS sans split → tout en SA 2.1.
3. **`compute_node_sa_install`** : les ZS retournent maintenant `{sa_15: node.sa_15, sa_21: node.sa_21_std}` (au lieu de `{0, 0, 0, 0}`). Elles sont **toujours** installées par la VT.
4. **`node_sa_total`** : retourne `sa_15 + sa_21` pour les ZS (au lieu de 0).
5. **`_aggregate_phasage_for_export`** : plus de branche spéciale iter28 pour ZS — la logique standard gère tout naturellement (`sa_mag = 0` pour ZS car `node_sa_total(zs) = inst_total`).
6. **`_write_code_couleur_sheet`** (Excel Tableau date) : branche `if zone:` ajoute `sa_15 + sa_21` à `t["eeg"]`, ne touche PLUS à `t["sa"]`.

### Impact sur les exports
- **Colonne « EEG ES+SA »** : les ZS y sont désormais comptées (VT-posé).
- **Colonne « SA 1.5 »** : ZS contribuent (400 par zone).
- **Colonne « SA 2.1 »** : ZS contribuent (1600 par zone).
- **Colonne « SA magasin »** : ZS n'y sont PLUS (elles sont maintenant VT-posées).

### Validé
- Iter28 réécrit (8 tests) + 53 régression = **61/61 backend, 100%**.
- Test intégré : Nuit avec 1 ZS → EEG ES+SA=2000, SA magasin=0, sa_inst_15=400, sa_inst_21=1600 ✅.
- Nuit avec 2 ZS → EEG ES+SA=4000, SA magasin=0, sa_inst_15=800, sa_inst_21=3200 ✅.


## Changelog 13/02/2026 (v27 — Fix Zones Saisonnières dans PPTX slide 11)

### Bug root cause (enfin identifié après iter26/iter27)
L'utilisateur a partagé le tableau Excel montrant Nuits 17-18 avec Zones Saisonnières (SA magasin 2000 et 4000). Le PPTX slide 11 restait tronqué. Analyse XML du fichier généré : l'extension de table à 19 colonnes fonctionnait, mais **le pipeline agrégat retournait `sa_mag=0` pour les nuits Zone Saisonnière uniquement**.

Cause : `_aggregate_phasage_for_export` utilisait `node_sa_total(node)` pour calculer `sa_mag`. Or `node_sa_total` retourne **0 pour les zones saisonnières** (par design : `is_seasonal=True → return 0.0`). Résultat : `sa_mag = max(0, 0 - 0) = 0` alors que l'Excel `_write_code_couleur_sheet` ajoutait directement `zone.eeg` en SA magasin.

### Fix appliqué
Dans `_aggregate_phasage_for_export` (server.py), branche dédiée pour les Zones Saisonnières :
```python
if node.get("is_seasonal"):
    b["sa_mag"] += float(node.get("seasonal_eeg") or 0)
else:
    b["sa_mag"] += max(0.0, node_sa_total(node) - sa_inst_total)
```

Résultat pour Nuit 17 (1 ZS) : `sa_mag = 2000` ✅ (auparavant 0).
Résultat pour Nuit 18 (2 ZS) : `sa_mag = 4000` ✅ (auparavant 0).

### Validé
- Iter28 : 4 nouveaux tests dédiés (zone_populates_sa_mag, 2zs_sums, es_only_includes_zone, nights_beyond_nb_nuits) + 53 régression = **57/57 backend, 100%**.
- Test intégré simulé : dataset avec `nb_nuits=16` + ZS sur Nuits 17-18 → aggregate populé pour toutes les nuits avec les bonnes valeurs (Nuit 17: es_only=2000/sa_mag=2000, Nuit 18: es_only=4000/sa_mag=4000).
- Ce fix + iter25/iter26/iter27 rendent enfin le slide 11 PPTX 100 % cohérent avec le tableau Excel.


## Changelog 13/02/2026 (v26 — Robustification all_nights pour Zones Saisonnières au-delà de nb_nuits)

### Contexte
L'utilisateur a partagé le tableau Excel (fonctionnel — Nuits 17-18 visibles dans un 2e bloc avec Zones Saisonnières : Nuit 17 = 4176 / 2000, Nuit 18 = 4000 / 4000). Le fix iter27 utilisait `nb_nuits` config du phasage, mais si les Zones Saisonnières sont placées **au-delà** de `nb_nuits` (via `es.rows` sans que `nb_nuits` soit augmenté), les dernières nuits restaient absentes du PPTX.

### Fix
- `_adapter` (`server.py`) : `max_night = max(nb_nuits, max_nuit_trouvé_dans_es.rows, max(nuit_es.keys() | nuit_cam.keys()))` — combine 3 sources pour ne rater aucune nuit du planning.
- `all_nights` est ensuite étendu à `sorted(all_keys | range(1, max_night+1))`.
- L'aggregate `_aggregate_phasage_for_export` gère déjà les Zones Saisonnières via `_resolve_idx_node` (qui remonte `es_21=sz_eeg`, `sa=sz_eeg`) — donc `es_per_nuit[17]/[18]` sont bien populés côté agrégation.

### Validé
- 53/53 tests iter21→27 + suivi_deploy passent.
- Vérif python-pptx sur preview (10 nuits) : slide 11 = 11 cols, toutes remplies, aucun attribut de fusion.
- ⚠ Test réel avec 18 nuits + Zones Saisonnières sur Nuits 17-18 à valider en prod après redeploy — le dataset preview ne contient pas cette configuration.


## Changelog 13/02/2026 (v25 — Fix PJ3 : nuits manquantes dans PPTX slide 11)

### Bug rapporté (récurrent malgré iter26)
Après le fix iter26 des calculs, le slide 11 PPTX « Plan de phasage EEG et rails par nuit complet (18 nuits) » affichait toujours seulement 16 nuits sur 18. Les 2 dernières cellules restaient vides à droite du tableau.

### Root cause double
1. **Adapter (`server.py::_adapter`)** : `all_nights = sorted(nuit_es.keys() | nuit_cam.keys())` — ne contenait que les nuits ayant des allées **assignées**. Si le phasage a `nb_nuits=18` mais que seules 16 nuits ont des allées ES assignées, les nuits 17-18 disparaissaient.
2. **PPTX (`pptx_export.py::_clone_last_col`)** : lors de l'extension de la table, les cellules clonées héritaient des attributs de fusion (`gridSpan`/`hMerge`) de la dernière colonne du template — devenant des « cellules fantômes » invisibles.

### Fix appliqué
- **Adapter** : `all_nights = sorted(all_keys) | range(1, nb_nuits+1)` — complète avec **toutes** les nuits planifiées ES (aligné sur le comportement Excel `Tableau date`).
- **`_clone_last_col`** : retire systématiquement `gridSpan`/`hMerge`/`rowSpan`/`vMerge` sur chaque cellule clonée.
- Nouveau helper **`_unmerge_row_cells(table, row_idx, n_cols)`** appelé au début de `_fill_slide_11` sur les 4 lignes du tableau — nettoie les merges hérités du template avant écriture.

### Validé
- Iter27 : 3 nouveaux tests dédiés + 50 régression = **53/53 backend, 100%**.
- Vérification python-pptx sur l'export du dataset test (10 nuits) :
  - Avant : slide 11 = 3 cols × 4 rows (uniquement Nuit 1, Nuit 2) ❌
  - Après : slide 11 = **11 cols × 4 rows** (Nuit 1 → Nuit 10, toutes remplies) ✅
  - Aucun attribut de fusion sur les cellules ✅


## Changelog 13/02/2026 (v24 — Fix Tableau date « EEG ES+SA » et « SA magasin »)

### Bugs remontés par l'utilisateur (PJ2/PJ3 sur PPTX)
Dans la slide « Plan de phasage EEG et rails par nuit complet » (PPTX slide 11 + feuille Excel « Tableau date ») :

1. **Ligne « EEG ES+SA »** affichait uniquement l'ES pur (155 pour Nuit 2 du dataset test) alors que le label sous-entend ES + SA à installer (215 attendu).
2. **Ligne « SA magasin »** affichait le total SA du nœud (incluant les SA à installer). Résultat : valeurs incohérentes entre le tableau Récap par nuit de l'UI (colonne « SA magasin » quasi vide) et la ligne SA magasin de la slide (2499, 2541, 1549, 1720…).

### Root causes
- `_write_code_couleur_sheet` (Excel Tableau date) : `t["eeg"] += base + bonus + 0` (SA jamais ajouté hors mag2) et `t["sa"] += node.get("sa")` = **total SA du nœud** au lieu du reliquat magasin.
- Adapter PPTX (`_adapter`) : `totals_by_nuit[n]["eeg"] = nuit_es[n]["eeg"]` = ES pur (après iter24) → cohérent AVEC la Récap par nuit mais **incohérent** avec le label « EEG ES+SA » du slide 11.

### Fix appliqué
**Excel `_write_code_couleur_sheet`** :
- `t["eeg"] = pure ES + bonus rails + flèches + SA à installer` (aligné label ES+SA).
- `t["sa"] = max(0, SA total node - SA à installer)` = **SA magasin** au sens VT (le reliquat qui reste posé par le magasin hors phasage).

**PPTX Adapter (`server.py::_adapter`)** :
- `totals_by_nuit[n]["eeg"] = es_only + Σ(sa_inst_*)` — utilise les 4 sous-familles de SA à installer déjà calculées par `_aggregate_phasage_for_export`.
- `totals_by_nuit[n]["sa"] = es_node["sa_mag"]` — reliquat magasin déjà correctement calculé côté agrégation.

### Validé
- Iter26 : 3 nouveaux tests + 47 régression = **50/50 backend, 100%**.
- Vérification dataset test (Nuit 2, 155 ES pur + 60 SA à installer) :
  - Avant : « EEG ES+SA » = 155 ❌ · « SA magasin » = total SA du node (60) ❌
  - Après : « EEG ES+SA » = **215** ✅ · « SA magasin » = 0 ✅
- ⚠ Le point PJ3 (nuits 17-18 manquantes sur le slide 11) n'est **pas reproductible** dans le preview (dataset limité à 10 nuits). Le code `_ensure_table_cols(t, 1 + len(all_nights))` étend correctement la table jusqu'à `len(all_nights)` colonnes. À valider en prod après redeploy — si le problème persiste, il vient probablement d'un template PPTX avec `tblGrid` figé qui ne se prolonge pas ; il faudra alors examiner le template PowerPoint source.


## Changelog 13/02/2026 (v23 — Rebrand bleu Carrefour + contrôle de cohérence à l'upload)

### Rebrand couleur (vert → bleu Carrefour #005BAB)
Objectif : différencier visuellement le nouvel outil de l'ancien (qui reste vert) pour éviter que les utilisateurs se trompent.
- **264 occurrences** remplacées automatiquement sur ~30 fichiers frontend + backend :
  - Tailwind `emerald-*` → `blue-*` (login, dashboards, boutons, tabs, alerts, phase picker, écarts, matériel...).
  - Excel exports : `#056839` (vert foncé) → `#005BAB` (bleu Carrefour) pour headers de feuille.
  - Excel fond conforme : `#D1FAE5` (vert clair) → `#DBEAFE` (bleu clair).
  - Excel accent : `#059669` → `#0369A1` (sky-700).
- Header de l'app avait déjà `#005BAB` — désormais cohérent avec le reste de l'UI.
- Validé par screenshots preview : login, phase picker (EEG en bleu foncé), suivi tabs, matériel & écart phasage — tout est aligné.

### Contrôle de cohérence automatique à l'upload (`server.py::_compute_coherence_warnings`)
Nouvelle fonction appelée à chaque `/upload-excel` qui inspecte le DataFrame et retourne des warnings structurés.

**Codes détectés** :
- `qty_negative` (**error**) — quantités négatives présentes.
- `qty_non_numeric` (warning) — quantités illisibles (texte / formule cassée).
- `empty_es/sa/rail/camera` (info) — famille présente dans les types mais totalise 0.
- `missing_column_secteur/rayon` (warning) — colonnes clés absentes.
- `sa_ratio_high` (warning) — SA > 2× ES pur, potentiel double comptage source.
- `few_rows` (warning) — fichier < 5 lignes.
- `check_failed` (info) — filet de sécurité si l'inspection plante sur un fichier atypique.

**Restitution frontend** (`App.js::handleUpload`) : chaque warning est affiché sous forme de toast persistant (8s) après le toast succès. Le niveau détermine l'icône :
- `error` → toast rouge « ⚠ Anomalie détectée ».
- `warning` → toast ambré « Cohérence — attention ».
- `info` → toast neutre « Cohérence ».

**Réponse API** enrichie de `coherence_warnings: []` dans le retour de `POST /api/upload-excel`.

### Validé
- Iter25 : 4 nouveaux tests + 43 régression = **47/47 backend, 100%**.
- Test manuel curl OK : fichier avec 1 qty négative + ratio SA/ES = 3.4 → détecte `qty_negative` (error) + `sa_ratio_high` (warning).
- Screenshot preview post-rebrand OK sur login, suivi et main app.


## Changelog 13/02/2026 (v22 — Fix double comptage colonne « EEG ES » exports Excel/PPTX)

### Bug rapporté par l'utilisateur
Les tableaux Excel exportés (Récap par nuit + Semaine Sx) et les slides PPTX affichaient dans la colonne « EEG ES » la valeur du **total EEG à poser** (ES + SA à installer) au lieu du **pur ES**. Comme les SA sont déjà affichées dans leurs propres colonnes (SA 1.5 / SA 2.1 / SA 2.1 frz / 4.2/4.2 WP), il y avait double comptage.

### Root cause (`server.py::_aggregate_phasage_for_export`)
Le champ `b["es"]` cumulait successivement :
1. Pur ES (es_15 + es_21 + bonus rails + flèches)
2. **+ SA à installer** (sa_inst_15 + sa_inst_21 + sa_inst_freezer + sa_inst_42)

Puis ce même `b["es"]` était utilisé partout : indicateurs globaux du dashboard (correct) MAIS aussi colonne « EEG ES » des tableaux (incorrect).

### Fix appliqué
- Nouveau champ `b["es_only"]` = pur ES uniquement (ES 1.5 + ES 2.1 + bonus rails + flèches).
- `b["es"]` conservé pour rétrocompatibilité (dashboards / indicateurs globaux « EEG à poser total »).
- `_write_recap` et `_write_week_sheets` (Excel) → colonne « EEG ES » utilise désormais `es_only`.
- `_adapter` pour PPTX → champ `"eeg"` reçoit `es_only` (fix étendu aux slides Récap et Semaine Sx du PowerPoint).
- Nouveau champ `"eeg_total"` (= `es`) disponible dans l'adapter PPTX si besoin d'un indicateur ES+SA cumulé ailleurs.

### Validé
- Iter24 : 3 nouveaux tests dédiés + 40 régression = **43/43 backend, 100%**.
- Vérification manuelle sur dataset test (1 allée Nuit 2, es_15=105, es_21=50, SA à installer=60) :
  - Avant : EEG ES = 215 (155 pur ES + 60 SA doublement comptées)
  - Après : EEG ES = **155** ✅


## Changelog 13/02/2026 (v21 — Feuille Excel "Écart phasage vs réel")

Extension du rapport Excel de nuit : nouvelle feuille dédiée qui reprend le récap d'écart affiché dans l'app.

### Backend (`suivi_deploy.py::_rapport_response`)
- Nouvelle feuille **"Écart phasage vs réel"** insérée entre "Détail produits" et "Synthèse déploiement".
- Génère un tableau par bloc (EEG + Caméras si applicable) avec :
  - Bandeau de mini-KPI : Conforme (fond vert) · Bonus (fond ambre) · Sous-livré (fond rouge).
  - Colonnes : Désignation · Type · Prévu · Réel · Δ · Écart % · Statut.
  - Tri prioritaire : **manques d'abord** (action logistique urgente), puis bonus, puis conforme.
  - Ligne **TOTAL** en gras avec somme prévu/réel/delta + écart global %.
- Ne s'affiche que si au moins un réel a été saisi pour la nuit (sinon la feuille est omise pour ne pas polluer).

### Validé
- Iter23bis : 5/5 tests iter23 + 35/35 régression = **40/40 backend, 100%**.
- Test `test_rapport_nuit_two_sheets_with_details` mis à jour pour accepter l'ajout de la nouvelle feuille.
- Curl E2E OK sur preview : feuille présente, KPIs corrects, tri par statut respecté, total agrégé.


## Changelog 13/02/2026 (v20 — Vue "Écart phasage vs réel" fin de nuit)

Nouvelle fonctionnalité proposée et confirmée par l'utilisateur : à la fin de chaque nuit dans l'onglet **Matériel**, un récap automatique compare **plan phasage vs réel posé** et catégorise chaque produit.

### Backend (`suivi_deploy.py::_materiel_nuit`)
- Chaque appel `GET /materiel/{nuit}?mode=eeg|cam` retourne désormais :
  - `ecarts[]` : liste des produits avec `designation`, `type`, `plan`, `reel`, `delta`, `status` (`conforme`/`bonus`/`manque`).
  - `ecart_stats` : `nb_saisis`, `nb_conforme`, `nb_bonus`, `nb_manque`, `nb_allees_validees/bloquees/a_faire`, `complete` (booléen).
  - Chaque `allees[i]` gagne aussi son propre `ecarts[]` et `status` pour le drill-down.
- Règle de classification : `conforme` si `|delta|/plan ≤ 5%`, `bonus` si `delta > 0` et écart > 5%, `manque` si `delta < 0` et écart > 5%.
- Mode CAM : le réel `cameras_reel` / `fixations_reel` est **réparti proportionnellement** aux quantités prévues par produit (même logique que le stock).

### Frontend (`SuiviMateriel.jsx::EcartRecap`)
- Nouvelle section affichée sous les allées d'une nuit dans le drill-down Matériel.
- Trois mini-KPI colorés : Conforme (vert), Bonus posé (bleu), Sous-livré (rouge).
- Filtre par catégorie (Tous / Conforme / Bonus / Manque) + pagination "Voir les X autres produits" au-delà de 8.
- Badge NUIT VALIDÉE si toutes les allées de la nuit sont validées, sinon EN COURS.
- Icônes CheckCircle2 / TrendingUp / TrendingDown selon le statut.

### Validé
- Iter23 : 4/4 nouveaux tests + 35/35 régression = **39/39 backend, 100%**.
- Screenshot preview OK : Nuit 2 EEG affiche 3 conformes / 2 bonus / 1 manque avec filtres opérationnels.


## Changelog 13/02/2026 (v19 — Fix Matériel affichait toujours caméras/SA-off + Matériel onglet Caméra)

### Bug fix critique — Matériel filtrait mal
- L'utilisateur a rapporté que malgré le split UI Phasage EEG vs Caméra (v18), l'onglet **Matériel** affichait toujours :
  - Caméra noire, Batterie caméra, Software caméra, Support ajustable adhésif Captana → alors qu'on était en Phasage EEG
  - Les SA à ne pas poser (config sa_install=disabled) apparaissaient encore dans le compteur EEG global
- **Root cause** : v18 ne filtrait que `state.allees[].products` (endpoint `/api/suivi/{id}`) mais l'onglet Matériel appelle un endpoint séparé `/materiel` qui utilisait `_materiel_par_allee` sans filtre.

### Fix appliqué
- **Backend** (`suivi_deploy.py`) :
  - Nouveau helper `_filter_materiel_node(node, mode, by_uid, cfg_sa)` : filtre les totaux/éléments d'un nœud matériel selon le mode ("eeg" exclut cam-side + SA off + plan≤0 ; "cam" ne garde QUE les cam-side).
  - Nouveau helper `_sa_families_off_for(a, cfg_sa)` : version standalone de `_sa_families_off` utilisable hors `_build_state`.
  - `_eff_nights_map(d, doc, mode)` étendu : en mode "cam" retourne les nuits ABSOLUES (`cam.start_at_nuit + row.nuit - 1`), pas les nuits relatives.
  - `_materiel_overview(d, doc, mode)` et `_materiel_nuit(d, doc, nuit, mode)` prennent un paramètre `mode`.
  - Endpoints étendus : `GET /api/suivi/{id}/materiel?mode=eeg|cam` (chef) + `GET /api/suivi-terrain/{id}/materiel?mode=eeg|cam` (terrain public) + variantes `/materiel/{nuit}?mode=`.
  - `_build_state` neutralise `plan['cameras']=0` et `plan[sa_off_family]=0` pour que `eeg_plan`, `total_eeg_plan` et « restant à poser » ne comptent plus ces catégories.
- **Frontend** :
  - `SuiviMateriel.jsx` : prop `phaseKind`, `useEffect` re-fetch quand `phaseKind` change, passe `mode` à `getMateriel/getMaterielNuit`.
  - `api.js` : `getMateriel(mode)` et `getMaterielNuit(n, mode)` transmettent le query param.
  - `TABS_CAM` (SuiviApp + TerrainApp) inclut maintenant l'onglet **Matériel**. L'utilisateur peut donc voir la ventilation par nuit/allée des caméras + fixations spécifiques en mode Phasage Caméra.

### Validé
- Iter22 : 11/11 nouveaux tests + 24/24 régression = **35/35 backend, 100%**.
- Screenshot preview OK : CAM Nuit 1 → "Caméra noire" seule ; EEG Nuit 2 → uniquement ES/SA sans aucune caméra.


## Changelog 13/02/2026 (v18 — Split UI Phasage EEG vs Caméra + fix SA/Caméra)

### Split UI "Phasage EEG" vs "Phasage Caméra"
- Nouveau composant `frontend/src/suivi/PhaseCategoryPicker.jsx` : après la sélection d'un magasin, un écran de choix affiche deux tuiles :
  - **Phasage EEG** (icône Boxes, accent emerald) → onglets Board / Nuits / Matériel / Stock
  - **Phasage Caméra** (icône Cctv, accent sky) → onglets Board / Caméras / Stock
- Un badge coloré (`PHASAGE EEG` emerald ou `PHASAGE CAMÉRA` sky) est affiché dans le header sous le nom du magasin pour indiquer le mode actif.
- Le bouton retour (chevron gauche) ramène au picker de phase (pas à la liste des magasins) tant qu'un phaseKind est sélectionné. Un second clic ramène à la liste.
- Persistance via `localStorage` : `suivi.lastPhase` (chef) et `suivi.terrain.lastPhase` (terrain). Réinitialisée au changement de magasin.
- Espace terrain public `/suivi/terrain` : même split avec accent `amber` pour rester dans le thème terrain.
- **Rapport backend commun** : les exports Excel / dashboards agrégés incluent toujours EEG + Caméras dans un rapport consolidé — le split est purement UI.
- Nouveau `CamDashboard` (`SuiviDashboard.jsx`) : dashboard cam-focus avec Avancement pose caméras, Géolocalisation, Fixations spécifiques, Allées validées / bloquées, Nuits caméras, alertes caméras.

### Fix critique — Caméras et fixations Captana isolées du côté EEG
- Nouveau helper `is_cam_side_product(desig, typ)` dans `backend/suivi_deploy.py` : détecte tout produit relevant du phasage caméra (type=Caméra OU désignation dans le référentiel `CAPTANA_DESIGNATIONS` OU désignation contient "captana" OU is_camera_fixation).
- Ces produits sont **exclus** de la liste `state.allees[].products` (côté EEG) — auparavant les caméras (type=Caméra) apparaissaient dans la nuit ES au lieu d'être uniquement dans la nuit caméra du phasage.
- Les produits avec `plan <= 0` (aucune quantité à poser) sont également filtrés du EEG.
- `state.cam.allees[].products` inclut maintenant une liste détaillée : caméras (`is_camera: true`) + fixations Captana (`is_fixation: true`) avec leurs quantités prévues.
- `state.cam.allees[].fix_plan` détecte désormais **toutes** les fixations Captana (support mobilier captana blanc/noir, support ajustable adhésif captana, pied réglable 0,5-1 m adhésif captana) — auparavant seuls les produits type "fixation" avec "cam" dans la désignation étaient comptés (⚠ "captana" ne contient PAS "cam", donc les vrais produits étaient manqués).
- Agrégation stock étendue : les caméras et fixations Captana sont maintenant présents dans `state.stock` avec ventilation `pose` proportionnelle aux quantités prévues (basée sur les totaux `cameras_reel` et `fixations_reel` saisis).
- Front `SuiviStock.jsx` : nouveau filtre `isCamStockRow(s)` selon `phaseKind` — le stock isole les produits caméra en mode CAM et les exclut en mode EEG.

### Fix — SA "à ne pas poser" correctement filtrées
- `_sa_families_off()` dans `backend/suivi_deploy.py` étendue :
  - Si `sa_install.answered=True` ET `sa_install.enabled=False` (réponse explicite "Non, je n'installe pas d'EEG SA hors saisonnier") → **toutes** les familles SA (sa_15, sa_21_std, sa_21_freezer, sa_42) avec plan>0 sont exclues des produits de chaque allée.
  - Sinon comportement existant conservé (via `compute_node_sa_install`).

### Validé par testing_agent
- Iteration 21 : 8/8 tests iter21 dédiés + 15/15 tests suivi_deploy régression = 100% success.
- Frontend flows validés : split UI apparaît, tabs filtrés selon phaseKind, back button ramène au picker, badge PHASAGE affiché.
- Backend validé : state.allees[].products sans caméra/Captana ni plan=0 ; state.cam.allees[].products correct ; stock inclut cameras avec prevu>0.


## Changelog 13/02/2026 (v17 — Fix bug critique clic allée)
- **Bug corrigé** : sur mobile/desktop, le clic sur une nuit ou une allée ne faisait rien (l'écran s'ouvrait puis se refermait immédiatement).
- **RCA** : le hook `useMobileBack` (utilisé pour intercepter le back Android) appelait `history.back()` dans son cleanup. Lors d'une navigation forward interne (Nuit → Allée), React démonte l'ancien composant AVANT de monter le nouveau dans le même commit. Le `history.back()` du cleanup était asynchrone : le popstate arrivait après le pushState du nouvel écran, était intercepté par le NOUVEAU listener, qui appelait `onBack` et refermait immédiatement l'écran.
- **Fix** : suppression du `history.back()` dans le cleanup de `useMobileBack.js`. Les entrées d'historique s'accumulent volontairement pendant la session (nettoyées à la sortie de la page). Le bouton back natif Android continue de fonctionner via le popstate → onBack.
- **Validé par testing_agent** (iteration_20) : navigation forward + back UI + back navigateur + chips de filtre tous fonctionnels sur viewport mobile 400x800. Success rate 100%.

## Changelog 12/02/2026 (v16 — Allées déplacées en orange + distinction Pose vs Géoloc)

### Allées déplacées en orange
- Nouveau flag backend `is_deplacee` = `nuit_reelle != nuit_plan` (rapatriement ou report).
- Frontend `SuiviNuits.jsx` : ligne d'allée en **fond orange** + badge du numéro d'allée orange tant que non validée. Petit badge "DÉPLACÉE (plan Nx)" visible avec tooltip précisant la nuit d'origine.
- Statistique dashboard `st.allees_deplacees` = compteur d'allées déplacées et non validées, affiché sur le KPI "Allées déplacées".

### Distinction Pose vs Géoloc (indicateurs séparés partout)
Un poseur peut avoir tout posé sans avoir tout géolocalisé (ou l'inverse). L'app expose maintenant clairement ces deux dimensions :
- **Par allée** (backend `_build_state`) : `pose_total / pose_saisis / pose_complete`, `geo_total / geo_saisis / geo_complete`.
- **Par nuit** : `nb_pose_complete`, `nb_geo_complete`, `pose_saisis/pose_total`, `geo_saisis/geo_total`.
- **Global (stats)** : `pose_pct`, `geo_pct` distincts.
- **Frontend allée dans liste** : "Pose X/Y · Géoloc A/B" (vert si complet, sky si en cours).
- **Frontend Dashboard** : deux jauges distinctes côte à côte — **Pose produits** (dégradé vert) et **Géolocalisation** (dégradé sky, icône MapPin). Chacune avec compteur X/Y et pourcentage.
- **Rapport nuit Excel** : 3 nouvelles colonnes en tête de tableau — **Pose** (X/Y en rouge si incomplet), **Géoloc** (A/B en rouge si incomplet), **Déplacée ?** ("Depuis Nx" en rouge si l'allée vient d'une autre nuit).

### KPI
Remplacement du KPI "Allées bloquées" par "Allées déplacées" (le premier n'est presque jamais utilisé dans la vraie vie, le second est bien plus actionnable).

### Testé
- 52/52 tests pytest suivi passent.
- Smoke visuel OK sur terrain.

## Changelog 12/02/2026 (v15 — Déplacement automatique + statut « en attente »)
- **Nuit de rattrapage devient optionnelle** dans la modale « Allée non faite » :
  - Si le poseur choisit une nuit → l'allée est **automatiquement déplacée** sur cette nuit et repasse en statut `a_faire` (prête à être travaillée). Le commentaire est conservé pour la traçabilité.
  - S'il choisit « ⏳ En attente — je ne sais pas encore quand » → l'allée reste `non_faite` sur la nuit d'origine, affichée « En attente » dans le dashboard (couleur orange distincte) et le rapport nuit Excel (nouvelle section dédiée).
- **Alerte dashboard non_faite enrichie** : champ `en_attente` (bool) qui déclenche l'affichage orange avec badge « ⏳ En attente ».
- **Rapport Excel nuit** : nouvelle section « ⏳ Allées non faites EN ATTENTE (rattrapage à définir) » listant les allées (Allée / Secteur / Rayon / Raison).
- **AlleeScreen** : le bandeau info "Allée non faite" affiche soit "→ rattrapage prévu nuit X" soit "⏳ En attente — nuit de rattrapage à définir".
- Testé : PATCH avec `nuit_rattrapage` → allée déplacée (status=a_faire, nuit_reelle=nr). Sans → non_faite conservée. 52/52 pytest passent.

## Changelog 12/02/2026 (v14 — P3 backlog terrain : F, G, H, I, J)
### (F) Géoloc = nombre de produits posés — validation bloquante
- Nouveau helper backend `_check_geoloc_gap` dans `suivi_deploy.py`.
- À la validation d'une allée (status → `validee`), pour chaque produit géolocalisable (rails ES, SA 1.5, SA 2.1, SA 2.1 freezer) : si `geo < reel` → 400 "Écart de géolocalisation : ..." avec la liste des produits en écart, sauf si un `geoloc_comment` est renseigné (justification).

### (G) Bouton « Non fait » avec commentaire + nuit de rattrapage
- Nouveau statut d'allée `non_faite` (en plus de a_faire / validee / bloquee / a_finaliser).
- Backend `_guarded_allee_update` bloque 400 si status → `non_faite` sans `comment` OU sans `nuit_rattrapage`.
- Modèle enrichi : `AlleeUpdate.nuit_rattrapage: Optional[int]`.
- Alerte dashboard `type=non_faite` avec message "nuit X NON FAITE, rattrapage nuit Y : commentaire".
- Compteur `nb_non_faites` par nuit + badge rouge sur la tuile de nuit.
- Frontend : bouton rouge « Allée non faite » avec modale (textarea comment + select nuit rattrapage) sur l'écran allée.

### (H) État stock dans rapport nuit + alerte dashboard "risque manque"
- Rapport Excel nuit enrichi : section "⚠ Risque de manque de stock" listant les produits en manque (Prévu / Reçu / Posé / Restant stock / Restant à poser / Manque). N'apparaît que s'il y a des alertes de rupture pour la nuit.
- Dashboard : alerte "Risque de manque" en gras rouge (le libellé est explicite) — cliquable pour aller sur l'onglet Stock.

### (I) Filtrer les SA à ne pas poser
- Backend `_build_state` utilise désormais `compute_node_sa_install(node, cfg_sa)` pour chaque allée.
- Les familles SA marquées comme "à ne pas poser" dans le phasage (`sa_install` config avec `enabled=True`) sont automatiquement exclues de la liste des produits du suivi de cette allée.
- Aucune modification du phasage nécessaire côté user : c'est la config déjà présente dans l'outil de phasage qui est prise en compte.

### (J) Fixations caméras Captana distinctes des EEG
- Nouveau helper `is_camera_fixation(desig, typ)` : True si type contient "fixation" ET désignation contient "captana" ou "cam"/"caméra".
- Ces produits sont exclus de la liste EEG d'une allée (ils apparaissent déjà côté suivi caméra où ils sont pertinents).

### Testé
- 52/52 tests pytest suivi passent.
- Validation non_faite testée par curl (400 sans comment/rattrapage, OK sinon).
- Smoke visuel terrain OK.

### Reste à faire (backlog)
- Confirmation manuelle par utilisateur sur mobile réel des flows F/G/H/I/J.

## Changelog 12/02/2026 (v13 — Panneau superadmin de gestion des utilisateurs)
- [x] **Bouton « Utilisateurs »** dans le header (badge ambre) visible uniquement pour le rôle `superadmin`. Ouvre un panneau modal `AdminUsersPanel.jsx` avec la liste complète des comptes.
- [x] **Actions par utilisateur** :
    - **Reset MDP** : génère un nouveau mot de passe temporaire (14 chars par défaut), affiché UNE SEULE FOIS avec bouton copier, invalide l'ancien MDP + efface les tentatives échouées.
    - **Débloquer** : efface les tentatives échouées pour cet email (utile si compte lock par brute-force).
    - **Changer le rôle** : dropdown user / admin / superadmin (superadmin ne peut pas se rétrograder lui-même).
    - **Supprimer** : suppression du compte (impossible sur son propre compte), phasages laissés orphelins en DB.
- [x] **Info par ligne** : nom, email, badge de rôle (Créateur/Admin/User avec icône), badge VOUS pour l'user connecté, badge BLOQUÉ si tentatives échouées, dates création + dernière connexion, nombre de phasages.
- [x] **Backend** : endpoints `/api/admin/users` (list), `/api/admin/users/{id}/reset-password`, `/unlock`, `/role`, `DELETE` — tous protégés par `_require_super()` (403 pour non-superadmin, testé). Colonne `last_login_at` ajoutée dans `users` (mise à jour à chaque login).
- [x] Endpoints d'urgence conservés : `/api/version`, `/api/auth/emergency-reseed-superadmin` (avec clear brute-force intégré), `/api/auth/emergency-debug-user`, `/api/auth/emergency-trace-login` — protégés par `X-Superadmin-Secret = SUPERADMIN_PASSWORD`.
- [x] Testé : curl (reset MDP, unlock, role change, guardrails self-demote et 403 non-superadmin) + smoke visuel OK.

## Changelog 11/02/2026 (v12 — Fixes bloquants terrain + UX validation)
### Bugs bloquants corrigés
- [x] **(A) Plus d'auto-remplissage posé = prévu** à la validation d'une allée vide. Les valeurs non saisies restent nulles → l'allée est validée mais le rapport reflète les vrais chiffres (0 posé sur X prévu si rien n'a été fait). Fichier : `SuiviNuits.jsx::confirmValidate`.
- [x] **(B) Allée validée = inputs verrouillés** : posé, géoloc, commentaire, comm. géoloc en `readOnly` + fond assombri + curseur `not-allowed`. Bandeau explicite « Allée validée — rouvrez pour modifier ». Le bouton « Rouvrir » reste actif. Backend `saveField` bloque aussi côté client pour éviter les patchs sur allée validée.
- [x] **(C) Retour Android** : hook `useMobileBack` dans `SuiviNuits.jsx`. Chaque écran (NightScreen, AlleeScreen) empile une entrée d'historique à l'ouverture et intercepte popstate → onBack. Les flèches UI passent par `history.back()` pour garder la stack propre. Un back sur l'écran racine sort de l'app (comportement browser natif) sans plus quitter l'app en cascade.

### UX terrain
- [x] **(D) Ligne produit sur toute la largeur** : nom complet du produit sur la première ligne (wrap si besoin, plus de troncature), et Prévu / Posé / Géoloc / Δ répartis sur une 2e ligne en grid 4-cols. Badge « géoloc » discret à droite du nom pour les produits géolocalisables. Fichier : `SuiviNuits.jsx`.
- [x] **(E) Dashboard : clic sur une nuit → mini-résumé modal** au lieu d'aller sur l'onglet Nuits. Affiche KPI (allées, EEG posées/prévues, restant), badges (bloquées, à finaliser), liste des allées avec statut coloré, bouton « Ouvrir la nuit » pour basculer sur l'onglet. Testids `night-summary-*`, `night-summary-allee-*`. Fichier : `SuiviDashboard.jsx`.

### Testé
- 52/52 tests pytest suivi passent, lint pass, smoke visuel OK (terrain + chef).

### Reste à faire (P3 — logique métier, prochaine vague)
- (F) Géoloc = nombre de produits posés (validation bloquante)
- (G) Bouton « Non fait » sur une allée : commentaire obligatoire + choix de nuit de rattrapage + alerte dashboard
- (H) État du stock dans le rapport nuit + alerte dashboard « risque de manque »
- (I) Filtrer les SA à ne pas poser (basé sur le phasage EEG existant : étiquettes marquées « à ne pas poser »)
- (J) Matériel caméras distinct des EEG : fixations Captana selon l'onglet Commande du phasage

## Changelog 11/02/2026 (v11 — Noms d'exports normalisés + affichage magasin propre + owner visible)
- [x] **Renommage de tous les exports** — format unique `Export {store_name} ({store_code}) DD-MM-YYYY HH-MM_{suffix}.{ext}` (date = heure de Paris au moment du téléchargement).
  - Concerne : Export RTR (`_RTR.xlsx`), Export Carrefour (`_Carrefour.xlsx`), PowerPoint CR VT (`_CR_VT.pptx`), Rapport nuit suivi (`_Rapport_nuit_N.xlsx`).
  - Helpers `server.py::_display_store(d)` + `_export_basename(d)` (source de vérité) ; fallback nettoyage regex du filename si store_name absent. Frontend `App.js::exportBase()` répliqué à l'identique (override du `Content-Disposition` par l'attr `download`).
- [x] **Affichage magasin propre dans le Suivi** — header chef & terrain + store picker terrain : `ST PIERRE DES CORPS (H7351)` (parenthèses au lieu de `· H7351`). Fichiers : `SuiviApp.jsx`, `TerrainApp.jsx`.
- [x] **Owner visible pour le superadmin** — `GET /api/datasets` enrichit chaque item avec `owner_email` + `owner_name` uniquement pour le superadmin. Affichage `· par email@x` (emerald) sur chaque tuile dans `SessionsMenu.jsx`. Testid `session-owner-{uid}`.
- [x] Testé : 52/52 tests pytest suivi passent, curl HTTP validé (`Content-Disposition: Export ST PIERRE DES CORPS (H7351) 11-07-2026 02-35_Carrefour.xlsx` conforme).

## Changelog 10/02/2026 (v10 — Super-admin créateur + badge « en avance »)
- [x] **Rôle `superadmin`** (créateur de l'outil) : accès en lecture/écriture à TOUS les phasages de tous les utilisateurs.
  - Seed via env `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` dans `backend/.env` + `backend/auth.py::setup_auth`.
  - Helpers `_scope(user)` et `_owner_filter(user_id, include_legacy)` dans `server.py` : bypass propriétaire quand rôle = superadmin. Appliqués à tous les endpoints datasets/phasage (list, get, delete, label, share, patch, exports). `suivi_deploy.py::_load` et `reset` idem (admin **ou** superadmin).
  - Isolation user standard préservée : un `user` ne voit toujours QUE ses propres phasages (validé par curl : superadmin voit 2/2, admin/poseur voient 1/1).
  - 52/52 tests pytest suivi passent (aucune régression).
- [x] **Badge « ⚡ N en avance »** sur les tuiles de nuit (chef & terrain) — compte les allées dont `nuit_plan > nuit_eff` (rapatriées depuis une nuit ultérieure). Champ `nb_rapatriees` exposé par `_build_state`. Testid `night-rapatriees-{n}`.

## Changelog 10/02/2026 (v9 — Rapatriement d'allées en avance)
- [x] **Bouton « Ajouter une allée » (en bas de la liste des allées d'une nuit)** : ouvre une modale listant les allées des nuits suivantes (triées par nuit croissante puis par n° d'allée en ordre naturel FR). Sélection une par une : le clic rapatrie immédiatement l'allée dans la nuit courante via `PATCH /allee {nuit_reelle: N}` (API existante). Le badge « plan N-x » est conservé automatiquement (existant). Désactivé si aucune allée ultérieure disponible. Fichier : `frontend/src/suivi/SuiviNuits.jsx`.

## Changelog 10/07/2026 (v8 — Suivi « tout par produit », plein écran, terrain = web)
- [x] **Saisie PAR PRODUIT** (remplace la saisie par famille) : PATCH allee `{uid, products:[{designation, reel?, geo?}], ...}` ; agrégats familles (reel/delta/geo/geo_gap), dashboard, alertes, rythme et rapports recalculés automatiquement via `classify_family(type, désignation)` (server.py). geo saisissable uniquement sur produits rails_es/sa_15/sa_21_std/sa_21_freezer (is_geo). Désignations inconnues du fichier filtrées. Chaque allée expose `products[]`, `nb_produits`, `nb_saisis`.
- [x] **Stock PAR PRODUIT** : chaque désignation (prévu → reçu saisi → posé auto → alerte manque nominale). `PATCH /stock {designation, recu}` (auth + PUBLIC terrain), `stock_received` en liste. UI : recherche + filtre alertes. Restant à poser = plan − déjà posé (allées non validées).
- [x] **Nuits en 3 niveaux PLEIN ÉCRAN** : liste nuits → allées de la nuit (X/Y produits saisis, incidents) → page allée plein écran : tableau produits (prévu/posé/géoloc/Δ), explication géoloc, photos, commentaire, gros bouton « Valider l'allée » (auto-remplit posé=prévu pour produits non saisis), Bloquer, déplacement de nuit.
- [x] **Terrain = même chose que le web** : 5 onglets identiques au chef (Board/Nuits/Caméras/Matériel/Stock) ; Board terrain sans carte publication ni Replanifier (via prop mode).
- [x] **Rapport nuit : 2 feuilles** — « Nuit N » (synthèse familles) + « Détail produits » (allée, désignation, type, prévu, posé, géolocalisé, Δ).
- [x] Testé : testing_agent iteration_16 — **45/45 pytest** (3 fichiers réécrits au format produit), frontend chef + terrain 100%. Garde-fou désignations inconnues ajouté post-test (45/45 re-vérifié).

## Changelog 10/07/2026 (v7 — Espace terrain commun, publication, effacement)
- [x] **SUPPRESSION du lien token par magasin** → **espace terrain commun `/suivi/terrain`** (public, sans compte) : store picker listant UNIQUEMENT les magasins publiés (avec « publié par ... »), puis interface 3 onglets. Routes publiques désormais clé upload_id : `/api/suivi-terrain/{upload_id}/...` + `GET /api/suivi-terrain/stores`. Résolution via `suivi_docs.published=True`.
- [x] **Publication par le créateur du phasage** : `POST /api/suivi/{id}/publish {published}` (auth) ; carte `publish-card` dans le dashboard chef (badge PUBLIÉ/NON PUBLIÉ, lien commun copiable). L'état chef expose `publication {published, published_by}` (absent côté terrain).
- [x] **Effacement du suivi réservé créateur + admin** : `DELETE /api/suivi/{id}/reset` — vide allees/cam_allees/incidents/stock_received (photos incluses via allees), conserve la publication. Non-créateur non-admin → 404/403. Bouton « Effacer le suivi » avec confirmation dans la carte publication.
- [x] Comptes : poseur@test.local / poseur123 (role user) créé pour tester les permissions.
- [x] Testé : testing_agent iteration_15 — **40/40 pytest** (test_suivi_terrain.py réécrit 16 tests publish/upload_id, test_suivi_cam_materiel.py adapté), frontend chef + terrain 100%.

## Changelog 10/07/2026 (v6 — Suivi : onglets Caméras & Matériel)
- [x] **Onglet « Caméras » à part** (chef + terrain) : suivi complet du phasage caméras — nuits caméras avec n° absolu (start_at_nuit + n − 1, date issue de phasage.dates), allées avec nb caméras prévues + chips n° éléments (doublons « ×2 » en rouge), saisie **posées + géolocalisées** (alerte 'geoloc' family 'cameras' avec explication demandée si géo < posé), valider/bloquer/commentaire, déplacement de nuit. Stockage : `suivi_docs.cam_allees[]`. Endpoints : `PATCH /api/suivi/{id}/allee-cam` + version terrain. Frontend : `SuiviCam.jsx`, section `cam` dans l'état.
- [x] **Onglet « Matériel » drill-down 3 niveaux** (chef + terrain) : Nuits (total de CHAQUE produit/désignation par nuit, nuits effectives incl. nuit_reelle) → clic nuit = allées avec totaux par produit → clic allée = chaque élément (N° élément, « (sans élément) » si vide) avec produits prévus. Bloc « Hors phasage » pour les allées non assignées. Endpoints : `GET /materiel` (overview léger) + `GET /materiel/{nuit}` (détail lazy) en auth + terrain. Frontend : `SuiviMateriel.jsx`, helpers backend `_materiel_par_allee/_materiel_overview/_materiel_nuit`.
- [x] Navigation : chef = 5 onglets (Board/Nuits/Caméras/Matériel/Stock), terrain = 3 onglets (Pose EEG/Caméras/Matériel).
- [x] Testé : testing_agent iteration_14 — **33/33 pytest** (13 nouveaux `tests/test_suivi_cam_materiel.py` + 20 régression), frontend chef + terrain 100%.

## Changelog 10/07/2026 (v5 — Suivi : équipe terrain, géolocalisation, photos)
- [x] **Lien équipe terrain SANS compte** : `/suivi/terrain/{token}` (router public `/api/suivi-terrain/{token}/...`). Activation/désactivation + copie du lien depuis le dashboard chef (carte `terrain-link-card`, endpoint auth `POST /api/suivi/{id}/terrain-share`). Les poseurs peuvent : saisir réel posé + géolocalisé, photos, commentaires, VALIDER/bloquer les allées, déplacer de nuit, incidents, télécharger le rapport. Frontend : `TerrainApp.jsx` (header ambre « Mode équipe terrain »), actions factorisées dans `suivi/api.js` (makeActions + compressImage).
- [x] **Géolocalisation posé VS géolocalisé** : familles Rails ES, SA 1.5, SA 2.1, SA 2.1 freezer (PAS SA 4.2/saisonnier/caisses). Champs `*_geo` (ge=0), `geo_gap` calculé si géo < posé → **alerte type 'geoloc' avec « explication demandée »** tant que `geoloc_comment` vide (bandeau rouge sur la carte allée + alerte dashboard). Rapport Excel : colonnes « Géoloc » + « Explication géoloc » + KPI « Posés non géolocalisés ».
- [x] **Photos par allée** : upload compressé côté client (canvas 1400px JPEG), stockage **Emergent Object Storage** (EMERGENT_LLM_KEY dans backend/.env, préfixe `phasage-crf/suivi/{upload_id}/`), refs dans suivi_docs.allees[].photos. Endpoints auth + terrain (POST allee-photo multipart, GET/DELETE photo). Max 8 Mo, images uniquement. **Photos intégrées dans le rapport Excel** de la nuit (PIL + insert_image, grille 3/ligne, max 30).
- [x] Testé : testing_agent iteration_13 — 20/20 pytest (9 terrain `tests/test_suivi_terrain.py` + 11 régression), frontend 100% (terrain mobile, dashboard chef, alertes géoloc, upload photo Playwright).
- Backlog sécu suggéré par tests : rate-limiting des endpoints publics terrain (photos) avant grosse prod.

## Changelog 10/07/2026 (v4 — NOUVELLE APP « Suivi de déploiement » sur /suivi)
- [x] **App séparée accessible sur `/suivi`** (même backend/DB, interface distincte dark mobile-first, login commun, lien « Suivi » dans le header de l'app phasage). Fichiers : `frontend/src/suivi/{SuiviApp,SuiviDashboard,SuiviNuits,SuiviStock}.jsx`, routage pathname dans `App.js`.
- [x] **Backend `backend/suivi_deploy.py`** (router `/api/suivi`, collection Mongo `suivi_docs`) :
  - `GET /api/suivi/{id}` : état complet (allées avec plan/réel/delta par famille, nuits, stock, alertes, stats, incidents). Familles : es_15, es_21, rails_es, sa_15, sa_21_std, sa_21_freezer, sa_42, cameras. ⚠️ uid des allées = champ `allee` des rows du phasage (pas `id`).
  - `PATCH /allee` : saisie réel par famille (ge=0), statut (a_faire/validee/bloquee), commentaire, `nuit_reelle` (déplacement d'allée vers une autre nuit, 0 = retour au plan). Valider sans saisie = auto-remplissage au prévu (côté frontend).
  - `PATCH /stock` : reçu réel par famille (null = théorique = prévu). Alerte rupture si restant stock < restant à poser (manque = restant_a_poser − max(0, restant_stock)).
  - `POST/DELETE /incident` : journal d'incidents par nuit.
  - `GET /rapport-nuit/{n}` : rapport Excel par nuit (xlsxwriter) — KPIs rythme (écart nuit, cumul, avance/retard estimé, verdict plus rapide/lent), tableau allées prévu/réel/Δ coloré, totaux, incidents.
  - `POST /replan {apply}` : replanification automatique du restant selon le rythme réel mesuré (nuits terminées = toutes allées validées), capacité = max(rythme réel, prévu) plafonnée 4900 EEG/nuit ; preview puis apply (snapshot phasage auto + persist + reset des nuit_reelle déplacées). 400 si aucune nuit terminée.
- [x] **Dashboard** : % avancement EEG, allées validées/bloquées, nuits terminées, rythme réel vs prévu, bandeau avance/retard (nuits estimées restantes), alertes rupture/blocage cliquables, grille des nuits, bouton Replanifier avec modal preview.
- [x] Testé : testing_agent iteration_12 — backend 11/11 pytest (`backend/tests/test_suivi_deploy.py`), frontend Playwright OK. Corrections post-test : validation ge=0 (422), warning snapshot loggé, fix warning `<option>`.

## Changelog 10/07/2026 (v3 — refonte template)
- [x] **Template PPTX remplacé par le modèle de référence utilisateur** (`rendu PPTX CR VT.pptx` du 10/07/2026). Le fichier `/app/backend/templates/cr_vt_template.pptx` est désormais le PPTX que l'utilisateur veut, garantissant un rendu identique à sa vision. L'ancien template est conservé en `cr_vt_template.OLD.pptx`.
- [x] Indices de slides mis à jour dans `build_pptx()` : idx 7=Matériel, 10=Plan EEG complet, 11=Récap par nuit, 12-15=S1-S4, 16=Plan cam complet, 17=Récap cam, 18=Détail cam, 19=Récap full.
- [x] Suppression du placement de tables (`_place_table` hardcodé) pour les slides — le nouveau template a déjà les bonnes dimensions.
- [x] Wifi placeholder conservé (le nouveau template n'a qu'UNE slide "Plan wifi magasin", plus aucune slide à supprimer).
- Vérifié : PPTX 39 Mo, 20 slides, layouts matchent 1:1 le modèle de référence sur 16 nuits de test.
- Version marker : `X-PPTX-Version: 2026-07-10-v24-new-template`

## Changelog 10/07/2026 (v2 — soir)
- [x] **BUGS PPTX PROD RÉELLEMENT CORRIGÉS** (fichier utilisateur `Export MONT ST AIGNAN` du 10/07 02:37 disséqué → 3 vrais défauts confirmés par LibreOffice→PDF→PNG et XML) :
  - **Slide 13 (Récap par nuit) — colonne Date trop étroite** : ratios `[12,7,18,22,7,7,6,6,7,7,7]` donnaient 6.25% à Date → "27/07/2026" wrappait sur **3 lignes** → lignes gonflées → **Nuit 16 débordait sous le pied de page**. Fix : nouveaux ratios `[8,11,16,20,7,7,6,6,7,6,6]` (Date passe à 9.8%) + row_h réduit `280000 → 240000` EMU pour tenir 20 nuits max.
  - **Slide 13 & 14-17 (Semaines) — texte violet/gris hérité du template** : SA 2.1, SA 2.1 frz, 4.2/4.2 WP, Caméras affichés en **`#6B21A8` (violet)** au lieu de noir. Cause : `_set_cell_text` réutilise le premier run cloné dont le `<a:solidFill>` du template persistait ; `r.font.color.rgb =` de python-pptx ne remplaçait pas fiablement. Fix : nouveau helper `_force_cell_text_color()` qui supprime tout `<a:solidFill>` existant sur TOUS les runs et injecte un nouveau `srgbClr val="000000"` propre. Appliqué à toutes les cellules data (slides 12, week 13-16) + lignes d'en-tête + sous-totaux.
  - **Slides 14-17 (Semaines) — Date trop étroite** : ratios `[7,9,20,22,8,8]+SA` → Date wrappait aussi. Fix : Date passe de 9 à 12.
  - **Slide 20 (Détail caméras par allée) — texte gris `#374151` sur rangées 2+** : idem, `_set_cell_text(color="#000000")` ne remplaçait pas la couleur héritée du clone. Fix : `_force_cell_text_color()` sur cellules + en-tête.
- Vérifié : PPTX 24.5 Mo généré en preview → LibreOffice→PDF→PNG des slides 13,14,20,21 → **toutes les 16 nuits visibles, dates sur 1 ligne, texte 100% noir**. Comparaison visuelle avant/après concluante.
- Version marker : `X-PPTX-Version: 2026-07-10-v19-force-black-date`
- ⚠️ **Redéploiement production requis pour que l'utilisateur voie les corrections.**

## Changelog 10/07/2026 (session en cours)
- [x] **Enquête « les tableaux PPTX sont cassés en production »** : vérification DIRECTE de la production (https://go-lang-43.emergent.host) — 6 exports successifs analysés (XML) : le code prod est À JOUR (11 colonnes complètes, bandeau « Récap par nuit » fusionné sur 11 col, en-têtes SA 1.5/2.1/frz/4.2/Caméras présents, titre « Informations Magasin » horizontal). Le fichier 38 Mo joint par l'utilisateur (« rendu PPTX CR VT.pptx ») provient d'une version TRÈS ancienne (colonne « SA » unique, « EEG » sans « ES ») et ses captures 01h54 d'une version intermédiaire → il regardait d'anciens fichiers téléchargés. ⚠️ Découverte : ~1 export sur 6 en prod échoue avec une erreur Cloudflare 520 (gros fichier) → un téléchargement raté peut amener à rouvrir un ancien fichier.
- [x] **3 vrais défauts PPTX trouvés (rendus LibreOffice) et corrigés (`pptx_export.py`)** :
  - `_fill_slide_17` : le tableau caméras transposé chevauchait le titre → top abaissé (624169 → 1250000 EMU).
  - `_fill_slide_19` (Détail caméras par allée) : lignes vides COLORÉES du template dans le tableau droit + débordement bas du tableau gauche → répartition équilibrée 50/50 entre les 2 tableaux (>14 lignes), suppression réelle des `tr` inutilisés, suppression du tableau droit si inutile, texte forcé noir/non-gras (le template avait des runs rouges/gras), fond blanc forcé si pas de couleur nuit.
  - `_fill_slide_20` (Phasage full) : lignes vides colorées sous TOTAL → `tr` excédentaires réellement supprimés (avant : texte vidé mais fonds conservés).
- Vérifié par rendu LibreOffice→PDF→PNG des slides 14-21 (preview) + test unitaire 30 lignes pour la slide 19. Aucune régression.
- ⚠️ Ces 3 correctifs sont en PREVIEW : un redéploiement est nécessaire pour la production.

## Changelog 25/06/2026
- [x] **Masquage des colonnes SA par semaine** : sur chaque slide/feuille semaine, les colonnes SA (SA 1.5 / SA 2.1 / SA 2.1 frz / SA info) ne s'affichent que si des SA sont posées sur les nuits de CETTE semaine (calcul par semaine et non global). Appliqué au PPTX (`_fill_slide_week`) et aux 2 Excel (`_write_week_sheets`). Vérifié : S1 (avec SA) → colonnes SA visibles ; S2/S3 (sans SA) → colonnes de base uniquement.
- [x] **Tableaux par semaine détaillés + harmonisation PPTX/Excel** :
  - PPTX slides semaine : remplacement du petit transposé par un tableau détaillé `Nuit · Date · Secteur/Rayon · Allées · EEG · Rails ES` + colonnes **SA à installer dynamiques** (SA 1.5 / SA 2.1 / SA 2.1 frz affichées seulement si posées ; « SA » magasin hors phasage en italique si présente) + ligne **« Sous-total S{n} »**.
  - Les 2 exports Excel : feuille « Récap par nuit » enrichie de lignes **Sous-total S{n}** ; ajout de **feuilles par semaine** (`Semaine S1…`) identiques au tableau PPTX (helper `_write_week_sheets`).
  - Mise en page : **titre remonté** (top ~90000 EMU) et **phrase de bas de page réduite à 7 pt** sur toutes les slides où elle apparaît (`_compact_layout`).
  - Vérifié en générant PPTX + 2 Excel.
- [x] **Mise en page PPTX compactée (positions/tailles reprises de la maquette de référence)** : ajout d'un helper `_place_table` qui repositionne et dimensionne chaque GraphicFrame (left/top/width), redistribue les colonnes pour remplir la largeur cible et applique une hauteur de ligne compacte (la hauteur totale s'adapte au nb de nuits). Appliqué aux tableaux : transposé complet, Récap par nuit, slides semaine, caméra transposé, caméra récap. Mesures alignées sur la référence, aucun débordement de slide. Vérifié sur fichier généré.
- [x] **Tableau « Récap par nuit » unifié (PPTX + 2 Excel)** : colonnes Nuit · Date · Secteur/Rayon · Allées · EEG · Rails ES · **SA 1.5** · **SA 2.1** · **Caméras**. Règle appliquée : SA 1.5 gardée séparée, SA 2.1 + Freezer fusionnés dans « SA 2.1 » ; colonne Caméras ajoutée ; SA magasin retirée. Helper Excel partagé `_write_recap_par_nuit_sheet` utilisé par l'export Carrefour (remplace « Récap EEG par nuit ») ET l'export traité (nouvelle feuille) → rendu identique au PPTX (`_fill_slide_12`). Vérifié en générant les 3 fichiers. Note : positionnement des titres / mise en page globale des slides inchangés (hérités du template).
- [x] **Export PPTX aligné sur le rendu de référence fourni par l'utilisateur** (vérifié sur fichier généré, structure comparée à la référence) :
  - Slide « Récap par nuit » complète : colonnes = Nuit · Date · Secteur/Rayon · Allées · EEG · Rails ES · **SA** · **Caméras**. La colonne SA regroupe désormais SA 1.5 + SA 2.1 + SA 2.1 Freezer (règle « mélange SA 2.1 et Freezer ») ; colonnes SA séparées et SA magasin supprimées ; colonne Caméras ajoutée. S'adapte au nombre de nuits.
  - Slide « complet » (transposé) : lignes Date / EEG / SA (label « SA »), texte 6 pt pour tenir jusqu'à 20 nuits.
  - Slides par semaine (S1..S5) : n'affichent QUE le petit tableau transposé (Date / EEG / SA) — le grand tableau détaillé par semaine est retiré (⚠️ inverse la demande précédente, conforme au PPTX de référence).
  - Slide caméra transposé : lignes Date / Caméra (ligne EEG retirée).
- [x] **Export PPTX — nettoyage des tableaux de phasage** (validé sur fichier généré) :
  - Slide « Plan de phasage … complet » : affiche désormais TOUTES les nuits (jusqu'à 20, plus de troncature 17-20) ; ligne « Caméra » retirée.
  - Slides « Récap par nuit » (complète, semaines, caméras) : colonne vide résiduelle de droite supprimée (`_trim_table_cols`) + hauteurs compactes.
  - Slides par semaine : suppression du petit tableau horizontal redondant (Date/EEG/Caméra/SA posées) et de l'en-tête noir du tableau détaillé restant (les en-têtes de colonnes passent en ligne 0).
  - Helpers ajoutés dans `pptx_export.py` : `_trim_table_cols`, `_remove_table_row`.
- [x] **Nb de nuits recalculé automatiquement après la sélection SA** : au clic « Continuer vers le phasage », le nombre de nuits suggéré est recalculé à partir du total EEG COMPLET incluant les EEG SA à installer (auparavant la suggestion ignorait les SA choisies → nb de nuits non aligné sur la moyenne). Vérifié via screenshot (Total 6 335, nb nuits 10, moyenne 634 EEG/nuit).
- [x] **Questions « Étiquettes SA à poser » déplacées avant la grille de phasage** : à l'étape 3, un écran d'intro (data-testid `sa-install-intro`) pose la question « Devez-vous installer des EEG SA hors zone saisonnière ? » (Oui/Non + cases). Le bouton « Continuer vers le phasage » (data-testid `sa-intro-continue`) est bloqué tant qu'on n'a pas répondu Oui/Non. Champ backend `answered` persisté (SaInstallConfig) → au retour, on accède directement à la grille. Bouton « EEG SA à poser » (data-testid `phasage-edit-sa`) dans la barre du haut pour revenir modifier. Validé testing_agent iteration_11 (frontend 100%).
- [x] **Fil de progression complet dans le stepper** : badges verts animés par étape — « Complète » (étape 2), « Prêt » (étape 3 Phasage, dès qu'une allée ES est assignée à une nuit), « Dates OK » (étape 4, quand toutes les nuits du plan ont une date). Statut 3/4 via nouvel endpoint `GET /api/dataset/{id}/wizard-status` (calcul backend sur phasage/dates), rafraîchi à chaque navigation d'onglet/étape. Vérifié via curl + screenshot.
- [x] **Indicateur « Étape 2 complète ✓ » dans le stepper** : badge vert animé (data-testid `step2-ready-badge`) affiché à côté de l'étape 2 dès que surface + dongles + références sont valides, calcul en direct côté frontend (miroir de la logique backend /step2-validation). Vérifié via screenshot.
- [x] **BUG P0 corrigé (validation étape 2 en prod)** : le modal « Surface non renseignée / Dongles non renseigné » s'affichait à tort en production même après saisie. Cause racine : cache mémoire `DATASTORE` par réplica K8s → un PATCH surface/dongles sur le réplica A mettait à jour Mongo + cache A, mais le GET `/step2-validation` pouvait arriver sur le réplica B avec un cache périmé. Fix : `load_dataset()` rafraîchit désormais les champs éditables légers (surface_category, dongles_quantity, recap_rows, phasage, comment_table, sa_install, métadonnées magasin) depuis Mongo à chaque cache hit (projection légère, sans re-décompresser le payload). Validé : backend 6/6 pytest, frontend 5/5 flux (testing_agent iteration_10).
- [x] **UX étape 2** : ajout d'un texte d'aide (data-testid `eeg-step3-hint`) indiquant « Le choix des EEG à poser se fait à l'étape 3 (Phasage). »

## Changelog 24/06/2026
- [x] **Export Carrefour : ajout des 2 feuilles « Recap par secteur »** (par rayon + global) — mêmes données que dans l'export RTR (factorisé via `_write_par_secteur_sheets`).
- [x] **PPTX : rendu des sections** (séparateurs bleu clair `#DDEBF7` sur la colonne Désignation) directement dans le tableau slide 9 — pas de nouvelles colonnes, mais le contexte des sections est désormais visible.

## Changelog 23/06/2026 (v5)
- [x] **Ordre des sections** revu : EEG / Rails EdgeSense / **Rails/Fixation SA** / Captana / Dongles / **VCare** (6 sections au lieu de 5, VCare désormais dans une section dédiée au lieu d'être réparti dans EEG/Captana).
- [x] **Référence doit être numérique** : `_validate_missing_refs` détecte aussi les refs alphanumériques (ex: "AUTRE1"). Frontend rouge + bandeau d'alerte + blocage exports avec message explicite.

## Changelog 23/06/2026 (v4)
- [x] **Restructuration du tableau Commandes en 5 sections** (séparateurs bleu clair, plus de « TOTAL EEG / Fixation / etc. ») :
  - **EEG** : ES/SA 1.5/2.1/4.2 + VCare associés
  - **Rails EdgeSense** : rails (longueurs mm), inclineurs, « Face arrière... », Vis fixation
  - **Captana** : caméras blanche/noire, batterie/software caméra, Support mobilier/ajustable/Pied réglable Captana, VCare Captana
  - **Dongles** : Dongles (16639)
  - **Rails/Fixation SA** : tout le reste + AUTRE*
- [x] **Bloqueur d'export si réf manquante** : helper `_check_export_refs()` appliqué aux 3 endpoints (RTR / Carrefour / PPTX). Renvoie HTTP 400 avec message explicatif listant les désignations concernées.
- [x] **Bandeau d'alerte rouge** en haut du tableau RecapTable quand des lignes manquent de référence + chaque ligne concernée passe en fond rouge.
- [x] Excel : section dividers fusionnés sur 10 colonnes en fond bleu clair `#DDEBF7`.

## Changelog 23/06/2026 (v3)
- [x] **Exports Excel RTR & Carrefour : 4 nouvelles colonnes ajoutées** à la feuille Commandes (Flèche, Signalétique, Saisonnier, Total + MOQ) + largeurs serrées (~19 cm total) pour tenir dans une slide PPTX.
- [x] `_apply_total_moq_and_bonuses` appelé désormais aussi dans les pipelines `/export/{id}`, `/export-carrefour/{id}` et `/export-pptx/{id}` (en plus de `get_dataset`).
- [x] Testé : ES 1.5 (blanc) Total=105 → Total+MOQ=200, ES 1.5 (noir) Signalétique=7868, ES 2.1 (noir) Total=40911 → 41000. « — » pour réfs sans MOQ.

## Changelog 23/06/2026 (v2)
- [x] **Nouvelles colonnes dans le tableau Commandes** : Flèche, Signalétique, Saisonnier, Total+MOQ.
  - Backend `server.py` :
    - Constante `MOQ_BY_REF` (57 références, hardcodée depuis MOQ.xlsx).
    - Helper `_apply_total_moq_and_bonuses()` qui :
      - Expose `_fleche_bonus` / `_rail_bonus` / delta surface en champs dédiés (`fleche`, `signaletique`, `saisonnier`).
      - Calcule `total_moq = ceil(total / moq) * moq`. « — » si la réf n'a pas de MOQ.
      - Nettoie l'ancien suffixe « — rajout de X rails/flèches » dans la désignation (rétro-compatible).
    - Appelé à : build initial, lecture dataset, PATCH/DELETE recap-row, surface, dongles.
    - Flèche : valeur appliquée à ES 1.5 (noir) ET SA 1.5 (noir) si les 2 existent.
    - Signalétique : sur ES 1.5 (noir/blanc) uniquement.
    - Saisonnier : sur SA 2.1 (noir) ET SA 1.5 (noir) uniquement.
  - Frontend `RecapTable.jsx` : 4 nouvelles colonnes, en-têtes colorés (Flèche amber / Signalétique purple / Saisonnier orange / Total+MOQ indigo), valeurs en lecture seule (calculées auto).
- [x] Testé end-to-end : surface +10000 → SA 2.1 saisonnier=4800, SA 1.5 saisonnier=1200 ; Total+MOQ correct pour les 57 réfs listées ; "—" affiché si réf non MOQ.

## Changelog 23/06/2026
- [x] **Nouvelle règle surface +/- 10000 m²** :
  - **+10000 m²** : SA 2.1 (noir) +4800, SA 1.5 (noir) **+1200 (nouveau)**, Support indiv alu SA +6000.
  - **-10000 m²** : SA 2.1 (noir) +3200, SA 1.5 (noir) **+800 (nouveau)**, Support indiv alu SA +4000.
  - Toujours **sans spare**. Suffixe « — rajout de X SA sans spare » sur les désignations.
  - Endpoint `update_surface` refactoré avec helper `_apply_delta_to_row()` (pas de duplication). Migration auto des `_surface_base_*` pour anciennes sessions.
  - Frontend `RecapTable.jsx` : libellé du bandeau surface mis à jour pour afficher les 3 lignes impactées avec leurs nouvelles valeurs.
- [x] Testé end-to-end : bascule +10000 → -10000 → null → valeurs d'origine restaurées sans dérive cumulative.

## Changelog 22/06/2026 (v2)
- [x] **Sauvegarde versionnée du Phasage avec restauration 1-clic** (`phasage_snapshots` collection, TTL 30j, 20 derniers/session).
  - Backend : `save_phasage_snapshot()` appelé à chaque `update_phasage` ; nouveau `snapshot_id` ajouté aux détails de l'audit log.
  - Endpoints : `GET /api/dataset/{id}/phasage-snapshots` (liste) et `POST /api/dataset/{id}/phasage-restore/{snapshot_id}` (restauration).
  - Avant restauration, l'état actuel est aussi snapshoté → undo possible.
  - Frontend : bouton « ↺ Restaurer » dans chaque entrée d'historique liée à un snapshot (icône `RotateCcw`, confirmation modale), remount auto des onglets Phasage via `phasageVersion` key.
  - Testé end-to-end : save→snapshot→restore→bon état restauré ✅

## Changelog 22/06/2026
- [x] **Tri auto par nuit** dans Phasage de pose & Caméras pour les nouvelles sessions uniquement.

## Changelog 21/06/2026 (v2)
- [x] **Sync auto Batterie & Software caméra** : nouveau helper `_refresh_batterie_software_block()` dans `server.py` qui aligne automatiquement les lignes batterie + software sur la somme de caméra noire + caméra blanche. Règle :
  - `batterie.qty` = sum(qty caméras), `batterie.t+s` = sum(t+s caméras), `batterie.spare` = différence (= sum des spares caméra).
  - `software.qty` = idem, `software.t+s` = idem, **`software.spare = ""` (toujours vide)**.
  - Appelé lors du build initial, de chaque PATCH recap-row, et à la lecture du dataset.
- [x] Testé end-to-end : édition de caméra noire → batterie + software + VCare 16783 mis à jour automatiquement, cohérent en Web/Excel/PPTX.

## Changelog 21/06/2026 (v1)
- [x] Compression « Secteur/Rayon » slides Semaine PPTX (regroupement par secteur + abréviation > 8 chars).

## Changelog 20/06/2026
- [x] **Slide 7 PPTX** — fix définitif : re-link de slide21 au layout `slideLayout42.xml` (`CONTENT 1 Column - Color`, fond crème FDF6E3, sans formes décoratives) directement dans le template. Aucune surcharge programmatique nécessaire — rendu identique au PPTX cible fourni par l'utilisateur.
- [x] **Titres PPTX dynamiques** : les slides 12, 13, 18, 19 (« Tableau phasage EEG/cameras par nuit (X nuits) ») reflètent désormais le vrai `nb_nuits` (helper `_replace_nb_nuits_in_title`). Fini les « (14 nuits) » figés.
- [x] **Erreur 520 Cloudflare sur export PPTX** : la génération `build_pptx` (CPU-bound, ~2-5s sur 38 Mo) bloquait la boucle event de FastAPI → toutes les requêtes concurrentes attendaient → Cloudflare timeout. Fix : wrap dans `run_in_threadpool` + `functools.partial`. Testé sur 3 exports concurrents (5.3s chacun) et auth en parallèle (96ms).

## Changelog 17/06/2026 (v2)
- [x] Slide 7 PPTX — fond crème (CONTENT 1 Column - Color) au lieu de dark teal.
- [x] Auto-suggestion nb_nuits caméras (max 170/nuit).
- [x] Toaster sonner repositionné `top-center`.
- [x] Auto-suggestion nb_nuits EEG enrichie : SA1.5 + saisonnier inclus dans le total, re-bump auto si > 4900 EEG/nuit.

## Problem Statement Original
"Je veut une application web. Je veux y mettre un excel avec 20000 lignes et je veux que l'application me crée automatiquement des nouveaux onglets avec un tri automatique. Comptage auto, etc etc... est possible?"

L'utilisateur traite des inventaires d'étiquettes électroniques (EEG) avec leurs fixations, rails et caméras. Il a fourni un fichier exemple `Prévisites Vusion_Massy (1).xlsx` (19780 lignes, 17 colonnes).

## User Personas
- **Responsable inventaire VusionGroup / déploiement EEG** : utilisateur principal qui reçoit des fichiers Excel d'inventaire (export système) et doit produire des récapitulatifs commerciaux/logistiques rapidement.

## Core Requirements (statiques)
1. Upload d'un fichier Excel `.xlsx` / `.xls` (jusqu'à 20 000+ lignes)
2. Génération automatique de l'onglet **Récapitulatif Produits** :
   - Par Type (EEG, Fixation, Rail, Caméra)
   - Ligne `TOTAL <Type>` en tête de groupe
   - Une ligne par couple (Référence, Désignation) avec somme `Quantité`
   - Ligne `Spare (+5%)` = `ceil(total × 0.05)`
   - Ligne `Inclineur` (uniquement pour Rail) = somme des Quantités de rails dont la désignation contient 1320, 1240, 990, 1187, 908, 650 ou 535 mm
   - 3 lignes vides en fin pour saisie manuelle
3. Génération automatique de l'onglet **Par Secteur / Allée** :
   - Groupé par Secteur → Rayon → N° allée
   - Comptage : `EEG ES` (Désignation commence par "ES"), `EEG SA` (commence par "SA"), `Rails`, `Caméras`
4. Onglet **Données Brutes** : affichage virtualisé des ~20 000 lignes
5. Recherche globale sur tous les onglets
6. Export Excel multi-onglets avec mise en forme (couleurs Total / Spare / Inclineur)


## Feature additions (06/02/2026) — Export PowerPoint "CR VT + Plan de phasage"
- [x] Nouveau template PowerPoint 21 slides stocké dans `/app/backend/templates/crvt_template.pptx`
- [x] Nouveau module `/app/backend/pptx_export.py` (générateur basé sur python-pptx + Pillow)
- [x] Nouveau endpoint `GET /api/dataset/{upload_id}/export-pptx` — renvoie le PPTX prérempli
- [x] Dialog "Infos magasin" (`StoreInfoDialog.jsx`) auto-ouvert après upload (étape obligatoire)
  + accessible à tout moment via le bouton **Infos magasin** dans le header
  + champs obligatoires : Nom magasin, Ville, Code magasin, Date début VT
  + champs optionnels : Adresse, Date fin VT, Participants, Resp magasin, Resp Vusion, Prestataire, Plan prévention, Version, Date validation Carrefour
- [x] Endpoint `PATCH /api/dataset/{id}/store-info` étendu pour tous ces champs, avec validation stricte des dates (rejet `2026-13-99`, `2026-02-30`)
- [x] Bouton header **PPT** (orange `#B45309`) à côté du bouton Excel (vert `#056839`) — `data-testid="export-pptx-button"`
- [x] Injection automatique dans le PPT :
  - Slide 1 (cover) : "{ville} {code magasin}"
  - Slide 4 : "Date de VT: du XX au YY"
  - Slide 6 : tableau Informations générales (Nom, Code, Adresse, VT, Participants, …)
  - Slide 9 : "Date installation: du XX au YY" (min/max du Tableau Date)
  - Slide 10 : nb nuits ES + nb nuits caméras + plage de dates
  - Slides 11/12 : titre "(X nuits)" dynamique
  - Slides 13-17 (S1-S5) : tableaux dates par semaine remplis automatiquement
  - Slide 18 : "(X nuits)" caméras + dates nuits caméras
  - Slide 19 : tableau récap caméras par nuit
  - Slide 20 : détail caméras par allée (2 colonnes)
  - Slide 21 : grand tableau récap global (EEG + Caméras)
  - Images statiques (slides 11-18) remplacées par des rendus PNG des données actuelles (avec marge 0.06")
- [x] Décorateur `@api_router.get` ajouté à `GET /api/dataset/{id}/activity` (manquant précédemment)
- [x] Tests pytest : `/app/backend/tests/test_pptx_export.py` (11/11 pass) + `test_pptx_export_e2e.py` (11/11 pass)
- [x] Testing agent : tous les flux UI validés (login, header, dialog, validation, save, export PPT 40 MB téléchargé)

## Architecture
- **Backend** : FastAPI + pandas + openpyxl + xlsxwriter
  - `POST /api/upload-excel` : upload + traitement
  - `GET /api/dataset/{id}` : récupération
  - `GET /api/export/{id}?sheet=all|raw|recap|secteur` : export Excel formaté
  - Stockage in-memory `DATASTORE` (dict clé = upload_id). Métadonnées légères dans MongoDB collection `uploads`.
- **Frontend** : React 19 + Tailwind + IBM Plex Sans/Mono + react-dropzone + react-window
  - Interface type tableur (style Excel), header avec recherche+export, onglets en bas

## What's been implemented (21/02/2026)
- [x] Backend complet : upload, parsing, génération recap & secteur, export Excel formaté
- [x] Détection automatique des colonnes (insensible à la casse, tolère variantes "Référence/Reference", etc.)
- [x] Calcul Spare (ceil 5%) et Inclineur (regex sur longueurs en mm)
- [x] Gestion JSON-safe (NaN/Inf/Timestamps)
- [x] Frontend complet : UploadZone drag-and-drop, Header avec recherche+export+reset, BottomTabs style Excel, RawTable virtualisée (react-window), RecapTable avec lignes colorées (jaune Total / vert Spare / bleu Inclineur), SecteurTable avec tfoot totaux
- [x] Tests backend : 16/16 pytest passés
- [x] Validé E2E par screenshots : 3 onglets affichent les données correctes

## Feature additions (22/02/2026)
- [x] Édition inline des lignes vides/manuelles du récapitulatif (endpoints PATCH/POST/DELETE)
- [x] Bouton "+ Ajouter une ligne" et suppression via icône poubelle
- [x] Conversion robuste de Quantité : int, float, "42", "42,5", "1 234,5" (FR locale)
- [x] Ré-export Excel inclut les lignes manuelles ajoutées
- [x] Tests backend : 41/41 (100%)

## Validations métier (sur fichier de référence 19 780 lignes)
- Total EEG = 76 366 ; Spare (+5%) EEG = 3 819
- Total Fixation = 41 806 ; Spare = 2 091
- Total Rail ; Spare = 610
- Total Caméra ; Spare = 175
- Inclineur (Rail) = 9 669
- 154 lignes Secteur / Allée

## Prioritized Backlog
### P0 (terminés)
- Upload Excel, génération 3 onglets, export, recherche

### P1 (à venir)
- [ ] Édition manuelle des 3 lignes vides + sauvegarde
- [ ] Sélection de la colonne de tri si différente de "Type"
- [ ] Mise en évidence visuelle des sous-totaux par sous-secteur dans l'onglet Par Secteur
- [ ] Persistance complète des datasets (gridfs ou disque) pour ne pas perdre au redémarrage
- [ ] LRU/expiry sur DATASTORE in-memory

### P2 (idées)
- [ ] Comparaison de deux fichiers (avant/après)
- [ ] Graphiques (recharts) : répartition par secteur, top références
- [ ] Personnalisation des produits comptés pour Inclineur (admin)
- [ ] Multi-utilisateurs avec historique

## Next Tasks
1. Recueillir feedback utilisateur sur le rendu réel (le fichier joint ressemble-t-il à ce que vous attendiez ?)
2. Activer édition inline des 3 lignes vides
3. Permettre tri/regroupement personnalisé

## Feature additions (05/06/2026, v5) — Historique des modifications (audit log)

- [x] **Collection `audit_log`** + helper `log_audit(upload_id, user, action, target, details)` non-bloquant.
- [x] **Index Mongo** : `upload_id` + TTL 1 an sur `timestamp`.
- [x] **Endpoints loggés** : `session_created` (upload), `session_deleted`, `label_changed`, `share_enabled`, `share_disabled`, `surface_changed`, `dongles_changed`, `phasage_updated` (avec liste des sous-éléments modifiés : dates / planning ES / planning Caméras / suivi), `comment_table_updated`, `recap_row_deleted`.
- [x] **Endpoint `GET /api/dataset/{id}/activity`** : retourne max 200 entrées, plus récentes d'abord, vérifie l'ownership.
- [x] **Composant frontend `ActivityPanel.jsx`** : bouton "Historique" dans le header, panel dropdown 460 px avec :
   - Badge coloré par action (créa = vert, suppr = rouge, etc.)
   - Cible (label, nom de fichier, etc.) + détails sérialisés humainement (`quantité = 500`, `19780 lignes`, etc.)
   - Timestamp relatif (`il y a 3 min`, `il y a 2 h`...) + email/nom de l'auteur
   - Bouton refresh
- [x] Validé E2E : actions de modification depuis l'API tracées et affichées correctement dans le panel.

## Feature additions (05/06/2026, v4) — Liste des jours fériés français (détection auto)



- [x] **Module `utils/frenchHolidays.js`** : calcul automatique de Pâques (algorithme grégorien anonyme) + fériés FR fixes (Jour de l'an, Fête travail, Victoire 1945, Fête nationale, Assomption, Toussaint, Armistice, Noël) + variables (Lundi de Pâques, Ascension, Lundi de Pentecôte).
- [x] **Intégration dans `PrefillDatesDialog`** : dès qu'une date Nuit 1 est saisie, l'app calcule les semaines suivantes (Lundi + 7n), détecte les fériés tombant sur Lun-Ven, et applique la règle métier :
   - Férié Lun → exclut nuit Lun
   - Férié Mar → exclut nuit Lun + nuit Mar
   - Férié Mer → exclut nuit Mar + nuit Mer
   - Férié Jeu → exclut nuit Mer + nuit Jeu
   - Férié Ven → exclut nuit Jeu
   - Auto-coche seulement si le nb de jours suggérés == nb nuits attendu pour la semaine (sinon fallback heuristique précédente).
- [x] **UI** : badge rouge `📅` sur les jours fériés (boutons Lun/Mar/Mer/Jeu), tooltip avec le nom du férié, note en bas de chaque semaine listant les fériés détectés.
- [x] Validé E2E avec date Nuit 1 = 30/03/2026 → la semaine 2 (06/04→09/04) détecte **Lundi de Pâques 2026** (6 avril) avec badge rouge sur "Lun" et message "Lundi : Lundi de Pâques".

## Feature additions (05/06/2026, v3) — Date/Secteur dans Excel Phasage pose+cam + Réordo onglets



- [x] **Excel "Phasage de pose"** récap droit + tableaux par semaine : +2 colonnes (Date dd/mm/yyyy + Secteur/Rayon). 8 colonnes au total : Nuit | Date | Secteur/Rayon | Allées | EEG | Rails ES | SA | Caméras. CF couleur préservée en sautant Date+SR (fond blanc). Sous-totaux par semaine adaptés.
- [x] **Excel "Phasage caméras"** récap droit : +2 colonnes (Date + Secteur/Rayon). 5 colonnes : Nuit | Date | Secteur/Rayon | Allées | Caméras. La Date affichée est la nuit globale (start_at + n - 1).
- [x] **Ordre des onglets UI** : Tableau date repositionné juste après « Phasage de pose » (à la demande utilisateur).
- [x] Validé E2E : export 1.5 MB, openpyxl confirme la structure correcte des deux feuilles, dates dd/mm/yyyy au format Excel natif, Secteur/Rayon dédupliqués avec ` / `.


- [x] **Bouton "Pré-remplir les dates"** dans l'onglet Tableau date → ouvre un modal `PrefillDatesDialog.jsx`.
- [x] **Logique métier 4 jours/semaine** (Lun-Mar-Mer-Jeu) avec détection automatique des fériés selon les semaines courtes du Phasage de pose :
   - 4 nuits → Lun + Mar + Mer + Jeu
   - 3 nuits → Mar + Mer + Jeu (férié Lundi par défaut)

## Feature additions (05/06/2026, v2) — Pré-remplir les dates (calendrier 4 jours/semaine)
   - 2 nuits → Mer + Jeu (férié Mardi par défaut)
   - 1 nuit → Jeu seulement
   - Règle métier : on saute la nuit dont la fin tombe sur un férié ET celle qui couvre le férié.
- [x] **Sélecteur manuel** : pour chaque semaine, l'utilisateur peut décocher/cocher des jours via 4 boutons Lun/Mar/Mer/Jeu. Badge vert si total OK, badge orange si écart avec le nombre de nuits attendu.
- [x] **Édition manuelle ultérieure préservée** : chaque cellule date reste éditable individuellement après le pré-remplissage (input HTML5 date).
- [x] **Validé E2E** : 6 nuits avec weeks=[4, 2], date Nuit 1 = 23/03/2026 (Lundi). Résultat : Lun 23, Mar 24, Mer 25, Jeu 26, Mer 01 Avr, Jeu 02 Avr — la semaine 2 saute correctement Lun + Mar grâce à la règle férié Mardi.

## Feature additions (05/06/2026) — Onglet Autre + Tableau date + colonnes Date/Secteur/Rayon



- [x] **Onglet "Autre"** (apparait uniquement si le fichier contient des fixations AUTRE*) :
   - Endpoints `/api/dataset/{id}/autre` + `/api/share/{token}/autre` qui filtrent `Type=Fixation && Référence.startswith("AUTRE")` (insensible casse/accents).
   - Composant `AutreTab.jsx` : tableau lecture seule, toutes les colonnes du fichier d'origine. Validé : 101 lignes sur le dataset vusion.xlsx.
   - Le champ `has_autre`/`autre_count` est exposé dans le payload `/dataset/{id}` pour conditionner l'affichage du tab.

- [x] **Renommage "Code couleur nuits" → "Tableau date"** (UI + Excel) :
   - Nouvel onglet UI `TableauDateTab.jsx`. Structure 4 lignes × N colonnes (N = nb nuits du planning ES + caméras avec offset start_at_nuit).
   - Lignes : **Date** (input HTML5 type="date", calendrier natif), **EEG** (auto), **Caméra** (auto), **SA** (auto, italique pour info).
   - Couleurs récurrentes bleu/jaune/rouge/vert selon position dans la semaine (cohérence avec PhasageTab).
   - Sauvegarde auto-debounce 500 ms via PATCH `/api/dataset/{id}/phasage` (champ `dates` ajouté à `PhasageFullUpdate`).

## Feature additions (04/06/2026, v4) — Nettoyage UI + Excel
   - Feuille Excel "Tableau date" générée avec les mêmes infos (16 nuits max par ligne, blocs `Nuit X` + 4 lignes), incluant les dates au format `dd/mm/yyyy`.

- [x] **Colonnes "Date" + "Secteur/Rayon" dans les tableaux phasage** :
   - **UI Phasage de pose** : récap droit ajoute 2 colonnes (Date format `JJ/MM`, Secteur/Rayon dédupliqués séparés par ` / `).
   - **UI Phasage caméras** : récap droit ajoute 2 colonnes (date alignée sur la nuit globale = `start_at + n - 1`).
   - **UI Phasage full** : tableau central ajoute 2 colonnes Date + Secteur/Rayon (font 10 px pour Secteur/Rayon).
   - **Excel Phasage full** : nouveau layout 9 colonnes (A-D ES | E Nuit | F Date | G Secteur/Rayon | H-I Cam). CF par nuit préservée. Date au format Excel natif `dd/mm/yyyy`. Total row mise à jour.
   - Backlog : ajouter les colonnes Date/Secteur dans les feuilles Excel "Phasage de pose" et "Phasage caméras" (récap droite). Les données sont déjà disponibles dans la feuille consolidée "Phasage full" et "Tableau date".


- [x] **Suppression de l'onglet "Tableau phasage"** (UI) : retiré de la barre d'onglets bas + case de rendu dans `App.js` (import `SecteurTable` retiré).
- [x] **Suppression de la feuille Excel "Tableau phasage"** : la branche `sheet in ("all", "secteur")` ne génère plus de feuille (les mêmes informations restent dans "Recap par secteur"). 12 feuilles → 11.
- [x] **Suppression du graphique "Répartition ES par nuit"** dans la feuille Excel "Phasage de pose" (chart Recharts/xlsxwriter retiré + variable `chart_row` conservée pour le placement de la note d'aide).
- [x] Validé : `xl/charts/` n'existe plus dans le `.xlsx` exporté, `Tableau phasage` n'apparaît pas dans la liste des feuilles.



- [x] **Renommage des sessions** : nouveau champ `label` (200 chars max). Endpoint `PATCH /api/dataset/{id}/label`. UI : icône crayon dans le menu Sessions → input inline (Enter pour valider, Escape pour annuler). Le filename d'origine reste affiché en gris en-dessous quand un label est défini.
- [x] **Partage lecture seule** : endpoint `POST /api/dataset/{id}/share` génère un `share_token` (24 octets url-safe) + `share_enabled=true`. `DELETE /api/dataset/{id}/share` désactive. 4 endpoints publics sans auth : `GET /api/share/{token}`, `/raw`, `/phasage-summary`, `/export`. UI : icône partage dans le menu Sessions, dialog avec lien copiable et bouton désactiver. Badge "partagé" vert dans la liste si actif.
- [x] **Vue partagée frontend** (`SharedView.jsx`) : routing par query string `?share=token`. Header dédié avec badge "LECTURE SEULE", bouton "Télécharger" (Excel complet). Onglets disponibles : Données Brutes, Commandes, Recap par secteur, Tableau phasage, Commentaire. Tous les `onUpdate/onChange` redirigés vers un toast "Mode lecture seule".
- [x] **Récupération mot de passe** :

## Feature additions (04/06/2026, v3) — Renommage, partage lecture-seule, reset mdp
   - `POST /api/auth/forgot-password` génère un token (32 octets), throttling 60s/email, logge le lien dans la console serveur (`[PASSWORD RESET]`). Réponse identique que le compte existe ou non (no email enumeration).
   - `POST /api/auth/reset-password` valide token + expiration 1h + non utilisé, met à jour `password_hash`, marque le token consommé.
   - Index TTL sur `password_reset_tokens.expires_at` pour nettoyage auto.
   - UI : lien "Mot de passe oublié ?" sous le formulaire de login. Écrans dédiés `ForgotPasswordScreen` + `ResetPasswordScreen` (routing `?reset=token`).
- [x] **Validé E2E** : renommage persisté en base et en UI, lien de partage anonyme accessible (cleared cookies + localStorage → vue partagée affichée avec 19 780 lignes + export), badge "LECTURE SEULE" visible, désactivation → HTTP 404 immédiat, forgot password → confirmation écran + lien dans logs serveur, reset → admin password mis à jour puis restauré.


## Feature additions (04/06/2026, v2) — Authentification & isolation par utilisateur


- [x] **Auth email + mot de passe JWT** (bcrypt + PyJWT, cookies httpOnly access 24h + refresh 7d, brute-force lockout 5×15min).
- [x] **Routes `/api/auth/{register,login,logout,me,refresh}`** + module `backend/auth.py` (build_auth_router, setup_auth, get_current_user).
- [x] **Seed admin idempotent au startup** : `admin@vusion.local` / `admin123` (via `.env`). Indexes Mongo : `users.email` unique, `datasets.user_id`, `login_attempts.identifier`.
- [x] **Isolation par utilisateur** : toutes les routes datasets (`/api/upload-excel`, `/api/datasets`, `/api/dataset/{id}*`, `/api/export/{id}`) requièrent un cookie d'auth valide et filtrent par `user_id`. Tentative sans cookie → HTTP 401.
- [x] **Migration des 109 sessions legacy** : script ponctuel a assigné tous les datasets sans `user_id` à l'admin (rétro-compatibilité préservée).
- [x] **Frontend** :
   - `contexts/AuthContext.jsx` (state global user, `withCredentials=true` global axios)
   - `components/AuthScreen.jsx` (formulaire Connexion/Création de compte avec onglets)
   - `Header` enrichi : affichage nom/email utilisateur + bouton **logout** rouge sur hover
   - L'app entière est gatée derrière l'auth (écran de chargement → écran de login → app)
   - Le logout vide aussi `eeg.lastUploadId` du localStorage pour ne pas leaker la session suivante.
- [x] **CORS** : `allow_origins` explicite sur `FRONTEND_URL` (incompatible avec `*` quand credentials sont activés).
- [x] **Cookies cross-origin** : `SameSite=None; Secure` quand `FRONTEND_URL` commence par `https://`, sinon `lax`.
- [x] **Validé E2E** :
   - Sans cookie → écran de login affiché ; `/api/datasets` retourne 401.
   - Login admin → 109 sessions affichées (toutes les legacy).
   - Création nouveau compte (Pierre) → 0 sessions ; logout fonctionne.
   - test_credentials.md mis à jour avec admin + utilisateur de test.


- [x] **Auto-restauration au refresh** : l'`upload_id` de la dernière session est stocké en `localStorage` (clé `eeg.lastUploadId`). Au reload de la page, l'app recharge automatiquement la session via `GET /api/dataset/{upload_id}` (incluant `surface_category` et `dongles_quantity`). Plus de perte de travail accidentelle.
- [x] **Bandeau "Restauration de la session précédente…"** affiché brièvement pendant le chargement.
- [x] **Menu "Sessions" dans le Header** (component `SessionsMenu.jsx`) : liste toutes les sessions sauvegardées sur le serveur (filename, date, nb lignes, taille gzippée) triées du plus récent au plus ancien. Permet de basculer entre fichiers à tout moment et de supprimer une session pour libérer l'espace serveur (confirmation native + cache mémoire vidé côté backend).
- [x] **Nouveaux endpoints backend** :
   - `GET /api/datasets` → liste métadonnées légères (sans payload), max 500 récents
   - `DELETE /api/dataset/{upload_id}` → supprime de MongoDB + cache `DATASTORE`
   - `GET /api/dataset/{upload_id}` enrichi avec `surface_category` + `dongles_quantity` pour restauration complète UI
- [x] **Reset (`Nouveau`) et suppression de la session active** vident le `localStorage` pour revenir à l'écran d'upload.
- [x] **Validé E2E** : restauration après refresh (toast "Session restaurée : vusion.xlsx"), 109 sessions affichées dans le menu, ouverture d'une session passée OK, suppression OK.


## Couleurs nuit fixes par position dans la semaine (03/06/2026)
- [x] Nouvelles **4 couleurs muted** récurrentes selon la position dans la semaine :
   - Position 1 → **bleu** `#DBEAFE`
   - Position 2 → **jaune** `#FEF3C7`
   - Position 3 → **rouge** `#FEE2E2`
   - Position 4 → **vert** `#DCFCE7`
- [x] Si découpage par semaine actif (ex: `weeks = [4, 2]`) : sem1 nuits 1-4 = bleu/jaune/rouge/vert, sem2 nuits 5-6 = bleu/jaune (récurrence).
- [x] Si pas de découpage : cycle modulo 4 sur le n° de nuit absolu.
- [x] Helpers module-level `night_position_in_week` + `night_color_hex` (backend) + `nightPositionInWeek` + `nightColor(n, weeks)` (frontend) centralisent la logique.
- [x] Appliqué partout : `PhasageTab.jsx`, `PhasageCamTab.jsx`, `SuiviPhasageTab.jsx`, `PhasageFullTab.jsx`, et toutes les feuilles Excel (`_write_phasage_sheet`, `_write_phasage_cam_sheet`, `_write_phasage_full_sheet`).
- [x] Validé Excel : règles conditional formatting pointent bien sur les bonnes couleurs (bleu Nuit 1, jaune Nuit 2, rouge Nuit 3, vert Nuit 4, bleu Nuit 5, jaune Nuit 6).

## Magasin 2 (03/06/2026) — Branche `magasin-2`
Cette branche applique des règles métier différentes du magasin 1 (branche `main`). Un constant module-level `STORE_MODE = "magasin_2"` dans `backend/server.py` active automatiquement ces règles.

**Différences avec magasin 1** :

| Élément | Magasin 1 (`main`) | Magasin 2 (cette branche) |
|---|---|---|
| EEG par nuit (Phasage) | ES + bonus rails + saisonnier SA 2.1 | **ES + SA 1.5 (noir+blanc) + saisonnier SA 2.1** |
| Bonus rails → ES 1.5 | inclus dans EEG du Phasage | **PAS inclus** dans EEG Phasage (mais **gardé dans Commandes**) |
| Colonne SA dans Phasage | Toutes SA cumulées | **2 colonnes séparées** : `SA 1.5` (à poser, inclus EEG) + `SA 2.1` (info) |
| Bonus rails dans Commandes | ✅ +N rails par couleur | ✅ inchangé (toujours appliqué) |

**Implémentation** :
- Backend `compute_phasage_summary` : split `sa_15` / `sa_21` par allée + dans totaux.
- Nouveaux helpers `_is_sa_15` / `_is_sa_21`.
- `phasage-summary` retourne `store_mode` (consommé par le frontend).
- Frontend `PhasageTab.jsx` : colonne supplémentaire SA 1.5 affichée en mode magasin 2, bandeau "SA 1.5 (à poser)" violet, EEG = ES + SA 1.5 (sans bonus).
- Excel export `_write_phasage_sheet` : `_Phasage_data` col B = ES + SA 1.5 en m2 (au lieu de ES + bonus), col D = SA 2.1 (au lieu de toutes SA), col E = SA 1.5 (info, déjà inclus). Bandeau "SA 1.5 (à poser) — inclus dans Total EEG" en violet. Récap SUMIFS direct sans prorata saisonnier (les zones sont assignées explicitement).

**Validation sur fichier Vusion réel** :
- Allée 1111 (CAISSES/Caisses) : 3 051 SA 1.5 → EEG = 3 051 (uniquement SA 1.5, pas d'ES dans cette allée caisses)
- Allée 102 (NAL/Papeterie) : 1 303 EEG = 350 ES + 953 SA 1.5
- Zones saisonnières : ZS1/ZS2/ZS3 = 2 000 EEG chacune (6 000 SA 2.1 saisonnier)
- Total EEG global = 71 370 (= 46 959 ES + 18 411 SA 1.5 + 6 000 saisonnier)
- Commandes recap : ES 1.5 (blanc) — rajout de 648 rails → T+S=7 454 (bonus rails toujours appliqué)

## Feature additions (02/06/2026, v5) — Excel : labels propres + lookup fonctionnel
- [x] **Affichage simplifié des allées dans l'Excel** : le `uid` composite interne (`8__PGC__Liquide`, `112__NAL__Enfants`, etc.) est désormais converti à l'export en **label court** :
   - Non-doublon : juste le n° d'allée (`"8"`, `"10"`)
   - Doublon : `"112-1"` / `"112-2"` (suffixé par l'index du doublon, comme l'utilisateur l'a fait manuellement pour ZS1/ZS2/ZS3)
   - Zone saisonnier : `"ZS1"` / `"ZS2"` / `"ZS3"` (inchangé)
- [x] **Bug VLOOKUP corrigé** : avant cette mise à jour, le plan d'attribution gauche stockait le `uid` complet (ex: `8__PGC__Liquide`) en col A mais `_Phasage_data` col A stockait seulement le n° d'allée → VLOOKUP échouait → EEG = 0 partout. Désormais les deux côtés utilisent le **même label court** → les formules SUMIFS calculent correctement EEG/Rails ES/SA par nuit.
- [x] **Zones saisonnières dans `_Phasage_data`** : ajoutées comme allées sélectionnables avec leur EEG (2000 chacune). Le VLOOKUP retourne la valeur attendue quand l'utilisateur affecte une ZS à une nuit.
- [x] **Helper `_allee_display_label` + `_build_uid_to_label`** (module-level) centralisent la logique de conversion uid → label court. Réutilisés dans : `_write_phasage_sheet`, `_write_phasage_cam_sheet`, `_build_consolidated_nuit_data`, `_write_phasage_full_sheet`.
- [x] Le mapping caméras tire désormais sur l'ensemble des allées du summary (pas juste celles avec caméras > 0) pour rester robuste si l'utilisateur affecte par erreur une allée sans caméras.

## Feature additions (02/06/2026, v4) — Bonus rails dans l'export Excel Phasage de pose
- [x] **`_Phasage_data`** (feuille cachée) : la colonne EEG = ES 1.5 + ES 2.1 + bonus rails (noir + blanc). Nouvelle colonne "Bonus rails" (col E) en info.
- [x] **Total EEG** dans l'en-tête de la feuille "Phasage de pose" inclut désormais le bonus rails (ex : 55 475 = ES brut 46 959 + bonus 8 516 + saisonnier 0).
- [x] **Nouveau bandeau** ligne 4 cols G–I : "Bonus rails → ES 1.5 : 8 516 (noir 7 868 / blanc 648)" en bleu clair pour signaler la composition.
- [x] Les VLOOKUP du tableau de planification tirent désormais sur la nouvelle colonne EEG (ES + bonus). Les formules SUMIFS du récap par nuit sont automatiquement compatibles.
- [x] Validé export complet (1.5 MB) : 12 feuilles présentes, `_Phasage_data` contient bien EEG combiné par allée (ex. Allée 2 → EEG = 501 incl. 80 de bonus).

## Feature additions (02/06/2026, v3) — Bonus rails comptabilisé dans Phasage de pose
- [x] **Le bonus rails → ES 1.5 est désormais réparti par allée et compté dans le Phasage de pose** : `compute_phasage_summary` ajoute `es_15_bonus_noir` et `es_15_bonus_blanc` à chaque allée + aux totaux globaux.
- [x] L'EEG affiché par allée dans le plan d'attribution intègre désormais le bonus (ES 1.5 + ES 2.1 + bonus rails noir + bonus rails blanc).
- [x] L'EEG total par nuit (récap droite) intègre le bonus rails des allées affectées (tooltip détaillé : "ES brut + Bonus rails + Zone saisonnier").
- [x] **Bandeau totaux** : nouveau pavé "Bonus rails → ES 1.5 : +N (noir X / blanc Y)" affiché quand > 0. Le label "Total EEG" devient "(ES + bonus rails + saison.)" pour clarifier la composition.
- [x] Validé sur fichier Vusion : bonus = 7 868 ES 1.5 noir + 648 ES 1.5 blanc → bien réparti par allée (ex. Allée 19 : 1149 ES brut + 184 bonus noir = 1333 EEG total).
- [x] Phasage caméras : confirmation que les 66 allées avec caméras sont bien toutes listées dans le dropdown (filtre `cameras > 0`, tri ascendant).

## Feature additions (02/06/2026, v2) — Doublons d'allée + tri ascendant strict
- [x] **Conservation des doublons d'allée** : `compute_phasage_summary` utilise désormais une clé composite `f"{allée}__{secteur}__{rayon}"` au lieu de simplement `str(allée)`. Une même allée présente dans plusieurs (secteur, rayon) du fichier source apparaît N fois dans `summary.allees` au lieu d'être silencieusement fusionnée.
- [x] Chaque entrée porte un `uid` unique + flags `is_dup`, `dup_index`, `dup_total` pour permettre au frontend de les distinguer visuellement.
- [x] **Marqueur visuel** dans les dropdowns Phasage pose et Phasage caméras : préfixe 🟠 `[DOUBLON N/M]` + texte orange + fond `bg-orange-50` pour chaque entrée dupliquée. Permet de choisir explicitement laquelle des 2 allées 112 (NAL/Enfants vs NAL/Loisirs) on cible.
- [x] **Tri strict ascendant numérique** : retrait de la logique "smart prefix" qui plaçait "4" après "40". Maintenant ordre simple : 2, 4, 5, 6, ..., 10, 11, 12, ..., 110, 112 (×2), 1001, 1120.
- [x] Frontend `PhasageTab.jsx`, `PhasageCamTab.jsx`, `SuiviPhasageTab.jsx`, `PhasageFullTab.jsx` migrés vers `String(a.uid || a.allee)` (fallback rétro-compatible avec datasets pré-migration).

## Feature additions (02/06/2026) — Zones saisonnières + Bonus rails ES 1.5
- [x] **Zones saisonnières dans Phasage de pose** : la catégorie surface du magasin ajoute désormais des **allées virtuelles sélectionnables** dans le dropdown du plan d'attribution :
   - `+ 10 000 m²` → 3 zones (`Zone saisonnier 1/2/3`) de 2000 EEG chacune (= 6000 SA 2.1 noir)
   - `− 10 000 m²` → 2 zones de 2000 EEG (= 4000 SA 2.1 noir)
   - Chaque zone est listée en fin de dropdown avec un préfixe 🌶 et le libellé "+2000 EEG".
   - La répartition prorata automatique du saisonnier est **remplacée** : l'utilisateur affecte explicitement chaque zone à une nuit. EEG par nuit = ES affectés + zones saisonnières affectées.
- [x] **Bonus rails → ES 1.5 (sans spare)** : à l'upload, chaque rail de longueur 1240(n) / 1320(b·n) / 535(n) / 650(n) / 990(b·n) ajoute **+1 EEG ES 1.5** de même couleur au `total_plus_spare` (sans spare additionnel). Désignation suffixée " — rajout de N rails".
   - Nouvelle constante `RAILS_BONUS_ES15` indépendante de `RAILS_ES_PATTERNS` (1187 mm est exclu du bonus mais reste dans le décompte rails ; 535 mm est inclus dans le bonus mais reste hors décompte rails).
   - **Action utilisateur** : les datasets uploadés AVANT cette mise à jour ne contiennent pas le bonus → ré-uploader le fichier Excel pour bénéficier de la règle.

## Feature additions (01/06/2026, v3) — Cohérence visuelle SA 2.1 + suppression graphique Phasage
- [x] **SA 2.1 (noir) — règle finale validée par l'utilisateur** : le delta (+6000/+4000) est désormais ajouté **à la fois sur `quantite` ET sur `total_plus_spare`** (le spare reste inchangé). Ainsi `Quantité + Spare == Total+Spare` visuellement, et la mention "— rajout de X SA sans spare" justifie pourquoi le Spare n'est pas 5% du nouveau total.
- [x] Recovery pour les datasets hérités où `_surface_base_total` était stocké à 0 alors que `_surface_base_quantite > 0` : recalcul auto à `quantite + spare` à la 1ère réactivation.
- [x] **Onglet "Tableau phasage (EEG)"** : suppression complète du graphique Recharts "Répartition par nuit" (demande utilisateur). L'import recharts a aussi été retiré.
- [x] Validé curl : Q=9974 → après +10000m² : Q=15974, S='', T+S=15974 (cohérent, +6000 visible).

## Feature additions (01/06/2026, v2) — Fix bugs critiques utilisateur
- [x] **Bug N° Elements caméras vide** (capture utilisateur) : `compute_phasage_summary` utilisait `next((c for c in [...] if c in columns))` insensible aux variantes "Élément" (É capitalisé), "Gondole", etc. → remplacé par `_detect_element_col` (lowercase matching) **+ fallback positionnel colonne G (index 6)**. Désormais robuste à tous les noms de colonnes possibles.
- [x] **Bug SA 2.1 nouvelle ligne** (capture utilisateur) : nettoyage **systématique** des anciennes lignes orphelines `kind="surface_added"` (héritage des versions buggées) au début de chaque appel `PATCH /surface`. La recherche cible maintenant **uniquement `kind="product"`** pour éviter de matcher une vieille ligne orpheline.
- [x] Validé sur dataset Vusion réel (104 lignes) : le nombre total de lignes reste **stable** (104) entre null/plus_10000/moins_10000, et la ligne SA 2.1 (noir) existante reçoit bien la mention "— rajout de X SA sans spare" + le delta dans son `total_plus_spare`.

## Feature additions (01/06/2026) — Surface magasin + doublons caméras + UI chart
- [x] **Surface magasin (+/- 10 000 m²)** : règle revue. Le delta (+6 000 ou +4 000) s'ajoute désormais **uniquement** au `total_plus_spare` de la ligne "SA 2.1 (noir)" existante du recap (jamais sur `quantite` ni sur `spare`). La désignation est suffixée " — rajout de X SA sans spare" pour signaler visuellement la règle métier.
- [x] **Bouton bascule Surface** redimensionné : padding et police plus grands (`px-5 py-2.5 text-base`), bordure renforcée, label "Surface magasin :" en gras, indicateur secondaire "→ +6 000 SA 2.1 (noir) sans spare" quand actif.
- [x] **Doublons éléments caméras** : la colonne "Détail éléments" du Phasage caméras détecte les éléments présents plusieurs fois dans une allée (= plusieurs caméras sur le même mobilier) et les affiche en `text-red-600 font-bold`.
- [x] **Bug visuel chart overlap** : ajout de `overflow-hidden`, `min-height`, `position: relative` et `zIndex: 0` sur les conteneurs Recharts de PhasageTab et PhasageCamTab, plus `mt-8` au lieu de `mt-6` pour aérer.
- [x] Migration auto de l'ancien schéma `_surface_base` → `_surface_base_quantite/_surface_base_spare/_surface_base_total/_surface_base_designation` (idempotent).
- [x] Tests : nouveau `tests/test_surface_sa21.py` (5 cas — plus_10000, moins_10000, null restitution, no-double-apply, switch entre catégories).


## Feature additions (25/05/2026, v4) — Phasage caméras + full + Suivi
- [x] Schéma MongoDB `phasage` nesté : `{es:{nb_nuits,rows}, cam:{nb_nuits,rows,start_at_nuit}, suivi:{rows}}` avec migration auto de l'ancien format plat (`_normalize_phasage`)
- [x] Endpoints adaptés : `GET /api/dataset/{id}/phasage-summary` renvoie le phasage nesté + `totals.cameras`; `PATCH /api/dataset/{id}/phasage` accepte `PhasageFullUpdate` (Pydantic) avec `es`, `cam`, `suivi`
- [x] **Onglet "Phasage caméras"** (frontend `PhasageCamTab.jsx`) : planificateur dédié aux caméras (noire/blanche uniquement), sélecteur Nb nuits + Démarre à la nuit X (label "Nuit 5/6/…"), indicateur ~300/nuit, sauvegarde debounced, graphique Recharts violet
- [x] **Onglet "Phasage full"** (frontend `PhasageFullTab.jsx`) : vue consolidée lecture-seule combinant ES + Caméras par nuit globale, type auto (ES / Caméras / Mixte), badges colorés
- [x] **Onglet "Suivi phasage"** (frontend `SuiviPhasageTab.jsx`) : tableau Prévu / Réel / Diff pour ES et Caméras + colonne Rails ES géolocalisé, saisie inline (cellules jaunes), calcul de Diff temps-réel, sauvegarde debounced
- [x] **Export Excel** : 3 nouvelles feuilles dans le `.xlsx` exporté — "Phasage caméras" (interactive avec VLOOKUP + SUMIFS + listes déroulantes), "Phasage full" (consolidée), "Suivi phasage" (formules `=E-D` pour Diff, conditional formatting vert/rouge). Toutes les formules limitées à IF / IFERROR / VLOOKUP / SUMIFS / COUNTA / SUM / ROUND (compatible vieil Excel)
- [x] Tests : 10/10 nouveaux pytest (`test_phasage_new_tabs.py`) + 8/8 régression + frontend Playwright tout vert

## Feature additions (25/05/2026, v3) — Phasage de pose : Excel INTERACTIF
- [x] La feuille "Phasage de pose" exportée est désormais **complètement interactive dans Excel** :
   - Cellule **Nb nuits** modifiable (jaune) avec data validation 1-30 → recalcule automatiquement la moyenne
   - **Listes déroulantes** sur les cellules `N° Allée` (source = liste des allées du fichier) et `Nuit` (Nuit 1, Nuit 2, …)
   - Les colonnes **ES 1.5 / ES 2.1 / Rails ES** sont des formules `VLOOKUP` qui se mettent à jour automatiquement quand l'utilisateur change l'allée
   - Le tableau droit utilise des formules **SUMIFS** (et **TEXTJOIN** array formula pour la colonne "Allées") qui se recalculent dès qu'on change une affectation de nuit
   - Cellule "Moyenne / nuit" = formule `=IFERROR((Total ES 1.5 + Total ES 2.1)/Nb nuits, 0)`
- [x] Feuille technique cachée `_Phasage_data` (state=hidden) qui sert de table de référence aux VLOOKUP
- [x] Lignes pré-remplies avec les assignations sauvegardées en preview (les couleurs de nuit du frontend sont appliquées à la cellule Nuit)

## Feature additions (25/05/2026, v2) — Améliorations Phasage de pose
- [x] Tableau gauche : **select déroulant** avec uniquement les allées qui existent dans le fichier (libellé = numéro + secteur/rayon, fini la saisie libre)
- [x] **Auto-exclusion** : une fois sélectionnée, l'allée disparaît du menu déroulant des autres lignes (zéro doublon possible)
- [x] **Lignes colorées par nuit** (palette douce) : Nuit 1 jaune, Nuit 2 bleu, Nuit 3 vert, Nuit 4 rose, etc. (10 couleurs en rotation). Bordure gauche colorée pour distinction rapide
- [x] Tableau droit : nouvelle colonne **Allées** listant les n° d'allées assignées à chaque nuit (ex. "1, 2, 5"), ligne TOTAL indique le nb total d'allées
- [x] Même cohérence visuelle dans l'export Excel : colonne "Allées" + même tri numérique

## Feature additions (25/05/2026) — Onglet "Phasage de pose"
- [x] Nouvel onglet **Phasage de pose** (5ème onglet en bas) pour planifier la pose d'étiquettes ES 1.5 / ES 2.1 par nuit
- [x] Sélecteur **Nombre de nuits** (1-30) + calcul automatique **Moyenne / nuit = (ES 1.5 + ES 2.1) / nb nuits**
- [x] **Détection automatique** des comptes par allée :
   - ES 1.5 : Type=EEG et Désignation contient "ES 1.5" ou "ES 1,5"
   - ES 2.1 : Type=EEG et Désignation contient "ES 2.1" ou "ES 2,1"
   - Rails ES : Type=Rail et Désignation contient une des 7 longueurs validées par l'utilisateur : 1187 mm (noir), 1240 mm (noir), 1320 mm (blanc), 1320 mm (noir), 650 mm (noir), 990 mm (blanc), 990 mm (noir)
- [x] **Tableau gauche** : ajout manuel des allées via bouton "+ Ajouter une allée", autocomplete depuis la liste des allées existantes (datalist), auto-fill ES 1.5/ES 2.1/Rails ES dès qu'une allée est saisie, dropdown "Nuit 1/2/…" + bouton supprimer
- [x] **Tableau droite** : cumul automatique par nuit (ES 1.5, ES 2.1, Rails ES, Total ES) avec ligne TOTAL en jaune. La colonne "Total ES" passe en rouge si elle dépasse l'objectif de 4 500 par nuit
- [x] **Bandeau supérieur** : totaux globaux du fichier (ES 1.5, ES 2.1, Rails ES + breakdown par longueur)
- [x] **Sauvegarde automatique** (debounced 600ms) via PATCH `/api/dataset/{id}/phasage` → persisté en MongoDB
- [x] **Export Excel** : nouvelle feuille "Phasage de pose" dans le fichier exporté (sheet=phasage ou inclus dans sheet=all)

## Feature additions (22/05/2026)
- [x] Onglet "Par Secteur" refondu en **tableau plat par rayon** (cf. maquette utilisateur) :
   - Une mini-table par Rayon : `N° Allée | Nbr éléments | <Désignation 1> | <Désignation 2> | ...`
   - "Nbr éléments" = nombre de **valeurs distinctes** de la colonne G (élément/gondole) par allée
   - Valeurs par produit = somme des Quantités par Désignation pour l'allée
   - Ligne TOTAL automatique au bas de chaque rayon
- [x] Bascule UI : "Désignations rayon" (colonnes = produits présents dans CE rayon) vs "Toutes désignations" (mêmes colonnes pour tous les rayons)
- [x] Export Excel `?sheet=parsecteur` génère **2 feuilles distinctes** :
   - **Par Secteur (rayon)** : colonnes produits dynamiques par rayon
   - **Par Secteur (global)** : toutes les désignations du fichier comme colonnes
- [x] Lazy-load des données brutes déclenché aussi sur l'onglet "Par Secteur"
- [x] Détection automatique de la colonne G (Element / Élément / Gondole / N° élément, avec fallback positionnel)
- [x] Tests backend mis à jour pour valider les nouveaux noms de feuilles


## Bug fixes (11/06/2026) — Phasage caméras & UX export
- [x] **Excel RTR / onglet "Phasage caméras"** : totaux caméras par nuit qui apparaissaient à 0
  - Cause 1 : les formules `VLOOKUP` / `SUMIFS` étaient écrites sans valeur en cache → LibreOffice et certains modes d'ouverture Excel affichaient 0 jusqu'à un recalcul manuel
  - Cause 2 : si la DB stocke un uid composite `{N}__{SECTEUR}__{RAYON}` qui n'existe plus après re-upload (secteur/rayon différent), le mapping `uid → label` échouait silencieusement → label brut affiché et VLOOKUP en échec
  - Correctifs :
    - Ajout d'une **valeur en cache** (`value=` sur `write_formula`) pour `B` (caméras VLOOKUP), `I` (total par nuit SUMIFS), `D4` (moyenne), `H{n}` (COUNTA), et la cellule TOTAL
    - Ajout d'un **fallback par numéro de base** dans `_build_uid_to_label`, `_full_allee_index` et `idx_allees_cam` via les helpers `_resolve_uid_label` et `_resolve_idx_node`
- [x] **Boutons d'export Excel RTR & Carrefour** :
  - Spinner animé (`Loader2`) qui remplace l'icône Download pendant la génération
  - Bouton désactivé pendant le téléchargement (anti double-clic)
  - Toast "Génération de l'export RTR/Carrefour…" sur les deux boutons
  - État `exportingRTR` / `exportingCarrefour` géré dans `App.js` et propagé à `Header.jsx`

## Bug fixes (11/06/2026 — soir) — Phasage caméras overlap + EEG/SA alignement Excel ↔ App
- [x] **CRITIQUE — Overlap "Détail caméras par allée" sur "Plan d'attribution"** (Excel RTR → onglet Phasage caméras) :
  - `detail_start` était calculé sur `nb_nuits` au lieu de `nb_rows_left` → la section Détail écrasait silencieusement les lignes 18+ du Plan d'attribution
  - Résultat : les SUMIFS `=Caméras` retombaient à 0 pour les nuits dont les assignations étaient au-delà de la ligne 18 (typiquement nuits 7-10 sur cas réel)
  - Correctif : `detail_start = first_data_row + nb_rows_left + 3`
- [x] **Alignement Excel ↔ App pour EEG / SA dans "Phasage de pose"** (Excel RTR) :
  - Suppression de la distribution prorata du SA 2.1 saisonnier dans la formule EEG par nuit (`=ROUND(SUMIFS+SUMIFS/SUM*$B$5,…)` → `=SUMIFS`). L'app n'incluait pas ce prorata → écart de +5 999 EEG. Désormais EEG par nuit identique entre app et Excel.
  - Ajout de `z.sa_21` dans la colonne SA (D) du lookup pour les zones saisonnières → les nuits avec ZS affichent désormais leur SA dans Excel (Nuit 13 → 3 800 SA, Nuit 14 → 4 000 SA, alignés sur l'app).
  - Total EEG (B4) ajusté pour ne plus inclure `sa_21_saisonnier` (sinon ≠ somme par nuit). Le SA 2.1 saisonnier reste affiché en ligne 5 à titre informatif.
- [x] **Avertissements "Nombre stocké sous forme de texte"** : désactivés via `ws.ignore_errors({"number_stored_as_text": "A1:Z2000"})` sur les onglets Phasage de pose et Phasage caméras (les n° d'allée sont volontairement en texte pour supporter "201-2", "ZS1"…).
- [x] **Helpers de fallback uid composite** : `_resolve_uid_label()` et `_resolve_idx_node()` étendus aux ndœuds `idx_allees_full` du Phasage de pose pour rattraper les assignations DB obsolètes (re-upload avec secteur/rayon différent).


## Feature (12/06/2026) — Bloc VCare dans le tableau Commandes
- [x] **Mapping VCare** (1 produit installé = 1 VCare correspondant) :
  - 15024 / 17673 / 17724 → **17889** V:Care 7Y E300 1.5 BWRY
  - 17869 / 16362 → **18052** V:Care Lite 7Y ES300 1.5 BWRY
  - 15910 / 17740 → **17900** V:Care 7Y E300 2.1 BWRY
  - 17870 → **17723** V:Care Lite 7Y ES300 2.1 BWRY
  - 15912 / 17979 → **17940** V:Care 5Y E300 2.1 F BWRY
  - 15551 → **17929** V:Care 5Y E300 4.2 BWRY
  - 15550 → **17938** V:Care Lite 5Y E300 4.2 WP BWRY
  - **Tous les rails ES** (liste exacte fournie 12/06/2026 : 16957, 15507, 14745, 13585, 18173, 17285, 15395, 15506, 17868) → **18183** V:Care 7Y ES Rail
  - 11892 / 14218 → **16783** V:Care Lite 3Y Captana StoreEy
- [x] **Règle finale VCare** (option b utilisateur, 12/06/2026) : la quantité VCare = somme directe du `Total + Spare` des refs sources. Aucune soustraction des rajouts "sans spare" (réserve saisonnière) ni traitement particulier. Le VCare couvre exactement ce qui est affiché en Total dans la ligne source.
- [x] **Spare VCare** : 5 % pour ES/SA/Rails, 2 % pour le VCare caméra (16783)
- [x] **Placement** : bloc "TOTAL VCare" en fin de tableau, avant les 3 lignes vides
- [x] **Auto-recalcul** à chaque édition d'une ligne Commandes (via `_refresh_vcare_block`) → réponse PATCH inclut désormais le récap complet (`res.data.rows`) pour synchronisation temps réel
- [x] **Backfill automatique** : les sessions créées avant l'ajout du bloc VCare reçoivent le bloc à la volée lors de la lecture (`get_dataset`) et de l'export (RTR + Carrefour) — sans persistance, pour rester idempotent
- Refs des fonctions clés : `VCARE_MAPPING`, `_build_vcare_rows()`, `_refresh_vcare_block()` dans `/app/backend/server.py`



## Feature (05/07/2026) — Éclatement colonnes SA + isolation caméras (étape Phasage)
- [x] **3 colonnes SA à installer** dans les 2 tableaux du step Phasage (plan par allée + récap par nuit) : `SA 1.5`, `SA 2.1`, `SA 2.1 frz` (vertes) — affichent UNIQUEMENT les SA à poser selon la config du panneau "Installer des EEG SA" (par secteur/rayon), pas toutes les SA.
- [x] **Colonne italique "SA magasin"** (info) = SA restantes installées par le magasin (total SA allée − SA à installer). Vaut 0 si "Toutes" cochées.
- [x] **SA à installer comptées dans l'EEG à poser** (par allée + par nuit + total) — cohérence App ↔ Excel.
- [x] **Tableau caméras dédié** `Récap caméras par nuit` (data-testid=phasage-cameras-table), colonne Caméras retirée du récap EEG.
- [x] **Helpers** : `computeNodeSaInstall` + `nodeSaTotal` (frontend SaInstallPanel.jsx) et miroir Python `compute_node_sa_install` + `node_sa_total` (server.py). Clé secteur/rayon = "secteur|||rayon" (défauts "(Sans secteur)"/"(Sans rayon)").
- [x] **Exports mis à jour** :
  - Carrefour "Récap EEG par nuit" : 10 col (ajout SA 1.5/2.1/frz/magasin).
  - Carrefour "Récap complet" : 13 col (bloc EEG élargi + caméras isolées, Nuit reste blanche).
  - RTR "Phasage full" : 13 col (même structure, CF par nuit ajustée sur col Nuit=I).
  - RTR "Phasage de pose" : EEG (col B _Phasage_data + Total EEG) inclut désormais les SA à installer.
- [x] Validé : pytest test_export_carrefour.py 8/8 + e2e manuel + testing agent frontend 100% (iteration_7.json).
- Fichiers : `frontend/src/components/PhasageTab.jsx`, `SaInstallPanel.jsx`, `backend/server.py` (`_aggregate_phasage_for_export`, `_write_phasage_full_sheet`, `_build_carrefour_export`, `_Phasage_data`), `backend/tests/test_export_carrefour.py`.
- Backlog connu (hors scope) : bouton "PowerPoint" encore visible dans le header alors que l'endpoint PPTX a été retiré (iteration 6) ; warning React `<span> in <option>` non bloquant ; PhasageTab.jsx > 700 lignes à découper.

## Suite (05/07/2026) — Masquage "SA magasin" (Toutes) + adaptation PPTX
- [x] **Frontend** : colonne "SA magasin" masquée dans les 2 tableaux Phasage quand `sa_install.enabled && toutes` (elle valait toujours 0). Booléen `hideSaMagasin` (PhasageTab.jsx).
- [x] **Exports Excel** : colonne "SA magasin" MASQUÉE (set_column hidden=True, sans réagencer) quand Toutes — "Récap EEG par nuit" (col J), "Récap complet" (col G), RTR "Phasage full" (col G).
- [x] **PPTX (`pptx_export.py` + adaptateur `server.py`)** :
  - Slide 12 (Récap par nuit) + slides Semaine : colonne SA unique éclatée en `SA 1.5 / SA 2.1 / SA 2.1 frz` (+ `SA magasin` masquée si Toutes), colonne **Caméras retirée** (caméras isolées slides 17-18). Table élargie via `_ensure_table_cols` + largeurs `_set_col_widths_by_ratio`.
  - Vues compactes (slide 11 "Tableau date", slide 20 consolidé) : valeur "SA" = **SA à poser** (total à installer) pour cohérence, libellé "SA posées".
- [x] Validé e2e : PPTX (24 Mo, slide 12 = 10 col partiel / 9 col Toutes, caméras absentes), Carrefour & RTR (colonnes SA magasin hidden=True en Toutes), pytest 8/8.
- [x] **(05/07/2026) Sécurisation ligne « Support individuel alu SA »** : quand le fichier importé ne contient PAS cette ligne, la sélection surface la crée avec la **référence 16808** (`SUPPORT_ALU_SA_REF`, MOQ=100 déjà connu) → export non bloqué, 100% saisonnier (6000 pour +10000 m², 4000 pour −10000 m²). Garde anti-doublon : recherche par désignation PUIS par réf 16808 (`_find_by_ref`) avant création → jamais deux lignes avec la même réf. Si la ligne existe déjà (fichier), le delta incrémente son `saisonnier` (réf d'origine conservée). Fichier : `backend/server.py`. Validé : 1 seule ligne après bascules multiples, MOQ appliqué (Total+MOQ 6000/4000), exports 200, pytest 8/8.

## Suite (05/07/2026) — Max nuits de pose 16 → 20 + fluidité UI
- [x] **20 nuits de pose max** (au lieu de 16) : `MAX_ES_NIGHTS=20`, valeurs standard `ALLOWED_ES_NIGHTS=[10,12,14,16,18,20]`, input `max=20` + clamp 20, avertissements fourchette 10-20. Suggestion auto : semaines de **4 nuits** + reste (ex : 20 → **5 semaines de 4**). Pas de 5ᵉ couleur (palettes restées à 4). PPTX : une **5ᵉ slide "semaine" est clonée** à la volée (`_duplicate_slide`) quand le phasage dépasse 4 semaines, insérée après la 4ᵉ ; détection des tables phasage/date rendue robuste (tri par nb de colonnes). Validé e2e : 20 nuits → 5 slides semaine (S1:1→4 … S5:17→20), 12 nuits → 3 slides (S4 supprimée), exports PPTX/RTR/Carrefour = 200, pytest 8/8.
- [x] **Fluidité UI (ressenti "appli pro")** : animations de transition au changement d'étape/onglet (`eeg-fade-in`), spinner animé (composant `LoadingState`) pour restauration session + chargement données, spinner sur bouton "Valider et continuer" (validation étape 2) et sur cartes d'export pendant génération, micro-interactions (enfoncement boutons, survol onglets, lift cartes export), respect `prefers-reduced-motion`. Fichiers : `index.css`, `App.js`, `WizardSteps.jsx`, `components/LoadingState.jsx`.

## Suite (08/07/2026) — Nettoyage UI exports + nouvelle catégorie "4.2/4.2 WP"
- [x] **Boutons d'export retirés** : suppression des 3 boutons (Excel RTR / Excel Carrefour / PowerPoint) du Header + des 4 boutons "Exporter cette vue" des sous-onglets (ParSecteurTable, PhasageCamTab, PhasageFullTab, SuiviPhasageTab). Tous les exports se font nativement à l'Étape 5.
- [x] **SA install : allées dépliables + présélection auto** : le breakdown SA (`phasage-summary`) inclut désormais le détail des allées par rayon. Dans le panneau SA, chaque rayon est dépliable pour voir ses allées (lecture seule). Cocher "SA 1.5" ou "SA 2.1" présélectionne automatiquement tous les rayons concernés (`allKeysForField`).
- [x] **Nouvelle catégorie "4.2/4.2 WP"** (demande 08/07) : traitée exactement comme le freezer, colonne dédiée juste après "SA 2.1 frz". Détection = désignation SA contenant "4.2" (regroupe "SA 4.2" et "SA 4.2 WP"). Famille SÉPARÉE des SA 2.1.
  - Backend (`server.py`) : `_is_sa_42`, champ `sa_42` dans totals/node/summary/breakdown/allees, `SaInstallConfig.sa_42`, `compute_node_sa_install`/`node_sa_total`, agrégations par nuit (`sa_inst_42`), totals_es, adaptateur PPTX.
  - Exports : colonne "4.2/4.2 WP" ajoutée dans Carrefour (Récap par nuit, Semaine S*, Récap complet), RTR (Récap par nuit, Semaine S*, Phasage full — décalage colonnes + CF/formules ajustés) et PPTX (slide Récap par nuit + slides Semaine).
  - Frontend (`SaInstallPanel.jsx`, `PhasageTab.jsx`) : case à cocher "4.2/4.2 WP" (comme freezer, tout ajouté), ligne "Toutes les 4.2/4.2 WP seront ajoutées", colonne dans la grille d'allées + Récap par nuit (Total inclut 4.2), `computeSaToInstall`/`computeNodeSaInstall`/`nodeSaTotal`.
  - Validé e2e : upload synthétique (SA 4.2 + 4.2 WP = 13) → summary/breakdown corrects, exports RTR/Carrefour/PPTX = 200 avec valeurs et alignement colonnes vérifiés (Récap par nuit N1=6/N2=7/Total=13, Phasage full CF sur col Nuit=J). Checkbox visible dans le panneau SA.

## Suite (08/07/2026 bis) — Sélection au niveau ALLÉE
- [x] La sélection SA passe du niveau rayon au niveau **allée** : clé de sélection = `secteur|||rayon|||allée`. Arbre à 3 niveaux dans le panneau SA (secteur → rayon → allée), case à cocher à chaque niveau (secteur/rayon en select-all avec état indéterminé si partiel). `allKeysForField` renvoie les clés d'allée. `computeSaToInstall`/`computeNodeSaInstall` (front) + `_sa_install_key(sec,ray,allee)`/`compute_node_sa_install` (back) mis à jour.
- [x] Validé e2e : upload 2 allées même rayon (allée1 SA1.5=5, allée2 SA1.5=3), sélection allée1 seule → export Récap par nuit N1=5 / N2=0. Cases d'allée visibles et cochables à l'écran.

## Suite (08/07/2026 ter) — +600 flèches automatiques sur ES 1.5 (noir)
- [x] Ajout automatique fixe de **600** dans la colonne « Flèche » de la ligne **ES 1.5 (noir)** de la commande (constante `FLECHE_FIXED_ES15_NOIR=600` dans `server.py`, bloc bonus flèches de `build_recap_produits`). Ajouté à `total_plus_spare` **sans spare**, cumulé avec le bonus flèches existant. Reste du calcul (Total + MOQ) inchangé.
- [x] Ces 600 EEG **n'entrent PAS dans le phasage** (recap/commande uniquement — le phasage lit les données brutes). Validé e2e : ES 1.5 (noir) 100 qté → flèche=600, total+spare=705 (sans spare add.) ; phasage-summary es_15=150 (100 noir+50 blanc, non gonflé).
- Note : s'applique aux **nouveaux uploads** (recap construit à l'import). Les sessions déjà créées ne récupèrent le +600 qu'après re-upload.

## Suite (08/07/2026 quater) — Récap sans sous-totaux + détail SA partout + "EEG ES"
- [x] **Récap par nuit à plat** (sans lignes « Sous-total Sx » qui perturbaient les calculs) : feuille dédiée « Récap par nuit » (Carrefour + RTR) réécrite en liste plate (nuits + TOTAL). Le « Découpage par semaine » (tableau distinct) garde ses sous-totaux (c'est sa fonction).
- [x] **Détail des types SA partout** : colonnes SA 1.5 / SA 2.1 / SA 2.1 frz / 4.2/4.2 WP dans la feuille « Récap par nuit » (avant : freezer fusionné dans 2.1), dans la feuille « Phasage de pose » (tableaux droite « Récap par nuit » + « Découpage par semaine », valeurs SA statiques via compute_node_sa_install), et dans le PPTX (slide Récap par nuit : ajout SA 2.1 frz, freezer défusionné). Les feuilles Semaine, Récap complet et Phasage full avaient déjà le détail.
- [x] **« EEG » → « EEG ES »** dans tous les en-têtes de tableaux de phasage (Excel RTR & Carrefour : Récap par nuit, Semaine Sx, Phasage de pose, Tableau date ; PPTX : slide Récap, slides Semaine, tableau compact).
- [x] Validé e2e : upload synthétique (ES+SA1.5+SA2.1+frz+4.2) → Carrefour/RTR Récap par nuit à plat avec EEG ES=168 (100+30+20+10+8) et colonnes SA correctes ; RTR Phasage de pose droite = SA détaillé statique + TOTAL SUM ; PPTX slide 12 = 11 colonnes correctes. Aucun « Sous-total » dans Récap par nuit.
- Limite connue : le tableau interactif GAUCHE « Plan d'attribution par allée » (feuille Phasage de pose RTR) garde une colonne « SA » unique (info de saisie) — non éclatée pour éviter un refactor risqué des formules VLOOKUP/validations.

## Suite (09/07/2026) — Phasage caméras = étape dédiée + retrait "Phasage full" de l'UI
- [x] Le wizard passe de 5 à **6 étapes** : Import(1) → Commande(2) → Phasage(3) → **Phasage caméras(4)** → Dates(5) → Export(6). `WIZARD_STEPS` et `stepSubTabs` mis à jour (App.js).
- [x] **"Phasage caméras"** n'est plus un sous-onglet de l'étape Phasage : c'est une étape à part entière (sous-onglet unique `pose_cam`).
- [x] **"Phasage full"** retiré de l'interface (sous-onglet + rendu + import PhasageFullTab supprimés) — il RESTE disponible dans les exports (backend inchangé).
- [x] Badges du stepper repositionnés (WizardSteps.jsx) : Complète→2, Prêt→3, Dates OK→5.
- [x] Validé : stepper affiche bien 6 étapes, l'étape 4 affiche le contenu caméras (Plan d'attribution + Récap par nuit). Compilation OK.

## Suite (09/07/2026 bis) — Correctifs tableaux PPTX
- [x] **Slide « Récap par nuit »** : la barre de titre (bandeau vert) avait un `gridSpan=8` figé alors que le tableau a 11 colonnes → 3 cellules vides dépassaient à droite. Ajout du helper `_merge_title_row()` (pptx_export.py) qui fusionne la ligne de titre sur toutes les colonnes. Titre span=11, plus de colonnes vides.
- [x] **Slides « Semaine S{n} »** : le titre « Plan de phasage … –S{n} » (largeur 8.16") chevauchait le tableau en haut à droite (L6.4"). La largeur du titre est réduite dynamiquement pour s'arrêter avant le tableau (right 6.27" < 6.4"). Plus de chevauchement.
- Non reproductible sur preview : le titre vertical « Informations Magasin » (slide 5) — sur le preview la zone de titre est large (8.16"), sans rotation ni wrap → rendu horizontal normal. Probable artefact prod (ancien build). À revérifier après redéploiement.

## Suite (10/07/2026) — Suivi déploiement : règle 5%, "à finaliser", produits extra, export enrichi, fixations cam
- [x] **Règle écart > 5% (EEG + rails ES)** : à la validation d'une allée, si un produit EEG/rails ES a un écart prévu/posé > 5%, la justification (texte libre) est OBLIGATOIRE. Backend : `_justifs_after_update` + `_guarded_allee_update` (400 sinon), champ `justification` persisté, `justif_products` exposé dans l'état. Frontend : bandeau ambre d'avertissement + zone de justification obligatoire dans le panneau de validation.
- [x] **Statut « à finaliser une autre nuit »** (`a_finaliser`) : bouton dédié dans l'écran allée → la nuit passe en ROUGE (bordure + badge « X à finaliser ») + alerte dashboard. Bouton « Reprendre la saisie » pour annuler. Une fois validée, la nuit redevient normale (choix utilisateur 3a).
- [x] **Produits non prévus** : panneau modal de validation demande « Avez-vous posé des produits non prévus ? » (désignation + qté, lignes dynamiques). Persistés (`extra_products`), affichés dans l'écran allée, agrégés dans le Stock et dans l'export.
- [x] **Export Excel de nuit enrichi (3 feuilles)** : « Nuit N » (KPIs incl. allées à finaliser, colonne Justification écart >5%, sections Produits supplémentaires + Écarts >5% et justifications, tableau Caméras si nuit couverte, incidents, photos) ; « Détail produits » ; « Synthèse déploiement » (KPIs globaux : avancement %, rythme, EEG restant, nuits estimées + tableau de TOUTES les nuits avec validées/bloquées/à finaliser/écarts, marqueur « ◀ cette nuit »).
- [x] **Fixations caméras** : champ « Fixations posées » (`fixations_reel`) par allée caméra, plan auto-détecté depuis le fichier (Type Fixation + désignation caméra), delta affiché. Inclus dans l'export.
- [x] Testé : 52/52 pytest backend + 10/10 étapes frontend (iteration_17). Nouveau fichier de tests `/app/backend/tests/test_suivi_justif_finaliser.py`.

## Suite (20/02/2026 iter41) — Rails ES visibles comme lignes distinctes dans le Stock
- [x] **Correctif Stock** : les Rails ES (`family == "rails_es"` : 1187/1240/1320/535/650/990 mm en noir/blanc) n'étaient plus visibles dans l'écran Stock car ils étaient fusionnés dans « ES 1.5 (noir/blanc) » avec la signalétique lors de l'agrégation `prod_agg`.
- [x] `backend/suivi_deploy.py` — Section « 3) Signalétique NON-rail → ES 1.5 » modifiée : on ignore désormais les produits `family == "rails_es"` lors de la fusion. Ils sont conservés comme lignes propres dans la liste `stock` retournée par `GET /api/suivi/{id}`.
- [x] **Bonus rail intact** : le bonus « 1 rail posé = +1 ES 1.5 » (`_rail_bonus_qty`) reste appliqué dans `reel_fam["es_15"]` (ligne 434-436) et dans `eeg_plan`/`eeg_reel` — l'affichage stock est indépendant de ce calcul.
- [x] Tests : `test_iter31_stock_fusion.py` mis à jour (`test_signaletique_non_rail_fusion_by_color`, `test_rails_es_stay_distinct`) — 6/6 passants. Validation E2E via curl sur `fd15443f-...` : « 990 mm (noir) » désormais présent dans le tableau `stock` avec `family=rails_es`.



## Suite (20/02/2026 iter42) — Bonus rails + flèche fixe intégrés au prévu stock (aligné phasage)
- [x] **Règle utilisateur (Commande exemple.xlsx + « base toi sur l'outil de phasage »)** : le stock du Suivi doit afficher **exactement** le "A afficher dans stock" du recap commande, en utilisant la MÊME source de vérité que la phasage de pose (`compute_phasage_summary` → `es_15_bonus_noir/blanc`, PhasageTab.jsx).
- [x] **Section 4 (nouveau)** : bonus rails → ES 1.5 (couleur). Filtrage aligné phasage : `type == "rail"` OU `family == "rails_es"` — inclut ainsi « 1187 mm (blanc) » qui est dans `RAILS_BONUS_ES15` mais pas dans `RAILS_ES_PATTERNS`. Pour chaque rail correspondant, sa quantité prévue/posée/restant à poser est **ajoutée** à l'ES 1.5 de sa couleur (mapping via `_RAILS_BONUS_COLORS`). Le rail **reste visible** sur sa propre ligne — pas de fusion.
- [x] **Section 5 (nouveau)** : import de `server.FLECHE_FIXED_ES15_NOIR` (=600) ajouté au **prévu** d'ES 1.5 (noir) uniquement (pas au posé, pas au restant à poser) — réserve commande pas posée physiquement.
- [x] **Section 3 (inchangée)** : signalétique NON-rail continue à être absorbée par ES 1.5 (couleur) (cas rare, générique).
- [x] Exemple validé sur dataset preview `fd15443f-…` : `ES 1.5 noir` prévu passé de 180 → 785 = **180 (brut) + 5 (rail 990 noir) + 600 (flèche fixe)** ; posé passé de 10 → 15 = **10 (brut) + 5 (rail bonus)** ; le rail 990 noir reste visible avec sa qté propre.
- [x] Tests : `test_iter42_stock_rail_bonus.py` (7 cas dont l'exemple complet 1773+600+9115=11488 + cas 1187 blanc + cas produit non-rail qui matche accidentellement un pattern couleur) → 7/7 passants. Aucune régression sur les tests logiques existants (11 échecs préexistants identiques avant/après, tous liés à des datasets E2E manquants).

## Suite (21/02/2026 iter43) — Rouge réservé aux VRAIS problèmes ; retards séparés (pose / géoloc)
- [x] **Règle utilisateur** : un écart négatif prévu/posé n'est PAS un retard, c'est juste une différence entre le moment du comptage (brief) et le moment de la pose (validé par le poseur). Les VRAIS retards sont ceux JUSTIFIÉS par un commentaire (retard de pose EEG OU retard de géoloc — bien séparés dans les rapports). Le rouge est réservé aux vrais problèmes (allées bloquées, retards commentés).
- [x] **Excel rapport nuit** (`backend/suivi_deploy.py`) :
  - KPI « 📈 ÉCART VS PRÉVU » : rouge → **orange** (`f_kpi_warn_*`) quand delta < 0 (avant : rouge alarmant).
  - Bandeau verdict : mention « Léger retard » et « Retard important » **supprimée**. Remplacée par « ℹ️ Écart de comptage vs pose (X EEG) — validé par le poseur » en orange. Vert conservé pour delta ≥ 0.
  - Nouveaux bandeaux ROUGES séparés : « 🚨 Retard de pose EEG justifié : X allée(s) » (allées avec `justif_products` + `justification` non vide + non `justif_ok`) ET « 🚨 Retard de géolocalisation : X allée(s) » (allées avec `geo_gap > 0` + `geoloc_comment` non vide). Bandeau bloquées séparé aussi.
  - Colonnes delta EEG dans « Détail allées », « Détail produits », « Synthèse déploiement » : nouveau format `f_delta_ok` **vert émeraude** pour delta ≥ 0 (avant : bleu/rouge/orange selon signe), `f_neg_soft` **orange** pour delta < 0.
- [x] **Frontend** :
  - `SuiviDashboard.jsx` (2×), `SuiviNuits.jsx`, `SuiviCam.jsx` : couleur delta_eeg passée de `text-red-400` → `text-amber-400` pour delta < 0, et de `text-blue-400` → `text-emerald-400` pour delta ≥ 0.
- [x] Validé : bandeau vérifié pour delta > 500 (« BRAVO »), delta ≥ 0 (« Nuit conforme »), delta < 0 (« Écart de comptage »). Excel généré HTTP 200 sur preview, aucun lint error, tests iter31 + iter42 (13/13) toujours verts.


## Suite (21/02/2026 iter44) — Caisses & Zones saisonnières exclues de la géoloc SA
- [x] **Règle métier Carrefour** : les EEG SA 1.5 et SA 2.1 sur les allées de type « caisse » (secteur commençant par « CAISSE » — ex : « CAISSES · Caisses ») et sur les zones saisonnières (`is_seasonal=True`) ne sont **jamais géolocalisés**. Les Rails ES gardent leur géoloc partout.
- [x] `backend/suivi_deploy.py` — dans `_build_state` :
  - Détection : `no_geo_sa = secteur.upper().startswith("CAISSE") or is_seasonal`.
  - Chaque produit : `is_geo = fam in GEO_KEYS AND not (no_geo_sa AND fam in ("sa_15", "sa_21_std"))`.
  - Le flag `no_geo_sa` est exposé sur l'objet allée pour les agrégations en aval.
- [x] Agrégations `geo_eeg_plan_night` / `geo_eeg_plan` : les clés géoloc sont réduites à `["rails_es"]` uniquement pour les allées `no_geo_sa=True` — les SA sur caisses/saisonnières n'apparaissent plus dans les KPI « Géoloc EEG prévues / effectuées » ni dans les alertes « Posés sans géoloc ».
- [x] **Frontend** : aucun changement nécessaire, la colonne géoloc est déjà conditionnée sur `p.is_geo` dans `SuiviNuits.jsx` (lignes 554, 580).

## Suite (21/02/2026 iter45) — Plan magasin interactif (MVP)
- [x] **Nouvelle fonctionnalité** : intégration d'un plan de magasin cliquable directement dans le suivi. Objectif : rendre visuel l'avancement du déploiement en recouvrant les allées faites/en cours/bloquées avec des zones colorées, mise à jour en temps réel.
- [x] **Backend** (`backend/suivi_deploy.py`) :
  - Modèles `FloorplanIn`, `FloorplanZone` (kind rect|polygon, coordonnées normalisées 0..1).
  - Endpoints admin `/api/suivi/{upload_id}/floorplans` (GET / POST / PUT / DELETE).
  - Endpoints terrain `/api/suivi-terrain/{upload_id}/floorplans` (accès sans auth, mêmes règles).
  - Endpoint viewer `/api/suivi-view/{upload_id}/floorplans?token=…` (lecture seule).
  - Stockage dans `db.suivi_docs.floorplans[]`. Image en base64 data-url (max 4 Mo). Sanitize coord (clamp 0..1, filtre polygones < 3 points).
- [x] **Frontend** (`frontend/src/suivi/SuiviFloorplan.jsx` — nouveau fichier, ~500 lignes) :
  - Rendu SVG natif (pas de dépendance externe — Konva initialement essayé mais retiré pour éviter les problèmes d'intégration).
  - Éditeur : upload PNG/JPEG (compressé côté client via `compressImage`), outils Sélectionner / Rectangle (drag) / Polygone (clic multiple + « Terminer »), suppression zone, sélecteur d'allée liée (groupé par secteur).
  - Rendu : zones colorées selon `allee.status` (vert=validee, orange=a_finaliser, rouge=bloquee, violet=non_faite, bleu=en cours, gris=a_faire).
  - Filtres : par nuit et par statut.
  - Multi-étages : onglets RDC / Étage 1 / etc.
  - Légende visuelle sous le canvas.
- [x] **Intégration navigation** : nouvel onglet 🗺️ « Plan » ajouté à `SuiviApp`, `TerrainApp` (édition) et `ViewerApp` (lecture seule). Fonctionne pour phases EEG et CAM.
- [x] **Compression image** : réutilise `compressImage()` existant (max 2000px, JPEG q=0.82) → image ~200-400 Ko.
- [x] Tests : `test_iter45_floorplan.py` — **7/7 verts** (CRUD admin, refus payloads invalides, clamp coords, filtrage polygones < 3 points, accès terrain sans auth, viewer read-only).
- [ ] **Phase 2 (backlog)** : snapshot du plan avec zones colorées dans le rapport Excel nocturne (via PIL côté serveur), zoom/pan mobile.

## Suite (21/02/2026 iter46) — Zoom/Pan Plan + Snapshot Plan dans le rapport Excel
- [x] **Zoom & Pan Plan** (`frontend/src/suivi/SuiviFloorplan.jsx`) :
  - Zoom molette (Ctrl ou simple, ancré sur le curseur) 0.5× → 6×.
  - Pan par drag souris (bouton gauche en mode Sélectionner, sur zone vide du plan).
  - Support tactile : 1 doigt = pan, 2 doigts = pinch-to-zoom (ancré sur le milieu des doigts).
  - Contrôles flottants coin bas-droit : Zoom+, Zoom−, Reset (Maximize2), badge % niveau de zoom.
  - Reset auto lors du changement d'étage.
- [x] **Snapshot Plan dans le rapport Excel** (`backend/suivi_deploy.py`) :
  - Nouveau(x) onglet(s) « Plan {label} » dans le fichier Nuit — un par étage/plan configuré sur le magasin.
  - Rendu via Pillow (`PIL.ImageDraw`) : base image PNG + overlay des zones colorées selon le statut de l'allée pour la nuit courante (validee/a_finaliser/bloquee/non_faite/en cours/a_faire). Les allées d'autres nuits apparaissent en teinte pâle atténuée (info seulement).
  - Labels centraux « SECTEUR N° allée » avec halo noir pour lisibilité.
  - Image redimensionnée si > 2400 px (Excel gère mal les très grandes images).

## Suite (21/02/2026 iter47) — Simplification Plan, banner « En avance », fix Excel Détail allées
### 1) Simplification du Plan (`SuiviFloorplan.jsx` + `suivi_deploy.py`)
- [x] **Zone liée à une NUIT** (numéro), pas à une allée. Un rectangle ou un polygone représente une portion des allées faites la nuit N.
- [x] **Palette 12 couleurs** — 1 couleur unique par nuit (cycle sur les nuits > 12). Constante `NIGHT_COLORS` partagée frontend/backend.
- [x] **Plusieurs zones par nuit** possibles — chaque forme est indépendante mais partage la même couleur/légende.
- [x] Toolbar : nouveau sélecteur « Dessine pour : Nuit N » à côté des boutons Rectangle/Polygone.
- [x] ZoneInspector : dropdown « Nuit associée » (avec swatch de couleur) au lieu du sélecteur d'allée par secteur.
- [x] Légende dynamique : liste uniquement les nuits présentes sur le plan avec leur couleur.
- [x] Filtre : filtre par nuit conservé (filtre par statut retiré — inutile puisque la couleur = nuit).
- [x] Modèle backend `FloorplanZone` : champ `nuit: int` remplace `allee_uid` (rétrocompat : le champ `allee_uid` reçu en entrée est ignoré, pas d'erreur).

### 2) Snapshot Excel adapté à la logique par nuit (`suivi_deploy.py`)
- [x] Overlay Pillow coloré par nuit avec la même palette RGB. Zone de la nuit courante = pleine opacité (alpha 130) + label « Nuit N ✓ » + bordure épaisse (4 px). Autres nuits = teinte pâle (alpha 55, bordure fine).
- [x] Légende Excel : ligne avec une swatch colorée par nuit présente sur le plan, « (courante) » sur la nuit du rapport.

### 3) Bandeau « EN AVANCE » — mise en avant forte
- [x] **Dashboard** : nouveau bandeau vert gradient (émeraude → teal) en tête de page si `cumul_delta_eeg > 0` OU s'il y a des allées rapatriées (`nb_rapatriees`). Affiche +N EEG au-dessus du prévisionnel, N allées rapatriées, N nuits d'avance estimée. Emoji 🎉 + badge « Bravo ».
- [x] **Excel Résumé N1** : bandeau vert plein (bg vert clair, texte vert foncé, bordure 3 px) « 🎉 EN AVANCE SUR LE PLANNING » juste avant le verdict de la nuit, uniquement si `cumul_delta_eeg > 0` OU `nb_rapatriees_total > 0`.

### 4) Fix bug Excel : « Détail allées » écarts justifiés incohérents
- [x] Onglet « Détail allées » — table « Écarts > 5% (EEG / rails ES) et justifications » : alignée sur « Résumé N1 » (iter36). Écart % passe en orange (`f_neg_soft`) et libellé « ✅ OK poseur — validé » si `justif_ok=True`. Reste rouge + « ⚠ manquante » uniquement si aucune justification.
- [x] Cohérence PJ1 ↔ PJ2 assurée : même règle appliquée dans les deux onglets.

### 5) Tests
- Aligné `test_iter45_floorplan.py` sur le nouveau schéma (`nuit` au lieu de `allee_uid`).
- **32/32 tests verts** (iter31 + iter42 + iter44 + iter45). Aucun lint error frontend/backend.
- E2E preview : plan créé avec zones Nuit 1 + Nuit 2, rapport Excel généré → onglet « Plan RDC » avec légende « Nuit 1 (courante) », « Nuit 2 » + image PNG intégrée. HTTP 200.
  - Support rectangle + polygone. Rejet gracieux si Pillow ou image data-url invalide.
  - Sanitize nom d'onglet Excel (≤ 31 chars, sans `[]:*?/\`, unique).
- [x] Testé E2E : plan de test avec 2 zones (rect + polygone) créé sur dataset preview → rapport Excel généré avec onglets « Plan RDC » + « Plan RDC Test », HTTP 200, 1 image insérée par onglet, labels et légende présents. Tests iter31/42/44/45 : 32/32 verts. Frontend recompile sans erreur.

## Suite (21/02/2026 iter48) — Plan agrandi + plans distincts EEG / Caméras
### 1) Canvas plan considérablement agrandi sur PC
- [x] Container canvas : hauteur fixe `min(75vh, 780px)` (au lieu de laisser l'aspect ratio de l'image contrôler la hauteur). Le SVG remplit maintenant à 100% en largeur ET en hauteur.
- [x] Aside droite : `lg:w-72` → `lg:w-56` (plus étroite, laisse plus de place au plan) + `sticky top-4` pour rester visible en scroll.
- [x] État vide : `minHeight: min(60vh, 600px)` avec centrage flex → même emprise visuelle que quand un plan est chargé.

### 2) Plans distincts EEG vs Caméras (base image partagée, zones séparées)
- [x] **Backend** (`backend/suivi_deploy.py`) : nouveau champ `phase_kind: str = "eeg"` sur `FloorplanIn` + `new_plan["phase_kind"]` persisté sur create (admin + terrain). Rétrocompatible : les plans sans `phase_kind` sont considérés « eeg ».
- [x] **Frontend** (`SuiviFloorplan.jsx`) : le composant reçoit maintenant le prop `phaseKind` (déjà propagé depuis SuiviApp / TerrainApp / ViewerApp). La liste des plans est filtrée par phase courante (`p.phase_kind === phaseKind`).
- [x] Badge visuel dans le header : « EEG / RAILS » bleu ou « Caméras » violet à côté du titre « Plan du magasin ».
- [x] Sous-titre explicite : « Ce plan est spécifique au phasage EEG / Rails » (ou Caméras).
- [x] Chaque nouveau plan est créé avec le `phaseKind` en cours automatiquement — pas de risque de mélange.
- [x] **Excel** : les onglets Plan sont préfixés « Plan EEG — RDC » ou « Plan CAM — RDC » pour distinguer les deux phasages dans le même rapport.
- [x] Testé E2E : plans EEG + CAM créés côte à côte sur le même dataset avec `phase_kind` correct, filtrage frontend fonctionnel.
- [x] Aucun lint error frontend/backend. 32/32 tests iter31+iter42+iter44+iter45 verts.

## Suite (21/02/2026 iter48b) — Fix taille du plan sur PC
- [x] **Bug** : sur PC, l'image du plan apparaissait toute petite centrée dans un grand cadre vide.
- [x] **Cause** : container avec `height: min(75vh, 780px)` fixe + SVG en `preserveAspectRatio="xMidYMid meet"` → l'image se fittait en hauteur et laissait des marges verticales énormes pour les plans très larges (aspect ~3:1).
- [x] **Fix** : suppression de la hauteur fixe → le container prend maintenant la largeur complète (100%) et sa hauteur s'adapte automatiquement à l'aspect ratio naturel de l'image. Plus de marges vides.
- [x] Le zoom molette + pan drag + pinch tactile restent fonctionnels.
- [x] Tests : `test_iter44_geoloc_caisses_saisonnier.py` — 12 cas (caisses en majuscule/minuscule, préfixe strict, rails toujours géoloc, agrégation nightly). **12/12 passants**, aucune régression (25/25 pour iter31+iter42+iter44).
## Suite (21/02/2026 iter48c) — Fix DEFINITIF taille plan sur PC (avec preuve visuelle)

### Cause racine (enfin identifiée avec preuve)
Les deux tentatives précédentes (iter48b et suivante) portaient sur le SVG lui-même (`height:auto`, aspect ratio). Le VRAI coupable était le conteneur **parent** :
- `TerrainApp.jsx` L161 → `<main className="max-w-3xl ...">` (**768px max**)
- `ViewerApp.jsx` L194 → même chose (768px max)
- `SuiviApp.jsx` L202 → `max-w-5xl` (1024px max)

Résultat : même sur écran 1920px, le plan était enfermé dans une colonne étroite. Aucun ajustement SVG ne pouvait compenser ça.

### Fix
Dans les 3 apps, la classe `<main>` devient conditionnelle :
- `tab === "plan"` → `max-w-[1600px]`
- autres onglets → largeur d'origine préservée (Board/Nuits/Stock/etc. inchangés)

### Validation visuelle (screenshot + mesures DOM)
Preview `/suivi/terrain`, viewport 1920x900, floorplan seed 3000x1200 :
- `main.width` : **1600px** (au lieu de 768px)
- `[data-testid=floorplan-canvas].width` : **1316px** (au lieu de ~480px)
- `svg.width` : **1314px**, height 526px, aspect 3000:1200 respecté
- Board tab (contrôle) : `main.width` = **768px** ✅ inchangé

### Fichiers modifiés
- `frontend/src/suivi/TerrainApp.jsx`
- `frontend/src/suivi/ViewerApp.jsx`
- `frontend/src/suivi/SuiviApp.jsx`

### Recommandation
Un test frontend automatisé (testing_agent) devrait couvrir ce cas en régression. L'utilisateur a choisi de tester manuellement (option a) après redéploiement.

## Suite (21/02/2026 iter48d) — Validation stricte cohérence Excel Résumé N1 ↔ Détail allées

### Test créé
`backend/tests/test_iter47_justif_coherence_excel.py` — 3 cas end-to-end qui construisent 2 allées sur la même nuit (via patch temporaire du phasage) et vérifient les couleurs de cellule ET les textes dans les 2 onglets Excel générés par `/rapport-nuit/{N}` :

| Scénario | Cellule écart % | Texte justification | Cohérence 2 onglets |
|---|---|---|---|
| `justif_ok=True` (poseur valide) | **Orange** (`FEF3C7`) partout | « ✅ OK poseur — validé » | ✅ Identique |
| `justification="Rayon réduit"` seul | **Rouge** (`FEE2E2`) partout | « Rayon réduit par le magasin » | ✅ Identique |
| delta ≥ 0 (pose ≥ prévu) | Aucun rouge sur la ligne allée | — | ✅ Pas de faux positif |

### Découverte du test
- L'onglet Résumé N1 utilise le titre **« 📌 ÉCARTS > 5% JUSTIFIÉS »** (majuscules + emoji)
- L'onglet Détail allées utilise **« Écarts > 5% (EEG / rails ES) et justifications »**
- Les deux blocs partagent EXACTEMENT la même logique de coloration (`fmt_pct = f_neg_soft if justif_ok else f_neg`) et de texte (`justification or "✅ OK poseur — validé" / "⚠ manquante"`)
- **Aucune incohérence détectée** — les 2 onglets renvoient toujours la même couleur ET le même texte pour une même ligne (allée × produit)

### Sémantique confirmée (règle utilisateur)
- Case « Tout est OK » cochée par le poseur → **orange**, jamais qualifié de retard
- Texte de justification écrit par le poseur (sans cocher OK) → **rouge** (poseur signale un vrai souci)
- Delta ≥ 0 (pose ≥ prévu) → **vert** partout, jamais rouge/orange

### Résultat
- iter47 test : **3/3 verts**
- Régression iter31 + iter42 + iter44 + iter45 : **28 passed, 7 skipped**, 0 échec
- Aucun lint error introduit
