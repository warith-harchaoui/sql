"""
test_widen_db.py — Tests de la fabrique de base « gros schéma » (HEAVY).

Vérifie sans réseau que :
  - la base HEAVY gagne bien ~N colonnes de décor par table ;
  - les colonnes/données d'origine sont intactes (le SQL de référence tourne) ;
  - le DDL vu par le LLM enfle réellement (l'enjeu de la démo LIGHT vs HEAVY) ;
  - les figures « light vs heavy » se construisent depuis deux rapports.
"""

from __future__ import annotations

from backend import db
from backend.widen_db import _decoy_columns, widen_db


def test_decoy_columns_are_unique_and_avoid_existing():
    """Les colonnes de décor sont uniques et évitent les colonnes déjà présentes."""
    existing = {"patient_id", "nom", "date_derniere_modification"}
    cols = _decoy_columns(50, existing)
    names = [c[0] for c in cols]
    # Bon compte, aucun doublon, aucune collision avec l'existant.
    assert len(cols) == 50
    assert len(set(names)) == 50
    assert not (set(names) & existing)
    # Types SQL plausibles seulement.
    assert all(t in ("TEXT", "INTEGER", "REAL") for _, t in cols)


def test_widen_db_adds_columns_keeps_data_and_grows_ddl(db_path, tmp_path):
    """La base HEAVY ajoute des colonnes, préserve les données et gonfle le DDL."""
    dst = tmp_path / "institut_wide_test.db"
    per_table = 40
    widen_db(src=db_path, dst=dst, per_table=per_table)

    # Chaque table a gagné exactement ``per_table`` colonnes.
    for table in db.list_tables(db_path):
        light_cols = {c["name"] for c in db.table_schema(table, db_path)["columns"]}
        heavy_cols = {c["name"] for c in db.table_schema(table, dst)["columns"]}
        assert light_cols <= heavy_cols  # colonnes d'origine conservées
        assert len(heavy_cols) == len(light_cols) + per_table

    # Les données d'origine sont intactes : une référence non triviale renvoie
    # le MÊME résultat sur les deux bases.
    sql = "SELECT sexe, COUNT(*) AS n FROM patients GROUP BY sexe ORDER BY sexe"
    light = db.run_select(sql, db_path)
    heavy = db.run_select(sql, dst)
    assert heavy.ok and light.ok
    assert heavy.rows == light.rows

    # Le DDL vu par le LLM est nettement plus gros (le cœur de la démonstration).
    assert len(db.schema_ddl(dst)) > 3 * len(db.schema_ddl(db_path))


def test_lightheavy_specs_build():
    """Les specs Vega « light vs heavy » se construisent depuis deux rapports."""
    from eval.bench_charts import (
        build_lightheavy_accuracy_spec,
        build_lightheavy_latency_spec,
    )

    def _report(acc: float, lat: float) -> dict:
        return {
            "summaries": [
                {"key": "qwen", "n": 10, "accuracy": acc, "latency_median": lat},
                {"key": "vanna_plus", "n": 10, "accuracy": acc - 0.1, "latency_median": lat + 1},
            ]
        }

    light, heavy = _report(0.9, 3.0), _report(0.6, 90.0)
    for builder in (build_lightheavy_accuracy_spec, build_lightheavy_latency_spec):
        spec = builder(light, heavy, "en")
        # Facetté par régime, deux moteurs × deux régimes = 4 lignes de données.
        assert spec["facet"]["field"] == "regime"
        assert len(spec["data"]["values"]) == 4
