"""
server.py — API FastAPI de la démo text2sql.

Rôle : exposer, derrière une petite API JSON, tout ce dont le front a besoin :
  - l'état de santé (Ollama up ? quelles approches disponibles ?) ;
  - le schéma de la base (pour l'afficher et expliquer le « comment ») ;
  - des questions d'exemple prêtes à cliquer ;
  - la génération de SQL par une approche (ou TOUTES, pour comparer) ;
  - l'exécution SÉCURISÉE (lecture seule) de la requête ;
  - la génération d'une figure par Gemma.

Le point pédagogique clé — expliquer à des collègues *comment on fait* — guide
l'API : on renvoie toujours le SQL généré, la sortie brute du modèle, la latence,
et une note sur l'approche, pas seulement le résultat final.
"""

from __future__ import annotations

import logging
from functools import cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, figures
from .approaches.base import ApproachUnavailable, SQLGeneration
from .approaches.langchain_sql import LangChainApproach
from .approaches.qwen_ollama import QwenOllamaApproach
from .approaches.vanna_rag import VannaApproach
from .llm import MODEL_FIGURE, MODEL_SQL, is_up, list_models

logger = logging.getLogger(__name__)

# Répertoire du front statique, à la racine du projet (../frontend).
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Registre des approches : identifiant stable -> classe. L'ordre est celui de la
# progression pédagogique (du plus brut au plus outillé).
APPROACHES: dict[str, type] = {
    "qwen": QwenOllamaApproach,
    "langchain": LangChainApproach,
    "vanna": VannaApproach,
}

# Questions d'exemple couvrant tous les domaines de la base : elles servent
# d'amorce dans le front et de vitrine de ce que le text2sql sait faire.
SAMPLE_QUESTIONS: list[dict] = [
    {
        "domaine": "Médical",
        "q": "Combien de patients par localisation de cancer, du plus fréquent au plus rare ?",
    },
    {"domaine": "Médical", "q": "Nombre de patients par stade global du cancer."},
    {
        "domaine": "Médical",
        "q": "Quels sont les 5 effets indésirables les plus fréquents des cures de chimiothérapie ?",  # noqa: E501
    },
    {"domaine": "Comptabilité", "q": "Chiffre d'affaires encaissé par mois en 2026."},
    {
        "domaine": "Comptabilité",
        "q": "Combien de factures sont impayées et pour quel montant total ?",
    },
    {"domaine": "RH", "q": "Masse salariale mensuelle par service pour les contrats en cours."},
    {"domaine": "RH", "q": "Nombre d'employés par catégorie et par service."},
    {"domaine": "Pharmacie", "q": "Quels médicaments sont sous leur seuil d'alerte de stock ?"},
    {"domaine": "Pharmacie", "q": "Top 10 des médicaments les plus chers à l'unité."},
    {"domaine": "Matériel", "q": "Coût total des maintenances par équipement."},
    {
        "domaine": "Matériel",
        "q": "Quels équipements sont actuellement en maintenance ou hors service ?",
    },
    {"domaine": "Recherche", "q": "Combien de patients inclus par essai clinique et par bras ?"},
    {"domaine": "Activité", "q": "Nombre de séances de radiothérapie par mois en 2026."},
]


# --------------------------------------------------------------------------- #
# Modèles de requête/réponse (Pydantic) — le contrat de l'API                 #
# --------------------------------------------------------------------------- #


class QueryRequest(BaseModel):
    """Corps d'une demande de traduction question -> SQL puis exécution."""

    # ``max_length`` borne l'entrée : garde-fou anti-abus (prompt géant) et
    # cohérent avec une vraie question métier.
    question: str = Field(
        ..., min_length=1, max_length=2000, description="Question en langage naturel."
    )
    approach: str = Field("qwen", description="Clé d'approche ou 'toutes'.")
    execute: bool = Field(True, description="Exécuter le SQL généré ?")
    max_rows: int = Field(1000, ge=1, le=5000, description="Plafond de lignes.")


class FigureRequest(BaseModel):
    """Corps d'une demande de figure sur un résultat déjà obtenu."""

    question: str = Field(..., description="Question d'origine.")
    columns: list[str] = Field(..., description="Colonnes du résultat.")
    rows: list[list] = Field(..., description="Lignes du résultat.")


# --------------------------------------------------------------------------- #
# Fabrique d'approches (avec cache)                                           #
# --------------------------------------------------------------------------- #


@cache
def _get_approach(key: str):
    """Instancie (et met en cache) une approche par sa clé.

    Le cache évite de reconstruire à chaque requête des objets coûteux (Vanna
    ré-entraîne son index, LangChain réintrospecte le schéma).

    Parameters
    ----------
    key : str
        Clé de l'approche dans ``APPROACHES``.

    Returns
    -------
    object
        L'instance d'approche prête à générer du SQL.

    Raises
    ------
    KeyError
        Si la clé est inconnue.
    ApproachUnavailable
        Si l'approche ne peut pas s'initialiser (dépendance/serveur absents).
    """
    # Clé inconnue -> KeyError explicite (l'appelant renverra un 4xx logique).
    cls = APPROACHES[key]
    # La construction peut lever ApproachUnavailable : on laisse remonter pour
    # que l'endpoint la formate en réponse d'erreur lisible.
    return cls()


