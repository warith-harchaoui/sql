"""eda_report.py — Profil exploratoire de la base hôpital via skrub.TableReport.

Artefact PÉDAGOGIQUE en marge du benchmark text2sql : « voici les données que le
LLM interroge ». On charge chaque table de ``data/institut.db`` dans un DataFrame
pandas et on rend un rapport interactif ``skrub.TableReport`` (types, valeurs
manquantes, cardinalités, distributions, associations) — le meilleur coup d'œil
sur un jeu tabulaire, sans écrire une ligne de plot.

Ce n'est PAS un maillon du pipeline text2sql (aucun modèle sklearn ici) : c'est un
outil de compréhension du schéma, utile pour saisir la richesse de la base fictive
(médical, RH, comptabilité, pharmacie…) avant de lire les résultats du benchmark.

Usage :
    python -m backend.eda_report                       # tables illustratives
    python -m backend.eda_report --all                 # toutes les tables
    python -m backend.eda_report --tables patients factures
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

import pandas as pd

from . import db

logger = logging.getLogger(__name__)

# Où déposer les rapports HTML (une page par table) + un index.
EDA_DIR = Path(__file__).resolve().parent.parent / "docs" / "eda"

# Sélection par défaut : les tables les plus parlantes du parcours de soins et de
# la gestion, pour un aperçu représentatif sans générer les 30 rapports.
DEFAULT_TABLES: list[str] = [
    "patients",
    "diagnostics",
    "sejours",
    "cures_chimio",
    "factures",
    "employes",
]


def load_table(table: str, db_path: Path | str = db.DB_PATH) -> pd.DataFrame:
    """Charge une table entière dans un DataFrame pandas (lecture seule).

    Parameters
    ----------
    table : str
        Nom de la table à charger.
    db_path : pathlib.Path | str
        Chemin de la base SQLite.

    Returns
    -------
    pandas.DataFrame
        Le contenu de la table, colonnes typées par pandas.
    """
    # Connexion read-only : l'EDA ne doit jamais modifier la base.
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(f'SELECT * FROM "{table}"', con)
    finally:
        con.close()


def render_reports(
    tables: list[str] | None = None,
    db_path: Path | str = db.DB_PATH,
    out_dir: Path = EDA_DIR,
) -> list[Path]:
    """Rend un ``skrub.TableReport`` HTML par table et un index qui les relie.

    Parameters
    ----------
    tables : list[str] | None
        Tables à profiler ; :data:`DEFAULT_TABLES` si ``None``.
    db_path : pathlib.Path | str
        Base source.
    out_dir : pathlib.Path
        Dossier de sortie des pages HTML.

    Returns
    -------
    list[pathlib.Path]
        Les chemins des fichiers HTML écrits (rapports + index).
    """
    from skrub import TableReport

    names = tables or DEFAULT_TABLES
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Une page par table : skrub calcule tout (manquants, cardinalité, distributions).
    index_rows: list[str] = []
    for table in names:
        frame = load_table(table, db_path)
        report = TableReport(frame, title=f"{table} — {len(frame)} lignes")
        path = out_dir / f"{table}.html"
        path.write_text(report.html(), encoding="utf-8")
        written.append(path)
        logger.info(
            "Rapport skrub : %-16s %6d lignes × %d colonnes → %s",
            table,
            frame.shape[0],
            frame.shape[1],
            path.name,
        )
        index_rows.append(
            f'<li><a href="{table}.html">{table}</a> — '
            f"{frame.shape[0]} lignes × {frame.shape[1]} colonnes</li>"
        )

    # Index simple : point d'entrée listant les rapports produits.
    index = (
        "<!doctype html><html lang='fr'><meta charset='utf-8'>"
        "<title>EDA — base hôpital (skrub)</title>"
        "<h1>Exploration de la base hôpital</h1>"
        "<p>Profils <code>skrub.TableReport</code> des tables interrogées par la démo text2sql.</p>"
        f"<ul>{''.join(index_rows)}</ul></html>"
    )
    index_path = out_dir / "index.html"
    index_path.write_text(index, encoding="utf-8")
    written.append(index_path)
    logger.info("Index écrit : %s", index_path)
    return written


def main() -> int:
    """CLI : produit les rapports skrub de la base et affiche leurs chemins.

    Returns
    -------
    int
        Code de sortie (0).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Profil skrub.TableReport de la base hôpital.")
    parser.add_argument("--tables", nargs="+", default=None, help="Tables à profiler.")
    parser.add_argument("--all", action="store_true", help="Profiler TOUTES les tables de la base.")
    args = parser.parse_args()
    tables = db.list_tables() if args.all else args.tables
    render_reports(tables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
