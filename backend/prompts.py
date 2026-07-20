"""
prompts.py — Chargeur unique de l'i18n (GUI + prompts LLM) depuis le YAML.

Toutes les chaînes traduites vivent dans ``locales/i18n.yaml`` — pas en dur dans
le code (ni JS, ni Python). Ce module lit ce fichier une fois (cache) et expose :

  - ``gui_strings()``    : le dict ``{lang: {clé: texte}}`` pour le front (/api/i18n) ;
  - ``sql_system(lang)`` : la consigne système SQL « soignée » ;
  - ``sql_naive(lang)``  : la consigne système « naïve » (témoin) ;
  - ``figure_system(lang)`` : la consigne de choix de figure (Gemma).

Ainsi, traduire une chaîne = éditer le YAML, sans toucher au code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# Emplacement du YAML source (racine/locales/i18n.yaml).
_YAML_PATH = Path(__file__).resolve().parent.parent / "locales" / "i18n.yaml"

# Langues supportées ; toute langue inconnue retombe sur le français (la base).
_LANGS = ("fr", "en")
_FALLBACK = "fr"


@lru_cache(maxsize=1)
def _load() -> dict:
    """Charge et met en cache le contenu du YAML d'i18n.

    Returns
    -------
    dict
        Le document YAML parsé (clés ``gui`` et ``prompts``).

    Raises
    ------
    FileNotFoundError
        Si ``locales/i18n.yaml`` est absent (installation cassée).
    """
    # Import local de PyYAML : dépendance nécessaire seulement si on charge l'i18n.
    import yaml

    with _YAML_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _norm(lang: str) -> str:
    """Normalise un code langue vers ``fr``/``en`` (repli sur le français).

    Parameters
    ----------
    lang : str
        Code langue quelconque (ex. ``fr``, ``en``, ``und``, ``de``).

    Returns
    -------
    str
        ``fr`` ou ``en``.
    """
    # On ne garde que le préfixe (``en-US`` -> ``en``) et on borne au supporté.
    base = (lang or "").lower().split("-")[0]
    return base if base in _LANGS else _FALLBACK


def gui_strings() -> dict:
    """Renvoie le dict des chaînes GUI par langue (pour le front).

    Returns
    -------
    dict
        ``{"en": {clé: texte, ...}, "fr": {...}}``.
    """
    return _load().get("gui", {})


def _prompt(name: str, lang: str) -> str:
    """Récupère un prompt nommé dans la langue voulue.

    Parameters
    ----------
    name : str
        Nom du prompt (``sql_system`` / ``sql_naive`` / ``figure_system``).
    lang : str
        Langue demandée (normalisée en fr/en).

    Returns
    -------
    str
        Le texte du prompt (chaîne vide si introuvable, jamais d'exception).
    """
    block = _load().get("prompts", {}).get(name, {})
    return (block.get(_norm(lang)) or block.get(_FALLBACK) or "").strip()


def sql_system(lang: str = _FALLBACK) -> str:
    """Consigne système SQL « soignée » dans la langue voulue."""
    return _prompt("sql_system", lang)


def sql_naive(lang: str = _FALLBACK) -> str:
    """Consigne système « naïve » (témoin de comparaison)."""
    return _prompt("sql_naive", lang)


def figure_system(lang: str = _FALLBACK) -> str:
    """Consigne système de choix de figure (Gemma)."""
    return _prompt("figure_system", lang)
