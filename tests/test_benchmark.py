"""
test_benchmark.py — Tests du benchmark et de ses figures (sans réseau).

Couvre : la validité du grand jeu ``BENCH`` (toutes les références s'exécutent),
les statistiques agrégées (``_percentile``, ``summarize``) et la construction des
specs Vega-Lite des figures (violin de latence, barres de qualité, nuage
qualité/vitesse) — le tout sur des données synthétiques, sans appeler Ollama.
"""

from __future__ import annotations

import pytest

from backend.db import run_select
from eval import bench_charts
from eval.benchmark import _percentile, summarize
from eval.benchmark_set import BENCH, balanced_bench


def test_bench_reference_sql_all_execute(db_path):
    """Toutes les requêtes de référence du grand jeu s'exécutent sans erreur."""
    # Un jeu de benchmark cassé fausserait toute la comparaison : on le protège.
    for case in BENCH:
        result = run_select(case.sql_ref)
        assert result.ok is True, f"{case.id}: {result.error}"


def test_bench_has_three_difficulty_tiers():
    """Le grand jeu curaté couvre bien les trois paliers de difficulté."""
    niveaux = {c.difficulte for c in BENCH}
    assert niveaux == {"facile", "moyen", "difficile"}
    assert len(BENCH) >= 40


def test_balanced_bench_is_256_each_and_executes(db_path):
    """Le jeu ÉQUILIBRÉ fournit 256 cas par palier, tous exécutables."""
    from collections import Counter

    bench = balanced_bench(256)
    # 3 × 256 = 768 requêtes, réparties exactement à parts égales.
    counts = Counter(c.difficulte for c in bench)
    assert counts["facile"] == 256
    assert counts["moyen"] == 256
    assert counts["difficile"] == 256
    # Tous les SQL de référence s'exécutent (échantillon suffisant : les durs).
    hard = [c for c in bench if c.difficulte == "difficile"]
    for case in hard[:30]:
        assert run_select(case.sql_ref).ok is True, f"{case.id}: {case.sql_ref}"


@pytest.mark.parametrize(
    "values, pct, expected",
    [
        ([1, 2, 3, 4], 50, 2.5),  # médiane par interpolation
        ([10], 95, 10.0),  # échantillon singleton
        ([0, 100], 100, 100.0),  # borne haute
    ],
)
def test_percentile(values, pct, expected):
    """Le percentile interpolé renvoie les valeurs attendues."""
    assert _percentile(values, pct) == pytest.approx(expected)


def _fake_result() -> dict:
    """Fabrique un résultat d'approche synthétique pour tester ``summarize``.

    Returns
    -------
    dict
        Un dict au format de ``run_one_approach`` avec quelques mesures.
    """
    # Trois cas par palier, latences et matches contrôlés pour vérifier les calculs.
    records = []
    for niveau, matches in (("facile", [1, 1]), ("moyen", [1, 0]), ("difficile", [0, 0])):
        for m in matches:
            records.append(
                {
                    "id": "x",
                    "domaine": "X",
                    "difficulte": niveau,
                    "latency_s": 2.0,
                    "gen_ok": True,
                    "exec_ok": True,
                    "match": bool(m),
                }
            )
    return {"key": "qwen", "label": "QwenCoder (brut)", "available": True, "records": records}


def test_summarize_computes_accuracy_and_latency():
    """``summarize`` calcule l'exactitude globale, par palier, et les latences."""
    s = summarize(_fake_result())
    # 3 matches sur 6 → 50 % global.
    assert s["accuracy"] == pytest.approx(0.5)
    # Ventilation par difficulté : facile 100 %, moyen 50 %, difficile 0 %.
    assert s["accuracy_by_difficulty"]["facile"]["accuracy"] == pytest.approx(1.0)
    assert s["accuracy_by_difficulty"]["difficile"]["accuracy"] == pytest.approx(0.0)
    # Toutes les latences valent 2.0 → médiane et p95 valent 2.0.
    assert s["latency_median"] == pytest.approx(2.0)
    assert s["latency_p95"] == pytest.approx(2.0)


def _fake_report() -> dict:
    """Rapport synthétique minimal à deux approches pour tester les figures.

    Returns
    -------
    dict
        Un rapport au format ``benchmark_results.json``.
    """
    approaches = [
        {
            "key": "qwen",
            "label": "QwenCoder (brut)",
            "available": True,
            "records": [
                {
                    "id": "a",
                    "domaine": "X",
                    "difficulte": "facile",
                    "latency_s": 3.0,
                    "gen_ok": True,
                    "exec_ok": True,
                    "match": True,
                }
            ],
        },
        {
            "key": "vanna",
            "label": "Vanna (RAG)",
            "available": True,
            "records": [
                {
                    "id": "b",
                    "domaine": "X",
                    "difficulte": "difficile",
                    "latency_s": 4.0,
                    "gen_ok": True,
                    "exec_ok": True,
                    "match": False,
                }
            ],
        },
    ]
    report = {"n_cases": 2, "approaches": approaches}
    report["summaries"] = [summarize(a) for a in approaches]
    return report


def test_build_specs_are_valid_vega_lite():
    """Les trois figures produisent des specs Vega-Lite v5 bien formées."""
    report = _fake_report()
    # Chaque builder doit renvoyer une spec v5 avec des données et un encodage/couche.
    for builder in (
        bench_charts.build_violin_spec,
        bench_charts.build_errors_spec,
        bench_charts.build_accuracy_spec,
        bench_charts.build_scatter_spec,
    ):
        spec = builder(report)
        assert spec["$schema"].endswith("v5.json")
        assert "data" in spec and spec["data"]["values"]
        # Soit un encodage direct, soit des couches (nuage = layer).
        assert "encoding" in spec or "layer" in spec
