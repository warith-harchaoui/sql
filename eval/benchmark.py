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

from .benchmark_set import balanced_bench, large_bench
from .execution_match import evaluate_sql

logger = logging.getLogger(__name__)

# Fabriques d'approches par clé + libellé lisible. IMPORTANT : les quatre
# configs partagent le MÊME LLM (`qwen2.5-coder`) — on compare les *approches*
# (contexte/stratégie), pas des modèles différents. ``qwen`` (bon prompt) et
# ``qwen_naive`` (schéma nu, sans valeurs ni auto-correction) servent à montrer
# qu'un bon prompt change tout.
_APPROACHES: dict[str, tuple] = {
    "qwen": (lambda db_path=None: QwenOllamaApproach(db_path=db_path), "QwenCoder (bon prompt)"),
    "qwen_naive": (
        lambda db_path=None: QwenOllamaApproach(db_path=db_path, naive=True),
        "QwenCoder (prompt naïf)",
    ),
    "langchain": (lambda db_path=None: LangChainApproach(db_path=db_path), "LangChain"),
    "vanna": (lambda db_path=None: VannaApproach(db_path=db_path), "Vanna 1"),
    "vanna_plus": (lambda db_path=None: VannaApproach(db_path=db_path, rich=True), "Vanna 2"),
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


def run_one_approach(key: str, dataset: list, repeats: int = 3, db_path: object = None) -> dict:
    """Fait tourner une approche sur ``dataset`` et collecte les mesures.

    Chaque requête est générée ``repeats`` fois ; on garde le **minimum** de
    latence horloge murale. Justification : le bruit (autres activités de la
    machine) ne fait qu'*ajouter* du temps, donc le minimum observé approche la
    latence « propre », débruitée. On capte aussi le temps mesuré PAR OLLAMA
    (``server_s``) et la vitesse ``tokens_per_s`` quand l'approche les expose, et
    on archive le SQL généré + le type d'échec pour l'analyse d'erreurs.

    Parameters
    ----------
    key : str
        Clé d'approche (``qwen`` / ``qwen_naive`` / ``langchain`` / ``vanna``).
    dataset : list
        Les cas (``GoldenCase``) à évaluer.
    repeats : int
        Nombre de répétitions par requête (on garde le min de latence).
    db_path : object, optional
        Base ciblée (LIGHT par défaut, ou HEAVY pour l'étude « gros schéma »).
        Elle est passée à l'approche (schéma vu par le LLM) ET à l'évaluation
        (exécution du généré et de la référence).

    Returns
    -------
    dict
        ``{"key", "label", "records": [...], "available": bool, "error": str?}``
        où chaque record est une mesure par requête.
    """
    cls, label = _APPROACHES[key]
    # Instanciation : peut échouer proprement (dépendance/serveur absents). On
    # passe la base ciblée : l'approche construit son schéma/RAG sur CETTE base.
    try:
        approach = cls(db_path)
    except ApproachUnavailable as exc:
        return {"key": key, "label": label, "available": False, "error": str(exc), "records": []}

    records: list[dict] = []
    # On déroule chaque cas : on répète la génération, on garde le min de latence,
    # puis on compare l'exécution du SQL généré à celle de la référence.
    for i, case in enumerate(dataset, 1):
        walls: list[float] = []
        server_times: list[float] = []
        tps_values: list[float] = []
        gen = None
        for _ in range(max(1, repeats)):
            started = time.perf_counter()
            gen = approach.generate(case.question)
            walls.append(time.perf_counter() - started)
            # Temps serveur Ollama et tokens/s : présents seulement sur les
            # approches instrumentées (QwenCoder). On collecte quand c'est là.
            if gen.server_s:
                server_times.append(gen.server_s)
            if gen.tokens_per_s:
                tps_values.append(gen.tokens_per_s)
        # Le SQL est déterministe (température 0) : le verdict est stable ; on
        # évalue la dernière génération.
        verdict = evaluate_sql(gen.sql, case.sql_ref, ordered=case.ordered, db_path=db_path)
        # Type d'échec pour l'analyse : « ok », « exec » (SQL invalide) ou
        # « semantique » (SQL valide mais mauvais résultat — l'erreur silencieuse).
        exec_ok = verdict.gen_rows != -1
        if verdict.match:
            err_type = "ok"
        elif exec_ok:
            err_type = "semantique"
        else:
            err_type = "exec"
        records.append(
            {
                "id": case.id,
                "domaine": case.domaine,
                "difficulte": case.difficulte,
                # Latence débruitée = minimum sur les répétitions.
                "latency_s": round(min(walls), 4),
                # Temps de calcul propre (Ollama) : min ; vitesse : max (meilleur cas).
                "server_s": round(min(server_times), 4) if server_times else None,
                "tokens_per_s": round(max(tps_values), 1) if tps_values else None,
                "gen_ok": gen.ok,
                "exec_ok": exec_ok,
                "match": verdict.match,
                "err_type": err_type,
                # SQL généré (tronqué) : sert d'exemple dans l'analyse d'erreurs.
                "sql": gen.sql[:300],
            }
        )
        # Trace de progression : utile car la campagne complète est longue.
        logger.info(
            "[%s] %d/%d %s  min %.2fs  %s",
            key,
            i,
            len(dataset),
            case.id,
            min(walls),
            "✓" if verdict.match else "✗",
        )
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

    # Mesures propres côté Ollama (présentes seulement pour les approches
    # instrumentées, ex. QwenCoder) : temps serveur et vitesse tokens/s.
    server_times = [r["server_s"] for r in records if r.get("server_s")]
    tps = [r["tokens_per_s"] for r in records if r.get("tokens_per_s")]

    # Anatomie des échecs : erreurs d'exécution (SQL invalide) vs erreurs
    # sémantiques (SQL valide, mauvais résultat — l'« erreur silencieuse »).
    errors = {
        "exec": sum(1 for r in records if r.get("err_type") == "exec"),
        "semantique": sum(1 for r in records if r.get("err_type") == "semantique"),
    }

    summary = {
        "key": result["key"],
        "label": result["label"],
        "n": len(records),
        "accuracy": sum(matches) / len(matches),
        "accuracy_by_difficulty": by_diff,
        "errors": errors,
        "latency_mean": statistics.mean(latencies),
        "latency_median": statistics.median(latencies),
        "latency_p95": _percentile(latencies, 95),
        "latency_min": min(latencies),
        "latency_max": max(latencies),
        "total_time_s": total_time,
        "throughput_per_min": 60 * len(records) / total_time if total_time else 0.0,
    }
    # On n'ajoute les stats serveur que si l'approche les fournit.
    if server_times:
        summary["server_median_s"] = statistics.median(server_times)
    if tps:
        summary["tokens_per_s_median"] = statistics.median(tps)
    return summary


def run_benchmark(
    keys: list[str],
    out_path: Path = DEFAULT_OUT,
    repeats: int = 3,
    merge: bool = True,
    db_path: object = None,
    per_level: int | None = None,
) -> dict:
    """Exécute le benchmark pour les approches demandées et écrit le JSON.

    Parameters
    ----------
    keys : list[str]
        Clés d'approches à évaluer.
    out_path : pathlib.Path
        Où écrire les résultats bruts + résumés (consommés par les figures).
    repeats : int
        Répétitions par requête (min de latence retenu) — robustesse au bruit.
    merge : bool
        Si vrai et qu'un rapport existe déjà, on CONSERVE les approches qui ne
        sont pas re-lancées (fusion par clé) : on peut ainsi ajouter une seule
        approche (ex. ``vanna_plus``) sans re-mesurer les autres.
    db_path : object, optional
        Base ciblée. LIGHT (défaut) ou HEAVY (gros schéma) pour l'étude de
        l'inversion du classement. Le JEU de questions reste identique — seule la
        base sur laquelle le schéma est lu et le SQL exécuté change.
    per_level : int | None
        Si fourni, on n'utilise qu'un ÉCHANTILLON de ``per_level`` cas par palier
        (facile/moyen/difficile). Indispensable sur HEAVY : le prompt géant y rend
        la génération lente, on ne lance donc pas les 768 cas complets.

    Returns
    -------
    dict
        Le rapport complet ``{"n_cases", "approaches": [...], "summaries": [...]}``.
    """
    approaches_raw: list[dict] = []
    summaries: list[dict] = []
    # Fusion : on repart des approches déjà mesurées dont la clé n'est PAS relancée.
    if merge and out_path.is_file():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            approaches_raw = [a for a in prev.get("approaches", []) if a.get("key") not in keys]
            summaries = [s for s in prev.get("summaries", []) if s.get("key") not in keys]
            if approaches_raw:
                logger.info("Fusion : on conserve %s", [a["key"] for a in approaches_raw])
        except Exception:
            # Fichier illisible : on repart de zéro plutôt que de planter.
            approaches_raw, summaries = [], []
    # Le jeu est construit UNE fois (sur la base LIGHT, toujours) et partagé par
    # toutes les approches — comparaison à jeu identique. Un échantillon par
    # palier est utilisé si ``per_level`` est fourni (cas HEAVY, prompt lent).
    dataset = balanced_bench(per_level) if per_level else large_bench()
    logger.info("Jeu : %d requêtes", len(dataset))

    def _write() -> dict:
        """Écrit l'état COURANT du rapport sur disque et le renvoie.

        Écriture INCRÉMENTALE (après chaque approche) : si le run est interrompu,
        les approches déjà terminées sont conservées plutôt que tout perdre.
        """
        report = {
            "n_cases": len(dataset),
            "repeats": repeats,
            "approaches": approaches_raw,
            "summaries": summaries,
        }
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    report: dict = {"n_cases": len(dataset), "repeats": repeats, "approaches": [], "summaries": []}
    # Séquentiel : on veut des latences propres, pas de contention GPU/CPU.
    for key in keys:
        logger.info("=== Approche %s (repeats=%d) ===", key, repeats)
        res = run_one_approach(key, dataset, repeats=repeats, db_path=db_path)
        approaches_raw.append(res)
        if res["available"]:
            summaries.append(summarize(res))
        # On persiste dès qu'une approche est finie (robustesse aux interruptions).
        report = _write()
        logger.info("Résultats partiels écrits (%d approche(s)) : %s", len(summaries), out_path)

    logger.info("Résultats finaux écrits : %s", out_path)
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
        cell = {
            niv: (f"{d[niv]['accuracy']:.0%}" if niv in d else "-")
            for niv in ("facile", "moyen", "difficile")
        }
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
    parser.add_argument(
        "--approaches", nargs="+", default=list(_APPROACHES), choices=list(_APPROACHES)
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--repeats", type=int, default=3, help="Répétitions par requête (min de latence)."
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Base ciblée (défaut : base LIGHT de la démo). Passer data/institut_wide.db "
        "pour l'étude « gros schéma » (HEAVY).",
    )
    parser.add_argument(
        "--per-level",
        type=int,
        default=None,
        help="Échantillon de N cas par palier (facile/moyen/difficile) au lieu du jeu complet. "
        "Recommandé sur HEAVY (génération lente).",
    )
    args = parser.parse_args()

    report = run_benchmark(
        args.approaches,
        Path(args.out),
        repeats=args.repeats,
        db_path=args.db,
        per_level=args.per_level,
    )
    logger.info("\n%s", _format_summary(report["summaries"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
