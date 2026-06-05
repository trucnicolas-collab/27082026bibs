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

## Feature additions (05/06/2026, v2) — Pré-remplir les dates (calendrier 4 jours/semaine)

- [x] **Bouton "Pré-remplir les dates"** dans l'onglet Tableau date → ouvre un modal `PrefillDatesDialog.jsx`.
- [x] **Logique métier 4 jours/semaine** (Lun-Mar-Mer-Jeu) avec détection automatique des fériés selon les semaines courtes du Phasage de pose :
   - 4 nuits → Lun + Mar + Mer + Jeu
   - 3 nuits → Mar + Mer + Jeu (férié Lundi par défaut)
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
