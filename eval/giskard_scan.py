"""
giskard_scan.py — Robustesse du text2sql (invariance aux perturbations).

Un bon système text2sql ne doit pas changer d'avis parce qu'on a écrit la
question en minuscules ou ajouté une faute de frappe. On mesure donc une
**robustesse par invariance** : on perturbe légèrement chaque question et on
vérifie que le résultat exécuté reste le même que pour la question d'origine.

Deux niveaux :
  1. ``robustness_score`` — métrique déterministe, 100 % locale, toujours
     disponible (ne dépend pas de Giskard).
  2. ``giskard_model_and_dataset`` — emballe une approche en ``giskard.Model`` +
     ``giskard.Dataset`` pour que l'utilisateur lance un ``giskard.scan`` complet
     s'il le souhaite. Optionnel : présent seulement si Giskard est installé.

Rationale : Giskard vise surtout les tâches de classification/NLP « ouvertes » ;
pour le text2sql on a une vérité terrain objective, donc l'invariance
d'exécution est la mesure de robustesse la plus parlante et la moins coûteuse.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .execution_match import evaluate_sql
from .golden import GOLDEN

logger = logging.getLogger(__name__)

# Import tolérant de Giskard : purement optionnel.
try:
    import giskard  # noqa: F401

    _GISKARD_OK = True
except Exception:  # ImportError ou incompatibilité
    _GISKARD_OK = False


def giskard_available() -> bool:
    """Indique si Giskard est importable.

    Returns
    -------
    bool
        Vrai si le paquet ``giskard`` est présent.
    """
    return _GISKARD_OK


def perturb(question: str) -> list[str]:
    """Génère des variantes « robustesse » d'une question.

    Les perturbations sont sémantiquement neutres : la bonne réponse SQL ne doit
    pas changer. On teste la casse, les espaces superflus et une reformulation
    d'amorce courante.

    Parameters
    ----------
    question : str
        Question d'origine.

    Returns
    -------
    list[str]
        Une liste de variantes (l'originale n'y figure pas).

    Examples
    --------
    >>> variants = perturb("Combien de patients ?")
    >>> len(variants) >= 2
    True
    """
    variants: list[str] = []
    # 1) Tout en minuscules : robustesse à la casse.
    variants.append(question.lower())
    # 2) Espaces internes doublés : robustesse au bruit de saisie.
    variants.append(re.sub(r"\s+", "  ", question))
    # 3) Amorce polie ajoutée : robustesse aux formulations conversationnelles.
    variants.append("Peux-tu me dire : " + question[0].lower() + question[1:])
    return variants


@dataclass
class RobustnessReport:
    """Rapport de robustesse pour une approche.

    Attributes
    ----------
    score : float
        Part des (cas × variantes) qui donnent le même résultat que l'origine.
    stable : int
        Nombre de variantes stables.
    total : int
        Nombre total de variantes testées.
    """

    score: float
    stable: int
    total: int


def robustness_score(approach, subset: int | None = 4) -> RobustnessReport:
    """Mesure l'invariance d'une approche aux perturbations de question.

    Pour chaque cas (limité à ``subset`` pour rester rapide), on génère le SQL de
    la question d'origine, puis de chaque variante perturbée, et on vérifie que
    toutes renvoient le même résultat exécuté.

    Parameters
    ----------
    approach : object
        Une instance d'approche exposant ``generate(question) -> SQLGeneration``.
    subset : int | None
        Nombre de cas du jeu de référence à tester (None = tous).

    Returns
    -------
    RobustnessReport
        Le score de robustesse agrégé.
    """
    # On borne le nombre de cas : chaque cas coûte plusieurs appels LLM.
    cases = GOLDEN[:subset] if subset else GOLDEN
    stable = 0
    total = 0
    for case in cases:
        # Résultat de référence = celui de la question d'origine générée.
        base = approach.generate(case.question)
        # On compare chaque variante au SQL de RÉFÉRENCE du cas (vérité terrain) :
        # ainsi une approche déjà fausse à l'origine ne « gagne » pas en stabilité.
        for variant in perturb(case.question):
            gen = approach.generate(variant)
            verdict = evaluate_sql(gen.sql, case.sql_ref, ordered=case.ordered)
            total += 1
            if verdict.match:
                stable += 1
        # ``base`` est calculé pour la traçabilité ; on log le SQL d'origine.
        logger.debug("Cas %s — SQL origine : %s", case.id, base.sql)

    score = stable / total if total else 0.0
    return RobustnessReport(score=score, stable=stable, total=total)


def giskard_model_and_dataset(approach):
    """Emballe une approche en ``giskard.Model`` + ``giskard.Dataset``.

    Permet à l'utilisateur de lancer ``giskard.scan(model, dataset)`` pour une
    analyse de robustesse/biais poussée. Le modèle Giskard prédit ici… le SQL
    généré (sortie texte) à partir de la colonne ``question``.

    Parameters
    ----------
    approach : object
        Instance d'approche exposant ``generate``.

    Returns
    -------
    (giskard.Model, giskard.Dataset)
        Le couple prêt à scanner.

    Raises
    ------
    RuntimeError
        Si Giskard n'est pas installé.
    """
    # Sans Giskard, impossible de construire ses objets : erreur explicite.
    if not _GISKARD_OK:
        raise RuntimeError("Giskard non installé. `pip install giskard`.")

    import pandas as pd

    def _predict(df: pd.DataFrame) -> list[str]:
        """Fonction de prédiction Giskard : question -> SQL généré.

        Parameters
        ----------
        df : pandas.DataFrame
            Doit contenir une colonne ``question``.

        Returns
        -------
        list[str]
            Le SQL généré pour chaque ligne.
        """
        # Giskard passe un batch de lignes ; on génère le SQL pour chacune.
        return [approach.generate(q).sql for q in df["question"].tolist()]

    # Jeu de données = les questions de référence.
    dataset = giskard.Dataset(
        pd.DataFrame({"question": [c.question for c in GOLDEN]}),
        name="Questions text2sql (institut cancéro)",
    )
    # Modèle « texte génératif » : la cible est la chaîne SQL.
    model = giskard.Model(
        model=_predict,
        model_type="text_generation",
        name="Approche text2sql",
        description="Traduit une question française en requête SQL.",
        feature_names=["question"],
    )
    return model, dataset
