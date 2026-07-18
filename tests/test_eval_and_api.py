"""
test_eval_and_api.py — Tests de la métrique d'éval et des routes API sans réseau.

Couvre : la logique d'exactitude d'exécution (comparaison ensembliste / ordonnée,
tolérance flottante), la validité du jeu de référence, et les endpoints de l'API
qui ne nécessitent pas Ollama (schéma, exemples, santé).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend import server
from backend.approaches.base import SQLGeneration
from backend.db import run_select
from backend.server import app
from eval.execution_match import compare_results, evaluate_sql
from eval.golden import GOLDEN, GOLDEN_HARD

# Client de test FastAPI partagé par les tests d'API (pas de serveur à lancer).
client = TestClient(app)


class _FakeApproach:
    """Approche factice qui renvoie un SQL fixe — permet de tester l'API sans Ollama."""

    def generate(self, question: str) -> SQLGeneration:
        """Renvoie toujours un SELECT valide, indépendamment de la question."""
        # SQL trivial mais exécutable : on teste le CÂBLAGE (génération→exécution),
        # pas la qualité d'un modèle.
        return SQLGeneration(
            sql="SELECT COUNT(*) AS n FROM services",
            approach="Fake",
            model="fake",
            raw="SELECT COUNT(*) AS n FROM services",
            notes="approche factice de test",
        )


def test_golden_reference_sql_all_execute(db_path):
    """Tous les SQL de référence (facile ET difficile) s'exécutent sans erreur."""
    # Un jeu de référence cassé invaliderait toute l'éval : on protège les deux.
    for case in GOLDEN + GOLDEN_HARD:
        result = run_select(case.sql_ref)
        assert result.ok is True, f"{case.id}: {result.error}"


def test_evaluate_sql_self_match_is_true(db_path):
    """Comparer une requête à elle-même donne toujours un match."""
    # Propriété de base (réflexivité) de la métrique d'exécution.
    for case in GOLDEN[:3]:
        verdict = evaluate_sql(case.sql_ref, case.sql_ref, ordered=case.ordered)
        assert verdict.match is True


def test_compare_results_is_order_insensitive_by_default(db_path):
    """Deux requêtes équivalentes à l'ordre près matchent en mode ensembliste."""
    # Même contenu, ORDER BY différent -> doit matcher (ordered=False).
    a = run_select("SELECT categorie, COUNT(*) AS n FROM employes GROUP BY categorie ORDER BY n")
    b = run_select(
        "SELECT categorie, COUNT(*) AS n FROM employes GROUP BY categorie ORDER BY categorie"
    )
    assert compare_results(a, b, ordered=False).match is True


def test_compare_results_detects_wrong_answer(db_path):
    """Un résultat sémantiquement faux est bien détecté comme non-match."""
    # 'Impayée' vs 'En attente' : nombres différents -> non-match attendu.
    good = run_select("SELECT COUNT(*) AS n FROM factures WHERE statut = 'Impayée'")
    wrong = run_select("SELECT COUNT(*) AS n FROM factures WHERE statut = 'En attente'")
    assert compare_results(wrong, good).match is False


def test_api_schema_endpoint(db_path):
    """/api/schema renvoie la liste des tables et un DDL non vide."""
    resp = client.get("/api/schema")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tables"]) >= 20
    assert "CREATE TABLE" in data["ddl"]


def test_api_samples_endpoint():
    """/api/samples renvoie des questions d'exemple groupées par domaine."""
    resp = client.get("/api/samples")
    assert resp.status_code == 200
    samples = resp.json()["samples"]
    assert len(samples) >= 10
    # Chaque exemple porte un domaine et une question.
    assert all("q" in s and "domaine" in s for s in samples)


def test_api_health_endpoint(db_path):
    """/api/health expose l'état d'Ollama, des approches et le nombre de tables."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    # Ces clés pilotent l'affichage du front : leur présence est un contrat.
    assert "ollama_up" in data
    assert "approaches" in data
    assert data["db_tables"] >= 20


def test_api_query_generate_and_execute(db_path, monkeypatch):
    """/api/query génère (approche mockée) PUIS exécute réellement le SQL."""
    # On remplace la fabrique d'approche par une factice : plus besoin d'Ollama,
    # on valide le câblage génération → exécution → réponse JSON.
    monkeypatch.setattr(server, "_get_approach", lambda key: _FakeApproach())
    resp = client.post("/api/query", json={"question": "peu importe", "approach": "qwen"})
    assert resp.status_code == 200
    block = resp.json()["results"][0]
    # Le SQL factice doit être exécuté et renvoyer le nombre de services (12).
    assert block["exec_ok"] is True
    assert block["columns"] == ["n"]
    assert block["rows"][0][0] >= 10


def test_api_query_rejects_empty_question():
    """/api/query refuse une question vide (garde-fou de validation Pydantic)."""
    # min_length=1 => 422 Unprocessable Entity attendu.
    resp = client.post("/api/query", json={"question": "", "approach": "qwen"})
    assert resp.status_code == 422
