"""
benchmark.py — Comparaison numérique des approches text2sql.

Fait tourner chaque approche disponible sur le grand jeu ``BENCH`` et collecte,
par requête : **latence** (temps de génération), **exactitude** (le SQL généré
renvoie-t-il le même résultat que la référence ?), et les drapeaux d'échec. On en
tire des statistiques agrégées (exactitude globale et par difficulté ; latence
moyenne / médiane / p95 ; débit) et on sauvegarde le tout en JSON pour les
graphiques (``eval/bench_charts.py``).

Usage :
    python -m eval.benchmark                          # les 3 approches
    python -m eval.benchmark --approaches qwen vanna  # sous-ensemble
    python -m eval.benchmark --out eval/benchmark_results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
from pathlib import Path

from backend.approaches.base import ApproachUnavailable
from backend.approaches.langchain_sql import LangChainApproach
from backend.approaches.qwen_ollama import QwenOllamaApproach
from backend.approaches.vanna_rag import VannaApproach

from .benchmark_set import BENCH
from .execution_match import evaluate_sql

logger = logging.getLogger(__name__)

# Fabriques d'approches par clé + libellé lisible pour les rapports/figures.
_APPROACHES: dict[str, tuple[type, str]] = {
    "qwen": (QwenOllamaApproach, "QwenCoder (brut)"),
    "langchain": (LangChainApproach, "LangChain"),
    "vanna": (VannaApproach, "Vanna (RAG)"),
}

# Chemin par défaut des résultats (consommés par les graphiques).
DEFAULT_OUT = Path(__file__).resolve().parent / "benchmark_results.json"


def _percentile(values: list[float], pct: float) -> float:
    """Renvoie le percentile ``pct`` (0-100) d'une liste de valeurs.

    Parameters
    ----------
    values : list[float]
        Échantillon (non vide).
    pct : float
        Percentile voulu, ex. 95 pour le p95.

    Returns
    -------
    float
        La valeur au percentile demandé (interpolation linéaire simple).

    Examples
    --------
    >>> _percentile([1, 2, 3, 4], 50)
    2.5
    """
    # Tri obligatoire pour lire un percentile ; copie pour ne pas muter l'appelant.
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    # Position fractionnaire dans l'échantillon trié, puis interpolation.
    rank = (pct / 100) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def run_one_approach(key: str) -> dict:
    """Fait tourner une approche sur tout ``BENCH`` et collecte les mesures.

    Parameters
    ----------
    key : str
        Clé d'approche (``qwen`` / ``langchain`` / ``vanna``).

    Returns
    -------
    dict
        ``{"key", "label", "records": [...], "available": bool, "error": str?}``
        où chaque record est une mesure par requête.
    """
    cls, label = _APPROACHES[key]
    # Instanciation : peut échouer proprement (dépendance/serveur absents).
    try:
        approach = cls()
    except ApproachUnavailable as exc:
        return {"key": key, "label": label, "available": False, "error": str(exc), "records": []}

    records: list[dict] = []
    # On déroule chaque cas : on chronomètre la génération, puis on compare
    # l'exécution du SQL généré à celle de la référence.
    for i, case in enumerate(BENCH, 1):
        started = time.perf_counter()
        gen = approach.generate(case.question)
        latency = time.perf_counter() - started
        verdict = evaluate_sql(gen.sql, case.sql_ref, ordered=case.ordered)
        records.append({
            "id": case.id,
            "domaine": case.domaine,
            "difficulte": case.difficulte,
            "latency_s": round(latency, 4),
            "gen_ok": gen.ok,
            "exec_ok": verdict.gen_rows != -1,
            "match": verdict.match,
        })
        # Trace de progression : utile car la campagne complète est longue.
        logger.info("[%s] %d/%d %s  %.2fs  %s",
                    key, i, len(BENCH), case.id, latency, "✓" if verdict.match else "✗")
    return {"key": key, "label": label, "available": True, "records": records}


def summarize(result: dict) -> dict:
    """Agrège les mesures d'une approche en statistiques lisibles.

    Parameters
    ----------
    result : dict
        Sortie de :func:`run_one_approach`.

    Returns
    -------
    dict
        Exactitude (globale + par difficulté), latences (moyenne/médiane/p95/
        min/max), temps total et débit (requêtes/minute).
    """
    records = result["records"]
    if not records:
        return {"key": result["key"], "label": result["label"], "n": 0}

    latencies = [r["latency_s"] for r in records]
    matches = [r["match"] for r in records]
    total_time = sum(latencies)

    # Exactitude ventilée par palier de difficulté.
    by_diff: dict[str, dict] = {}
    for niveau in ("facile", "moyen", "difficile"):
        subset = [r["match"] for r in records if r["difficulte"] == niveau]
        if subset:
            by_diff[niveau] = {
                "passed": sum(subset),
                "total": len(subset),
                "accuracy": sum(subset) / len(subset),
            }

    return {
        "key": result["key"],
        "label": result["label"],
        "n": len(records),
        "accuracy": sum(matches) / len(matches),
        "accuracy_by_difficulty": by_diff,
        "latency_mean": statistics.mean(latencies),
        "latency_median": statistics.median(latencies),
        "latency_p95": _percentile(latencies, 95),
        "latency_min": min(latencies),
        "latency_max": max(latencies),
        "total_time_s": total_time,
        "throughput_per_min": 60 * len(records) / total_time if total_time else 0.0,
    }


def run_benchmark(keys: list[str], out_path: Path = DEFAULT_OUT) -> dict:
    """Exécute le benchmark pour les approches demandées et écrit le JSON.

    Parameters
    ----------
    keys : list[str]
        Clés d'approches à évaluer.
    out_path : pathlib.Path
        Où écrire les résultats bruts + résumés (consommés par les figures).

    Returns
    -------
    dict
        Le rapport complet ``{"n_cases", "approaches": [...], "summaries": [...]}``.
    """
    approaches_raw: list[dict] = []
    summaries: list[dict] = []
    # Séquentiel : on veut des latences propres, pas de contention GPU/CPU.
    for key in keys:
        logger.info("=== Approche %s ===", key)
        res = run_one_approach(key)
        approaches_raw.append(res)
        if res["available"]:
            summaries.append(summarize(res))

    report = {
        "n_cases": len(BENCH),
        "approaches": approaches_raw,
        "summaries": summaries,
    }
    # Persistance pour les graphiques (violin de latence, barres de qualité).
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Résultats écrits : %s", out_path)
    return report


def _format_summary(summaries: list[dict]) -> str:
    """Met en forme un tableau texte récapitulatif du benchmark.

    Parameters
    ----------
    summaries : list[dict]
        Les résumés par approche.

    Returns
    -------
    str
        Tableau lisible en console.
    """
    lines = [
        f"{'Approche':<20} {'Exact.':>7} {'facile':>7} {'moyen':>7} {'diff.':>7} "
        f"{'lat.méd':>8} {'lat.p95':>8} {'req/min':>8}",
        "-" * 82,
    ]
    for s in summaries:
        d = s.get("accuracy_by_difficulty", {})
        # Accuracy d'un palier formatée, ou « - » s'il est absent.
        cell = {niv: (f"{d[niv]['accuracy']:.0%}" if niv in d else "-")
                for niv in ("facile", "moyen", "difficile")}
        lines.append(
            f"{s['label']:<20} {s['accuracy']:>6.0%} {cell['facile']:>7} {cell['moyen']:>7} "
            f"{cell['difficile']:>7} {s['latency_median']:>7.2f}s {s['latency_p95']:>7.2f}s "
            f"{s['throughput_per_min']:>8.1f}"
        )
    return "\n".join(lines)


def main() -> int:
    """Point d'entrée CLI : lance le benchmark et affiche le récapitulatif.

    Returns
    -------
    int
        Code de sortie (0).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Benchmark text2sql (latence + exactitude).")
    parser.add_argument("--approaches", nargs="+", default=list(_APPROACHES),
                        choices=list(_APPROACHES))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    report = run_benchmark(args.approaches, Path(args.out))
    logger.info("\n%s", _format_summary(report["summaries"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
