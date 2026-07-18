"""
vanna_rag.py — Approche 3 : Vanna AI (RAG entraîné sur le schéma).

Vanna change de paradigme : au lieu de coller TOUT le schéma dans le prompt à
chaque question, on « entraîne » Vanna une fois (DDL, documentation métier,
paires question→SQL exemples). Ces éléments sont vectorisés dans ChromaDB. À
l'exécution, Vanna récupère (RAG) uniquement les morceaux pertinents et les
donne au LLM. Avantage décisif sur les grosses bases : le contexte reste petit
et ciblé, et l'on peut injecter du savoir métier (« CA = somme des paiements »).

Stack locale : LLM ``qwen2.5-coder`` via Ollama + vecteurs ChromaDB + embeddings
``nomic-embed-text``. Aucune donnée ne sort de la machine.

Dépendances : ``vanna``, ``chromadb``. Absentes → approche indisponible.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .. import db
from ..llm import MODEL_EMBED, MODEL_SQL, OLLAMA_URL, is_up
from .base import ApproachUnavailable, SQLGeneration, clean_sql

# Logger de module : reçoit notamment les logs verbeux redirigés de Vanna.
logger = logging.getLogger(__name__)

# Paires question→SQL servant de few-shot RAG. Elles enseignent à Vanna le style
# de la maison (jointures fréquentes, vocabulaire métier) sans surcharger chaque
# prompt : elles ne remontent que si la question s'en rapproche sémantiquement.
TRAINING_PAIRS: list[tuple[str, str]] = [
    (
        "Combien de patients par localisation de cancer ?",
        "SELECT localisation, COUNT(DISTINCT patient_id) AS nb_patients "
        "FROM diagnostics GROUP BY localisation ORDER BY nb_patients DESC",
    ),
    (
        "Quel est le chiffre d'affaires encaissé par mois en 2026 ?",
        "SELECT strftime('%Y-%m', date) AS mois, SUM(montant_eur) AS ca "
        "FROM paiements WHERE date >= '2026-01-01' GROUP BY mois ORDER BY mois",
    ),
    (
        "Quels médicaments sont sous le seuil d'alerte de stock ?",
        "SELECT m.nom, s.quantite, s.seuil_alerte FROM stocks s "
        "JOIN medicaments m ON m.medicament_id = s.medicament_id "
        "WHERE s.quantite < s.seuil_alerte ORDER BY s.quantite",
    ),
    (
        "Masse salariale mensuelle par service.",
        "SELECT se.nom AS service, SUM(c.salaire_brut_mensuel) AS masse_salariale "
        "FROM contrats c JOIN employes e ON e.employe_id = c.employe_id "
        "JOIN services se ON se.service_id = e.service_id "
        "WHERE c.date_fin IS NULL GROUP BY se.nom ORDER BY masse_salariale DESC",
    ),
]

# Documentation métier : du savoir qu'aucun schéma ne capture, mais qui guide le
# LLM (définitions d'indicateurs, conventions). C'est LA valeur ajoutée du RAG.
BUSINESS_DOCS: list[str] = [
    "Le chiffre d'affaires encaissé correspond à la somme de paiements.montant_eur.",
    "Un stock est en alerte quand stocks.quantite < stocks.seuil_alerte.",
    "Un contrat en cours a contrats.date_fin IS NULL.",
    "Le statut vital d'un patient est dans patients.statut_vital "
    "('Vivant', 'En rémission', 'Décédé').",
    "Le stade global d'un cancer (I à IV) est dans diagnostics.stade_global ; "
    "le stade TNM détaillé est dans diagnostics.stade_tnm.",
]


def _make_vanna_class():
    """Construit dynamiquement la classe Vanna (Ollama + ChromaDB).

    On assemble la classe à l'intérieur d'une fonction pour que les imports
    lourds (``vanna``, ``chromadb``) restent paresseux : ils ne sont tentés que
    si l'on instancie réellement cette approche.

    Returns
    -------
    type
        Une sous-classe combinant le store vectoriel ChromaDB et le LLM Ollama.

    Raises
    ------
    ApproachUnavailable
        Si ``vanna`` / ``chromadb`` ne sont pas installés.
    """
    try:
        from vanna.chromadb import ChromaDB_VectorStore
        from vanna.ollama import Ollama
    except Exception as exc:  # ImportError ou version incompatible
        raise ApproachUnavailable(
            "Vanna non installé. `pip install 'vanna[chromadb,ollama]'`."
        ) from exc

    class LocalVanna(ChromaDB_VectorStore, Ollama):
        """Vanna 100 % local : vecteurs ChromaDB + génération Ollama.

        Le double héritage est le patron officiel de Vanna : un mixin pour le
        stockage vectoriel, un mixin pour le LLM. On câble les deux sur des
        briques locales.
        """

        def __init__(self, config: dict | None = None) -> None:
            """Initialise les deux mixins avec la même configuration locale."""
            # ChromaDB gère l'index vectoriel (persisté sur disque) ; Ollama gère
            # la génération. Les deux __init__ partagent le dict de config.
            ChromaDB_VectorStore.__init__(self, config=config)
            Ollama.__init__(self, config=config)

        def log(self, message: str, title: str = "Info") -> None:
            """Redirige les logs verbeux de Vanna vers le logger (niveau DEBUG).

            Par défaut, Vanna imprime le prompt complet et la réponse sur stdout,
            ce qui spamme la console du serveur. On route tout vers ``logging``
            en DEBUG : silencieux par défaut, mais récupérable si besoin.

            Parameters
            ----------
            message : str
                Le message de log émis par Vanna.
            title : str
                Le titre/catégorie fourni par Vanna.
            """
            logger.debug("[vanna] %s: %s", title, message)

    return LocalVanna


class VannaApproach:
    """Approche RAG : Vanna entraîné une fois, interrogé ensuite.

    Parameters
    ----------
    db_path : str | None
        Chemin de la base (défaut : base de la démo).
    model : str
        LLM Ollama de génération (défaut : ``qwen2.5-coder``).
    persist_dir : str | None
        Dossier de persistance ChromaDB. Réutilisé entre lancements pour éviter
        de ré-entraîner à chaque démarrage.
    """

    name: str = "Vanna AI (RAG)"

    def __init__(
        self,
        db_path: str | None = None,
        model: str = MODEL_SQL,
        persist_dir: str | None = None,
    ) -> None:
        """Instancie Vanna, le connecte à la base et l'entraîne si nécessaire."""
        # Ollama obligatoire (LLM + embeddings passent par lui).
        if not is_up():
            raise ApproachUnavailable("Serveur Ollama injoignable (`ollama serve`).")

        self.model = model
        self.db_path = db_path or db.DB_PATH
        # Persistance du vector store à côté de la base pour la réutiliser.
        persist = persist_dir or str(Path(self.db_path).parent / "vanna_chroma")

        # Construction paresseuse de la classe (peut lever ApproachUnavailable).
        local_vanna_cls = _make_vanna_class()
        # Config Vanna : quel modèle Ollama, où pointe Ollama, quels embeddings,
        # et où persister l'index. ``n_results`` borne le RAG au top-k pertinent.
        self._vn = local_vanna_cls(
            config={
                "model": model,
                "ollama_host": OLLAMA_URL,
                "embedding_model": MODEL_EMBED,
                "path": persist,
                "n_results": 6,
            }
        )
        # Connexion à la base pour l'introspection interne de Vanna.
        self._vn.connect_to_sqlite(str(self.db_path))
        # Entraînement idempotent : si l'index est vide, on l'alimente.
        self._train_if_needed()

    @classmethod
    def available(cls) -> bool:
        """Vrai si ``vanna`` + ``chromadb`` sont importables ET Ollama répond."""
        try:
            import chromadb  # noqa: F401
            import vanna  # noqa: F401
        except Exception:
            return False
        return is_up()

    def _train_if_needed(self) -> None:
        """Alimente l'index RAG (DDL + docs + paires) s'il est vide.

        On évite de ré-entraîner à chaque démarrage : si Vanna a déjà des données
        d'entraînement persistées, on ne fait rien. Sinon, on injecte le DDL de
        chaque table, la documentation métier, puis les paires question→SQL.
        """
        try:
            existing = self._vn.get_training_data()
            # ``get_training_data`` renvoie un DataFrame ; non-vide => déjà entraîné.
            if existing is not None and len(existing) > 0:
                return
        except Exception:
            # En cas de doute (store neuf), on entraîne : c'est idempotent côté sens.
            pass

        # 1) Le DDL table par table : Vanna vectorise chaque définition.
        for table in db.list_tables(self.db_path):
            ddl = db.schema_ddl(self.db_path).split("CREATE TABLE " + table, 1)
            # On ré-extrait proprement le bloc DDL de la table courante.
            block = (
                "CREATE TABLE " + table + ddl[1].split("CREATE TABLE", 1)[0] if len(ddl) > 1 else ""
            )
            if block:
                self._vn.train(ddl=block)

        # 2) La documentation métier (définitions d'indicateurs, conventions).
        for doc in BUSINESS_DOCS:
            self._vn.train(documentation=doc)

        # 3) Les paires question→SQL de référence (few-shot récupérable).
        for question, sql in TRAINING_PAIRS:
            self._vn.train(question=question, sql=sql)

    def generate(self, question: str) -> SQLGeneration:
        """Génère le SQL via le pipeline RAG de Vanna.

        Parameters
        ----------
        question : str
            Question en langage naturel.

        Returns
        -------
        SQLGeneration
            SQL nettoyé + latence ; ``ok=False`` si Vanna échoue.
        """
        started = time.perf_counter()
        try:
            # ``generate_sql`` fait tout le RAG : récupération du contexte
            # pertinent (DDL + docs + exemples proches) puis génération LLM.
            raw = self._vn.generate_sql(question=question, allow_llm_to_see_data=False)
        except Exception as exc:  # réseau, embeddings, parsing
            return SQLGeneration(
                sql="",
                approach=self.name,
                model=self.model,
                latency_s=time.perf_counter() - started,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                notes="RAG Vanna (ChromaDB + Ollama).",
            )

        sql = clean_sql(raw)
        return SQLGeneration(
            sql=sql,
            approach=self.name,
            model=self.model,
            latency_s=time.perf_counter() - started,
            raw=raw,
            notes="Vanna récupère (RAG) le schéma pertinent + le savoir métier "
            "appris, puis génère. Idéal quand le schéma est trop gros pour tenir "
            "dans un prompt.",
        )