def _run_one(key: str, request: QueryRequest) -> dict:
    """Exécute une approche unique : génération + exécution optionnelle.

    Parameters
    ----------
    key : str
        Clé d'approche.
    request : QueryRequest
        Paramètres de la demande.

    Returns
    -------
    dict
        Bloc résultat sérialisable : SQL, métadonnées de génération, et
        (si demandé) colonnes/lignes exécutées ou l'erreur SQL.
    """
    # 1) Instanciation (peut échouer proprement si l'approche est indisponible).
    try:
        approach = _get_approach(key)
    except ApproachUnavailable as exc:
        return {"approach_key": key, "available": False, "error": str(exc)}
    except KeyError:
        return {"approach_key": key, "available": False, "error": "Approche inconnue."}

    # 2) Génération du SQL.
    gen: SQLGeneration = approach.generate(request.question)
    block: dict = {
        "approach_key": key,
        "available": True,
        "approach": gen.approach,
        "model": gen.model,
        "sql": gen.sql,
        "raw": gen.raw,
        "latency_s": round(gen.latency_s, 3),
        "notes": gen.notes,
        "gen_ok": gen.ok,
        "gen_error": gen.error,
    }

    # 3) Exécution sécurisée si demandée et si un SQL a bien été produit.
    if request.execute and gen.ok and gen.sql:
        result = db.run_select(gen.sql, max_rows=request.max_rows)
        block["exec_ok"] = result.ok
        block["exec_error"] = result.error
        block["columns"] = result.columns
        block["rows"] = result.rows
        block["row_count"] = result.row_count
        block["truncated"] = result.truncated
    return block


# --------------------------------------------------------------------------- #
# Application                                                                  #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="Text2SQL — Institut de Cancérologie",
    description="Démo pédagogique : traduire le langage naturel en SQL, "
    "de trois façons, 100 % en local via Ollama.",
    version="1.0.0",
)


@app.get("/api/health")
def health() -> dict:
    """État de santé : serveur Ollama, modèles, disponibilité des approches.

    Returns
    -------
    dict
        Drapeaux d'état consommés par le front pour griser ce qui n'est pas prêt.
    """
    # Disponibilité par approche : on interroge la méthode de classe ``available``
    # (test léger : imports + ping Ollama) sans instancier l'objet coûteux.
    availability = {
        key: bool(getattr(cls, "available", lambda: False)()) for key, cls in APPROACHES.items()
    }
    return {
        "ollama_up": is_up(),
        "models_installed": list_models(),
        "model_sql": MODEL_SQL,
        "model_figure": MODEL_FIGURE,
        "approaches": availability,
        "db_tables": len(db.list_tables()),
    }


@app.get("/api/schema")
def schema() -> dict:
    """Schéma de la base : liste des tables + DDL complet (pour l'affichage)."""
    # Le front montre ce contexte pour expliquer le « comment » : c'est ce même
    # schéma que reçoivent les modèles.
    return {
        "tables": db.list_tables(),
        "ddl": db.schema_ddl(sample_rows=0),
    }


@app.get("/api/samples")
def samples() -> dict:
    """Renvoie la liste des questions d'exemple, groupées par domaine."""
    return {"samples": SAMPLE_QUESTIONS}


@app.post("/api/query")
def query(request: QueryRequest) -> dict:
    """Traduit la question en SQL (une approche ou toutes) puis l'exécute.

    Parameters
    ----------
    request : QueryRequest
        Question, approche visée, et options d'exécution.

    Returns
    -------
    dict
        ``{"results": [...]}`` — un bloc par approche exécutée. Le front les
        affiche côte à côte pour la comparaison pédagogique.
    """
    # « toutes » : on lance chaque approche pour permettre la comparaison. Sinon
    # une seule. On filtre les clés inconnues en amont.
    keys = list(APPROACHES) if request.approach == "toutes" else [request.approach]
    results = [_run_one(k, request) for k in keys]
    return {"question": request.question, "results": results}


@app.post("/api/figure")
def figure(request: FigureRequest) -> dict:
    """Génère une figure (choisie par Gemma) à partir d'un résultat.

    Parameters
    ----------
    request : FigureRequest
        Question d'origine + colonnes + lignes du résultat.

    Returns
    -------
    dict
        Spec Vega-Lite + choix de Gemma, ou un message expliquant l'absence.
    """
    result = figures.make_figure(request.question, request.columns, request.rows)
    return {
        "ok": result.ok,
        # Le front rend cette spec avec vega-embed ; None si pas de figure.
        "vega_spec": result.vega_spec,
        "spec": result.spec,
        "error": result.error,
        "model": result.model,
    }


@app.get("/")
def index() -> FileResponse:
    """Sert la page d'accueil du front."""
    return FileResponse(FRONTEND_DIR / "index.html")


# Montage des fichiers statiques (JS, CSS) sous /static. On le fait en dernier
# pour ne pas masquer les routes /api ci-dessus.
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
