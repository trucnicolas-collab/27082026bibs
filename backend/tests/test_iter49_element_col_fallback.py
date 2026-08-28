"""
Test: _resolve_element_col ne doit PAS retomber aveuglément sur columns[6]
si cette colonne contient des valeurs textuelles (ex: noms de rayons).

Contexte régression (26/02/2026) : le slide 20 "Détail caméras par allée"
affichait "Pain de mie, Frites, Glace..." au lieu de "1, 2, 3, 4..."
car _detect_element_col retombait sur la colonne "Rayon" (index 6) quand
la colonne "N° élément" était absente ou nommée différemment.

Fix : le fallback positionnel n'est activé QUE si les valeurs de columns[6]
sont majoritairement numériques (>= 60%).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import _resolve_element_col  # noqa: E402


def _cols_from_records(records):
    return list(records[0].keys())


def test_no_fallback_when_col_g_is_text():
    """Reproduit le bug utilisateur : colonne G = 'Pain de mie' → doit renvoyer None."""
    records = [
        {"Secteur": "PGC", "Rayon": "Boulangerie", "N° allée": "1",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 20,
         "AutreCol": "X", "Rayon2": "Pain de mie"},
        {"Secteur": "PGC", "Rayon": "Frites", "N° allée": "3",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 10,
         "AutreCol": "Y", "Rayon2": "Frites"},
    ]
    cols = _cols_from_records(records)
    # colonne G (index 6) = "AutreCol" avec valeurs "X"/"Y" (texte)
    assert cols[6] == "AutreCol"
    result = _resolve_element_col(cols, records)
    # Doit renvoyer None (pas de nom reconnu ET colonne G texte)
    assert result is None, f"Expected None but got {result}"


def test_fallback_when_col_g_is_numeric():
    """columns[6] contient des N° d'éléments (numériques) → fallback OK."""
    records = [
        {"Secteur": "PGC", "Rayon": "R1", "N° allée": "1",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 20,
         "Elem": 5},
        {"Secteur": "PGC", "Rayon": "R2", "N° allée": "3",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 10,
         "Elem": 12},
        {"Secteur": "PGC", "Rayon": "R3", "N° allée": "5",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 8,
         "Elem": 7},
    ]
    cols = _cols_from_records(records)
    assert cols[6] == "Elem"
    result = _resolve_element_col(cols, records)
    assert result == "Elem"


def test_named_detection_wins_over_fallback():
    """Si 'N° élément' est présent, on l'utilise sans regarder columns[6]."""
    records = [
        {"Secteur": "PGC", "Rayon": "R", "N° allée": "1",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 20,
         "N° élément": 5, "IgnoredExtra": "text"},
    ]
    cols = _cols_from_records(records)
    result = _resolve_element_col(cols, records)
    assert result == "N° élément"


def test_no_fallback_when_less_than_7_cols():
    """Fichier avec < 7 colonnes → None."""
    records = [{"A": 1, "B": 2, "C": 3}]
    cols = _cols_from_records(records)
    result = _resolve_element_col(cols, records)
    assert result is None


def test_no_fallback_when_col_g_empty():
    """columns[6] entièrement vide → None (pas de fallback)."""
    records = [
        {"Secteur": "PGC", "Rayon": "R", "N° allée": "1",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 20,
         "Empty": None},
        {"Secteur": "PGC", "Rayon": "R", "N° allée": "3",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 10,
         "Empty": ""},
    ]
    cols = _cols_from_records(records)
    result = _resolve_element_col(cols, records)
    assert result is None


def test_gondole_column_name_detected():
    """Variante 'Gondole' doit être détectée."""
    records = [
        {"Secteur": "PGC", "Rayon": "R", "N° allée": "1",
         "Type": "Camera", "Désignation": "CAM", "Quantité": 20,
         "Gondole": 42},
    ]
    cols = _cols_from_records(records)
    result = _resolve_element_col(cols, records)
    assert result == "Gondole"
