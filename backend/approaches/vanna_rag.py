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

# Paires question→SQL RICHES (mode « Vanna 2 »). Plus nombreuses et variées que
# TRAINING_PAIRS, elles couvrent value-filters, jointures, dates, HAVING : le RAG
# a ainsi de bons exemples à récupérer pour la plupart des familles de questions.
RICH_PAIRS: list[tuple[str, str]] = [
    (
        "Combien de factures sont impayées ?",
        "SELECT COUNT(*) AS n FROM factures WHERE statut = 'Impayée'",
    ),
    ("Nombre de patients par sexe.", "SELECT sexe, COUNT(*) AS n FROM patients GROUP BY sexe"),
    (
        "Nombre d'employés par catégorie.",
        "SELECT categorie, COUNT(*) AS n FROM employes GROUP BY categorie",
    ),
    (
        "Combien de patients ont le statut vital 'Décédé' ?",
        "SELECT COUNT(*) AS n FROM patients WHERE statut_vital = 'Décédé'",
    ),
    (
        "Quels médicaments sont sous leur seuil d'alerte de stock ?",
        "SELECT m.nom FROM stocks s JOIN medicaments m "
        "ON m.medicament_id = s.medicament_id WHERE s.quantite < s.seuil_alerte",
    ),
    (
        "Montant total encaissé par moyen de paiement.",
        "SELECT moyen, SUM(montant_eur) AS total FROM paiements GROUP BY moyen",
    ),
    (
        "Nombre d'équipements par statut.",
        "SELECT statut, COUNT(*) AS n FROM equipements GROUP BY statut",
    ),
    (
        "Combien d'essais cliniques sont au statut 'Ouvert' ?",
        "SELECT COUNT(*) AS n FROM essais_cliniques WHERE statut = 'Ouvert'",
    ),
    (
        "Nombre de diagnostics par stade global du cancer.",
        "SELECT stade_global, COUNT(*) AS n FROM diagnostics GROUP BY stade_global",
    ),
    (
        "Durée moyenne de séjour en jours par type de séjour.",
        "SELECT type_sejour, AVG(julianday(date_sortie) - julianday(date_entree)) AS duree "
        "FROM sejours GROUP BY type_sejour",
    ),
    (
        "Nombre de patients décédés par localisation de cancer.",
        "SELECT d.localisation, COUNT(DISTINCT p.patient_id) AS n FROM patients p "
        "JOIN diagnostics d ON d.patient_id = p.patient_id "
        "WHERE p.statut_vital = 'Décédé' GROUP BY d.localisation",
    ),
    (
        "Nombre de médicaments par classe thérapeutique.",
        "SELECT classe, COUNT(*) AS n FROM medicaments GROUP BY classe",
    ),
    (
        "Nombre de cures de chimiothérapie par médicament.",
        "SELECT m.nom, COUNT(*) AS n FROM cures_chimio c "
        "JOIN medicaments m ON m.medicament_id = c.medicament_id GROUP BY m.nom",
    ),
    (
        "Nombre de séances de radiothérapie par mois en 2026.",
        "SELECT strftime('%Y-%m', date) AS mois, COUNT(*) AS n FROM seances_radio "
        "WHERE date >= '2026-01-01' AND date < '2027-01-01' GROUP BY mois ORDER BY mois",
    ),
]


