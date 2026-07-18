"""
base.py — Contrat commun aux trois approches text2sql.

Toutes les approches (LangChain, QwenCoder brut, Vanna) répondent à la même
question : « transformer une phrase en une requête SQL ». Pour pouvoir les
comparer *équitablement* et *en sécurité*, on impose deux choses :

  1. Chaque approche ne fait que **générer** le SQL (elle ne l'exécute pas
     elle-même). L'exécution passe par l'unique garde-fou lecture seule de
     ``backend.db.run_select`` — un seul endroit à sécuriser.
  2. Chaque approche renvoie le même objet ``SQLGeneration`` : SQL produit,
     sortie brute du modèle (transparence pédagogique), latence, erreurs.

Une approche indisponible (dépendance non installée, serveur éteint) ne casse
pas la démo : elle expose ``available()`` et lève ``ApproachUnavailable`` à la
construction avec un message actionnable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ApproachUnavailable(RuntimeError):
    """Levée quand une approche ne peut pas fonctionner (dépendance/config manquante)."""


@dataclass
class SQLGeneration:
    """Résultat normalisé de la génération de SQL par une approche.

    Attributes
    ----------
    sql : str
        La requête SQL extraite, prête à exécuter (ou vide si échec).
    approach : str
        Identifiant lisible de l'approche (« LangChain », « QwenCoder », ...).
    model : str | None
        Modèle LLM sous-jacent, quand il y en a un.
    latency_s : float
        Temps de génération en secondes (utile pour comparer les approches).
    ok : bool
        Faux si la génération a échoué (le champ ``error`` explique alors).
    error : str | None
        Message d'erreur éventuel.
    raw : str
        Sortie brute du modèle avant nettoyage — affichée pour la transparence.
    notes : str
        Remarque pédagogique sur ce que fait l'approche.
    """

    sql: str
    approach: str
    model: str | None = None
    latency_s: float = 0.0
    ok: bool = True
    error: str | None = None
    raw: str = ""
    notes: str = ""


@runtime_checkable
class Text2SQL(Protocol):
    """Interface minimale d'une approche text2sql.

    Toute approche concrète implémente ``generate`` ; le nom lisible est porté
    par l'attribut de classe ``name``.
    """

    name: str

    def generate(self, question: str) -> SQLGeneration:
        """Transforme une question en langage naturel en un ``SQLGeneration``."""
        ...


# Repère un bloc SQL entre backticks ```sql ... ``` (le format que les LLM
# adorent produire malgré nos consignes). Capturé pour être retiré proprement.
_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def clean_sql(raw: str) -> str:
    r"""Extrait une requête SQL propre de la sortie potentiellement bavarde d'un LLM.

    Les modèles enrobent souvent le SQL de texte (« Voici la requête : »),
    de blocs Markdown, ou de préfixes ``SQLQuery:``. Cette fonction déroule les
    nettoyages classiques dans l'ordre pour retomber sur une requête nue.

    Parameters
    ----------
    raw : str
        Texte brut renvoyé par le modèle.

    Returns
    -------
    str
        La requête SQL isolée, sans clôture ni bavardage.

    Examples
    --------
    >>> clean_sql("Voici :\\n```sql\\nSELECT 1;\\n```")
    'SELECT 1'
    """
    text = raw.strip()

    # 1) Si un bloc ```sql ... ``` existe, il contient la requête : on le prend.
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    # 2) Certains modèles préfixent « SQLQuery: » ou « Requête : » — on coupe.
    for prefix in ("SQLQuery:", "SQL:", "Requête :", "Query:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :].strip()

    # 3) Ne garder que jusqu'au premier point-virgule : le modèle peut ajouter
    #    des explications après la requête.
    if ";" in text:
        text = text.split(";", 1)[0]

    # 4) Nettoyage final des espaces et retours superflus.
    return text.strip()
