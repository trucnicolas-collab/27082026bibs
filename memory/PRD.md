# PRD - Application Inventaire EEG (Étiquettes Électroniques)

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
