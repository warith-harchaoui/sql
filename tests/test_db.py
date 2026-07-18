"""
test_db.py — Tests de la couche base : introspection + garde-fou lecture seule.

Ces tests sont le filet de sécurité le plus important du projet : ils vérifient
qu'aucune requête d'écriture ne peut passer, que l'exécution reste bornée, et que
le schéma est correctement exposé aux modèles.
"""

from __future__ import annotations

import pytest

from backend import db


def test_schema_lists_all_domains(db_path):
    """Le schéma expose bien toutes les tables des grands domaines métier."""
    # On vérifie la présence de tables représentatives de chaque domaine.
    tables = set(db.list_tables(db_path))
    for expected in (
        "patients",
        "diagnostics",
        "employes",
        "factures",
        "medicaments",
        "equipements",
        "essais_cliniques",
    ):
        assert expected in tables


def test_schema_ddl_contains_foreign_keys(db_path):
    """Le DDL généré pour les prompts contient les clés étrangères (contexte clé)."""
    ddl = db.schema_ddl(db_path)
    # Les relations sont cruciales pour que le LLM sache joindre les tables.
    assert "REFERENCES" in ddl
    assert "CREATE TABLE patients" in ddl


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DELETE FROM patients",
        "UPDATE patients SET nom = 'x'",
        "DROP TABLE patients",
        "INSERT INTO patients (nom) VALUES ('x')",
        "SELECT 1; DELETE FROM patients",  # injection multi-instruction
        "ALTER TABLE patients ADD COLUMN x TEXT",
        "PRAGMA table_info(patients)",  # introspection non autorisée en exec
        "",  # requête vide
    ],
)
def test_forbidden_queries_are_rejected(bad_sql):
    """Toute requête d'écriture / dangereuse est refusée AVANT exécution."""
    # is_safe_select est la première ligne de défense.
    ok, _ = db.is_safe_select(bad_sql)
    assert ok is False
    # Et run_select ne doit jamais exécuter une requête non sûre.
    result = db.run_select(bad_sql)
    assert result.ok is False


@pytest.mark.parametrize(
    "good_sql",
    [
        "SELECT COUNT(*) FROM patients",
        "select nom from employes limit 5",
        "WITH x AS (SELECT 1 AS a) SELECT a FROM x",  # CTE autorisée
    ],
)
def test_valid_selects_are_accepted(good_sql):
    """Les SELECT (et WITH ... SELECT) légitimes passent le garde-fou."""
    ok, _ = db.is_safe_select(good_sql)
    assert ok is True


def test_run_select_truncates_at_max_rows(db_path):
    """L'exécution est bornée à ``max_rows`` et signale la troncature."""
    # patients contient 600 lignes ; on demande 10 -> troncature attendue.
    result = db.run_select("SELECT patient_id FROM patients", max_rows=10)
    assert result.ok is True
    assert result.row_count == 10
    assert result.truncated is True


def test_run_select_reports_sql_error(db_path):
    """Une erreur SQL (table inexistante) est rapportée, pas levée."""
    result = db.run_select("SELECT * FROM table_qui_nexiste_pas")
    assert result.ok is False
    assert result.error is not None
