# PRD - Application Inventaire EEG (Étiquettes Électroniques)

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
