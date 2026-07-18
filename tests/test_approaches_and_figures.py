"""
test_approaches_and_figures.py — Tests unitaires SANS réseau.

On teste ici tout ce qui ne dépend pas d'un serveur Ollama : le nettoyage du SQL
bavard des LLM, la construction déterministe des specs Vega-Lite, et les petites
heuristiques de typage de colonnes. Les tests d'intégration (qui appellent les
modèles) vivent dans ``test_integration.py`` et sont marqués ``slow``.
"""

from __future__ import annotations

import pytest

from backend import figures
from backend.approaches.base import clean_sql


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Bloc Markdown ```sql ... ``` : on extrait la requête nue.
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        # Préfixe « SQLQuery: » de LangChain : on le retire.
        ("SQLQuery: SELECT 2", "SELECT 2"),
        # Bavardage + point-virgule + explication après : on coupe.
        ("Voici :\n```sql\nSELECT 3;\n```\nExplication…", "SELECT 3"),
        # Requête déjà propre : inchangée.
        ("SELECT 4", "SELECT 4"),
    ],
)
def test_clean_sql_extracts_bare_query(raw, expected):
    """clean_sql isole la requête quel que soit l'enrobage du modèle."""
    assert clean_sql(raw) == expected


def test_looks_temporal_detects_iso_dates():
    """L'heuristique temporelle reconnaît les mois/dates ISO et rejette le texte."""
    # Des mois ISO -> temporel ; des libellés -> non temporel.
    assert figures._looks_temporal(["2026-01", "2026-02", "2026-03"]) is True
    assert figures._looks_temporal(["Sein", "Poumon", "Côlon"]) is False


def test_is_numeric_distinguishes_numbers_from_text():
    """L'heuristique numérique sépare colonnes de nombres et de chaînes."""
    assert figures._is_numeric([1, 2, 3]) is True
    assert figures._is_numeric(["a", "b"]) is False
    # Les booléens ne doivent pas être pris pour des mesures numériques.
    assert figures._is_numeric([True, False]) is False


def test_build_vega_bar_spec_is_house_style():
    """La spec Vega-Lite d'un bar chart porte le house style (config + palette)."""
    # Choix simulé de Gemma : un bar chart localisation -> nombre.
    choice = {"chart_type": "bar", "x": "localisation", "y": "n", "title": "Test"}
    cols = ["localisation", "n"]
    rows = [["Sein", 47], ["Poumon", 40]]
    spec = figures._build_vega(choice, cols, rows)
    # Vega-Lite v5 + config maison + encodage x/y attendus.
    assert spec["$schema"].endswith("v5.json")
    assert "config" in spec and "range" in spec["config"]
    assert spec["encoding"]["x"]["field"] == "localisation"
    assert spec["encoding"]["y"]["type"] == "quantitative"


def test_build_vega_rejects_unknown_columns():
    """Une colonne inexistante dans le résultat lève une ValueError explicite."""
    choice = {"chart_type": "bar", "x": "inconnue", "y": "n", "title": "X"}
    with pytest.raises(ValueError):
        figures._build_vega(choice, ["localisation", "n"], [["Sein", 1]])
