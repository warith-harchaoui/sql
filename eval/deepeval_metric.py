"""
deepeval_metric.py — La métrique d'exactitude d'exécution, empaquetée pour DeepEval.

Pourquoi une métrique DeepEval « maison » ? Les métriques par défaut de DeepEval
(GEval, hallucination…) s'appuient sur un LLM *juge* qui, par défaut, appelle
l'API OpenAI — incompatible avec notre contrainte 100 % local/offline et coûteux.
Le text2sql a de la chance : il existe une vérité terrain **objective** (le
résultat de la requête). On encapsule donc notre comparaison d'exécution dans une
``BaseMetric`` DeepEval : on profite de l'outillage DeepEval (test cases, seuils,
rapports, intégration CI) SANS aucun juge LLM ni appel réseau.

Ce module est optionnel : si DeepEval n'est pas installé, l'import échoue
proprement et la suite d'éval retombe sur l'évaluateur « maison » (run_eval).
"""

from __future__ import annotations

from .execution_match import evaluate_sql

# Import paresseux/tolérant de DeepEval : on n'impose pas le paquet.
try:
    from deepeval.metrics import BaseMetric
    from deepeval.test_case import LLMTestCase

    _DEEPEVAL_OK = True
except Exception:  # ImportError ou incompatibilité
    _DEEPEVAL_OK = False
    # Bornes de secours pour que l'annotation de type ne casse pas à l'import.
    BaseMetric = object  # type: ignore
    LLMTestCase = object  # type: ignore


def deepeval_available() -> bool:
    """Indique si DeepEval est importable.

    Returns
    -------
    bool
        Vrai si le paquet ``deepeval`` est présent.
    """
    return _DEEPEVAL_OK


class ExecutionAccuracyMetric(BaseMetric):
    """Métrique DeepEval d'exactitude d'exécution du SQL généré.

    On lit le test case DeepEval de la façon suivante :
      - ``input``           : la question en langage naturel ;
      - ``actual_output``   : le SQL généré par l'approche ;
      - ``expected_output`` : le SQL de référence correct.

    Le score est binaire (1.0 si les résultats d'exécution coïncident, 0.0
    sinon) et la métrique n'appelle AUCUN juge LLM — 100 % déterministe et local.

    Parameters
    ----------
    threshold : float
        Seuil de succès (par défaut 1.0 : match exact d'exécution requis).
    ordered : bool
        L'ordre des lignes est-il significatif pour ces cas ?
    """

    def __init__(self, threshold: float = 1.0, ordered: bool = False) -> None:
        """Initialise la métrique avec son seuil et son mode de comparaison."""
        # Attributs attendus par le contrat BaseMetric de DeepEval.
        self.threshold = threshold
        self.ordered = ordered
        self.score = 0.0
        self.success = False
        self.reason = ""

    def measure(self, test_case: LLMTestCase) -> float:
        """Évalue un test case et renvoie le score (0.0 ou 1.0).

        Parameters
        ----------
        test_case : LLMTestCase
            Cas DeepEval portant question / SQL généré / SQL de référence.

        Returns
        -------
        float
            1.0 si les exécutions coïncident, 0.0 sinon.
        """
        # On délègue toute la logique à la comparaison d'exécution partagée.
        verdict = evaluate_sql(
            test_case.actual_output or "",
            test_case.expected_output or "",
            ordered=self.ordered,
        )
        # On alimente les attributs que DeepEval lira ensuite.
        self.score = 1.0 if verdict.match else 0.0
        self.success = self.score >= self.threshold
        self.reason = verdict.reason
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        """Variante asynchrone exigée par DeepEval ; délègue à ``measure``.

        Parameters
        ----------
        test_case : LLMTestCase
            Le cas à évaluer.

        Returns
        -------
        float
            Le score calculé par ``measure``.
        """
        # Notre mesure est purement locale/CPU : pas d'I/O async réelle à faire.
        return self.measure(test_case)

    def is_successful(self) -> bool:
        """Renvoie si le dernier appel à ``measure`` a passé le seuil.

        Returns
        -------
        bool
            L'état de succès courant.
        """
        return self.success

    @property
    def __name__(self) -> str:
        """Nom lisible de la métrique, affiché dans les rapports DeepEval."""
        return "Exactitude d'exécution SQL"


def build_test_cases(generated_by_case: dict[str, str]) -> list:
    """Construit les ``LLMTestCase`` DeepEval à partir de SQL déjà générés.

    Parameters
    ----------
    generated_by_case : dict[str, str]
        Mapping ``id_du_cas -> SQL généré`` par une approche.

    Returns
    -------
    list
        Une liste de ``LLMTestCase`` prêts pour ``deepeval.evaluate``.

    Raises
    ------
    RuntimeError
        Si DeepEval n'est pas installé.
    """
    # Sans DeepEval, on ne peut pas fabriquer ses objets : erreur explicite.
    if not _DEEPEVAL_OK:
        raise RuntimeError("DeepEval non installé. `pip install deepeval`.")

    # Import local du jeu de référence pour retrouver question + SQL attendu.
    from .golden import GOLDEN

    cases = []
    for case in GOLDEN:
        # On n'ajoute que les cas pour lesquels on a un SQL généré.
        if case.id not in generated_by_case:
            continue
        cases.append(
            LLMTestCase(
                input=case.question,
                actual_output=generated_by_case[case.id],
                expected_output=case.sql_ref,
            )
        )
    return cases
