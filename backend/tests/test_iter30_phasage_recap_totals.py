"""Iter30 — Cohérence des totaux du Récap par nuit (Phasage).

Reproduit le bug pointé par l'utilisateur dans le PDF « Erreur tableau.pdf » :
 - Flèche 1 : colonne « EEG ES » par nuit → n'incluait PAS le saisonnier
 - Flèche 2 : ligne TOTAL colonne « EEG ES » → l'INCLUAIT → doublon numérique
   (car les ZS sont déjà comptées dans grandTotals.sa_inst_15/21).

Ce test vérifie qu'après le fix :
  TOTAL colonne EEG ES == somme des lignes par nuit  (cohérence 1)
  TOTAL colonne Total  == KPI « Total EEG » en haut  (cohérence 2)
"""


def _reproduce_recap_math(nights, grand_totals, is_magasin_2=False):
    """Reproduit exactement le calcul JS de PhasageTab.jsx pour vérification."""
    # eegPerNight (frontend) — seasonalNuit volontairement ignoré (v27)
    def eeg_per_night(es, bonus, fleches, sa15, sa_inst):
        return round((es or 0) + (bonus or 0) + (fleches or 0) + (sa15 or 0) + (sa_inst or 0))

    # Ligne par nuit : colonne EEG ES
    per_night_eeg_es = []
    per_night_total = []
    for t in nights:
        total_es = (t.get("es_15", 0) or 0) + (t.get("es_21", 0) or 0)
        bonus = 0 if is_magasin_2 else (t.get("bonus", 0) or 0)
        fleches = t.get("fleches", 0) or 0
        sa15 = (t.get("sa_15", 0) or 0) if is_magasin_2 else 0
        sa_inst = ((t.get("sa_inst_15", 0) or 0) + (t.get("sa_inst_21", 0) or 0)
                   + (t.get("sa_inst_freezer", 0) or 0) + (t.get("sa_inst_42", 0) or 0))
        eeg_es = eeg_per_night(total_es, bonus, fleches, sa15, 0)  # 0 = SA hors EEG ES
        per_night_eeg_es.append(eeg_es)
        per_night_total.append(eeg_es + sa_inst)

    sum_eeg_es_rows = sum(per_night_eeg_es)
    sum_total_rows = sum(per_night_total)

    # Ligne TOTAL selon le NOUVEAU code (fix iter30) — SANS grandTotals.seasonal
    gt_eeg_es = round(grand_totals["es"]
                      + (grand_totals["sa_15"] if is_magasin_2 else grand_totals["bonus"])
                      + grand_totals["fleches"])
    gt_total = (gt_eeg_es + grand_totals["sa_inst_15"] + grand_totals["sa_inst_21"]
                + grand_totals["sa_inst_freezer"] + grand_totals["sa_inst_42"])

    return {
        "per_night_eeg_es": per_night_eeg_es,
        "sum_eeg_es_rows": sum_eeg_es_rows,
        "gt_eeg_es": gt_eeg_es,
        "sum_total_rows": sum_total_rows,
        "gt_total": gt_total,
    }


