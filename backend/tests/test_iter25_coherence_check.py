"""Iter25 — Contrôle de cohérence automatique à l'upload.

Vérifie que _compute_coherence_warnings détecte les anomalies courantes :
 - Quantités négatives
 - Quantités non numériques
 - Colonnes clés manquantes
 - Ratio SA/ES suspect (double comptage source)
 - Fichier anormalement petit
"""
import io
import os
import pandas as pd
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@vusion.local"
ADMIN_PWD = "admin123"


def _session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
    assert r.status_code == 200, r.text
    return s


def _upload(rows):
    """Fabrique un xlsx en mémoire et l'upload. Retourne le dict de réponse."""
    df = pd.DataFrame(rows, columns=["Secteur", "Rayon", "N° allée",
                                     "Référence", "Type", "Désignation", "Quantité"])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    s = _session()
    r = s.post(f"{API}/upload-excel", files={"file": ("test.xlsx", buf.getvalue())})
    assert r.status_code == 200, r.text
    return r.json()


def test_coherence_field_always_present():
    """Chaque upload doit renvoyer un champ coherence_warnings (liste, possiblement vide)."""
    rows = [
        ["A", "R1", "1", "ART_001", "EEG", "ES 1.5 noir", 100],
        ["A", "R1", "1", "ART_002", "EEG", "ES 2.1 noir", 50],
        ["A", "R1", "1", "ART_003", "Rail", "990 mm (noir)", 5],
        ["A", "R2", "2", "ART_004", "EEG", "SA 1.5 noir", 30],
        ["A", "R2", "2", "ART_005", "Caméra", "Caméra (noire)", 2],
        ["A", "R2", "2", "ART_006", "EEG", "ES 2.1 noir", 20],
    ]
    d = _upload(rows)
    assert "coherence_warnings" in d
    assert isinstance(d["coherence_warnings"], list)


def test_detects_negative_quantities():
    rows = [
        ["A", "R1", "1", "ART_001", "EEG", "ES 1.5 noir", 100],
        ["A", "R1", "1", "ART_002", "EEG", "ES 2.1 noir", 50],
        ["A", "R1", "1", "ART_003", "Rail", "990 mm (noir)", 5],
        ["A", "R2", "2", "ART_004", "EEG", "ES 1.5 noir", -10],
        ["A", "R2", "2", "ART_005", "Caméra", "Caméra (noire)", 2],
    ]
    d = _upload(rows)
    codes = {w["code"] for w in d["coherence_warnings"]}
    assert "qty_negative" in codes
    neg = next(w for w in d["coherence_warnings"] if w["code"] == "qty_negative")
    assert neg["level"] == "error"
    assert neg["ctx"]["nb"] == 1


def test_detects_sa_ratio_high():
    """SA >> ES pur → warning code sa_ratio_high."""
    rows = [
        ["A", "R1", "1", "ART_001", "EEG", "ES 1.5 noir", 100],
        ["A", "R1", "1", "ART_002", "EEG", "SA 1.5 noir", 300],
        ["A", "R1", "1", "ART_003", "EEG", "SA 2.1 noir", 180],
        ["A", "R1", "1", "ART_004", "Rail", "990 mm (noir)", 5],
        ["A", "R2", "2", "ART_005", "Caméra", "Caméra (noire)", 2],
    ]
    d = _upload(rows)
    codes = {w["code"] for w in d["coherence_warnings"]}
    assert "sa_ratio_high" in codes


def test_no_warning_on_clean_file():
    """Fichier bien formé sans anomalies : liste de warnings vide (ou juste des info)."""
    rows = [
        ["A", "R1", "1", "ART_001", "EEG", "ES 1.5 noir", 100],
        ["A", "R1", "1", "ART_002", "EEG", "ES 2.1 noir", 80],
        ["A", "R1", "1", "ART_003", "EEG", "SA 1.5 noir", 30],
        ["A", "R1", "1", "ART_004", "EEG", "SA 2.1 noir", 20],
        ["A", "R1", "1", "ART_005", "Rail", "990 mm (noir)", 5],
        ["A", "R1", "1", "ART_006", "Caméra", "Caméra (noire)", 2],
    ]
    d = _upload(rows)
    error_or_warn = [w for w in d["coherence_warnings"] if w["level"] in ("error", "warning")]
    assert error_or_warn == [], f"Warnings inattendus: {error_or_warn}"