def _category_docs(db_path: object) -> list[str]:
    """Fabrique une doc RAG par colonne énumérée (les VALEURS possibles).

    C'est l'info décisive que reçoit le « bon prompt » de QwenCoder
    (``with_categories``) : on la donne AUSSI à Vanna 2 pour une comparaison à
    information égale. Ex. « factures.statut peut valoir : Payée, En attente,
    Partielle, Impayée. »

    Parameters
    ----------
    db_path : object
        Chemin de la base (passé à ``db.categorical_values``).

    Returns
    -------
    list[str]
        Une phrase de documentation par colonne énumérée.
    """
    docs: list[str] = []
    # Pour chaque table et colonne énumérée : une phrase listant ses valeurs.
    for table, cols in db.categorical_values(db_path).items():
        for col, values in cols.items():
            docs.append(f"{table}.{col} peut valoir : {', '.join(values)}.")
    return docs


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
    rich : bool
        Si vrai, entraîne un Vanna « bien nourri » (**Vanna 2**) : on lui donne la
        MÊME info décisive que le bon prompt de QwenCoder — les **valeurs
        énumérées** des colonnes en documentation — plus un large jeu de paires
        question→SQL. Sert à montrer qu'un RAG bien alimenté rattrape/dépasse
        (par opposition à **Vanna 1**, volontairement sous-entraîné).
    """

    name: str = "Vanna 1"

    def __init__(
        self,
        db_path: str | None = None,
        model: str = MODEL_SQL,
        persist_dir: str | None = None,
        rich: bool = False,
        self_correct: bool = True,
    ) -> None:
        """Instancie Vanna, le connecte à la base et l'entraîne si nécessaire."""
        # Ollama obligatoire (LLM + embeddings passent par lui).
        if not is_up():
            raise ApproachUnavailable("Serveur Ollama injoignable (`ollama serve`).")

        self.model = model
        self.db_path = db_path or db.DB_PATH
        self.rich = rich
        # Auto-correction par execution feedback : la MÊME arme que le bon prompt de
        # QwenCoder. Sans elle, Vanna perdait chaque SQL invalide (erreurs d'exécution
        # 31–46) ; avec elle, il réessaie une fois en voyant l'erreur SQLite.
        self.self_correct = self_correct
        if rich:
            self.name = "Vanna 2"
        # Index SÉPARÉ pour le mode riche (corpus différent) : on ne mélange pas
        # les deux entraînements. On sépare AUSSI par base : le DDL entraîné diffère
        # entre LIGHT et HEAVY (gros schéma), donc chaque base a son propre index —
        # sinon Vanna réutiliserait le schéma LIGHT sur la base HEAVY. La base par
        # défaut garde les noms historiques (index déjà entraîné, pas de re-train).
        base_dir = "vanna_chroma_plus" if rich else "vanna_chroma"
        stem = Path(self.db_path).stem
        default_dir = base_dir if stem == Path(db.DB_PATH).stem else f"{base_dir}_{stem}"
        persist = persist_dir or str(Path(self.db_path).parent / default_dir)

        # Construction paresseuse de la classe (peut lever ApproachUnavailable).
        local_vanna_cls = _make_vanna_class()
        # ``n_results`` borne le RAG au top-k récupéré. Vanna 2 en prend un peu plus
        # (10) pour mieux couvrir le schéma d'une jointure, sans exploser le contexte
        # (au-delà, la génération ralentit énormément pour un gain nul).
        self._vn = local_vanna_cls(
            config={
                "model": model,
                "ollama_host": OLLAMA_URL,
                "embedding_model": MODEL_EMBED,
                "path": persist,
                "n_results": 10 if rich else 6,
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

        # 2 bis) MODE RICHE (Vanna 2) : on ajoute les VALEURS énumérées des colonnes
        # en documentation — la même info décisive que le bon prompt de QwenCoder —
        # pour une comparaison à information égale (anti-erreur sémantique).
        if self.rich:
            for doc in _category_docs(self.db_path):
                self._vn.train(documentation=doc)

        # 3) Les paires question→SQL. Vanna 2 en reçoit beaucoup plus (RICH_PAIRS) :
        # un RAG bien alimenté a un bon exemple à récupérer pour la plupart des cas.
        pairs = TRAINING_PAIRS + RICH_PAIRS if self.rich else TRAINING_PAIRS
        for question, sql in pairs:
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
        notes = (
            "Vanna récupère (RAG) le schéma pertinent + le savoir métier appris, "
            "puis génère. Idéal quand le schéma est trop gros pour tenir dans un prompt."
        )

        # AUTO-CORRECTION (execution feedback) : on exécute le SQL en lecture seule ;
        # s'il est invalide, on redonne l'erreur SQLite à Vanna pour UN réessai. Même
        # mécanisme que le bon prompt de QwenCoder → comparaison à armes égales.
        if self.self_correct and sql:
            check = db.run_select(sql, max_rows=1)
            if not check.ok:
                repaired = self._repair(question, sql, check.error or "")
                if repaired:
                    sql = repaired
                    notes += " Auto-corrigé après une erreur d'exécution."

        return SQLGeneration(
            sql=sql,
            approach=self.name,
            model=self.model,
            latency_s=time.perf_counter() - started,
            raw=raw,
            notes=notes,
        )

    def _repair(self, question: str, bad_sql: str, error: str) -> str | None:
        """Tente une correction unique en redonnant l'erreur d'exécution à Vanna.

        On re-sollicite le pipeline RAG de Vanna avec la question d'origine enrichie
        du SQL fautif et du message d'erreur SQLite : le modèle voit ce qui a cassé
        et propose une requête corrigée (l'état de l'art 2025 en réduction d'erreurs).

        Parameters
        ----------
        question : str
            La question d'origine en langage naturel.
        bad_sql : str
            Le SQL invalide produit au premier essai.
        error : str
            Le message d'erreur renvoyé par SQLite.

        Returns
        -------
        str | None
            Le SQL corrigé (nettoyé) s'il s'exécute, sinon ``None``.
        """
        repair_q = (
            f"{question}\n\n"
            f"-- Ta requête précédente a échoué à l'exécution :\n{bad_sql}\n"
            f"-- Erreur SQLite : {error}\n"
            f"-- Renvoie UNIQUEMENT une requête SQL SELECT corrigée."
        )
        try:
            raw = self._vn.generate_sql(question=repair_q, allow_llm_to_see_data=False)
        except Exception:  # réseau, parsing : on renonce proprement à la réparation
            return None
        fixed = clean_sql(raw)
        # On ne garde la correction que si elle s'exécute vraiment (sinon on garde
        # le SQL d'origine : au moins il est explicite dans la sortie).
        if fixed and db.run_select(fixed, max_rows=1).ok:
            return fixed
        return None
