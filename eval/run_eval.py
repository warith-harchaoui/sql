"""
run_eval.py — Évalue une approche text2sql sur le jeu de référence.

Calcule l'**exactitude d'exécution** (part des questions pour lesquelles le SQL
généré renvoie le même résultat que le SQL de référence) et la compare à un
seuil versionné (cf. CODING.md §14 : métriques + seuils + gate CI).

Usage :
    python -m eval.run_eval --approach qwen
    python -m eval.run_eval --approach vanna --threshold 0.7
"""

from __future__ import annotations

import argparse
import logging

from backend.approaches.base import ApproachUnavailable
from backend.approaches.langchain_sql import LangChainApproach
from backend.approaches.qwen_ollama import QwenOllamaApproach
from backend.approaches.vanna_rag import VannaApproach

from .execution_match import evaluate_sql
from .golden import GOLDEN, GOLDEN_HARD

logger = logging.getLogger(__name__)

# Fabriques d'approches par clé (mêmes clés que l'API).
_APPROACHES = {
    "qwen": QwenOllamaApproach,
    "langchain": LangChainApproach,
    "vanna": VannaApproach,
}

# Seuils d'exactitude d'exécution VERSIONNÉS par approche (petits modèles
# locaux → attentes réalistes ; on ne vise pas GPT-4). Ajustables ici, sous
# revue de code, plutôt que dispersés dans le code.
# NB : le jeu de référence est volontairement ABORDABLE (agrégats, filtres,
# jointures simples) ; sur ce jeu, qwen (valeurs énumérées + auto-correction)
# atteint 100 %. Les seuils reflètent ce niveau — un jeu de questions dures
# (fenêtres temporelles, sous-requêtes) ferait chuter ces chiffres.
THRESHOLDS: dict[str, float] = {
    "qwen": 0.8,
    "langchain": 0.6,
    "vanna": 0.7,  # le RAG few-shot doit faire mieux sur des questions proches
}


def run_approach_eval(key: str, threshold: float | None = None, hard: bool = False) -> dict:
    """Évalue une approche sur le jeu de référence (facile ou difficile).

    Parameters
    ----------
    key : str
        Clé d'approche (``qwen`` / ``langchain`` / ``vanna``).
    threshold : float | None
        Seuil d'accuracy exigé ; défaut : ``THRESHOLDS[key]``.
    hard : bool
        Si vrai, évalue sur le jeu DIFFICILE (``GOLDEN_HARD``) qui expose le
        vrai plafond ; sinon sur le jeu abordable (``GOLDEN``).

    Returns
    -------
    dict
        Rapport : accuracy, seuil, statut pass/fail, et détail par cas.

    Raises
    ------
    ApproachUnavailable
        Si l'approche ne peut pas être initialisée.
    KeyError
        Si la clé d'approche est inconnue.
    """
    # Sur le jeu difficile, on n'impose pas de seuil de succès : le but est de
    # MESURER le plafond, pas de « passer ». Défaut : seuil versionné sur le jeu facile.
    limit = threshold if threshold is not None else (0.0 if hard else THRESHOLDS.get(key, 0.6))
    dataset = GOLDEN_HARD if hard else GOLDEN
    # Instanciation (peut lever ApproachUnavailable : on laisse remonter au CLI).
    approach = _APPROACHES[key]()

    details: list[dict] = []
    passed = 0
    # On déroule chaque cas : génération → exécution comparée à la référence.
    for case in dataset:
        gen = approach.generate(case.question)
        verdict = evaluate_sql(gen.sql, case.sql_ref, ordered=case.ordered)
        if verdict.match:
            passed += 1
        # On archive le détail pour le rapport (débogage des échecs).
        details.append(
            {
                "id": case.id,
                "domaine": case.domaine,
                "question": case.question,
                "sql": gen.sql,
                "match": verdict.match,
                "reason": verdict.reason,
            }
        )

    total = len(dataset)
    accuracy = passed / total if total else 0.0
    return {
        "approach": key,
        "accuracy": accuracy,
        "passed": passed,
        "total": total,
        "threshold": limit,
        "ok": accuracy >= limit,
        "details": details,
    }


def _format_report(report: dict) -> str:
    """Met en forme un rapport d'évaluation pour la sortie console.

    Parameters
    ----------
    report : dict
        Rapport renvoyé par :func:`run_approach_eval`.

    Returns
    -------
    str
        Texte multi-lignes lisible.
    """
    lines = [
        f"Approche : {report['approach']}",
        f"Exactitude d'exécution : {report['accuracy']:.0%} "
        f"({report['passed']}/{report['total']})  | seuil {report['threshold']:.0%}  "
        f"=> {'PASS' if report['ok'] else 'FAIL'}",
        "",
    ]
    # Détail par cas : ✓/✗ + question, et la raison en cas d'échec.
    for d in report["details"]:
        mark = "✓" if d["match"] else "✗"
        lines.append(f"  {mark} [{d['id']}] {d['question']}")
        if not d["match"]:
            lines.append(f"      → {d['reason']}  SQL: {d['sql'][:90]}")
    return "\n".join(lines)


def main() -> int:
    """Point d'entrée CLI : évalue l'approche demandée et code de sortie CI.

    Returns
    -------
    int
        0 si le seuil est atteint, 1 sinon (gate CI).
    """
    # Configuration console : ce module est un utilitaire d'éval en ligne de commande.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Évaluation text2sql (exactitude d'exécution).")
    parser.add_argument("--approach", default="qwen", choices=list(_APPROACHES))
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--hard", action="store_true", help="Évalue sur le jeu DIFFICILE (expose le plafond)."
    )
    args = parser.parse_args()

    # Approche indisponible : on l'annonce et on sort en échec « soft ».
    try:
        report = run_approach_eval(args.approach, args.threshold, hard=args.hard)
    except ApproachUnavailable as exc:
        logger.error("Approche indisponible : %s", exc)
        return 1

    logger.info(_format_report(report))
    # Code de sortie = gate CI : non-zéro si le seuil n'est pas atteint.
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
