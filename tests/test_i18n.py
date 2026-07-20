"""
test_i18n.py — Tests de l'i18n YAML (GUI + prompts) et de la détection de langue.

Vérifie que la source de vérité ``locales/i18n.yaml`` est bien chargée, que les
prompts sont bilingues, que l'endpoint ``/api/i18n`` expose les chaînes GUI, et
que ``detect_language`` reconnaît fr/en (repli ``und`` si trop court). Aucun appel
Ollama : tout est local.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend import prompts
from backend.llm import detect_language
from backend.server import app

client = TestClient(app)


def test_gui_strings_have_both_languages():
    """Le dict GUI contient en ET fr, avec les mêmes clés dans les deux."""
    gui = prompts.gui_strings()
    assert "en" in gui and "fr" in gui
    # Parité des clés entre les deux langues : pas de chaîne oubliée d'un côté.
    assert set(gui["en"]) == set(gui["fr"])
    # Une clé connue est bien traduite différemment selon la langue.
    assert gui["fr"]["run"] == "Exécuter"
    assert gui["en"]["run"] == "Run"


def test_prompts_are_bilingual_and_nonempty():
    """Les prompts système existent en fr et en, non vides et distincts."""
    for getter in (prompts.sql_system, prompts.sql_naive, prompts.figure_system):
        fr, en = getter("fr"), getter("en")
        assert fr and en, f"{getter.__name__} vide"
        assert fr != en, f"{getter.__name__} identique fr/en (traduction manquante ?)"
    # Une langue inconnue retombe sur le français (la base).
    assert prompts.sql_system("de") == prompts.sql_system("fr")


def test_api_i18n_endpoint():
    """/api/i18n expose les chaînes GUI (source YAML) pour le front."""
    resp = client.get("/api/i18n")
    assert resp.status_code == 200
    gui = resp.json()["gui"]
    assert "en" in gui and "fr" in gui
    assert gui["fr"]["footer"].startswith("Démo")


def test_detect_language():
    """detect_language reconnaît fr/en et renvoie « und » si trop court."""
    assert detect_language("Combien de patients par sexe ?") == "fr"
    assert detect_language("How many patients grouped by sex?") == "en"
    # Chaîne trop courte : on ne devine pas (repli déterministe).
    assert detect_language("ok") == "und"
