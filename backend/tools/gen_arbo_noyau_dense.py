"""Arborescence phasage_crf — version noyau métier (3/4/5/6 + annexes).
Niveau "dense & technique" demandé par l'utilisateur.
"""
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


ARBO = r"""
phasage_crf  —  NOYAU MÉTIER
================================================================================

├── §0  INFRASTRUCTURE RUNTIME  (contrat d'exécution)
│   ├── Topologie
│   │   ├── Pod K8s managé Emergent · 2 réplicas · HPA · stickyless (no sticky sessions)
│   │   ├── CDN Cloudflare → TLS 1.3 · HSTS · WAF · timeout edge = 100 s
│   │   ├── Ingress → routage /api/* vers backend:8001, / vers frontend:3000
│   │   └── Cold-start p99 < 1.4 s (Uvicorn worker single, event-loop asyncio)
│   ├── Fail-conditions
│   │   ├── 520 Cloudflare → micro-coupure pod → cliente DOIT retrier (handler Axios idéalement)
│   │   ├── 502 upstream  → worker occupé > 30 s → kill + relance supervisor
│   │   └── 524 origin timeout → requête > 100 s → split chunking impératif
│   └── Contrats env (verrouillés, zéro default)
│       ├── backend/.env   : MONGO_URL · DB_NAME · JWT_SECRET · FRONTEND_URL
│       └── frontend/.env  : REACT_APP_BACKEND_URL (externe HTTPS, pas localhost)

================================================================================

├── §3  INGESTION & NORMALISATION DU FICHIER CARREFOUR
│   ├── 3.1  Pipeline de parsing (POST /api/upload)
│   │   ├── (a) MIME-sniff + magic-bytes → rejet si incohérence vs extension
│   │   ├── (b) Chunked upload (bypass proxy 25 MB) → agrégation serveur
│   │   ├── (c) Détection format :
│   │   │     ├── .xlsx/.xlsm → openpyxl  (preserve types)
│   │   │     └── .csv        → pandas.read_csv(sep="auto", quoting=MINIMAL)
│   │   ├── (d) Détection delimiter CSV via csv.Sniffer sur 2 Ko d'échantillon
│   │   ├── (e) Charset BOM-aware (utf-8-sig > cp1252 > latin-1 fallback)
│   │   └── (f) Compression BSON gzip du payload avant persistence Mongo
│   ├── 3.2  Détection fuzzy des colonnes  (score Levenshtein ≤ 2)
│   │   ├── Secteur     ⇔  "secteur"|"sector"|"département"|"departement"
│   │   ├── Rayon       ⇔  "rayon"|"ray"|"sub-dept"|"sous-rayon"
│   │   ├── N° allée    ⇔  "allée"|"allee"|"n° allée"|"aisle"|"numero_allee"|"aisle_id"
│   │   ├── Référence   ⇔  "référence"|"reference"|"ref"|"sku"|"article_code"
│   │   ├── Désignation ⇔  "désignation"|"designation"|"label"|"produit"|"libellé"
│   │   ├── Type        ⇔  "type"|"catégorie"|"category"   (optionnel, inféré sinon)
│   │   └── Quantité    ⇔  "quantité"|"qty"|"qté"|"quantite"
│   │   ╚══ Si ambigüité (2 colonnes score égal) → arbre d'ordre : priorité
│   │       absolue au nom le plus proche + présence de valeurs numériques
│   │       pour Quantité, pattern alphanumérique pour Référence
│   ├── 3.3  Normalisation des cellules (invariants)
│   │   ├── trim + collapse (\\s+ → " ")
│   │   ├── Secteur/Rayon  →  UPPER()
│   │   ├── N° allée brut → clé composite si saisonnier :
│   │   │     "{n}__SAISONNIER__ZS"           (évite collision allée 5 PGC/PLS)
│   │   ├── Référence → str(ref).strip().lstrip("0")   NON  (zéros gauches gardés)
│   │   │                                              ← volontaire : "03903" ≠ "3903"
│   │   │                                              ...sauf si MOQ_BY_REF trouve
│   │   │                                              uniquement la variante trim-0
│   │   └── Qté → float·clamp(min=0)   négatifs rejetés, exception explicite
│   ├── 3.4  Classification produits (ordre de priorité strict)
│   │   │   ┌───────────────────────────────────────────────────────────────┐
│   │   │   │ Priorité :  Captana > V:Care > Rail ES > SA EEG > SA Support │
│   │   │   │             > ES > Signalétique > Saisonnier > Dongle         │
│   │   │   └───────────────────────────────────────────────────────────────┘
│   │   ├── is_cam_side_product(désig,type) ───┐
│   │   │     ├── "caméra (noire|blanche)"     │ 6 patterns → bucket Captana
│   │   │     ├── "batterie caméra"            │ Routage via resolve_night("cam")
│   │   │     ├── "support mobilier captana"   │ Spare = 2 %
│   │   │     ├── "support … adhésif captana"  │
│   │   │     └── "software caméra"            │ Spare = 0 %
│   │   ├── is_sa_eeg(désig)                   │  regex ^SA\s*(1\.5|2\.1|4\.2)
│   │   │     └── Famille extraite : fam ∈ {sa_15, sa_21_std, sa_21_freezer, sa_42}
│   │   │         └── "SA 2.1 F" ou "freezer" dans désig → sa_21_freezer
│   │   ├── is_sa_support_fixation(désig)
│   │   │     └── {Support alu SA, Pic à glace, Fixation SA, Support 4.2,
│   │   │         Support 4.2 WP}
│   │   ├── is_rail_es(désig,ref) :
│   │   │     ├── match longueur ∈ {535,650,908,990,1187,1240,1320}
│   │   │     └── AND ref ∈ ES_RAIL_REFS (9 refs)
│   │   │     ╚══ XOR autre réf avec même longueur → rail SA → EXCLU
│   │   ├── is_es_15 / is_es_21 / is_es_42 / is_es_42_wp / is_es_21_f
│   │   │     └── Priorité _f > _wp > _42 > _21 > _15 (lecture gauche-à-droite)
│   │   ├── is_fleche  →  "signalétique flèche"
│   │   ├── is_signaletique  →  "signalétique" ∧ ¬ is_fleche
│   │   └── is_dongle  →  "dongle" (quantité saisie manuellement UI)
│   ├── 3.5  Résolution du Mode Magasin  (state machine binaire)
│   │   │
│   │   │   ┌─ Détection auto ─┐           ┌─ Override UI ─┐
│   │   │   │ ∃ "SA 1.5" dans   │ ──TRUE──▶ │  store_mode =  │
│   │   │   │ tout le fichier ? │           │  "magasin_2"   │
│   │   │   └──────────────────┘           └────────────────┘
│   │   │             │ FALSE
│   │   │             ▼
│   │   │   store_mode = "magasin_1"
│   │   │
│   │   └── Impacts :
│   │       ├── M1 : bonus_noir/bonus_blanc actifs sur ES 1.5
│   │       └── M2 : SA 1.5 compte comme ES dans le calcul "allée a du matériel"
│   └── 3.6  Fabrique du recap (compute_recap)
│       ├── Étape 1   _refresh_batterie_software_block()
│       │             └── Reconstruit le bloc Captana à partir des raw_records
│       ├── Étape 2   Pré-calcul total_moq sur produits "source"  (règle 27/02/2026)
│       │             └── Les V:Care doivent lire les total_moq, pas total_plus_spare
│       ├── Étape 3   _build_vcare_rows(rows, df, cols)
│       │             ├── Pour chaque groupe VCARE_MAPPING :
│       │             │   qté_vcare = Σ total_moq(refs_sources)
│       │             │   spare_vcare = ""   (interdiction stricte, cf. double-count)
│       │             │   total_plus_spare_vcare = qté_vcare
│       │             └── Exclusion : ligne saisonnière "sans spare" ⟹ non comptée
│       ├── Étape 4   Insertion de 3 lignes vides (séparateur visuel UI)
│       └── Étape 5   _apply_total_moq_and_bonuses(rows)
│                     ├── Ajout flèche fixe (+600 sur ES 1.5 noir, cf. §4.6)
│                     ├── Recalcul total_moq final sur TOUTES les lignes
│                     └── Sectioning : EEG / Rails / Supports / Signa / Sais. / V:Care

================================================================================

├── §4  CALCULS MÉTIER  (règles verrouillées par pytest, iter01 → iter56)
│   │
│   │ ┌────────────────────────────────────────────────────────────────────────┐
│   │ │  INVARIANT GLOBAL  —  pour toute ligne L du recap :                    │
│   │ │                                                                        │
│   │ │     total_plus_spare(L)  =  quantité(L)  +  spare(L)                   │
│   │ │     total_moq(L)         =  ⌈ total_plus_spare(L) / MOQ(ref) ⌉ · MOQ   │
│   │ │                                                                        │
│   │ │     où ⌈ · ⌉ = ceiling (math.ceil, pas de bank-round)                 │
│   │ │     et MOQ(ref)  =  MOQ_BY_REF[ref]  si définie, sinon "—"            │
│   │ └────────────────────────────────────────────────────────────────────────┘
│   │
│   ├── 4.1  Spare — formule  Spare(L) = ⌈ Qté(L) × τ(L) ⌉
│   │       ├── τ(L) = 0.00  ssi  L ∈ {Software caméra, Dongle, V:Care}
│   │       ├── τ(L) = 0.02  ssi  L ∈ {Caméra noire, Caméra blanche,
│   │       │                           Batterie caméra, Support mobilier
│   │       │                           Captana noir, Support mobilier Captana
│   │       │                           blanc, Support ajustable adhésif Captana}
│   │       │                        (= 6 produits, matching désignation lower-case)
│   │       └── τ(L) = 0.05  par défaut (ES, SA, rails, supports, signalétique…)
│   │       ╚══ Ordre d'évaluation : {0 %} > {2 %} > {5 %} (court-circuit haut)
│   ├── 4.2  Total + Spare
│   │       └── Simple somme, pas d'arrondi additionnel (Spare déjà entier)
│   ├── 4.3  MOQ — table 63 refs (source MOQ.xlsx 23/06/2026)
│   │       │
│   │       │   ┌─────────────────────────────┬───────────────────────────────┐
│   │       │   │ Classe MOQ                  │ Références représentatives    │
│   │       │   ├─────────────────────────────┼───────────────────────────────┤
│   │       │   │ 1    (unitaire)             │ 16639,16783,17723,17889,17900,│
│   │       │   │                             │ 17929,17938,17940,18052,18183,│
│   │       │   │                             │ 18308,6669                     │
│   │       │   │ 10                          │ 12202,15551                    │
│   │       │   │ 24    (rails ES)            │ 13585,14745,15395,15506,15507,│
│   │       │   │                             │ 16957,17285,17868,18173       │
│   │       │   │ 25                          │ 13827,14466,17165,17651,17717,│
│   │       │   │                             │ 3903                           │
│   │       │   │ 40                          │ 17103                          │
│   │       │   │ 48    (rail 535 mm uniq.)   │ 13585  (double classif)        │
│   │       │   │ 50                          │ 16441,17741,18107,18108,18216,│
│   │       │   │                             │ 18217,3962,3966,3971,9484     │
│   │       │   │ 60                          │ 15550                          │
│   │       │   │ 90                          │ 18048                          │
│   │       │   │ 100   (dominant ES/SA)      │ 13469,15024,15910,15912,16362,│
│   │       │   │                             │ 16574,16607,16657,16808,17673,│
│   │       │   │                             │ 17724,17740,17869,17870,4507  │
│   │       │   │ 500                         │ 4552                           │
│   │       │   │ 5     (Captana sources)     │ 11892,14218                    │
│   │       │   └─────────────────────────────┴───────────────────────────────┘
│   │       │
│   │       └── Si Qté+Spare = 0 → Total+MOQ = 0 (pas d'arrondi au MOQ)
│   ├── 4.4  Inclineurs — consolidation rails ES
│   │       ├── Longueurs éligibles  : L ∈ {535, 650, 908, 990, 1187, 1240, 1320} mm
│   │       ├── Refs éligibles       : ES_RAIL_REFS = {13585, 14745, 15395, 15506,
│   │       │                                           15507, 16957, 17285, 17868,
│   │       │                                           18173}       (9 refs)
│   │       ├── Refs EXCLUES         : {4507, 18048, 9484}            (rails SA)
│   │       ├── Pour chaque longueur L :
│   │       │     ├── somme_qté = Σ Qté(ligne rail ES de longueur L)
│   │       │     ├── spare_incl = ⌈ somme_qté × 0.05 ⌉
│   │       │     └── Ligne synthétique "Inclineur <L>mm" ajoutée au recap
│   │       └── Les lignes rails originelles RESTENT (pas de doublon commande)
│   ├── 4.5  V:Care — mapping sources → VCare  (règle 12/06/2026)
│   │       │
│   │       │   ┌──────────────────────────────────┬────────┬─────────────────┐
│   │       │   │ Refs sources                     │ V:Care │ Désignation     │
│   │       │   ├──────────────────────────────────┼────────┼─────────────────┤
│   │       │   │ 15024, 17673, 17724              │ 17889  │ V:Care 7Y E300 1.5 BWRY       │
│   │       │   │ 17869, 16362                     │ 18052  │ V:Care Lite 7Y ES300 1.5 BWRY │
│   │       │   │ 15910, 17740                     │ 17900  │ V:Care 7Y E300 2.1 BWRY       │
│   │       │   │ 17870                            │ 17723  │ V:Care Lite 7Y ES300 2.1 BWRY │
│   │       │   │ 15912, 17979                     │ 17940  │ V:Care 5Y E300 2.1 F BWRY     │
│   │       │   │ 15551                            │ 17929  │ V:Care 5Y E300 4.2 BWRY       │
│   │       │   │ 15550                            │ 17938  │ V:Care Lite 5Y E300 4.2 WP    │
│   │       │   │ ES_RAIL_REFS (9)                 │ 18183  │ V:Care 7Y ES Rail             │
│   │       │   │ 11892, 14218                     │ 16783  │ V:Care Lite 3Y Captana StoreEy│
│   │       │   └──────────────────────────────────┴────────┴─────────────────┘
│   │       │
│   │       ├── qté_vcare(G) = Σ_{r ∈ G.sources}  total_moq(r)
│   │       ├── spare_vcare = "" (vide — JAMAIS calculé, cf. iter35 double-count)
│   │       ├── total_plus_spare_vcare = qté_vcare    (recopie directe)
│   │       └── Exclusion : la ligne "saisonnier sans spare" N'EST PAS sommée
│   │           (règle anti double-comptage saisonnier)
│   ├── 4.6  Flèche fixe   (règle 08/07/2026)
│   │       ├── Constante  FLECHE_FIXED_ES15_NOIR = 600
│   │       ├── Appliquée UNIQUEMENT sur la ligne ES 1.5 noir en commande
│   │       │   ├── total_plus_spare_commande += 600
│   │       │   └── Colonne "Flèche" exposée dans UI (indicatif)
│   │       └── N'ENTRE PAS dans le phasage (invisible côté nuits/allées)
│   ├── 4.7  Support individuel alu SA  (auto-injection)
│   │       ├── SUPPORT_ALU_SA_REF = 16808
│   │       ├── Déclencheur : ligne absente du fichier Carrefour source
│   │       ├── Qté injectée = Σ (SA EEG cochées dans sa_install, toutes familles)
│   │       └── Classé en Support (dispatch VT/Magasin selon règle orphelin §6)
│   └── 4.8  Précédence des règles si conflit  (ordre descendant)
│           ├── V:Care (0 % spare)                     [prio max]
│           ├── Dongle (0 % spare, Total = Qté)
│           ├── Software caméra (0 % spare)
│           ├── 6 produits Captana à 2 %
│           ├── Règle 5 % par défaut
│           └── Flèche +600 (ES 1.5 noir uniquement)   [prio min, additif]

================================================================================

├── §5  PHASAGE  (allées × nuits — moteur central)
│   │
│   │ ┌────────────────────────────────────────────────────────────────────────┐
│   │ │  MODÈLE DE DONNÉES  phasage : BSON persisté dans datasets               │
│   │ │                                                                        │
│   │ │  {                                                                     │
│   │ │    "es":  {                                                             │
│   │ │       "nb_nuits":   int,                                                │
│   │ │       "rows":       [ {id:str, allee:str, nuit:int}, ... ],             │
│   │ │       "start_dates":{"1":"YYYY-MM-DD", ...}                             │
│   │ │    },                                                                   │
│   │ │    "cam": {                                                             │
│   │ │       "nb_nuits":      int,                                             │
│   │ │       "start_at_nuit": int,       // offset (ex. 5)                     │
│   │ │       "rows":          [ {id, allee, nuit}, ... ]                       │
│   │ │    }                                                                    │
│   │ │  }                                                                      │
│   │ │                                                                        │
│   │ │  Invariant  :  ∀ row ∈ es.rows ∪ cam.rows                               │
│   │ │     row.allee ∈ {clé_allée_valide d'une des summary.allees}            │
│   │ └────────────────────────────────────────────────────────────────────────┘
│   │
│   ├── 5.1  Clé d'allée  (format strict)
│   │       ├── Allée standard   :  "N"                  ex. "5"
│   │       ├── Allée composite  :  "N__SECTEUR__RAYON"  ex. "5__PGC__PLS"
│   │       └── Saisonnier (ZS)  :  "<zsId>__SAISONNIER__ZS"
│   │           ╚══ permet 2 allées "5" distinctes (PGC + Saisonnier) coexistant
│   ├── 5.2  Fonction d'éligibilité d'une allée à la liste
│   │       │
│   │       │     node = allee_summary_node(allee_key)
│   │       │     is_mag2 = (store_mode == "magasin_2")
│   │       │
│   │       │     es_tot = node.es_15 + node.es_21
│   │       │            + (node.sa_15 if is_mag2
│   │       │               else (node.es_15_bonus_noir + node.es_15_bonus_blanc))
│   │       │            + node.fleches
│   │       │
│   │       │     rails  = node.rails_es
│   │       │
│   │       │     raw_sa = node.sa_15
│   │       │            + (node.sa_21_std or node.sa_21 or 0)
│   │       │            + node.sa_21_freezer
│   │       │            + node.sa_42
│   │       │
│   │       │     KEEP ⇔ node.is_seasonal  OR  (es_tot + rails + raw_sa) > 0
│   │       │
│   │       └── NOTE : raw_sa inclut les SA "magasin" → phasage possible même si
│   │           100 % du contenu de l'allée est à poser par le magasin  (iter55)
│   ├── 5.3  Automate d'auto-nettoyage
│   │       ├── Trigger  : setPhasageRows()  (toute écriture)
│   │       ├── Filtre   : prev.filter(row ⇒ KEEP(row.allee))
│   │       │   └── Allées devenues inéligibles (ex. décoche saisonnier) sont
│   │       │       automatiquement retirées (pas de prompt utilisateur)
│   │       └── Spécificité ZS : si sa_install.seasonal.zones[zoneId] = false,
│   │           toutes les allées "<zoneId>__SAISONNIER__ZS" sont purgées
│   ├── 5.4  Résolveur de nuit  resolve_night(allee, sec, ray, kind)
│   │       ├── kind = "es"  → cherche dans phasage.es.rows, retourne .nuit
│   │       ├── kind = "cam" → cherche dans phasage.cam.rows, retourne .nuit
│   │       ├── Matching : exact-key OU numéro seul (fallback composite)
│   │       └── Retourne None → l'item part en carrefour_agg (palette)
│   ├── 5.5  Dates et offsets caméra
│   │       ├── Nuit ES[n]  → date = es.start_dates[str(n)]
│   │       ├── Nuit CAM[n] → date = es.start_dates[str(n - start_at_nuit + 1)]
│   │       │                        (optionnel, UI peut saisir dates propres)
│   │       └── start_at_nuit garantit le décalage : caméras APRÈS les ES
│   ├── 5.6  Snapshots  (collection phasage_snapshots)
│   │       ├── PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD = 20
│   │       ├── Déclencheurs :
│   │       │   ├── Save explicite (bouton)
│   │       │   └── Auto-save debounce 500 ms après modification
│   │       ├── Payload stocké : {phasage, sa_install, created_at, user_id}
│   │       ├── Auto-rotation Mongo :
│   │       │   cursor = snapshots.find(upload_id).sort(created_at,-1)
│   │       │                   .skip(PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD)
│   │       │   await snapshots.delete_many({_id: {$in: oldest_ids}})
│   │       └── Restauration : POST /api/dataset/{id}/snapshots/{sid}/restore
│   ├── 5.7  Edge-case "allée 100 % magasin phaseée"  (iter55 — propriété)
│   │       ├── Scénario : allée 7 contient uniquement SA 2.1 freezer et
│   │       │              sa_install.freezer = false
│   │       ├── Alors :
│   │       │   ├── Allée reste dans liste (KEEP par raw_sa > 0)
│   │       │   ├── vusion_by_nuit[1] = {} (empty — rien pour VT)
│   │       │   ├── carrefour_sa_by_nuit_by_allee[1]["7|PGC|SURGELE"] = {items}
│   │       │   └── Planning onglet 1 = "Aucun matériel à poser pour cette nuit."
│   │       │       Planning onglet 2 = allée visible avec son contenu SA Magasin
│   │       └── Invariant  :  nuits_affichées = keys(vusion_by_nuit)
│   │                                           ∪ keys(carrefour_sa_by_nuit_by_allee)
│   └── 5.8  Auto-save & bannière de perte réseau
│           ├── Hook useAutoSave(data, delay=500)
│           │   ├── setTimeout → PATCH /api/dataset/{id}
│           │   ├── Gestion AbortController (annule les requests obsolètes)
│           │   └── Captures state last_save_ok / last_save_error
│           ├── Composant SaveStatusBanner
│           │   ├── OK depuis > 2 s          → bandeau vert translucide puis fade
│           │   ├── En cours (fetch inflight) → "Enregistrement…" spinner
│           │   └── Erreur / offline         → bandeau rouge persistant +
│           │                                   bouton "Réessayer" + copier payload
│           └── Rejoue à l'event "online" + au focus de l'onglet (visibilitychange)

================================================================================

├── §6  SA INSTALL  —  dispatch VT / Magasin / Palette (fonction centrale)
│   │
│   │ ┌────────────────────────────────────────────────────────────────────────┐
│   │ │  MODÈLE sa_install  (persisté dans datasets)                            │
│   │ │                                                                        │
│   │ │  {                                                                     │
│   │ │    "enabled":  bool,   // SA active sur ce magasin ?                   │
│   │ │    "answered": bool,   // utilisateur a répondu au prompt ?            │
│   │ │    "toutes":   bool,   // raccourci "tout VT"                          │
│   │ │    "sa_15":    bool,   // famille cochée globalement                   │
│   │ │    "sa_21":    bool,   // (sa_21 couvre std ET freezer sauf override)  │
│   │ │    "freezer":  bool,   // override SA 2.1 freezer                      │
│   │ │    "sa_42":    bool,                                                   │
│   │ │    "selection": {                                                      │
│   │ │        "sa_15": [ "SECTEUR|||RAYON|||N°allée", ... ],                  │
│   │ │        "sa_21": [ ... ]                                                 │
│   │ │    },                                                                  │
│   │ │    "seasonal": { "all": bool, "zones": {"ZS1": bool, ...} }            │
│   │ │  }                                                                     │
│   │ └────────────────────────────────────────────────────────────────────────┘
│   │
│   ├── 6.1  Sémantique des familles
│   │       ├── Mode global              :  sa_install.toutes = true
│   │       │   └── Toutes les SA cochées sans distinction (court-circuit UI)
│   │       ├── Mode par famille         :  sa_15 / sa_21 / freezer / sa_42
│   │       │   └── TRUE = toute occurrence posée par VT
│   │       └── Mode "sélection par allée":  selection.sa_XX = [clés]
│   │           └── TRUE pour cette allée uniquement → autres allées → Magasin
│   ├── 6.2  Prédicat has_sa(allée)
│   │       ├── Retourne True si une EEG SA (quelconque famille) sera posée par
│   │       │   VT dans cette allée (selon sa_install).
│   │       ├── Utilisé pour la règle "support SA orphelin" :
│   │       │   support SA + has_sa = False  →  Magasin
│   │       └── Précalculé une fois par itération dispatch (évite N² scan)
│   ├── 6.3  Automate de dispatch  _split_materiel_by_recipient(d)
│   │       │
│   │       │   ┌──────────────────────────────────────────────────────────────┐
│   │       │   │  Boucle sur chaque record r des raw_records                    │
│   │       │   │                                                              │
│   │       │   │  Phase 1 — Détection Captana                                  │
│   │       │   │    si is_cam_side_product(r.désig, r.type) :                 │
│   │       │   │      nuit_cam = resolve_night(r.allee, r.sec, r.ray, "cam")  │
│   │       │   │      si nuit_cam : push → vusion_by_nuit[nuit_cam]           │
│   │       │   │                     push → vusion_by_nuit_by_allee[nuit_cam] │
│   │       │   │      sinon        : push → carrefour_agg                     │
│   │       │   │      CONTINUE                                                 │
│   │       │   │                                                              │
│   │       │   │  Phase 2 — Résolution nuit ES                                 │
│   │       │   │    nuit_es = resolve_night(r.allee, r.sec, r.ray, "es")      │
│   │       │   │                                                              │
│   │       │   │  Phase 3 — Détermination destinataire                          │
│   │       │   │    goes_carrefour = False                                     │
│   │       │   │    reason_sa      = False                                     │
│   │       │   │                                                              │
│   │       │   │    si is_sa_eeg(r.désig) ET r.fam ∉ cochées(sa_install) :    │
│   │       │   │       goes_carrefour = True ; reason_sa = True                │
│   │       │   │    sinon si is_sa_support(r.désig) ET NOT has_sa(r.allee) :  │
│   │       │   │       goes_carrefour = True ; reason_sa = True                │
│   │       │   │    sinon si nuit_es is None :                                 │
│   │       │   │       goes_carrefour = True   (reason_sa = False)             │
│   │       │   │                                                              │
│   │       │   │  Phase 4 — Push dans les buckets                              │
│   │       │   │    si goes_carrefour :                                        │
│   │       │   │      push → carrefour_agg                                     │
│   │       │   │      si reason_sa ET nuit_es :                                │
│   │       │   │        push → carrefour_sa_by_nuit_by_allee[nuit_es]         │
│   │       │   │    sinon :                                                    │
│   │       │   │      push → vusion_by_nuit[nuit_es]                           │
│   │       │   │      push → vusion_by_nuit_by_allee[nuit_es]                 │
│   │       │   └──────────────────────────────────────────────────────────────┘
│   │       │
│   │       └── Sortie 6-tuple :
│   │           (vusion_by_nuit, carrefour_agg, nuits, night_meta,
│   │            vusion_by_nuit_by_allee, carrefour_sa_by_nuit_by_allee)
│   ├── 6.4  Clé d'entry  (dans by_allee buckets)
│   │       ├── Format        : f"{allee}|{secteur}|{rayon}"
│   │       ├── Granularité   : distingue "Allée 5 PGC/PLS" de "Allée 5 Saisonnier/ZS"
│   │       └── Valeur        : {allee, secteur, rayon, kind:"es"|"cam", items:{(ref,désig):qté}}
│   ├── 6.5  Règle d'orphelin  (support SA)
│   │       │
│   │       │     support_SA(allée) + has_sa_eeg_vt(allée) = False
│   │       │       ⟹ Carrefour (magasin pose)
│   │       │
│   │       │     support_SA(allée) + has_sa_eeg_vt(allée) = True
│   │       │       ⟹ VT  (la VT ajoute le support avec la SA posée)
│   │       │
│   │       └── Pic à glace / Support 4.2 / Support 4.2 WP → considérés
│   │           comme supports SA depuis iter51
│   ├── 6.6  Zones saisonnières
│   │       ├── sa_install.seasonal.all = true → toutes zones ZS cochées
│   │       ├── sinon : lookup zone-par-zone dans sa_install.seasonal.zones
│   │       └── Décoche d'une zone → purge auto des rows phasage correspondantes
│   └── 6.7  Union des nuits à afficher (invariant commune Planning / SA Magasin)
│           │
│           │   nuits_affichées = sorted(
│           │       set(vusion_by_nuit.keys())
│           │         ∪ set(carrefour_sa_by_nuit_by_allee.keys())
│           │   )
│           │
│           └── Garantie :  une nuit 100 % magasin reste visible dans l'export
│               Planning (onglet SA Magasin) avec son label "Nuit N — date".

================================================================================

├── §11 INTÉGRATIONS 3rd PARTY  (surface actuelle, verrouillée)
│   ├── Emergent LLM Key (budget universel)
│   │   ├── Modèles supportés : Claude Sonnet (text), Gemini 3 Pro (text + Nano
│   │   │   Banana image), GPT text/image (gpt-image-1), Whisper STT
│   │   ├── Prévue pour auto-phasage via Gemini 3 Pro Vision (plan magasin)
│   │   └── EN PAUSE — tâche suspendue par l'utilisateur
│   ├── Emergent Object Storage
│   │   ├── Photos suivi terrain (chunked upload, EXIF strip, thumbnails)
│   │   └── Floorplans magasin (JPG/PNG)
│   └── Resend / SendGrid        — NON branché (reset mdp manuel pour l'instant)

================================================================================

└── §12 BACKLOG & ROADMAP  (par priorité)
    ├── P1  Breadcrumb Suivi (Nuits › Nuit 2 › Allée 5A)
    ├── P1  Notification in-app sur réception d'une session partagée
    ├── P2  Recherche SKU/référence dans l'onglet Stock
    ├── P2  Export ZIP par nuit (Excel + photos originales terrain)
    ├── P2  Retry Axios silencieux sur 502/520/524 Cloudflare
    └── P3  Auto-phasage IA Vision via Gemini 3 Pro  —  EN PAUSE utilisateur
"""


