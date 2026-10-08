"""Génère l'arborescence détaillée de phasage_crf en .docx (niveau profond)."""
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


ARBO = r"""
phasage_crf  (racine applicative — https://go-lang-43.preview.emergentagent.com)
│
├── 0. INFRASTRUCTURE RUNTIME
│   ├── Pod Kubernetes managé Emergent (2 réplicas, HPA actif)
│   ├── CDN Cloudflare  TLS 1.3  HSTS  SameSite=Lax
│   ├── Frontend  →  React 19 / Tailwind 3 / Shadcn/UI / Lucide / Sonner / Axios (cookies auto)
│   ├── Backend   →  FastAPI (Python 3.11) / Uvicorn / Pydantic v2 / Motor async
│   ├── Base      →  MongoDB (BSON gzip pour payloads lourds, index sur user_id/upload_id)
│   ├── Observabilité → supervisor logs → /var/log/supervisor/backend.{err,out}.log
│   ├── Backup Mongo quotidien (snapshot ponctuel)
│   ├── Variables d'env verrouillées : REACT_APP_BACKEND_URL / MONGO_URL / DB_NAME / FRONTEND_URL / JWT_SECRET
│   └── Hot reload supervisor (restart manuel uniquement sur .env ou install dépendances)
│
├── 1. AUTHENTIFICATION & SÉCURITÉ
│   ├── 1.1 Flow Login
│   │   ├── POST /api/auth/login  {email, password}
│   │   ├── bcrypt coût 12  →  comparaison constant-time
│   │   ├── Rate-limit  IP  →  3 tentatives / 60 s / IP  (brute-force shield)
│   │   ├── Set-Cookie  access_token  (JWT HS256, exp 24 h)
│   │   ├── Set-Cookie  refresh_token (exp 30 j, httpOnly + Secure + SameSite=Lax)
│   │   └── Journalisation last_login_at dans users
│   ├── 1.2 Flow Register
│   │   ├── POST /api/auth/register  {email, password, name}
│   │   ├── Validation email RFC 5321 (Pydantic EmailStr)
│   │   ├── Mdp fort : min 8 car, 1 maj, 1 chiffre, 1 spécial
│   │   ├── Insert users {role:"user", active:true, created_at:utc}
│   │   └── Auto-login (cookies posés immédiatement)
│   ├── 1.3 Flow Reset mot de passe
│   │   ├── POST /api/auth/forgot-password  {email}
│   │   │   └── Flag "demande en attente" visible côté superadmin uniquement
│   │   ├── Admin UI (AdminUsersPanel)  →  bouton "Réinitialiser"
│   │   ├── Génération mdp temporaire aléatoire 12 car.
│   │   └── Affichage dans l'UI pour transmission manuelle (pas d'email auto)
│   ├── 1.4 Changement de mot de passe (self)
│   │   ├── POST /api/auth/change-password  {old_password, new_password}
│   │   ├── Vérifie l'ancien mdp
│   │   ├── Hash nouveau + revocation des sessions actives
│   │   └── Invalidation des refresh_token existants
│   ├── 1.5 Rôles et permissions
│   │   ├── user       →  CRUD sur SES sessions (shared_with inclus)
│   │   ├── admin      →  user + accès lecture à toutes les sessions (support)
│   │   └── superadmin →  admin + gestion users + reset mdp + accès cross-tenant
│   │       └── Promotion AUTO au démarrage pour :
│   │           ├── nicolas.truc@vusion.com
│   │           └── smaille.haouari@vusion.com
│   └── 1.6 Isolation des données
│       ├── Fonction _owner_filter(user_id)
│       │   └── Mongo query {$or: [{user_id}, {shared_with: user_id}]}
│       ├── load_dataset() refuse si user ≠ owner ET user ∉ shared_with
│       └── Routes export/suivi re-vérifient à chaque appel (zero-trust)
│
├── 2. GESTION DES SESSIONS  (SessionsMenu.jsx)
│   ├── 2.1 Liste
│   │   ├── GET /api/datasets  →  tri desc par uploaded_at (max 500)
│   │   ├── Projection légère : upload_id / filename / label / row_count /
│   │   │                       size_bytes / share_enabled / shared_with
│   │   ├── Enrichissement : is_shared_with_me + shared_from_email
│   │   ├── Badge "partagée par X" pour les sessions reçues
│   │   └── Recherche instantanée côté client (label + filename)
│   ├── 2.2 Ouverture
│   │   ├── GET /api/dataset/{upload_id}
│   │   ├── Refresh des flat fields depuis Mongo (cross-réplica safe)
│   │   └── Store dans DATASTORE in-memory (payload lourd)
│   ├── 2.3 Renommer                                 [owner only]
│   │   └── PATCH /api/dataset/{id}  {label: "Nouveau nom"}
│   ├── 2.4 Supprimer                                [owner only]
│   │   ├── DELETE /api/dataset/{id}
│   │   ├── Nettoyage phasage_snapshots + activity_log + suivi_terrain
│   │   └── Pull des floorplans dans Emergent Object Storage
│   ├── 2.5 Partage public par lien                  [owner only]
│   │   ├── POST /api/dataset/{id}/share  →  active share_token (UUID v4)
│   │   ├── URL /api/dataset/share/{token}  (lecture seule, NO AUTH)
│   │   ├── DELETE /api/dataset/{id}/share  →  désactive
│   │   └── Dialog ShareDialog.jsx (bouton Share2)
│   ├── 2.6 Partage par email (édition complète)     [iter56 — NOUVEAU]
│   │   ├── GET    /api/dataset/{id}/user-shares                      [owner]
│   │   ├── POST   /api/dataset/{id}/share-with-user  {email}         [owner]
│   │   │   ├── Résolution email → user_id en DB
│   │   │   ├── 404 si email inconnu
│   │   │   ├── 400 si email == owner (self-share interdit)
│   │   │   ├── 409 si déjà partagé
│   │   │   └── $addToSet shared_with  (idempotent)
│   │   ├── DELETE /api/dataset/{id}/share-with-user?email=…
│   │   │   ├── Autorisé pour owner, superadmin ou self-removal
│   │   │   └── $pull shared_with
│   │   └── UI UserShareDialog.jsx (bouton UserPlus)
│   │       ├── Input email + Add
│   │       ├── Liste des accès (nom + email + X)
│   │       ├── Bandeau ambre si "partagée avec moi"
│   │       └── Bouton rouge "Retirer mon accès" (self-removal)
│   └── 2.7 Historique de session
│       ├── Collection phasage_snapshots
│       ├── PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD = 20
│       ├── Auto-rotation (DELETE des plus anciens)
│       ├── GET /api/dataset/{id}/snapshots  →  liste triée desc
│       └── POST /api/dataset/{id}/snapshots/{snapshot_id}/restore
│
├── 3. IMPORT FICHIER CARREFOUR
│   ├── 3.1 Upload
│   │   ├── POST /api/upload  (multipart)
│   │   ├── Taille max 25 MB  (chunked bypass proxy)
│   │   ├── Formats : .xlsx / .xlsm / .csv (séparateur auto ,;)
│   │   └── Validation Mime + Magic bytes (anti-fichier déguisé)
│   ├── 3.2 Détection des colonnes (fuzzy, insensible à la casse)
│   │   ├── Secteur       →  "secteur", "sector", "département"
│   │   ├── Rayon         →  "rayon", "ray", "sub-dept"
│   │   ├── N° allée      →  "allée", "n° allée", "aisle", "numero_allee"
│   │   ├── Référence     →  "référence", "ref", "sku"
│   │   ├── Désignation   →  "désignation", "designation", "label", "produit"
│   │   ├── Type          →  "type", "catégorie" (optionnel, inféré sinon)
│   │   └── Quantité      →  "quantité", "qté", "qty"
│   ├── 3.3 Normalisation
│   │   ├── Trim + collapse whitespaces
│   │   ├── Uppercase sur Secteur / Rayon pour cohérence
│   │   ├── Allée saisonnière → clé composite "<n>__SAISONNIER__ZS"
│   │   └── Qté parsing : floats admis, négatifs refusés
│   ├── 3.4 Classification auto des produits (par désignation)
│   │   ├── is_es_15        →  regex "ES\s*1[.,]?5" + exclusion freezer
│   │   ├── is_es_21        →  regex "ES\s*2[.,]?1"  (+ _f si "freezer")
│   │   ├── is_es_42        →  regex "ES\s*4[.,]?2" (_wp si "WP|water|humide")
│   │   ├── is_sa_eeg       →  regex "^SA\s*(1\.5|2\.1|4\.2)"
│   │   ├── is_sa_support   →  "support alu SA" / "pic à glace" / "fixation SA" /
│   │   │                      "support 4.2" / "support 4.2 WP"
│   │   ├── is_rail_es      →  longueur dans INCLINEUR_LENGTHS ET ref ∈ ES_RAIL_REFS
│   │   ├── is_cam_side_product  →  "caméra" / "batterie caméra" /
│   │   │                           "support mobilier captana" / "adhésif captana" /
│   │   │                           "software caméra"
│   │   ├── is_fleche       →  "signalétique flèche"
│   │   └── is_signaletique →  "signalétique" (sauf flèche)
│   ├── 3.5 Mode magasin
│   │   ├── Détection auto :  présence de "SA 1.5" dans tout le fichier → Magasin 2
│   │   ├── Sinon → Magasin 1 (bonus noir/blanc applicable)
│   │   └── Override manuel UI (store_mode field)
│   └── 3.6 Génération du recap complet
│       ├── compute_recap(raw_records, store_mode) → recap_rows
│       ├── Sectioning : EEG / Rails / Supports / Signalétique / Saisonnier / VCare
│       ├── Pré-calcul total_moq AVANT V:Care (règle 27/02/2026)
│       ├── _build_vcare_rows() : lignes synthétiques injectées
│       ├── _refresh_batterie_software_block() : bloc Captana recalculé
│       └── _apply_total_moq_and_bonuses() : flèche + signa + saisonnier + MOQ
│
├── 4. CALCULS MÉTIER (règles codées en Python, verrouillées par pytest)
│   ├── 4.1 Spare — ceil(Qté × taux)
│   │   ├── 0%  →  Software caméra + Dongles + V:Care (toutes refs)
│   │   ├── 2%  →  Caméra noire / blanche / Batterie caméra /
│   │   │          Support mobilier Captana (noir/blanc) /
│   │   │          Support ajustable adhésif Captana  (6 produits)
│   │   └── 5%  →  tous les autres (ES, SA, rails, supports, signa, saisonnier, …)
│   ├── 4.2 Total + Spare   =   Qté + Spare
│   ├── 4.3 MOQ — Minimum Order Quantity
│   │   ├── Table codée MOQ_BY_REF  (63 refs — source MOQ.xlsx 23/06/2026)
│   │   ├── Formule : Total+MOQ = ceil(Total+Spare / MOQ) × MOQ
│   │   └── Ref absente du dict → affichage "—" (pas d'arrondi)
│   ├── 4.4 Inclineurs (consolidation rails ES uniquement)
│   │   ├── Longueurs : 535 / 650 / 908 / 990 / 1187 / 1240 / 1320 mm
│   │   ├── Refs incluses :  13585 15395 15506 15507 14745 16957
│   │   │                    17285 17868 18173                 (9 refs ES_RAIL_REFS)
│   │   ├── Refs exclues :   4507  18048  9484                 (rails SA, pas d'inclineur)
│   │   ├── Spare inclineur = ceil(somme × 5%)
│   │   └── Les rails originaux restent dans le recap (pas de doublon commande)
│   ├── 4.5 V:Care (lignes synthétiques — règle 12/06/2026)
│   │   ├── Mapping VCARE_MAPPING (10 groupes)
│   │   ├── Qté V:Care = Σ total_moq des refs sources
│   │   ├── Pas de spare additionnel (sinon double comptage)
│   │   ├── Ligne saisonnière "sans spare" EXCLUE de la somme
│   │   └── Groupes:
│   │       ├── 15024 / 17673 / 17724 → 17889 V:Care 7Y E300 1.5 BWRY
│   │       ├── 17869 / 16362         → 18052 V:Care Lite 7Y ES300 1.5 BWRY
│   │       ├── 15910 / 17740         → 17900 V:Care 7Y E300 2.1 BWRY
│   │       ├── 17870                 → 17723 V:Care Lite 7Y ES300 2.1 BWRY
│   │       ├── 15912 / 17979         → 17940 V:Care 5Y E300 2.1 F BWRY
│   │       ├── 15551                 → 17929 V:Care 5Y E300 4.2 BWRY
│   │       ├── 15550                 → 17938 V:Care Lite 5Y E300 4.2 WP BWRY
│   │       ├── [9 rails ES_RAIL_REFS] → 18183 V:Care 7Y ES Rail
│   │       └── 11892 / 14218          → 16783 V:Care Lite 3Y Captana StoreEy
│   ├── 4.6 Flèche fixe (règle 08/07/2026)
│   │   ├── FLECHE_FIXED_ES15_NOIR = 600
│   │   ├── Ajouté sur la ligne ES 1.5 noir dans total_plus_spare commande
│   │   ├── Colonne "Flèche" exposée dans l'UI
│   │   └── N'entre PAS dans le phasage (commande/recap uniquement)
│   └── 4.7 Support individuel alu SA (auto-injection)
│       ├── SUPPORT_ALU_SA_REF = 16808
│       ├── Si absent du fichier Carrefour → ligne auto-créée
│       └── Qté = somme SA EEG cochées dans sa_install
│
├── 5. PHASAGE (allées × nuits)
│   ├── 5.1 Modèle de données
│   │   └── phasage = { es: {...}, cam: {...} }
│   │       ├── es.nb_nuits               int
│   │       ├── es.rows[]                 [{id, allee, nuit}]
│   │       ├── es.start_dates            {"1":"2026-03-10", "2":"2026-03-11", …}
│   │       ├── cam.nb_nuits              int
│   │       ├── cam.start_at_nuit         int (offset, ex. 5)
│   │       └── cam.rows[]                [{id, allee, nuit}]
│   ├── 5.2 Interface (PhasageTab.jsx)
│   │   ├── Panneau gauche  → Allées à phaser (liste filtrée)
│   │   ├── Panneau droit   → Grille nuits × allées (drag & drop)
│   │   ├── Modal zones saisonnières (ZS1, ZS2, …)
│   │   └── SaveStatusBanner (bannière rouge si auto-save KO)
│   ├── 5.3 Règle d'affichage d'une allée dans la liste
│   │   ├── Zone saisonnière  → TOUJOURS visible
│   │   ├── Sinon :
│   │   │   es_total = (es_15 + es_21 + fleches +
│   │   │               (bonus_noir+bonus_blanc) si M1 sinon sa_15)
│   │   │   rails    = rails_es
│   │   │   raw_sa   = sa_15 + sa_21_std + sa_21_freezer + sa_42
│   │   │   KEEP si (es_total + rails + raw_sa) > 0
│   │   └── Permet le phasage d'une allée 100 % magasin (iter55)
│   ├── 5.4 Nuits ES vs Nuits Caméra
│   │   ├── ES   →  1 .. nb_nuits_es
│   │   ├── CAM  →  start_at_nuit .. start_at_nuit + nb_nuits_cam - 1
│   │   └── Captana → routage automatique sur nuit CAM via resolve_night
│   ├── 5.5 Historique (snapshots)
│   │   ├── Déclencheurs : save explicite + auto-save
│   │   ├── Diff JSON compressé + user_id + timestamp
│   │   ├── UI icone horloge  (ActivityPanel.jsx)
│   │   └── Restauration en 1 clic (replace phasage dans datasets)
│   └── 5.6 Auto-save
│       ├── Hook useAutoSave.js  (debounce 500 ms)
│       ├── PATCH /api/dataset/{id}  {phasage|sa_install|…}
│       ├── SaveStatusBanner.jsx  → rouge si dernier save en erreur
│       └── Rejoue au focus de l'onglet si Online event
│
├── 6. SA INSTALL — qui pose quoi ?
│   ├── 6.1 Modèle sa_install
│   │   ├── enabled           bool  (feature SA activée pour ce magasin)
│   │   ├── answered          bool  (l'utilisateur a répondu au prompt initial)
│   │   ├── toutes            bool  (shortcut "toutes les SA" = VT pose tout)
│   │   ├── sa_15 / sa_21 / freezer / sa_42   bool par famille
│   │   ├── selection {sa_15:[clés], sa_21:[clés]}
│   │   │   └── clé = "SECTEUR|||RAYON|||N°allée"
│   │   └── seasonal { all: bool, zones: {"ZS1": true, "ZS2": false, …} }
│   ├── 6.2 Dispatch _split_materiel_by_recipient (iter52 → 56)
│   │   └── Itère sur raw_records :
│   │       ├── 1. Captana  →  nuit CAM via _resolve_night
│   │       │   └── sinon  →  carrefour_agg (palette)
│   │       ├── 2. is_sa_eeg + famille non cochée → Magasin
│   │       ├── 3. is_sa_support + pas d'EEG SA VT même allée → Magasin (orphelin)
│   │       ├── 4. Allée pas dans phasage ES → Magasin (palette)
│   │       └── 5. Sinon → VT
│   ├── 6.3 Sorties (6-tuple)
│   │   ├── vusion_by_nuit[nuit] = {(ref,désig): qté}            →  PPTX
│   │   ├── carrefour_agg[(ref,désig)] = qté                      →  Palette
│   │   ├── nuits[]  (union VT + magasin)
│   │   ├── night_meta[nuit] = {date, aisles, kind}
│   │   ├── vusion_by_nuit_by_allee[nuit][allee_key] = {items}    →  Planning
│   │   └── carrefour_sa_by_nuit_by_allee[nuit][allee_key] = {…}  →  SA Magasin
│   │       (allee_key = "allee|secteur|rayon")
│   └── 6.4 Règles additionnelles
│       ├── Les SA décochées JAMAIS visibles dans le suivi
│       ├── Supports SA masqués en suivi si l'allée n'a pas d'EEG SA VT
│       └── Allée phaseée 100 % magasin → entrée dans SA Magasin uniquement
│
├── 7. SUIVI TERRAIN (TerrainApp)
│   ├── 7.1 Navigation
│   │   ├── Liste des nuits  →  statut global par nuit
│   │   ├── Détail nuit      →  statut par allée
│   │   └── Détail allée     →  checklist + photos + commentaires
│   ├── 7.2 Statuts (progression)
│   │   ├── À démarrer      (gris)
│   │   ├── En cours         (bleu)
│   │   ├── Posé             (vert)
│   │   ├── Contrôlé         (vert foncé)
│   │   └── RAS              (déjà conforme avant VT)
│   ├── 7.3 Photos
│   │   ├── Upload chunked  →  Emergent Object Storage
│   │   ├── Compression auto JPEG qualité 70 côté client
│   │   ├── Thumbnails pour galerie
│   │   └── Rotation EXIF corrigée
│   ├── 7.4 Règles d'affichage
│   │   ├── Items décochés dans sa_install → cachés
│   │   ├── Supports SA cachés si has_sa_eeg_vt = false
│   │   └── Zones saisonnières décochées → cachées
│   ├── 7.5 Collaboration
│   │   ├── Partage par email → chaque poseur a sa session
│   │   └── Activity log (qui a changé quoi, quand)
│   └── 7.6 Endpoints principaux
│       ├── GET  /api/suivi/{id}
│       ├── POST /api/suivi/{id}/{nuit}/{allee}  {status, comment}
│       ├── POST /api/suivi/{id}/photo/{nuit}/{allee}  (multipart)
│       └── DELETE /api/suivi/{id}/photo/{photo_id}
│
├── 8. EXPORTS
│   ├── 8.1 PPTX de brief VT (/api/export-pptx)
│   │   ├── Slide 1   Couverture  (logo + magasin + dates + équipe)
│   │   ├── Slide 2   Sommaire
│   │   ├── Slide 3   Infos magasin + prestataire + plan prévention
│   │   ├── Slide 4-5 Vue d'ensemble planning (grille nuits × allées)
│   │   ├── Slide 6   Récap matériel global
│   │   ├── Slide 7-N Une slide par nuit (matériel + floorplan annoté)
│   │   ├── Slide 18  Captana (toutes nuits caméra)
│   │   ├── Slide 19  Commande détaillée
│   │   ├── Slide 20  N° Elements par rayon  (iter49 — fix fallback aveugle)
│   │   └── Anti-corruption ZIP XML (iter49b)
│   │       └── Vérifie aucun fichier dupliqué dans la ZIP PPTX avant livraison
│   ├── 8.2 Excel Planning (/api/export-planning)
│   │   ├── Onglet "Planning"  (matériel VT — bleu Vusion)
│   │   │   └── Pour chaque nuit:
│   │   │       ├── En-tête Nuit X — date
│   │   │       ├── Récap "Allées : ..."
│   │   │       └── Blocs Allée X — Secteur / Rayon → table (Ref, Désig, Qté)
│   │   └── Onglet "SA Magasin"  (iter54 — orange)
│   │       └── Même structure, uniquement SA à poser par le magasin
│   ├── 8.3 Excel Préparation palette Carrefour
│   │   └── /api/export-preparation-palette-carrefour
│   │       └── carrefour_agg complet (ref, désig, qté totale)
│   ├── 8.4 Excel Commande
│   │   └── /api/export-commande
│   │       └── Agrégat global : ref, désig, qté brute, spare, total+spare,
│   │           total+MOQ, inclineurs, V:Care, flèche, signa, saisonnier
│   └── 8.5 Tables de référence (hébergées sous /public)
│       ├── MOQ_par_reference.xlsx          (63 refs × MOQ)
│       ├── Spare_par_produit.xlsx          (3 catégories 0% / 2% / 5%)
│       └── Spare_par_reference.xlsx        (63 refs × taux applicable)
│
├── 9. ADMINISTRATION (/admin — superadmin uniquement)
│   ├── 9.1 Liste des utilisateurs (AdminUsersPanel.jsx)
│   │   ├── GET /api/admin/users  →  robuste même si données DB corrompues
│   │   ├── Colonnes : email / nom / rôle / dernière connexion / actif
│   │   └── Compte de datasets par owner (agrégation 1 requête)
│   ├── 9.2 Actions
│   │   ├── PATCH /api/admin/users/{id}  {role|active|name}
│   │   ├── POST  /api/admin/users/{id}/reset-password
│   │   └── DELETE /api/admin/users/{id}  (soft delete via active=false)
│   └── 9.3 Promotion automatique
│       └── Au startup, super-promotion pour :
│           ├── nicolas.truc@vusion.com
│           └── smaille.haouari@vusion.com
│
├── 10. ROBUSTESSE & QUALITÉ
│   ├── 10.1 Auto-save
│   │   ├── useAutoSave hook  →  debounce 500 ms
│   │   ├── SaveStatusBanner  →  bannière rouge si KO
│   │   └── Rejoue au focus onglet
│   ├── 10.2 Cross-réplica consistency
│   │   ├── load_dataset relit TOUJOURS depuis Mongo les champs éditables
│   │   └── Cache DATASTORE in-memory ne contient que raw_records lourds
│   ├── 10.3 Snapshots
│   │   └── 20 par upload, auto-rotation
│   ├── 10.4 Tests pytest  (/app/backend/tests)
│   │   ├── 55+ fichiers (iter01 → iter56)
│   │   ├── Chaque règle métier critique a son test
│   │   ├── conftest.py + pytest.ini (asyncio_mode=auto)
│   │   └── Lancement : cd /app/backend && python -m pytest tests/ -q
│   ├── 10.5 Anti-corruption PPTX
│   │   └── Dédup des entrées ZIP avant écriture (iter49b)
│   └── 10.6 Memory artifacts
│       ├── /app/memory/PRD.md
│       ├── /app/memory/CHANGELOG.md
│       └── /app/memory/test_credentials.md
│
├── 11. INTÉGRATIONS 3rd PARTY
│   ├── Emergent LLM Key  (budget universel)
│   │   ├── Prévue pour Gemini 3 Pro Vision (auto-phasage) — EN PAUSE
│   │   └── Non utilisée actuellement en production
│   ├── Emergent Object Storage  (photos suivi, floorplans)
│   └── Resend / SendGrid  →  NON branché (reset mdp manuel pour l'instant)
│
└── 12. BACKLOG & ROADMAP
    ├── P1  Breadcrumb Suivi (Nuits › Nuit 2 › Allée 5A)
    ├── P1  Notification in-app pour les sessions reçues
    ├── P2  Recherche SKU dans l'onglet Stock
    ├── P2  Export ZIP par nuit (Excel + photos originales)
    ├── P2  Retry Axios silencieux (502/520/524 Cloudflare)
    └── P3  Auto-phasage IA Vision (Gemini 3 Pro)  —  EN PAUSE utilisateur
"""


