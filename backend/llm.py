"""
llm.py — Client Ollama synchrone et autoportant.

Adapté (copié-collé puis simplifié) du client asynchrone de `roitelet`
(`core/providers/ollama.py`) : on garde l'esprit — timeouts généreux pour les
modèles locaux lents, dégradation propre en cas d'erreur réseau — mais sans la
machinerie du framework (config globale, schémas Pydantic, comptabilité énergie).

Un seul module, deux appels utiles :
  - `chat()`      : complétion de chat classique (messages system/user).
  - `is_up()`     : le serveur Ollama répond-il ?
  - `list_models()` : tags disponibles localement.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import requests

# URL du serveur Ollama local. Surchageable par variable d'environnement pour
# pointer vers un hôte distant sans toucher au code.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")

# Modèles par défaut de la démo. Ils correspondent à ce qui est déjà tiré
# localement (cf. `ollama list`). Surchargeables par l'environnement.
MODEL_SQL = os.environ.get("MODEL_SQL", "qwen2.5-coder:latest")  # texte -> SQL
MODEL_FIGURE = os.environ.get("MODEL_FIGURE", "gemma4:e4b-mlx")  # résultats -> spec Vega-Lite
MODEL_EMBED = os.environ.get("MODEL_EMBED", "nomic-embed-text:latest")  # RAG (Vanna)


@dataclass
class LLMResult:
    """Réponse d'une complétion, enrichie de métadonnées de traçabilité.

    En plus de la latence horloge murale (``latency_s``, sensible à la charge
    de la machine), on remonte les **durées mesurées par Ollama lui-même**
    (champs ``server_*`` et ``eval_*``). Ces durées isolent le temps de calcul
    utile (chargement, traitement du prompt, génération) indépendamment de
    l'ordonnancement du process Python — c'est la mesure « propre » du temps
    GPU/CPU, insensible aux autres activités de la machine.
    """

    content: str
    model: str
    latency_s: float
    ok: bool = True
    error: str | None = None
    usage: dict = field(default_factory=dict)
    # Durées côté serveur Ollama (en secondes ; 0 si absentes du build).
    server_total_s: float = 0.0  # total_duration : bout-en-bout côté Ollama
    server_load_s: float = 0.0  # load_duration  : chargement du modèle
    server_prompt_s: float = 0.0  # prompt_eval_duration : lecture du prompt
    server_eval_s: float = 0.0  # eval_duration  : génération des tokens
    eval_count: int = 0  # nombre de tokens générés

    @property
    def tokens_per_s(self) -> float:
        """Vitesse de génération (tokens/s) mesurée par Ollama — quasi insensible à la charge.

        Returns
        -------
        float
            ``eval_count / server_eval_s`` (0 si la durée est inconnue).
        """
        # C'est LA vitesse hardware pure : combien de tokens le GPU sort par
        # seconde, indépendamment de ce que fait le reste de la machine.
        return self.eval_count / self.server_eval_s if self.server_eval_s > 0 else 0.0


def chat(
    messages: list[dict],
    model: str = MODEL_SQL,
    temperature: float = 0.0,
    timeout: float = 300.0,
    options: dict | None = None,
) -> LLMResult:
    """Appelle `/api/chat` d'Ollama et renvoie une complétion unique.

    Parameters
    ----------
    messages : list[dict]
        Historique de chat, chaque élément ``{"role": ..., "content": ...}``.
    model : str
        Tag Ollama du modèle (ex. ``qwen2.5-coder:latest``).
    temperature : float
        0.0 par défaut : on veut du SQL/déterministe, pas de créativité.
    timeout : float
        300 s : un modèle local sur CPU peut être lent ; on préfère une réponse
        lente valide à un timeout compté comme erreur.
    options : dict | None
        Options Ollama additionnelles (``num_ctx``, ``top_p``, ...).

    Returns
    -------
    LLMResult
        Contenu + latence ; en cas d'échec réseau, ``ok=False`` et ``error``
        renseigné plutôt qu'une exception (l'appelant décide quoi faire).
    """
    started = time.perf_counter()
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, **(options or {})},
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # Les réponses de chat nichent le texte sous ``message.content`` ;
        # défaut chaîne vide pour qu'un corps malformé dégrade en blanc, pas en crash.
        content = data.get("message", {}).get("content", "") or ""
        # Compteurs optionnels selon les builds ; ``or 0`` neutralise clés
        # manquantes et null explicites.
        usage = {
            "prompt_tokens": int(data.get("prompt_eval_count", 0) or 0),
            "completion_tokens": int(data.get("eval_count", 0) or 0),
        }
        # Durées serveur Ollama : nanosecondes -> secondes. Absentes => 0.
        ns = 1e9
        server_total_s = float(data.get("total_duration", 0) or 0) / ns
        server_load_s = float(data.get("load_duration", 0) or 0) / ns
        server_prompt_s = float(data.get("prompt_eval_duration", 0) or 0) / ns
        server_eval_s = float(data.get("eval_duration", 0) or 0) / ns
        return LLMResult(
            content=content,
            model=model,
            latency_s=time.perf_counter() - started,
            usage=usage,
            server_total_s=server_total_s,
            server_load_s=server_load_s,
            server_prompt_s=server_prompt_s,
            server_eval_s=server_eval_s,
            eval_count=int(data.get("eval_count", 0) or 0),
        )
    except Exception as exc:  # réseau, timeout, HTTP, JSON — tout est capté
        return LLMResult(
            content="",
            model=model,
            latency_s=time.perf_counter() - started,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def is_up() -> bool:
    """Vrai si le serveur Ollama répond sur `/api/tags`."""
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


def list_models() -> list[str]:
    """Liste les tags de modèles disponibles localement (vide si serveur muet)."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []
