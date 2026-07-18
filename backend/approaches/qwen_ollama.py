"""
qwen_ollama.py — Approche 2 : QwenCoder « brut », servi par Ollama.

L'approche la plus transparente et la plus pédagogique : AUCUN framework. On
construit nous-mêmes le prompt (schéma + consignes + question), on appelle
``qwen2.5-coder`` via notre petit client Ollama, et on nettoie la sortie. C'est
exactement ce que font les frameworks sous le capot, mais visible ligne à ligne.

Forces : contrôle total, zéro dépendance lourde, on voit tout.
Limites : c'est à nous de gérer le schéma, le few-shot, les dialectes SQL.
"""

from __future__ import annotations

import time

from .. import db
from ..llm import MODEL_SQL, chat, is_up
from .base import ApproachUnavailable, SQLGeneration, clean_sql

# Consigne système : on cadre fermement le modèle pour qu'il rende du SQLite
# valide, en lecture seule, sans bavardage. Le ton impératif limite les
# préambules (« Bien sûr, voici... ») qui polluent l'extraction.
SYSTEM_PROMPT = """Tu es un expert SQL. Tu traduis des questions en français \
en requêtes SQL pour SQLite.
Règles STRICTES :
- Réponds UNIQUEMENT par la requête SQL, sans explication, sans Markdown, sans point-virgule final.
- Utilise exclusivement les tables et colonnes du schéma fourni.
- Génère du SQL valide pour SQLite (fonctions date : strftime, etc.).
- Requêtes en LECTURE SEULE (SELECT). Jamais d'INSERT/UPDATE/DELETE/DROP.
- Quand la question implique un agrégat, utilise GROUP BY et des alias lisibles.
- Limite à 200 lignes maximum sauf si la question demande explicitement tout.
"""


class QwenOllamaApproach:
    """Génère du SQL par prompt direct sur ``qwen2.5-coder`` via Ollama.

    Parameters
    ----------
    db_path : str | None
        Chemin de la base (défaut : base de la démo).
    model : str
        Tag Ollama du modèle de code (défaut : ``qwen2.5-coder:latest``).
    sample_rows : int
        Nombre de lignes-exemples annexées au schéma dans le prompt. Quelques
        exemples aident le modèle à deviner les valeurs de filtres.
    self_correct : bool
        Si vrai, valide le SQL généré en l'exécutant (lecture seule) et, en cas
        d'erreur SQL, effectue UN réessai en renvoyant l'erreur au modèle
        (« execution feedback », bonne pratique de l'état de l'art).
    """

    name: str = "QwenCoder (Ollama, brut)"

    def __init__(
        self,
        db_path: str | None = None,
        model: str = MODEL_SQL,
        sample_rows: int = 2,
        self_correct: bool = True,
    ) -> None:
        """Initialise l'approche et pré-calcule le schéma injecté au prompt."""
        # Sans serveur Ollama, cette approche ne peut rien faire : on échoue tôt
        # avec un message clair plutôt qu'à la première requête.
        if not is_up():
            raise ApproachUnavailable(
                f"Serveur Ollama injoignable. Lance `ollama serve` puis `ollama pull {model}`."
            )
        self.model = model
        self.db_path = db_path or db.DB_PATH
        self.self_correct = self_correct
        # Le schéma inclut les VALEURS énumérées (with_categories) : c'est le
        # meilleur rempart contre les erreurs sémantiques (filtrer sur la bonne
        # valeur, ex. statut = 'Impayée' et non 'En attente'). Stable → calculé une fois.
        self.schema = db.schema_ddl(self.db_path, sample_rows=sample_rows, with_categories=True)

    @classmethod
    def available(cls) -> bool:
        """Vrai si le serveur Ollama répond — condition nécessaire de l'approche."""
        return is_up()

    def _build_messages(self, question: str) -> list[dict]:
        """Assemble les messages system/user injectés au modèle.

        Parameters
        ----------
        question : str
            Question de l'utilisateur en langage naturel.

        Returns
        -------
        list[dict]
            Deux messages : la consigne système et le schéma + la question.
        """
        # On colle le schéma juste avant la question : le modèle a le contexte
        # sous les yeux au moment de répondre, ce qui améliore l'ancrage.
        user = (
            f"Voici le schéma de la base :\n\n{self.schema}\n\n"
            f"Question : {question}\n\n"
            "Requête SQL SQLite (SELECT uniquement) :"
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def generate(self, question: str) -> SQLGeneration:
        """Génère le SQL correspondant à ``question``.

        Parameters
        ----------
        question : str
            Question en langage naturel.

        Returns
        -------
        SQLGeneration
            SQL nettoyé + sortie brute + latence ; ``ok=False`` si échec réseau.
        """
        started = time.perf_counter()
        # Appel unique, température 0 : on veut du déterminisme, pas de créativité.
        result = chat(self._build_messages(question), model=self.model, temperature=0.0)

        # Échec réseau/timeout : on remonte l'erreur sans lever d'exception.
        if not result.ok:
            return SQLGeneration(
                sql="",
                approach=self.name,
                model=self.model,
                latency_s=time.perf_counter() - started,
                ok=False,
                error=result.error,
                notes="Prompt maison → modèle de code local. Aucun framework.",
            )

        # Le modèle rend souvent du SQL enrobé : on isole la requête nue.
        sql = clean_sql(result.content)
        raw = result.content
        note = (
            "Prompt maison (schéma + valeurs énumérées) → qwen2.5-coder via Ollama. "
            "L'approche la plus transparente : tout est visible."
        )

        # Auto-correction par execution feedback : on VALIDE le SQL en l'exécutant
        # (lecture seule, sûr) ; s'il échoue, on renvoie l'erreur au modèle pour un
        # unique réessai. C'est ce que font les pipelines text2sql modernes.
        if self.self_correct and sql:
            check = db.run_select(sql, max_rows=1)
            if not check.ok:
                repaired, raw2 = self._repair(question, sql, check.error or "")
                # On ne garde la correction que si elle produit un SQL non vide.
                if repaired:
                    sql, raw = repaired, raw2
                    note += " ↻ Auto-corrigé après une erreur d'exécution."

        return SQLGeneration(
            sql=sql,
            approach=self.name,
            model=self.model,
            latency_s=time.perf_counter() - started,
            raw=raw,
            notes=note,
        )

    def _repair(self, question: str, bad_sql: str, error: str) -> tuple[str, str]:
        """Tente UNE correction du SQL en renvoyant l'erreur d'exécution au modèle.

        Parameters
        ----------
        question : str
            La question d'origine.
        bad_sql : str
            Le SQL qui a échoué à l'exécution.
        error : str
            Le message d'erreur SQLite renvoyé par la base.

        Returns
        -------
        (str, str)
            ``(sql_corrigé, sortie_brute)`` ; ``("", "")`` si le réessai échoue.
        """
        # On rejoue le contexte + la requête fautive + l'erreur, et on demande un
        # correctif. Un seul tour : au-delà, le gain marginal chute vite.
        repair_user = (
            f"Voici le schéma :\n\n{self.schema}\n\n"
            f"Question : {question}\n"
            f"Requête proposée (INCORRECTE) :\n{bad_sql}\n"
            f"Erreur SQLite renvoyée : {error}\n\n"
            "Corrige la requête. Réponds UNIQUEMENT par le SQL corrigé."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": repair_user},
        ]
        result = chat(messages, model=self.model, temperature=0.0)
        # Échec réseau : on renonce à la correction (l'appelant garde l'original).
        if not result.ok:
            return "", ""
        return clean_sql(result.content), result.content