def _set_margins(section, cm_v=1.3, cm_h=1.3):
    section.top_margin = Cm(cm_v)
    section.bottom_margin = Cm(cm_v)
    section.left_margin = Cm(cm_h)
    section.right_margin = Cm(cm_h)


def _set_landscape(section):
    # Pour avoir plus de largeur horizontale pour l'arbo
    from docx.enum.section import WD_ORIENT
    new_width, new_height = section.page_height, section.page_width
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = new_width
    section.page_height = new_height


def build(output_path: str):
    doc = Document()
    section = doc.sections[0]
    _set_margins(section, 1.2, 1.2)
    _set_landscape(section)

    # Titre
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("phasage_crf — Arborescence fonctionnelle & technique détaillée")
    r.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = RGBColor(0x00, 0x5B, 0xAB)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run("Document interne Vusion — préparé pour Carrefour — février 2026 — v29/iter56")
    sr.italic = True
    sr.font.size = Pt(9)
    sr.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    doc.add_paragraph("")

    # Arbo en police monospace
    p = doc.add_paragraph()
    rr = p.add_run(ARBO)
    rr.font.name = "Consolas"
    # Force la font Consolas aussi sur East-Asian et Complex Script
    rPr = rr._element.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Consolas")
    rFonts.set(qn("w:hAnsi"), "Consolas")
    rFonts.set(qn("w:cs"), "Consolas")
    rPr.append(rFonts)
    rr.font.size = Pt(7.5)
    rr.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)

    # Légende
    doc.add_paragraph("")
    leg = doc.add_paragraph()
    lrun = leg.add_run(
        "Légende :  [owner only] = action réservée au propriétaire de la session.   "
        "Toutes les règles métier sont verrouillées par pytest (55+ fichiers).   "
        "Source : /app/backend/server.py + /app/memory/PRD.md.")
    lrun.italic = True
    lrun.font.size = Pt(8)
    lrun.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    doc.save(output_path)
    print(f"OK → {output_path}")


if __name__ == "__main__":
    build("/app/frontend/public/phasage_crf_arborescence_detaillee.docx")
