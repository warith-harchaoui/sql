"""
figures.py — Figures Vega-Lite pilotées par Gemma.

Après l'exécution d'une requête, on demande à ``gemma4`` (via Ollama) de CHOISIR
la meilleure visualisation — type de graphique + colonnes — puis on assemble une
**spécification Vega-Lite v5** au *house style* du skill front-figures (Roboto,
palette Apple CVD-safe, pas de spine haut/droite, pas de ticks, pas de grille
superflue). Le rendu se fait côté navigateur avec ``vega-embed`` : figures
nettes, interactives, cohérentes avec le reste du front.

Pourquoi Vega-Lite plutôt qu'un PNG matplotlib ? C'est la recommandation du
skill front-figures : une spec JSON déclarative est légère, interactive,
themable, et — surtout — on ne rend jamais du code exécutable produit par un
LLM. Gemma reste le cerveau du choix ; la spec finale est déterministe.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

from .llm import MODEL_FIGURE, chat, is_up

logger = logging.getLogger(__name__)

# Types de graphiques autorisés : vocabulaire fermé imposé à Gemma.
_ALLOWED = {"bar", "line", "pie", "scatter", "hist", "none"}

# Palette qualitative « Apple » CVD-safe, réordonnée pour éviter les paires
# rouge/vert adjacentes (cf. house style front-colors). Bleu en tête : c'est la
# couleur d'une série unique.
_CATEGORY = ["#007AFF", "#FF9500", "#34C759", "#AF52DE", "#00C7BE", "#FFCC00", "#A2845E", "#8E8E93"]
_PRIMARY = _CATEGORY[0]  # série unique -> bleu

# Consigne système : Gemma ne renvoie QUE du JSON, choisi dans un menu fermé.
_SYSTEM = """Tu es un assistant de data-visualisation. On te donne une question,
les colonnes d'un résultat SQL et un échantillon de lignes. Choisis LA meilleure
figure et réponds UNIQUEMENT par un objet JSON valide, sans Markdown, avec les clés :
  "chart_type": un de ["bar","line","pie","scatter","hist","none"],
  "x": nom exact de la colonne des abscisses (ou catégories),
  "y": nom exact de la colonne des valeurs numériques (ou null),
  "title": titre court en français,
  "rationale": une phrase expliquant le choix.