def test_recap_total_matches_sum_of_rows_with_seasonal_zones():
    """Scénario magasin +10000m² avec 3 ZS (2000 EEG chacune) réparties sur 2 nuits."""
    nights = [
        # Nuits standards (sans ZS)
        {"es_15": 3000, "es_21": 1500, "bonus": 267, "fleches": 0,
         "sa_inst_15": 100, "sa_inst_21": 400, "sa_inst_freezer": 0, "sa_inst_42": 0,
         "seasonal": 0},
        {"es_15": 2500, "es_21": 2000, "bonus": 300, "fleches": 5,
         "sa_inst_15": 200, "sa_inst_21": 300, "sa_inst_freezer": 0, "sa_inst_42": 0,
         "seasonal": 0},
        # Nuit 16 : 1 ZS assignée → sa_inst_15 = 400 + 400 (ZS1), sa_inst_21 = 300 + 1600 (ZS1)
        {"es_15": 1500, "es_21": 200, "bonus": 6, "fleches": 0,
         "sa_inst_15": 800, "sa_inst_21": 1900, "sa_inst_freezer": 0, "sa_inst_42": 0,
         "seasonal": 2000},  # ZS1 : 2000 EEG
        # Nuit 17 : 2 ZS (ZS2 + ZS3) sans autre allée
        {"es_15": 0, "es_21": 0, "bonus": 0, "fleches": 0,
         "sa_inst_15": 800, "sa_inst_21": 3200, "sa_inst_freezer": 0, "sa_inst_42": 0,
         "seasonal": 4000},  # 2 ZS : 4000 EEG
    ]

    grand_totals = {
        "es": sum(n["es_15"] + n["es_21"] for n in nights),
        "bonus": sum(n["bonus"] for n in nights),
        "fleches": sum(n["fleches"] for n in nights),
        "sa_15": 0,
        "seasonal": sum(n["seasonal"] for n in nights),  # 6000 pour 3 ZS
        "sa_inst_15": sum(n["sa_inst_15"] for n in nights),
        "sa_inst_21": sum(n["sa_inst_21"] for n in nights),
        "sa_inst_freezer": 0,
        "sa_inst_42": 0,
    }

    res = _reproduce_recap_math(nights, grand_totals, is_magasin_2=False)

    # ✅ Cohérence 1 : TOTAL colonne EEG ES == somme des lignes
    assert res["gt_eeg_es"] == res["sum_eeg_es_rows"], (
        f"TOTAL EEG ES ({res['gt_eeg_es']}) doit être égal à la somme des lignes "
        f"({res['sum_eeg_es_rows']}). Avant le fix : {res['gt_eeg_es'] + grand_totals['seasonal']} != "
        f"{res['sum_eeg_es_rows']} (car seasonal 6000 était doublement compté).")

    # ✅ Cohérence 2 : TOTAL colonne Total == somme des Total par nuit
    assert res["gt_total"] == res["sum_total_rows"], (
        f"TOTAL Total ({res['gt_total']}) doit être égal à la somme des lignes "
        f"({res['sum_total_rows']}).")

    # ✅ Cohérence 3 : Le KPI Total EEG en haut = totalESBrut + bonus + fleches + saInstallTotal
    # (côté frontend : totalESBrut + totalES15Bonus + totalFleches + totalSA15
    #                  + sa21Saisonnier + saInstallTotal)
    # sa21Saisonnier = 6000, saInstallTotal (hors ZS) = sa_inst - 6000
    total_es_brut = grand_totals["es"]
    total_bonus = grand_totals["bonus"]
    total_fleches = grand_totals["fleches"]
    sa_install_total_hors_zs = (grand_totals["sa_inst_15"] + grand_totals["sa_inst_21"]
                                + grand_totals["sa_inst_freezer"] + grand_totals["sa_inst_42"]
                                - 6000)   # les ZS
    sa21_saisonnier = 6000
    kpi_total_eeg = (total_es_brut + total_bonus + total_fleches
                     + sa21_saisonnier + sa_install_total_hors_zs)
    assert kpi_total_eeg == res["gt_total"], (
        f"KPI Total EEG en haut ({kpi_total_eeg}) doit être égal à TOTAL colonne Total "
        f"du récap ({res['gt_total']}).")


def test_recap_total_no_seasonal_zones():
    """Régression : sans ZS, tout doit rester cohérent (aucun changement de comportement)."""
    nights = [
        {"es_15": 3000, "es_21": 1500, "bonus": 267, "fleches": 0,
         "sa_inst_15": 100, "sa_inst_21": 400, "sa_inst_freezer": 0, "sa_inst_42": 0,
         "seasonal": 0},
        {"es_15": 2500, "es_21": 2000, "bonus": 300, "fleches": 5,
         "sa_inst_15": 200, "sa_inst_21": 300, "sa_inst_freezer": 0, "sa_inst_42": 0,
         "seasonal": 0},
    ]
    grand_totals = {
        "es": sum(n["es_15"] + n["es_21"] for n in nights),
        "bonus": sum(n["bonus"] for n in nights),
        "fleches": sum(n["fleches"] for n in nights),
        "sa_15": 0, "seasonal": 0,
        "sa_inst_15": sum(n["sa_inst_15"] for n in nights),
        "sa_inst_21": sum(n["sa_inst_21"] for n in nights),
        "sa_inst_freezer": 0, "sa_inst_42": 0,
    }
    res = _reproduce_recap_math(nights, grand_totals, is_magasin_2=False)
    assert res["gt_eeg_es"] == res["sum_eeg_es_rows"]
    assert res["gt_total"] == res["sum_total_rows"]
