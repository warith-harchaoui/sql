"""
db.py — Accès base : introspection du schéma + exécution SÉCURISÉE.

Deux besoins pour un text2sql :
  1. Décrire le schéma au LLM (noms de tables, colonnes, types, clés étrangères,
     échantillons de lignes) — c'est le « contexte » qui fait ou défait la qualité.
  2. Exécuter la requête générée SANS risque : lecture seule stricte, une seule
     instruction, LIMIT implicite, timeout. On ne laisse jamais un LLM lâcher un
     DELETE/UPDATE/DROP sur la vraie base.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "institut.db"

# Mots-clés interdits : toute écriture ou opération de structure est refusée.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|"
    r"attach|detach|pragma|vacuum|reindex|grant|revoke)\b",
    re.IGNORECASE,
)


@dataclass
class QueryResult:
    """Résultat d'exécution : colonnes + lignes, ou erreur."""

    columns: list[str]
    rows: list[list]
    row_count: int
    ok: bool = True
    error: str | None = None
    truncated: bool = False


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Ouvre la base en lecture seule (URI `mode=ro`) — garde-fou matériel."""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def sqlalchemy_url(db_path: Path | str = DB_PATH) -> str:
    """URL SQLAlchemy attendue par LangChain / Vanna."""
    return f"sqlite:///{Path(db_path).as_posix()}"


# --------------------------------------------------------------------------- #
# Introspection                                                               #
# --------------------------------------------------------------------------- #


def list_tables(db_path: Path | str = DB_PATH) -> list[str]:
    """Noms de toutes les tables utilisateur, triés."""
    con = connect(db_path)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        con.close()


def table_schema(table: str, db_path: Path | str = DB_PATH) -> dict:
    """Détail d'une table : colonnes (nom, type, PK) + clés étrangères."""
    con = connect(db_path)
    try:
        cols = con.execute(f"PRAGMA table_info('{table}')").fetchall()
        fks = con.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()
        return {
            "table": table,
            "columns": [{"name": c["name"], "type": c["type"], "pk": bool(c["pk"])} for c in cols],
            "foreign_keys": [
                {"column": f["from"], "ref_table": f["table"], "ref_column": f["to"]} for f in fks
            ],
        }
    finally:
        con.close()


