"""
conftest.py — Fixtures partagées de la suite de tests.

Garantit que la base SQLite de démo existe avant les tests qui en dépendent, et
expose des raccourcis (chemin de base, détection d'Ollama) pour marquer/sauter
les tests d'intégration lents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import db
from backend.build_db import build
from backend.llm import is_up


@pytest.fixture(scope="session")
def db_path() -> Path:
    """Chemin de la base de démo, construite une fois si absente.

    Returns
    -------
    pathlib.Path
        Le chemin du fichier SQLite garanti présent pour la session de tests.
    """
    # La base est déterministe : on ne la reconstruit que si elle manque, pour
    # garder la suite rapide.
    path = db.DB_PATH
    if not path.exists():
        build(path)
    return path


@pytest.fixture(scope="session")
def ollama_up() -> bool:
    """Indique si un serveur Ollama est joignable (pour les tests d'intégration).

    Returns
    -------
    bool
        Vrai si Ollama répond. Les tests ``slow`` s'en servent pour se sauter
        proprement quand le serveur est éteint.
    """
    return is_up()