Règles : "line" pour une évolution temporelle ; "bar" pour comparer des catégories ;
"pie" seulement si peu de catégories (<8) qui somment à un tout ; "hist" pour une
distribution d'une variable ; "scatter" pour deux variables numériques ;
"none" si aucune figure n'a de sens. Utilise EXACTEMENT les noms de colonnes fournis.
"""

# Repère un objet JSON dans une sortie éventuellement bavarde du modèle.
_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

# Repère une chaîne ressemblant à une date/mois ISO (2026, 2026-07, 2026-07-18).
_DATEISH = re.compile(r"^\d{4}(-\d{2}){0,2}$")


@dataclass
class FigureResult:
    """Résultat d'une génération de figure.

    Attributes
    ----------
    ok : bool
        Vrai si une spec Vega-Lite a été produite.
    vega_spec : dict | None
        La spécification Vega-Lite v5 prête à passer à ``vega-embed``.
    spec : dict | None
        Le choix brut de Gemma (type, x, y, rationale) — transparence.
    error : str | None
        Message d'erreur éventuel.
    model : str
        Modèle utilisé.
    """

    ok: bool
    vega_spec: dict | None = None
    spec: dict | None = None
    error: str | None = None
    model: str = MODEL_FIGURE


def _house_config(dark: bool = False) -> dict:
    """Renvoie le bloc ``config`` Vega-Lite au house style front-figures.

    Copié-collé fidèle des tokens du skill (``_style.vega_config``) : Roboto,
    domaines sans spine haut/droite, ni ticks ni grille, coins arrondis.

    Parameters
    ----------
    dark : bool
        Variante sombre (fond, texte).

    Returns
    -------
    dict
        Bloc ``config`` fusionnable dans une spec Vega-Lite v5.
    """
    # Couleurs de premier plan / fond selon le thème.
    fg = "#F5F5F7" if dark else "#1D1D1F"
    bg = "#1D1D1F" if dark else "#FFFFFF"
    return {
        "background": bg,
        "font": "Roboto, system-ui, sans-serif",
        # Vue sans contour, coins arrondis (esthétique carte).
        "view": {"stroke": None, "cornerRadius": 10},
        # Axes : domaine visible, pas de grille ni de ticks, labels en mono.
        "axis": {
            "domainColor": fg,
            "labelColor": fg,
            "titleColor": fg,
            "grid": False,
            "ticks": False,
            "labelFont": "Roboto Mono",
            "titleFont": "Roboto",
        },
        # On masque explicitement les spines haut et droite.
        "axisTop": {"domain": False, "labels": False, "ticks": False, "title": None},
        "axisRight": {"domain": False, "labels": False, "ticks": False, "title": None},
        "legend": {
            "titleFont": "Roboto",
            "labelFont": "Roboto",
            "labelColor": fg,
            "titleColor": fg,
        },
        "title": {"font": "Roboto", "fontSize": 15, "color": fg},
        # Palette qualitative maison pour les encodages catégoriels.
        "range": {"category": _CATEGORY},
        "bar": {"cornerRadiusEnd": 4},
        "line": {"strokeWidth": 2},
        "point": {"filled": True, "size": 45},
    }


def _looks_temporal(values: list) -> bool:
    """Devine si une colonne est temporelle (dates/mois ISO).

    Parameters
    ----------
    values : list
        Échantillon de valeurs de la colonne.

    Returns
    -------
    bool
        Vrai si la majorité des valeurs ressemblent à des dates ISO.

    Examples
    --------
    >>> _looks_temporal(["2026-01", "2026-02"])
    True
    >>> _looks_temporal(["Sein", "Poumon"])
    False
    """
    # On ignore les None ; sans échantillon exploitable, ce n'est pas temporel.
    sample = [v for v in values if v is not None][:20]
    if not sample:
        return False
    # Compte les valeurs qui matchent le motif date ISO OU sont déjà des dates.
    hits = sum(1 for v in sample if isinstance(v, (date, datetime)) or _DATEISH.match(str(v)))
    # Majorité franche -> on considère la colonne comme temporelle.
    return hits >= max(1, int(0.6 * len(sample)))


def _records(columns: list[str], rows: list[list]) -> list[dict]:
    """Transforme colonnes + lignes en une liste de dicts (format Vega ``values``).

    Parameters
    ----------
    columns : list[str]
        Noms de colonnes.
    rows : list[list]
        Lignes de valeurs.

    Returns
    -------
    list[dict]
        Un dict par ligne, clé = nom de colonne. Les dates sont stringifiées.
    """
    out: list[dict] = []
    for r in rows:
        rec: dict = {}
        for col, val in zip(columns, r, strict=False):
            # Vega attend du JSON : on convertit dates en ISO string.
            rec[col] = val.isoformat() if isinstance(val, (date, datetime)) else val
        out.append(rec)
    return out


def _ask_gemma_for_spec(question: str, columns: list[str], rows: list[list], model: str) -> dict:
    """Demande à Gemma la spécification de figure et la parse en dict.

    Parameters
    ----------
    question : str
        La question d'origine (contexte du choix).
    columns : list[str]
        Colonnes du résultat.
    rows : list[list]
        Lignes du résultat (échantillon envoyé seulement).
    model : str
        Tag Ollama du modèle de figure.

    Returns
    -------
    dict
        La spec parsée ; ``{"chart_type": "none", ...}`` si parsing impossible.

    Raises
    ------
    RuntimeError
        Si l'appel au modèle échoue (réseau).
    """
    # Gemma n'a besoin que de « sentir » les données : on borne l'échantillon.
    payload = {"question": question, "columns": columns, "sample_rows": rows[:8]}
    user = (
        "Contexte du résultat SQL (JSON) :\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
        + "\n\nDonne la spécification de figure en JSON."
    )
    # Petite température : le choix de figure tolère un peu de souplesse.
    result = chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        model=model,
        temperature=0.2,
    )
    if not result.ok:
        raise RuntimeError(result.error or "Appel Gemma échoué")

    # Extraction défensive du premier objet JSON de la réponse.
    match = _JSON_OBJ.search(result.content)
    if not match:
        return {"chart_type": "none", "rationale": "Réponse non-JSON du modèle."}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"chart_type": "none", "rationale": "JSON invalide du modèle."}


def _build_vega(spec: dict, columns: list[str], rows: list[list], dark: bool = False) -> dict:
    """Assemble la spec Vega-Lite v5 à partir du choix de Gemma et des données.

    Parameters
    ----------
    spec : dict
        Choix de Gemma (chart_type, x, y, title).
    columns : list[str]
        Colonnes du résultat.
    rows : list[list]
        Lignes du résultat.
    dark : bool
        Thème sombre.

    Returns
    -------
    dict
        Spec Vega-Lite v5 complète (``$schema``, ``data``, ``mark``, ``encoding``).

    Raises
    ------
    ValueError
        Si les colonnes demandées n'existent pas dans le résultat.
    """
    chart = spec.get("chart_type", "bar")
    x_col = spec.get("x")
    y_col = spec.get("y")
    title = spec.get("title") or "Figure"

    # Index par nom pour extraire les échantillons de colonnes et valider.
    idx = {name: i for i, name in enumerate(columns)}
    data = {"values": _records(columns, rows)}

    # Enveloppe commune : schéma v5, données, titre, config maison. On fixe une
    # largeur en pixels (et non "container") : vega-embed mesure sinon le conteneur
    # avant qu'il ait une largeur → SVG de largeur 0. ``autosize: fit`` garde tout
    # le contenu (labels compris) dans le cadre.
    base: dict = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title,
        "data": data,
        "width": 620,
        "height": 340,
        "autosize": {"type": "fit", "contains": "padding"},
        "config": _house_config(dark),
    }

    # --- Histogramme : distribution d'UNE colonne numérique ----------------
    if chart == "hist":
        if x_col not in idx:
            raise ValueError(f"Colonne inconnue pour l'histogramme : {x_col!r}")
        base["mark"] = {"type": "bar", "color": _PRIMARY, "cornerRadiusEnd": 4}
        base["encoding"] = {
            # ``bin`` demande à Vega de regrouper la variable en classes.
            "x": {"field": x_col, "bin": True, "type": "quantitative", "axis": {"title": x_col}},
            "y": {"aggregate": "count", "type": "quantitative", "axis": {"title": "Effectif"}},
        }
        return base

    # --- Nuage de points : deux colonnes numériques ------------------------
    if chart == "scatter":
        if x_col not in idx or y_col not in idx:
            raise ValueError("scatter demande deux colonnes x et y valides.")
        base["mark"] = {"type": "point", "filled": True, "color": _PRIMARY}
        base["encoding"] = {
            "x": {"field": x_col, "type": "quantitative", "axis": {"title": x_col}},
            "y": {"field": y_col, "type": "quantitative", "axis": {"title": y_col}},
            "tooltip": [{"field": x_col}, {"field": y_col}],
        }
        return base

    # --- Camembert : catégories qui somment à un tout ----------------------
    if chart == "pie":
        if x_col not in idx or y_col not in idx:
            raise ValueError("pie demande x (catégories) et y (valeurs).")
        # L'arc n'a pas d'axes : on encode l'angle (theta) et la couleur.
        base["mark"] = {"type": "arc", "innerRadius": 0}
        base["encoding"] = {
            "theta": {"field": y_col, "type": "quantitative"},
            "color": {"field": x_col, "type": "nominal", "scale": {"range": _CATEGORY}},
            "tooltip": [{"field": x_col}, {"field": y_col}],
        }
        return base

    # --- Barres ou courbe : catégorie/temps -> valeur ----------------------
    if x_col not in idx or y_col not in idx:
        raise ValueError("bar/line demandent x et y valides.")
    # Type de l'axe x : temporel si ça ressemble à des dates, sinon nominal.
    x_values = [r[idx[x_col]] for r in rows]
    x_type = "temporal" if _looks_temporal(x_values) else "nominal"

    if chart == "line":
        # Courbe + points marqués pour la lisibilité des évolutions.
        base["mark"] = {"type": "line", "point": True, "color": _PRIMARY}
        x_type = "temporal" if x_type == "temporal" else "ordinal"
    else:  # bar (défaut robuste)
        base["mark"] = {"type": "bar", "color": _PRIMARY, "cornerRadiusEnd": 4}

    base["encoding"] = {
        "x": {"field": x_col, "type": x_type, "axis": {"title": x_col, "labelAngle": -40}},
        "y": {"field": y_col, "type": "quantitative", "axis": {"title": y_col}},
        "tooltip": [{"field": x_col}, {"field": y_col}],
    }
    return base


def make_figure(
    question: str,
    columns: list[str],
    rows: list[list],
    model: str = MODEL_FIGURE,
    dark: bool = False,
) -> FigureResult:
    """Choisit (Gemma) puis assemble une spec Vega-Lite pour un résultat de requête.

    Parameters
    ----------
    question : str
        Question d'origine (guide le choix de visualisation).
    columns : list[str]
        Colonnes du résultat SQL.
    rows : list[list]
        Lignes du résultat SQL.
    model : str
        Tag Ollama du modèle (défaut : ``gemma4:e4b-mlx``).
    dark : bool
        Thème sombre pour la config Vega.

    Returns
    -------
    FigureResult
        Spec Vega-Lite + choix de Gemma, ou ``ok=False`` avec la raison.

    Examples
    --------
    >>> res = make_figure("CA par mois", ["mois", "ca"], [["2026-01", 10.0]])
    >>> isinstance(res.ok, bool)
    True
    """
    # Garde-fous d'entrée : sans serveur, sans données, ou sans colonnes -> pas
    # de figure, proprement, plutôt qu'un plantage.
    if not is_up():
        return FigureResult(ok=False, error="Serveur Ollama injoignable.", model=model)
    if not rows or not columns:
        return FigureResult(ok=False, error="Résultat vide : aucune figure.", model=model)

    try:
        # 1) Gemma choisit type + colonnes.
        choice = _ask_gemma_for_spec(question, columns, rows, model)
    except RuntimeError as exc:
        return FigureResult(ok=False, error=str(exc), model=model)

    # Normalisation : un type hors menu est ramené à « none ».
    chart = str(choice.get("chart_type", "none")).lower()
    if chart not in _ALLOWED:
        chart = "none"
        choice["chart_type"] = "none"

    # Gemma peut légitimement juger qu'aucune figure n'a de sens.
    if chart == "none":
        return FigureResult(
            ok=False,
            spec=choice,
            error=choice.get("rationale", "Aucune figure pertinente."),
            model=model,
        )

    try:
        # 2) Assemblage déterministe de la spec Vega-Lite au house style.
        vega = _build_vega(choice, columns, rows, dark=dark)
    except ValueError as exc:
        # Colonnes incompatibles avec le choix : on l'explique.
        return FigureResult(ok=False, spec=choice, error=str(exc), model=model)

    return FigureResult(ok=True, vega_spec=vega, spec=choice, model=model)