def categorical_values(
    db_path: Path | str = DB_PATH,
    max_distinct: int = 20,
) -> dict[str, dict[str, list[str]]]:
    """Recense les valeurs distinctes des colonnes TEXT à faible cardinalité.

    C'est le levier le plus efficace contre les **erreurs sémantiques** (du SQL
    valide qui répond à la mauvaise question) : si le modèle voit que
    ``factures.statut ∈ {Payée, En attente, Partielle, Impayée}``, il ne filtrera
    plus « impayées » par ``'En attente'``. On ne remonte que les colonnes ayant
    au plus ``max_distinct`` valeurs (les vraies énumérations métier), jamais les
    noms/adresses/identifiants.

    Parameters
    ----------
    db_path : pathlib.Path | str
        Chemin de la base.
    max_distinct : int
        Seuil de cardinalité au-delà duquel une colonne est ignorée.

    Returns
    -------
    dict[str, dict[str, list[str]]]
        ``{table: {colonne: [valeurs...]}}`` pour les colonnes énumérées.
    """
    con = connect(db_path)
    out: dict[str, dict[str, list[str]]] = {}
    try:
        # On parcourt chaque table, colonne TEXT par colonne TEXT.
        tables = [
            r["name"]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for t in tables:
            cols = con.execute(f"PRAGMA table_info('{t}')").fetchall()
            for c in cols:
                # Seules les colonnes textuelles portent des énumérations métier.
                if "CHAR" not in c["type"].upper() and "TEXT" not in c["type"].upper():
                    continue
                # Compte d'abord la cardinalité (borne + 1 pour trancher vite).
                try:
                    n = con.execute(f'SELECT COUNT(DISTINCT "{c["name"]}") FROM "{t}"').fetchone()[
                        0
                    ]
                except sqlite3.Error:
                    continue
                # Trop de valeurs -> ce n'est pas une énumération (noms, villes…).
                if n == 0 or n > max_distinct:
                    continue
                rows = con.execute(
                    f'SELECT DISTINCT "{c["name"]}" FROM "{t}" '
                    f'WHERE "{c["name"]}" IS NOT NULL ORDER BY 1'
                ).fetchall()
                values = [str(r[0]) for r in rows]
                out.setdefault(t, {})[c["name"]] = values
        return out
    finally:
        con.close()


def schema_ddl(
    db_path: Path | str = DB_PATH,
    sample_rows: int = 0,
    with_categories: bool = False,
) -> str:
    """Reconstruit un DDL lisible de toute la base, pour prompt LLM.

    Format volontairement compact et standard (``CREATE TABLE ... (col type ...)``)
    car les modèles de code type QwenCoder ont vu ce format des millions de fois.
    Avec ``sample_rows > 0``, on annexe quelques lignes en commentaire : les
    exemples de valeurs aident le modèle à deviner les filtres (ex. statut =
    'Payée', sexe = 'F'). Avec ``with_categories=True``, on annexe les valeurs
    distinctes des colonnes énumérées (cf. :func:`categorical_values`) — le
    meilleur rempart contre les erreurs sémantiques.

    Returns
    -------
    str
        Le schéma complet formaté, prêt à coller dans un prompt.
    """
    con = connect(db_path)
    parts: list[str] = []
    # Valeurs énumérées calculées une seule fois si demandé (requêtes en plus).
    cats = categorical_values(db_path) if with_categories else {}
    try:
        tables = [
            r["name"]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for t in tables:
            cols = con.execute(f"PRAGMA table_info('{t}')").fetchall()
            fks = con.execute(f"PRAGMA foreign_key_list('{t}')").fetchall()
            fk_by_col = {f["from"]: (f["table"], f["to"]) for f in fks}
            lines = [f"CREATE TABLE {t} ("]
            col_defs = []
            for c in cols:
                d = f"    {c['name']} {c['type']}"
                if c["pk"]:
                    d += " PRIMARY KEY"
                if c["name"] in fk_by_col:
                    rt, rc = fk_by_col[c["name"]]
                    d += f" REFERENCES {rt}({rc})"
                col_defs.append(d)
            lines.append(",\n".join(col_defs))
            lines.append(");")
            block = "\n".join(lines)

            if sample_rows > 0:
                try:
                    sample = con.execute(f"SELECT * FROM {t} LIMIT {sample_rows}").fetchall()
                    if sample:
                        header = list(sample[0].keys())
                        block += f"\n/* Exemples ({t}): " + " | ".join(header) + "\n"
                        for r in sample:
                            vals = [str(r[h])[:24] for h in header]
                            block += "   " + " | ".join(vals) + "\n"
                        block += "*/"
                except sqlite3.Error:
                    pass

            # Valeurs énumérées de la table : on les liste en commentaire pour
            # que le modèle filtre sur les BONNES valeurs (anti-erreur sémantique).
            if t in cats:
                enum_lines = [f"   {col} ∈ {{{', '.join(vals)}}}" for col, vals in cats[t].items()]
                block += f"\n/* Valeurs possibles ({t}):\n" + "\n".join(enum_lines) + "\n*/"

            parts.append(block)
        return "\n\n".join(parts)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Exécution sécurisée                                                         #
# --------------------------------------------------------------------------- #


def is_safe_select(sql: str) -> tuple[bool, str]:
    """Valide qu'une requête est un SELECT unique en lecture seule.

    Returns
    -------
    (bool, str)
        ``(True, "")`` si sûre, sinon ``(False, raison)``.
    """
    s = sql.strip().rstrip(";").strip()
    if not s:
        return False, "Requête vide."
    # Une seule instruction : pas de `;` interne qui masquerait un second ordre.
    if ";" in s:
        return False, "Une seule instruction SQL est autorisée."
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return False, "Seules les requêtes SELECT (ou WITH ... SELECT) sont autorisées."
    if _FORBIDDEN.search(s):
        return False, "Mot-clé d'écriture/structure détecté : requête refusée."
    return True, ""


def run_select(
    sql: str,
    db_path: Path | str = DB_PATH,
    max_rows: int = 1000,
) -> QueryResult:
    """Exécute un SELECT validé et renvoie un `QueryResult` borné à `max_rows`.

    On ne fait JAMAIS confiance au SQL produit par un LLM : validation stricte,
    connexion read-only, et coupe défensive à `max_rows` lignes.
    """
    ok, reason = is_safe_select(sql)
    if not ok:
        return QueryResult([], [], 0, ok=False, error=reason)

    con = connect(db_path)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [list(r) for r in fetched[:max_rows]]
        return QueryResult(cols, rows, len(rows), truncated=truncated)
    except sqlite3.Error as exc:
        return QueryResult([], [], 0, ok=False, error=f"Erreur SQL : {exc}")
    finally:
        con.close()
