"""
test_integration.py — Tests d'intégration LENTS (appellent Ollama).

Marqués ``slow`` : ils sont sautés automatiquement si aucun serveur Ollama n'est
joignable, pour que la suite rapide reste exécutable partout (CI sans GPU).
Lancer explicitement :  ``pytest -m slow``.

Ils valident le bout-en-bout réel : une approche génère du SQL exécutable, la
métrique d'exécution atteint le seuil, Gemma produit une spec Vega-Lite, et le
système est robuste aux petites perturbations de la question.
"""

from __future__ import annotations

import pytest

from backend import figures
from backend.approaches.qwen_ollama import QwenOllamaApproach
from backend.db import run_select
from eval.giskard_scan import robustness_score
from eval.run_eval import run_approach_eval

# Tous les tests de ce fichier sont lents (appels modèles).
pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def qwen(ollama_up):
    """Instance QwenCoder, ou skip du module si Ollama est éteint.

    Parameters
    ----------
    ollama_up : bool
        Fixture indiquant si le serveur répond.

    Returns
    -------
    QwenOllamaApproach
        L'approche prête à générer du SQL.
    """
    # Sans serveur, ces tests n'ont pas de sens : on saute proprement.
    if not ollama_up:
        pytest.skip("Serveur Ollama injoignable — tests d'intégration sautés.")
    return QwenOllamaApproach()


def test_qwen_generates_executable_sql(qwen):
    """QwenCoder produit un SELECT qui s'exécute et renvoie des lignes."""
    gen = qwen.generate("Combien de patients par localisation de cancer ?")
    assert gen.ok is True
    # Le SQL généré doit s'exécuter via le garde-fou lecture seule.
    result = run_select(gen.sql)
    assert result.ok is True
    assert result.row_count > 0


def test_qwen_execution_accuracy_meets_threshold(qwen):
    """L'exactitude d'exécution de QwenCoder atteint le seuil versionné."""
    # Éval complète sur le jeu de référence ; gate identique à la CI.
    report = run_approach_eval("qwen")
    assert report["ok"] is True, (
        f"Accuracy {report['accuracy']:.0%} < seuil {report['threshold']:.0%}"
    )


def test_gemma_builds_vega_spec(qwen, ollama_up):
    """Gemma choisit une visualisation et renvoie une spec Vega-Lite valide."""
    # On part d'un vrai résultat de requête pour la figure.
    cols = ["localisation", "n"]
    rows = [["Sein", 47], ["Poumon", 40], ["Côlon", 45]]
    res = figures.make_figure("Patients par localisation", cols, rows)
    # Gemma peut refuser une figure, mais ici un bar chart est évident.
    assert res.ok is True
    assert res.vega_spec is not None
    assert res.vega_spec["$schema"].endswith("v5.json")


def test_qwen_is_reasonably_robust(qwen):
    """QwenCoder reste stable face à des perturbations neutres de la question."""
    # Invariance : casse, espaces, amorce polie ne doivent pas casser la réponse.
    report = robustness_score(qwen, subset=3)
    # Seuil indulgent : petit modèle local ; on veut surtout détecter l'instabilité.
    assert report.score >= 0.5, f"Robustesse trop faible : {report.score:.0%}"
