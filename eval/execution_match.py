"""
execution_match.py — Métrique d'exactitude d'exécution pour le text2sql.

Principe : deux requêtes SQL sont « équivalentes » si elles renvoient le MÊME
résultat sur la base. C'est la métrique standard du domaine (execution accuracy,
cf. Spider/BIRD) : elle ne pénalise pas une bonne requête écrite autrement que
la référence, et attrape les requêtes plausibles mais fausses.

On compare de façon robuste :
  - par valeurs de lignes (pas par noms de colonnes, qui varient d'un modèle à
    l'autre : ``n`` vs ``nombre`` vs ``COUNT(*)``) ;
  - en ensembliste (ordre ignoré) sauf si le cas déclare l'ordre significatif ;
  - avec une tolérance numérique pour les flottants.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.db import QueryResult, run_select


@dataclass
class MatchResult:
    """Verdict de comparaison entre résultat généré et résultat de référence.

    Attributes
    ----------
    match : bool
        Vrai si les deux résultats sont équivalents.
    reason : str
        Explication courte (utile en cas d'échec).
    gen_rows : int
        Nombre de lignes du résultat généré (-1 si non exécuté).
    ref_rows : int
        Nombre de lignes du résultat de référence.
    """

    match: bool
    reason: str
    gen_rows: int
    ref_rows: int


def _normalize_cell(value: object) -> object:
    """Ramène une cellule à une forme comparable (arrondi flottant, str sinon).

    Parameters
    ----------
    value : object
        Valeur de cellule brute.

    Returns
    -------
    object
        Un float arrondi si numérique, sinon la représentation str.

    Examples
    --------
    >>> _normalize_cell(3.0000001)
    3.0
    >>> _normalize_cell("Sein")
    'Sein'
    """
    # bool est un int en Python : on le laisse tel quel converti en int.
    if isinstance(value, bool):
        return int(value)
    # Les nombres sont arrondis pour absorber les micro-écarts de flottants.
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    # Tout le reste (str, None, dates ISO) est comparé en chaîne.
    return "" if value is None else str(value)


def _rows_as_multiset(result: QueryResult) -> list[tuple]:
    """Transforme les lignes d'un résultat en multi-ensemble trié de tuples.

    On trie les lignes ET on normalise les cellules pour rendre la comparaison
    indépendante de l'ordre et des types exacts.

    Parameters
    ----------
    result : QueryResult
        Résultat d'exécution SQL.

    Returns
    -------
    list[tuple]
        Les lignes normalisées, triées de façon stable.
    """
    # Chaque ligne devient un tuple de cellules normalisées.
    rows = [tuple(_normalize_cell(c) for c in row) for row in result.rows]
    # Tri stable par représentation str : rend la comparaison ordre-insensible.
    return sorted(rows, key=lambda r: tuple(str(c) for c in r))


def compare_results(gen: QueryResult, ref: QueryResult, ordered: bool = False) -> MatchResult:
    """Compare un résultat généré à un résultat de référence.

    Parameters
    ----------
    gen : QueryResult
        Résultat de la requête générée par une approche.
    ref : QueryResult
        Résultat de la requête de référence.
    ordered : bool
        Si vrai, l'ordre des lignes doit coïncider (comparaison positionnelle).

    Returns
    -------
    MatchResult
        Le verdict d'équivalence.
    """
    # Un résultat généré en erreur ne peut pas matcher.
    if not gen.ok:
        return MatchResult(False, f"SQL généré en erreur : {gen.error}", -1, ref.row_count)

    # Nombre de colonnes différent -> formes incompatibles (on compare les
    # valeurs, pas les noms, mais l'arité doit correspondre).
    gen_arity = len(gen.columns)
    ref_arity = len(ref.columns)
    if gen_arity != ref_arity:
        return MatchResult(
            False,
            f"Arité différente : {gen_arity} colonnes vs {ref_arity} attendues.",
            gen.row_count,
            ref.row_count,
        )

    # Comparaison selon que l'ordre compte ou non.
    if ordered:
        # Positionnelle : lignes normalisées, dans l'ordre.
        g = [tuple(_normalize_cell(c) for c in row) for row in gen.rows]
        r = [tuple(_normalize_cell(c) for c in row) for row in ref.rows]
    else:
        # Ensembliste : lignes triées (ordre ignoré).
        g = _rows_as_multiset(gen)
        r = _rows_as_multiset(ref)

    if g == r:
        return MatchResult(True, "Résultats identiques.", gen.row_count, ref.row_count)
    return MatchResult(False, "Résultats différents.", gen.row_count, ref.row_count)


def evaluate_sql(generated_sql: str, sql_ref: str, ordered: bool = False) -> MatchResult:
    """Exécute les deux requêtes et compare leurs résultats.

    Parameters
    ----------
    generated_sql : str
        SQL produit par une approche text2sql.
    sql_ref : str
        SQL de référence correct.
    ordered : bool
        L'ordre des lignes est-il significatif ?

    Returns
    -------
    MatchResult
        Le verdict d'équivalence d'exécution.
    """
    # Requête vide générée : échec immédiat, sans toucher la base.
    if not generated_sql.strip():
        ref = run_select(sql_ref)
        return MatchResult(False, "Aucun SQL généré.", -1, ref.row_count)
    # On exécute les deux côtés via le même garde-fou lecture seule.
    gen = run_select(generated_sql)
    ref = run_select(sql_ref)
    return compare_results(gen, ref, ordered=ordered)