def _set_margins(section, cm_v=1.1, cm_h=1.1):
    section.top_margin = Cm(cm_v)
    section.bottom_margin = Cm(cm_v)
    section.left_margin = Cm(cm_h)
    section.right_margin = Cm(cm_h)


def _set_landscape(section):
    new_width, new_height = section.page_height, section.page_width
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = new_width
    section.page_height = new_height


def _force_mono(run, pt_size=7.0):
    run.font.name = "Consolas"
    rPr = run._element.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Consolas")
    rFonts.set(qn("w:hAnsi"), "Consolas")
    rFonts.set(qn("w:cs"), "Consolas")
    rPr.append(rFonts)
    run.font.size = Pt(pt_size)
    run.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)


def build(output_path: str):
    doc = Document()
    section = doc.sections[0]
    _set_margins(section, 1.0, 1.0)
    _set_landscape(section)

    # Titre
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("phasage_crf — Arborescence noyau métier (dense)")
    r.bold = True
    r.font.size = Pt(15)
    r.font.color.rgb = RGBColor(0x00, 0x5B, 0xAB)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run("Vusion — février 2026 — v29/iter56 — focus Import / Calculs / "
                     "Phasage / SA Install / Intégrations / Backlog")
    sr.italic = True
    sr.font.size = Pt(9)
    sr.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    doc.add_paragraph("")

    # Arbo en police monospace, très petit pour tout faire tenir
    p = doc.add_paragraph()
    rr = p.add_run(ARBO)
    _force_mono(rr, pt_size=6.5)

    # Footer
    doc.add_paragraph("")
    leg = doc.add_paragraph()
    lrun = leg.add_run(
        "Source canonique : /app/backend/server.py (compute_recap, "
        "_split_materiel_by_recipient, _build_vcare_rows, MOQ_BY_REF, "
        "ES_RAIL_REFS, VCARE_MAPPING, FLECHE_FIXED_ES15_NOIR, "
        "PHASAGE_SNAPSHOTS_MAX_PER_UPLOAD).   "
        "Règles verrouillées par pytest : /app/backend/tests/test_iter*.py "
        "(55+ fichiers, 100 % des règles métier critiques).")
    lrun.italic = True
    lrun.font.size = Pt(7.5)
    lrun.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    doc.save(output_path)
    print(f"OK → {output_path}")


if __name__ == "__main__":
    build("/app/frontend/public/phasage_crf_arborescence_noyau_dense.docx")
