"""
langchain_sql.py — Approche 1 : la « toolbox connue », LangChain.

LangChain est le framework text2sql le plus répandu. On l'utilise ici « comme
prévu » : ``SQLDatabase`` introspecte la base et fournit le schéma, et une
chaîne LCEL (prompt → ``ChatOllama`` → parseur) génère le SQL, branchée sur
notre LLM local. Intérêt pédagogique : montrer que le framework fait, en
quelques lignes, ce que l'approche « brute » fait à la main — au prix d'une
dépendance lourde et d'un peu de magie cachée.

Compatibilité versions : l'API historique ``create_sql_query_chain`` a disparu
de LangChain 1.x (le paquet ``community`` est en fin de vie). On tente donc
d'abord l'import classique (LangChain 0.2/0.3) ; à défaut, on reconstruit une
chaîne équivalente avec les primitives officielles encore disponibles. Dans les
deux cas, c'est bien la *toolbox LangChain* qui travaille.

Dépendances : ``langchain``, ``langchain-community``, ``langchain-ollama``.
Absentes → l'approche se déclare indisponible proprement.
"""

from __future__ import annotations

import time

from .. import db
from ..llm import MODEL_SQL, is_up
from .base import ApproachUnavailable, SQLGeneration, clean_sql

# Gabarit de prompt de secours, calqué sur celui de ``create_sql_query_chain`` :
# on donne le dialecte, le schéma des tables, une limite de lignes, et on exige
# une requête nue. Utilisé uniquement quand l'API historique est absente.
_FALLBACK_TEMPLATE = """Tu es un expert {dialect}. Étant donné une question, écris \
une requête SQL {dialect} syntaxiquement correcte qui y répond. \
Sauf demande explicite, limite le résultat à {top_k} lignes.
Utilise UNIQUEMENT les tables et colonnes ci-dessous. Réponds par la requête SQL SEULE, \
sans Markdown, sans explication, sans point-virgule final.

Schéma des tables :
{table_info}

Question : {input}
Requête SQL :"""


class LangChainApproach:
    """Génère du SQL avec la toolbox LangChain (``SQLDatabase`` + LCEL) sur Ollama.

    Parameters
    ----------
    db_path : str | None
        Chemin de la base (défaut : base de la démo).
    model : str
        Tag Ollama passé à ``ChatOllama``.
    top_k : int
        Limite de lignes suggérée au modèle dans le prompt.
    """

    name: str = "LangChain (toolbox connue)"

    def __init__(
        self, db_path: str | None = None, model: str = MODEL_SQL, top_k: int = 200
    ) -> None:
        """Construit la chaîne LangChain ; échoue tôt si dépendances/serveur absents."""
        # Import paresseux : on n'impose pas LangChain à qui n'utilise que
        # l'approche brute. Tout échec d'import devient une indisponibilité claire.
        try:
            from langchain_community.utilities import SQLDatabase
            from langchain_ollama import ChatOllama
        except Exception as exc:  # ImportError ou incompatibilité de version
            raise ApproachUnavailable(
                "LangChain non installé. `pip install langchain "
                "langchain-community langchain-ollama`."
            ) from exc

        # Sans serveur Ollama, le LLM local est injoignable : on s'arrête net.
        if not is_up():
            raise ApproachUnavailable("Serveur Ollama injoignable (`ollama serve`).")

        self.model = model
        self.top_k = top_k
        self.db_path = db_path or db.DB_PATH
        # ``SQLDatabase`` lit le schéma via SQLAlchemy — c'est LA brique
        # d'introspection de la toolbox LangChain.
        self._sqldb = SQLDatabase.from_uri(db.sqlalchemy_url(self.db_path))
        # Température 0 pour du SQL déterministe, comme dans l'approche brute.
        self._llm = ChatOllama(model=model, temperature=0.0)
        # Construit la chaîne : API historique si dispo, sinon reconstruction.
        self._chain, self._how = self._build_chain()

    def _build_chain(self):
        """Assemble la chaîne de génération, selon la version de LangChain installée.

        Returns
        -------
        (callable, str)
            Un couple ``(chaine, description)`` : la chaîne expose ``.invoke``
            comme les objets LCEL ; la description dit quelle voie a été prise
            (utile pour la note pédagogique).
        """
        # Voie 1 — API historique ``create_sql_query_chain`` (LangChain 0.2/0.3).
        try:
            from langchain.chains import create_sql_query_chain

            chain = create_sql_query_chain(self._llm, self._sqldb, k=self.top_k)
            return chain, "create_sql_query_chain (API historique)"
        except Exception:
            # L'API a disparu (LangChain 1.x) : on reconstruit à la main.
            pass

        # Voie 2 — reconstruction LCEL avec les primitives officielles.
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(_FALLBACK_TEMPLATE)

        # Le schéma complet des tables, fourni par SQLDatabase (même source que
        # l'API historique). On le calcule une fois : il est stable.
        table_info = self._sqldb.get_table_info()

        def _fill(inputs: dict) -> dict:
            """Injecte dialecte, schéma et limite autour de la question de l'utilisateur."""
            # On complète le dict d'entrée avec les variables du gabarit.
            return {
                "input": inputs["question"],
                "dialect": self._sqldb.dialect,
                "table_info": table_info,
                "top_k": self.top_k,
            }

        # Pipeline LCEL : remplissage → prompt → LLM → texte brut.
        chain = _fill | prompt | self._llm | StrOutputParser()
        return chain, "reconstruction LCEL (SQLDatabase + ChatOllama)"

    @classmethod
    def available(cls) -> bool:
        """Vrai si les primitives LangChain sont importables ET si Ollama répond."""
        try:
            import langchain_community.utilities  # noqa: F401  (test d'import)
            import langchain_ollama  # noqa: F401
        except Exception:
            return False
        return is_up()

    def generate(self, question: str) -> SQLGeneration:
        """Génère le SQL via la chaîne LangChain.

        Parameters
        ----------
        question : str
            Question en langage naturel.

        Returns
        -------
        SQLGeneration
            SQL nettoyé + latence ; ``ok=False`` si la chaîne échoue.
        """
        started = time.perf_counter()
        try:
            # ``invoke`` déclenche prompt → LLM → SQL. LangChain préfixe parfois
            # « SQLQuery: » : notre ``clean_sql`` s'en charge.
            raw = self._chain.invoke({"question": question})
        except Exception as exc:  # erreur réseau, parsing, etc.
            return SQLGeneration(
                sql="",
                approach=self.name,
                model=self.model,
                latency_s=time.perf_counter() - started,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                notes=f"Toolbox LangChain — {self._how}.",
            )

        text = raw if isinstance(raw, str) else str(raw)
        return SQLGeneration(
            sql=clean_sql(text),
            approach=self.name,
            model=self.model,
            latency_s=time.perf_counter() - started,
            raw=text,
            notes=f"Toolbox LangChain ({self._how}) : SQLDatabase introspecte le "
            "schéma et prompte le LLM pour toi — concis, mais plus « boîte noire » "
            "que l'approche brute.",
        )
